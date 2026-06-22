#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Full product catalogue batch generation script.

Generates 40,000 product records using Amazon Bedrock Batch Inference,
which processes all description requests as a single async job with no
per-request rate limits.

Workflow:
  1. Generate all structural records (SKU, price, attributes, stock) locally
  2. Write a JSONL of description prompts → upload to S3
  3. Submit a Bedrock CreateModelInvocationJob
  4. Poll until complete (typically 1–3 hours for 40k records)
  5. Download output JSONL from S3, merge descriptions back
  6. Write products_full_40000.parquet + .json to --output directory

Usage:
    python generate_products_batch.py --count 40000 --output ../../data/

    # Resume after a job was already submitted:
    python generate_products_batch.py --job-arn <arn> --output ../../data/

Cost estimate (40,000 products):
    ~300 input tokens + ~200 output tokens per product × 40,000 = ~20M tokens
    Amazon Nova 2 Lite batch pricing: < $5 USD

Requirements:
    pip install boto3 pandas pyarrow tqdm
    IAM role arn:aws:iam::771834037671:role/bedrock-batch-s3-role
    S3 bucket dataforai-771834037671-eu-west-2-an
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from tqdm import tqdm

# Import shared product generation logic
sys.path.insert(0, str(Path(__file__).parent))
from generate_products import (
    STORES,
    build_products,
    write_outputs,
    _build_description_prompt,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_PROFILE = "ridge-course-dev"
AWS_REGION = "eu-west-1"
BEDROCK_MODEL = "eu.amazon.nova-2-lite-v1:0"
S3_BUCKET = "dataforai-771834037671-eu-west-2-an"
ROLE_ARN = "arn:aws:iam::771834037671:role/bedrock-batch-s3-role"
S3_PREFIX = "data-generation"

# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def s3_upload(s3: Any, local_path: Path, bucket: str, key: str) -> None:
    print(f"  Uploading s3://{bucket}/{key} ...")
    s3.upload_file(str(local_path), bucket, key)


def s3_download_prefix(s3: Any, bucket: str, prefix: str, local_dir: Path) -> list[Path]:
    """Download all objects under prefix to local_dir. Returns list of local paths."""
    local_dir.mkdir(parents=True, exist_ok=True)
    paginator = s3.get_paginator("list_objects_v2")
    paths: list[Path] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            filename = Path(key).name
            local_path = local_dir / filename
            print(f"  Downloading s3://{bucket}/{key} → {local_path.name}")
            s3.download_file(bucket, key, str(local_path))
            paths.append(local_path)
    return paths


# ---------------------------------------------------------------------------
# Batch job
# ---------------------------------------------------------------------------


def build_input_jsonl(products: list[dict[str, Any]], local_path: Path) -> None:
    """Write one JSONL record per product in Bedrock batch input format."""
    print(f"Writing {len(products)} prompts to {local_path.name} ...")
    with open(local_path, "w", encoding="utf-8") as f:
        for p in tqdm(products, desc="Building JSONL", unit="product"):
            prompt = _build_description_prompt(p)
            record = {
                "recordId": p["sku"],
                "modelInput": {
                    "messages": [{"role": "user", "content": [{"text": prompt}]}],
                    "inferenceConfig": {"max_new_tokens": 350, "temperature": 0.7},
                },
            }
            f.write(json.dumps(record) + "\n")
    size_mb = local_path.stat().st_size / 1024 / 1024
    print(f"  {local_path.name}: {size_mb:.1f} MB")


def submit_batch_job(
    bedrock: Any,
    job_name: str,
    model_id: str,
    role_arn: str,
    s3_input_uri: str,
    s3_output_uri: str,
) -> str:
    """Submit a Bedrock batch inference job. Returns job ARN."""
    response = bedrock.create_model_invocation_job(
        jobName=job_name,
        roleArn=role_arn,
        modelId=model_id,
        inputDataConfig={
            "s3InputDataConfig": {
                "s3Uri": s3_input_uri,
                "s3InputFormat": "JSONL",
            }
        },
        outputDataConfig={
            "s3OutputDataConfig": {
                "s3Uri": s3_output_uri,
            }
        },
    )
    return response["jobArn"]


def poll_batch_job(bedrock: Any, job_arn: str, poll_interval: int = 60) -> str:
    """Poll until the job reaches a terminal state. Returns final status."""
    terminal = {"Completed", "Failed", "Stopped", "Expired"}
    print(f"\nPolling job {job_arn.split('/')[-1]} every {poll_interval}s ...")
    while True:
        job = bedrock.get_model_invocation_job(jobIdentifier=job_arn)
        status = job["status"]
        elapsed = ""
        if "submitTime" in job:
            delta = datetime.now(timezone.utc) - job["submitTime"]
            mins = int(delta.total_seconds() // 60)
            elapsed = f"  ({mins}m elapsed)"
        print(f"  [{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {status}{elapsed}")
        if status in terminal:
            return status
        time.sleep(poll_interval)


def merge_descriptions(
    products: list[dict[str, Any]], output_files: list[Path]
) -> list[dict[str, Any]]:
    """Parse batch output JSONL files and merge descriptions into product records."""
    descriptions: dict[str, dict[str, str]] = {}
    parse_errors = 0

    for path in output_files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    record_id = row["recordId"]
                    text = row["modelOutput"]["output"]["message"]["content"][0]["text"].strip()
                    # Strip markdown fences if present
                    if text.startswith("```"):
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                    desc = json.loads(text)
                    descriptions[record_id] = {
                        "short_description": desc.get("short_description", ""),
                        "long_description": desc.get("long_description", ""),
                    }
                except (json.JSONDecodeError, KeyError, IndexError) as exc:
                    parse_errors += 1
                    if parse_errors <= 5:
                        print(f"  ⚠ Parse error on record: {exc}", file=sys.stderr)

    matched = 0
    for p in products:
        desc = descriptions.get(p["sku"])
        if desc:
            p["short_description"] = desc["short_description"]
            p["long_description"] = desc["long_description"]
            matched += 1
        else:
            p.setdefault("short_description", "")
            p.setdefault("long_description", "")

    print(f"  Descriptions merged: {matched}/{len(products)} matched")
    if parse_errors:
        print(f"  Parse errors: {parse_errors}", file=sys.stderr)
    return products


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate full Meridian product catalogue via Bedrock batch inference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--count", type=int, default=40000,
                   help="Number of products to generate (default: 40000)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed (default: 42)")
    p.add_argument("--output", type=str, default="../../data/",
                   help="Output directory (default: ../../data/)")
    p.add_argument("--job-arn", type=str, default=None,
                   help="Resume from an existing batch job ARN (skips submission)")
    p.add_argument("--profile", type=str, default=AWS_PROFILE)
    p.add_argument("--region", type=str, default=AWS_REGION)
    p.add_argument("--model", type=str, default=BEDROCK_MODEL)
    p.add_argument("--s3-bucket", type=str, default=S3_BUCKET)
    p.add_argument("--role-arn", type=str, default=ROLE_ARN)
    p.add_argument("--no-poll", action="store_true",
                   help="Submit job and exit without polling (print job ARN to resume later)")
    p.add_argument("--poll-interval", type=int, default=60,
                   help="Seconds between status checks (default: 60)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client("s3")
    bedrock = session.client("bedrock")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_name = f"meridian-products-{ts}"

    # -----------------------------------------------------------------------
    # Step 1: Build structural records
    # -----------------------------------------------------------------------
    if args.job_arn:
        # Resuming — reload products from existing no-description file
        existing = list(output_dir.glob("products_full_*.json"))
        if not existing:
            print("ERROR: --job-arn requires a previously generated products JSON in --output.", file=sys.stderr)
            sys.exit(1)
        latest = max(existing, key=lambda p: p.stat().st_mtime)
        print(f"Resuming job {args.job_arn}")
        print(f"Loading structural records from {latest.name} ...")
        products = json.loads(latest.read_text(encoding="utf-8"))
        print(f"  {len(products)} records loaded")
    else:
        print(f"Meridian batch product generation — {args.count} products (seed={args.seed})")
        print(f"Model: {args.model}  Region: {args.region}  Bucket: {args.s3_bucket}")
        print()
        print("Step 1: Building structural records ...")
        products = build_products(count=args.count, seed=args.seed)
        print(f"  {len(products)} records built")

        # Save structural-only JSON immediately (safe checkpoint)
        struct_path = output_dir / f"products_full_{args.count}.json"
        struct_path.write_text(
            json.dumps(products, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  Structural records saved to {struct_path.name}")

    # -----------------------------------------------------------------------
    # Step 2: Build and upload JSONL
    # -----------------------------------------------------------------------
    if not args.job_arn:
        print("\nStep 2: Building input JSONL ...")
        jsonl_path = output_dir / f"batch_input_{ts}.jsonl"
        build_input_jsonl(products, jsonl_path)

        s3_input_key = f"{S3_PREFIX}/input/{job_name}/batch_input.jsonl"
        s3_upload(s3, jsonl_path, args.s3_bucket, s3_input_key)
        s3_input_uri = f"s3://{args.s3_bucket}/{s3_input_key}"
        s3_output_uri = f"s3://{args.s3_bucket}/{S3_PREFIX}/output/{job_name}/"

        # -----------------------------------------------------------------------
        # Step 3: Submit batch job
        # -----------------------------------------------------------------------
        print("\nStep 3: Submitting Bedrock batch job ...")
        try:
            job_arn = submit_batch_job(
                bedrock=bedrock,
                job_name=job_name,
                model_id=args.model,
                role_arn=args.role_arn,
                s3_input_uri=s3_input_uri,
                s3_output_uri=s3_output_uri,
            )
        except ClientError as exc:
            print(f"ERROR submitting batch job: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"  Job ARN: {job_arn}")
        print(f"  Input:   {s3_input_uri}")
        print(f"  Output:  {s3_output_uri}")

        # Save job metadata for resuming
        meta_path = output_dir / f"batch_job_{ts}.json"
        meta_path.write_text(json.dumps({
            "job_arn": job_arn,
            "job_name": job_name,
            "s3_input_uri": s3_input_uri,
            "s3_output_uri": s3_output_uri,
            "submitted_at": ts,
            "count": args.count,
        }, indent=2), encoding="utf-8")
        print(f"  Job metadata saved to {meta_path.name}")

        if args.no_poll:
            print(f"\nJob submitted. To resume after completion:")
            print(f"  python generate_products_batch.py --job-arn {job_arn} --output {args.output}")
            return
    else:
        job_arn = args.job_arn
        # Recover output URI from saved metadata
        meta_files = list(output_dir.glob("batch_job_*.json"))
        if meta_files:
            latest_meta = max(meta_files, key=lambda p: p.stat().st_mtime)
            meta = json.loads(latest_meta.read_text())
            s3_output_uri = meta["s3_output_uri"]
        else:
            print("ERROR: could not find batch_job_*.json metadata in --output.", file=sys.stderr)
            sys.exit(1)

    # -----------------------------------------------------------------------
    # Step 4: Poll
    # -----------------------------------------------------------------------
    print("\nStep 4: Waiting for batch job to complete ...")
    status = poll_batch_job(bedrock, job_arn, poll_interval=args.poll_interval)

    if status != "Completed":
        print(f"\nERROR: Job ended with status '{status}'. Check the AWS console for details.", file=sys.stderr)
        sys.exit(1)

    print(f"\nJob completed.")

    # -----------------------------------------------------------------------
    # Step 5: Download output
    # -----------------------------------------------------------------------
    print("\nStep 5: Downloading output from S3 ...")
    output_prefix = s3_output_uri.replace(f"s3://{args.s3_bucket}/", "")
    local_results_dir = output_dir / "batch_output"
    output_files = s3_download_prefix(s3, args.s3_bucket, output_prefix, local_results_dir)
    print(f"  {len(output_files)} output file(s) downloaded")

    # -----------------------------------------------------------------------
    # Step 6: Merge and write final output
    # -----------------------------------------------------------------------
    print("\nStep 6: Merging descriptions ...")
    products = merge_descriptions(products, output_files)

    print("\nStep 7: Writing final outputs ...")
    write_outputs(products, output_dir, args.count)
    print("\nDone.")


if __name__ == "__main__":
    main()
