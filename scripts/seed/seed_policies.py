#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Policy document seed script.

Uploads the pre-generated policy documents to S3 (PolicyDocsBucket)
and stores policy metadata in Aurora PostgreSQL. No Bedrock calls.

Run after `make deploy-base`:
    python scripts/seed/seed_policies.py

Prerequisites:
    - meridian-base stack deployed
    - data/policies_40.json exists
    - data/policies/ directory contains POL-*.txt files
    - AWS profile ridge-course-dev configured

What this does:
    1. Creates a policy_documents table in Aurora (for metadata/search)
    2. Uploads each .txt file to s3://meridian-policies-{account}-{env}/documents/
    3. Inserts metadata (doc_id, title, type, tags, S3 key) into Aurora

Cost estimate: nil (S3 PUT for 40 small files ≈ £0.00)
Runtime: under 1 minute
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_PROFILE  = "ridge-course-dev"
AWS_REGION   = "eu-west-2"
STACK_BASE   = "meridian-base"
ENVIRONMENT  = "dev"
S3_PREFIX    = "documents/"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS policy_documents (
    doc_id          VARCHAR(20)    PRIMARY KEY,
    title           VARCHAR(255)   NOT NULL,
    doc_type        VARCHAR(50),
    applies_to      VARCHAR(100),
    tags            TEXT[],
    s3_key          VARCHAR(500),
    word_count      INTEGER,
    version         VARCHAR(10),
    last_updated    DATE,
    indexed_at      TIMESTAMPTZ    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policy_doc_type   ON policy_documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_policy_applies_to ON policy_documents (applies_to);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_stack_output(cfn, stack_name: str, key: str) -> str:
    resp = cfn.describe_stacks(StackName=stack_name)
    for o in resp["Stacks"][0].get("Outputs", []):
        if o["OutputKey"] == key:
            return o["OutputValue"]
    raise ValueError(f"Output '{key}' not found in stack '{stack_name}'")


def run_sql(rds_data, cluster_arn: str, secret_arn: str, statement: str, params=None):
    kwargs = dict(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database="meridian",
        sql=statement,
    )
    if params:
        kwargs["parameters"] = params
    return rds_data.execute_statement(**kwargs)


def load_policy_metadata(data_dir: Path) -> list[dict]:
    json_path = data_dir / "policies_40.json"
    if json_path.exists():
        with open(json_path) as f:
            records = json.load(f)
        print(f"  Loaded {len(records):,} policy records from JSON")
        return records

    parquet_path = data_dir / "policies_40.parquet"
    if parquet_path.exists() and PANDAS_AVAILABLE:
        df = pd.read_parquet(parquet_path)
        records = df.to_dict("records")
        print(f"  Loaded {len(records):,} policy records from parquet")
        return records

    print(f"ERROR: No policy metadata found in {data_dir}", file=sys.stderr)
    sys.exit(1)


def pg_array(values: list) -> str:
    if not values:
        return "{}"
    return "{" + ",".join(f'"{v}"' for v in values) + "}"


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------

def upload_policies_to_s3(s3, bucket_name: str, policies_dir: Path,
                           policy_records: list[dict]) -> dict[str, str]:
    """
    Upload .txt files from policies/ directory to S3.
    Returns a dict mapping doc_id -> s3_key.
    """
    s3_keys: dict[str, str] = {}
    uploaded = 0
    skipped  = 0

    print(f"  Uploading to s3://{bucket_name}/{S3_PREFIX}")

    for record in policy_records:
        doc_id = record["doc_id"]
        txt_path = policies_dir / f"{doc_id}.txt"

        if not txt_path.exists():
            # Fall back: write content from the JSON directly if txt file missing
            content = record.get("content", "")
            if content:
                txt_path.write_text(content, encoding="utf-8")
            else:
                print(f"  Warning: no file or content for {doc_id}", file=sys.stderr)
                skipped += 1
                continue

        s3_key = f"{S3_PREFIX}{doc_id}.txt"

        try:
            s3.upload_file(
                str(txt_path),
                bucket_name,
                s3_key,
                ExtraArgs={
                    "ContentType": "text/plain",
                    "Metadata": {
                        "doc_id":   doc_id,
                        "title":    record.get("title", "")[:256],
                        "doc_type": record.get("doc_type", ""),
                    },
                },
            )
            s3_keys[doc_id] = s3_key
            uploaded += 1
            print(f"  Uploaded {doc_id}.txt  ({uploaded}/{len(policy_records)})", end="\r")
        except ClientError as exc:
            print(f"\n  Upload error for {doc_id}: {exc}", file=sys.stderr)
            skipped += 1

    print(f"\n  S3 upload complete: {uploaded} uploaded, {skipped} skipped")
    return s3_keys


# ---------------------------------------------------------------------------
# Aurora metadata
# ---------------------------------------------------------------------------

def seed_policy_metadata(rds_data, cluster_arn: str, secret_arn: str,
                          policy_records: list[dict], s3_keys: dict[str, str]) -> int:

    def sql(statement, params=None):
        return run_sql(rds_data, cluster_arn, secret_arn, statement, params)

    print("  Creating schema...")
    for stmt in SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                sql(stmt + ";")
            except ClientError as exc:
                if "already exists" not in str(exc):
                    print(f"  Schema warning: {exc}", file=sys.stderr)

    upsert_sql = """
INSERT INTO policy_documents (
    doc_id, title, doc_type, applies_to, tags, s3_key,
    word_count, version, last_updated
) VALUES (
    :doc_id, :title, :doc_type, :applies_to, :tags, :s3_key,
    :word_count, :version, CAST(:last_updated AS DATE)
)
ON CONFLICT (doc_id) DO UPDATE SET
    title        = EXCLUDED.title,
    s3_key       = EXCLUDED.s3_key,
    indexed_at   = NOW();
""".strip()

    inserted = 0
    errors   = 0

    for record in policy_records:
        doc_id = record["doc_id"]
        tags   = record.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        params = [
            {"name": "doc_id",       "value": {"stringValue": doc_id}},
            {"name": "title",        "value": {"stringValue": record.get("title", "")}},
            {"name": "doc_type",     "value": {"stringValue": record.get("doc_type", "")} if record.get("doc_type") else {"isNull": True}},
            {"name": "applies_to",   "value": {"stringValue": record.get("applies_to", "")} if record.get("applies_to") else {"isNull": True}},
            {"name": "tags",         "value": {"stringValue": pg_array(tags)}},
            {"name": "s3_key",       "value": {"stringValue": s3_keys.get(doc_id, "")} if s3_keys.get(doc_id) else {"isNull": True}},
            {"name": "word_count",   "value": {"longValue": int(record.get("word_count", 0))} if record.get("word_count") else {"isNull": True}},
            {"name": "version",      "value": {"stringValue": str(record.get("version", "1.0"))}},
            {"name": "last_updated", "value": {"stringValue": str(record.get("last_updated", ""))} if record.get("last_updated") else {"isNull": True}},
        ]
        try:
            sql(upsert_sql, params)
            inserted += 1
        except ClientError as exc:
            errors += 1
            print(f"\n  Insert error for {doc_id}: {exc}", file=sys.stderr)

    print(f"  Aurora metadata: {inserted} inserted, {errors} errors")
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Meridian policy documents to S3 + Aurora")
    p.add_argument("--profile",     default=AWS_PROFILE)
    p.add_argument("--region",      default=AWS_REGION)
    p.add_argument("--data-dir",    default="data")
    p.add_argument("--environment", default=ENVIRONMENT)
    p.add_argument("--skip-aurora", action="store_true",
                   help="Skip Aurora metadata seeding (S3 upload only)")
    return p.parse_args()


def main() -> None:
    args      = parse_args()
    data_dir  = Path(args.data_dir)
    policies_dir = data_dir / "policies"

    print("Meridian policy seed")
    print(f"Profile: {args.profile}  Region: {args.region}  Environment: {args.environment}")

    session  = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfn      = session.client("cloudformation")
    s3       = session.client("s3")
    rds_data = session.client("rds-data")

    print("\nFetching stack outputs...")
    try:
        policy_bucket = get_stack_output(cfn, STACK_BASE, "PolicyDocsBucketName")
        cluster_arn   = get_stack_output(cfn, STACK_BASE, "AuroraClusterArn")
        secret_arn    = get_stack_output(cfn, STACK_BASE, "AuroraSecretArn")
        print(f"  S3 bucket: {policy_bucket}")
        print(f"  Aurora:    {cluster_arn.split(':cluster:')[-1]}")
    except Exception as exc:
        print(f"ERROR: Could not get stack outputs: {exc}", file=sys.stderr)
        print("Make sure meridian-base is deployed.", file=sys.stderr)
        sys.exit(1)

    print("\nLoading policy metadata...")
    policy_records = load_policy_metadata(data_dir)

    print("\nUploading policy documents to S3...")
    s3_keys = upload_policies_to_s3(s3, policy_bucket, policies_dir, policy_records)

    if not args.skip_aurora:
        print("\nSeeding policy metadata into Aurora...")
        seed_policy_metadata(rds_data, cluster_arn, secret_arn, policy_records, s3_keys)
    else:
        print("\nSkipping Aurora metadata (--skip-aurora)")

    print(f"\nSeed complete. {len(s3_keys)} documents in s3://{policy_bucket}/{S3_PREFIX}")


if __name__ == "__main__":
    main()
