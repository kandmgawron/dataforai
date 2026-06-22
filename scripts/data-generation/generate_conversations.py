#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Customer service conversation generation script.

Generates synthetic customer service conversations for the Ridge AI course dataset.
Amazon Bedrock Nova generates multi-turn dialogue; all structural fields
(IDs, channels, topics, statuses, timestamps) are deterministically seeded.

Usage:
    # 100-conversation spot-check sample
    python generate_conversations.py --count 100 --output ../../data/

    # Full 50,000-conversation dataset
    python generate_conversations.py --count 50000 --output ../../data/ --seed 42

Requirements:
    pip install boto3 pandas pyarrow tqdm
    AWS profile 'ridge-course-dev' with Bedrock model access in eu-west-1
    products_full_40000.json must exist in the output directory
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_PROFILE = "ridge-course-dev"
AWS_REGION = "eu-west-1"
BEDROCK_MODEL = "eu.amazon.nova-2-lite-v1:0"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOPIC_CONTEXTS = {
    "product_query": "Customer asks about a specific product's features or availability.",
    "recommendation": "Customer wants help choosing the right gear for a trip.",
    "returns": "Customer wants to return or exchange a product.",
    "order_tracking": "Customer asking about order status or delivery.",
    "product_advice": "Customer wants advice on gear care or use.",
    "complaint": "Customer is unhappy with a product or experience.",
}

# Channel weights: web_chat 40%, mobile_app 35%, email 15%, phone_transcript 10%
CHANNELS = ["web_chat", "mobile_app", "email", "phone_transcript"]
CHANNEL_WEIGHTS = [0.40, 0.35, 0.15, 0.10]

# Topic weights: product_query 25%, recommendation 25%, returns 15%, order_tracking 10%,
#                product_advice 15%, complaint 10%
TOPICS = ["product_query", "recommendation", "returns", "order_tracking", "product_advice", "complaint"]
TOPIC_WEIGHTS = [0.25, 0.25, 0.15, 0.10, 0.15, 0.10]

# Status weights: resolved 80%, escalated 10%, abandoned 10%
STATUSES = ["resolved", "escalated", "abandoned"]
STATUS_WEIGHTS = [0.80, 0.10, 0.10]

# Resolution types when status == resolved
RESOLUTION_TYPES = ["answered", "refund_issued", "replacement_sent", "escalated_to_human"]
RESOLUTION_WEIGHTS = [0.60, 0.20, 0.10, 0.10]

# Topics where product mention is sometimes absent
NO_PRODUCT_TOPICS = {"order_tracking", "complaint"}


# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------


def _generate_conversation(
    client: Any,
    conversation_id: str,
    channel: str,
    topic: str,
    num_turns: int,
    product_name: str | None,
    model_id: str,
) -> str:
    """Call Bedrock to generate a multi-turn conversation. Returns raw response text."""
    product_line = f'Product: "{product_name}"' if product_name else "No specific product."
    prompt = (
        f"Write a {num_turns}-turn customer service chat for Meridian Outdoor Co. (UK outdoor retailer).\n"
        f"Channel: {channel}. Topic: {topic}. {TOPIC_CONTEXTS[topic]}\n"
        f"{product_line}\n"
        f"Ridge Assist (AI) is helpful and friendly. UK English.\n"
        f'Return ONLY JSON: {{"messages": [{{"role": "customer", "content": "..."}}, {{"role": "assistant", "content": "..."}}]}}\n'
        f"Alternate customer/assistant. {num_turns} turns each. 1-2 sentences per message."
    )
    body = json.dumps({
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"max_new_tokens": 400, "temperature": 0.7},
    })
    for attempt in range(4):
        try:
            response = client.invoke_model(
                modelId=model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            text = result["output"]["message"]["content"][0]["text"].strip()
            return text
        except Exception as exc:
            if "Throttling" in type(exc).__name__ and attempt < 3:
                time.sleep((2 ** attempt) + random.random())
                continue
            return ""
    return ""


def _parse_messages(raw_response: str) -> str:
    """Extract the messages JSON string from a Bedrock response."""
    text = raw_response
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    try:
        parsed = json.loads(text)
        messages_str = json.dumps(parsed.get("messages", []))
    except (json.JSONDecodeError, ValueError):
        messages_str = "[]"
    return messages_str


# ---------------------------------------------------------------------------
# Conversation assembly
# ---------------------------------------------------------------------------


def _created_at(rng: random.Random) -> str:
    """Random datetime in the last 2 years."""
    base = datetime.now(tz=timezone.utc) - timedelta(days=2 * 365)
    delta = timedelta(seconds=rng.randint(0, 2 * 365 * 24 * 3600))
    dt = base + delta
    return dt.isoformat()


def build_conversation_records(
    count: int,
    featured_products: list[dict[str, Any]],
    seed: int = 42,
) -> list[dict[str, Any]]:
    """
    Build structural fields for `count` conversations.
    Returns a list of dicts with messages left as "[]".
    """
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []

    for i in range(count):
        channel = rng.choices(CHANNELS, weights=CHANNEL_WEIGHTS, k=1)[0]
        topic = rng.choices(TOPICS, weights=TOPIC_WEIGHTS, k=1)[0]
        status = rng.choices(STATUSES, weights=STATUS_WEIGHTS, k=1)[0]
        num_turns = rng.randint(3, 8)

        # Determine resolution type
        if status == "resolved":
            resolution_type = rng.choices(RESOLUTION_TYPES, weights=RESOLUTION_WEIGHTS, k=1)[0]
        else:
            resolution_type = None

        # Determine product SKUs mentioned (0-2)
        # Some topics sometimes have no product
        if topic in NO_PRODUCT_TOPICS and rng.random() < 0.40:
            product_skus_mentioned: list[str] = []
            product_name: str | None = None
        else:
            n_products = rng.choices([0, 1, 2], weights=[0.15, 0.60, 0.25], k=1)[0]
            if n_products == 0 or not featured_products:
                product_skus_mentioned = []
                product_name = None
            else:
                sampled = rng.sample(featured_products, min(n_products, len(featured_products)))
                product_skus_mentioned = [p["sku"] for p in sampled]
                product_name = sampled[0]["name"]

        records.append({
            "conversation_id": f"CONV-{i:06d}",
            "customer_id": f"CUST-{rng.randint(1, 5000):05d}",
            "channel": channel,
            "topic": topic,
            "status": status,
            "created_at": _created_at(rng),
            "num_turns": num_turns,
            "messages": "[]",
            "product_skus_mentioned": product_skus_mentioned,
            "resolution_type": resolution_type,
            # Store product_name temporarily for Bedrock generation; removed before output
            "_product_name": product_name,
        })

    return records


# ---------------------------------------------------------------------------
# Bedrock generation (threaded)
# ---------------------------------------------------------------------------


def _generate_one_conversation(
    args_tuple: tuple[Any, dict[str, Any], str],
) -> dict[str, Any]:
    client, record, model_id = args_tuple
    raw = _generate_conversation(
        client,
        record["conversation_id"],
        record["channel"],
        record["topic"],
        record["num_turns"],
        record["_product_name"],
        model_id,
    )
    record["messages"] = _parse_messages(raw)
    del record["_product_name"]
    return record


def generate_conversation_messages(
    client: Any,
    records: list[dict[str, Any]],
    model_id: str = BEDROCK_MODEL,
    workers: int = 25,
) -> list[dict[str, Any]]:
    results: dict[int, dict[str, Any]] = {}
    tasks = [(client, record, model_id) for record in records]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_generate_one_conversation, task): i
            for i, task in enumerate(tasks)
        }
        with tqdm(total=len(records), desc="Generating conversations", unit="conversation") as bar:
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()
                bar.update(1)

    return [results[i] for i in range(len(records))]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_outputs(records: list[dict[str, Any]], output_dir: Path, count: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"conversations_{count}"

    # Serialise product_skus_mentioned as JSON string for parquet
    flat_records = []
    for r in records:
        row = dict(r)
        row["product_skus_mentioned"] = json.dumps(r["product_skus_mentioned"])
        flat_records.append(row)

    # JSON — store original (with list for product_skus_mentioned)
    json_path = output_dir / f"{stem}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str, ensure_ascii=False)
    print(f"  Wrote {json_path} ({len(records)} conversations)")

    # Parquet
    df = pd.DataFrame(flat_records)
    parquet_path = output_dir / f"{stem}.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"  Wrote {parquet_path} ({df.shape[0]} rows x {df.shape[1]} columns)")

    # Summary
    print("\nTopic distribution:")
    topic_counts = df["topic"].value_counts()
    for topic, n in topic_counts.items():
        pct = 100 * n / len(df)
        print(f"  {topic:<20} {n:>7,}  ({pct:.1f}%)")

    print("\nChannel distribution:")
    channel_counts = df["channel"].value_counts()
    for channel, n in channel_counts.items():
        pct = 100 * n / len(df)
        print(f"  {channel:<20} {n:>7,}  ({pct:.1f}%)")

    print("\nStatus breakdown:")
    status_counts = df["status"].value_counts()
    for status, n in status_counts.items():
        pct = 100 * n / len(df)
        print(f"  {status:<20} {n:>7,}  ({pct:.1f}%)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic Meridian Outdoor Co. customer service conversations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--count", type=int, default=50000,
                   help="Number of conversations to generate (default: 50000)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed (default: 42)")
    p.add_argument("--output", type=str, default="../../data/",
                   help="Output directory (default: ../../data/)")
    p.add_argument("--workers", type=int, default=25,
                   help="Concurrent Bedrock threads (default: 25)")
    p.add_argument("--profile", type=str, default=AWS_PROFILE,
                   help=f"AWS profile name (default: {AWS_PROFILE})")
    p.add_argument("--region", type=str, default=AWS_REGION,
                   help=f"AWS region (default: {AWS_REGION})")
    p.add_argument("--model", type=str, default=BEDROCK_MODEL,
                   help=f"Bedrock model ID (default: {BEDROCK_MODEL})")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output)

    print(f"Meridian conversation generation — {args.count:,} conversations (seed={args.seed})")
    print(f"Output: {output_dir.resolve()}")
    print(f"Bedrock: {args.model} in {args.region} (profile: {args.profile})")
    print()

    # 1. Load products
    products_path = output_dir / "products_full_40000.json"
    if not products_path.exists():
        print(f"ERROR: {products_path} not found. Run generate_products.py first.", file=sys.stderr)
        sys.exit(1)
    print(f"Loading products from {products_path}...")
    with open(products_path) as f:
        all_products = json.load(f)
    print(f"  Loaded {len(all_products)} products")

    # 2. Select 300 featured products (seed-stable)
    feat_rng = random.Random(args.seed)
    featured_products = feat_rng.sample(
        [{"sku": p["sku"], "name": p["name"]} for p in all_products],
        min(300, len(all_products)),
    )
    print(f"  Selected {len(featured_products)} featured products for conversation context")

    # 3. Build structural fields
    print(f"\nBuilding {args.count:,} conversation records...")
    records = build_conversation_records(args.count, featured_products, seed=args.seed)
    print(f"  {len(records):,} records built")

    # 4. Generate messages via Bedrock
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        bedrock = session.client("bedrock-runtime")
    except Exception as exc:
        print(f"Could not create Bedrock client: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nGenerating conversation messages via Bedrock ({args.model}, {args.workers} workers)...")
    records = generate_conversation_messages(bedrock, records, model_id=args.model, workers=args.workers)

    # 5. Write outputs
    print("\nWriting outputs...")
    write_outputs(records, output_dir, args.count)
    print("\nDone.")


if __name__ == "__main__":
    main()
