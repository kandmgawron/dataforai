#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Conversation seed script.

Loads the pre-generated conversations_50000.json into DynamoDB
(meridian-conversations-{env} table). No Bedrock calls. No data generation.

Run after `make deploy-base`:
    python scripts/seed/seed_conversations.py

Prerequisites:
    - meridian-base stack deployed
    - data/conversations_50000.json (or .parquet) exists
    - AWS profile ridge-course-dev configured

DynamoDB table: meridian-conversations-{environment}
  Partition key: customer_id (S)
  Sort key:      conversation_id (S)

Cost estimate: nil (DynamoDB on-demand pricing, ~50,000 writes ≈ £0.05)
Runtime: ~3-5 minutes
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
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
AWS_REGION   = "eu-west-1"
STACK_BASE   = "meridian-base"
ENVIRONMENT  = "dev"
BATCH_SIZE   = 25   # DynamoDB batch_write_item limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_stack_output(cfn, stack_name: str, key: str) -> str:
    resp = cfn.describe_stacks(StackName=stack_name)
    for o in resp["Stacks"][0].get("Outputs", []):
        if o["OutputKey"] == key:
            return o["OutputValue"]
    raise ValueError(f"Output '{key}' not found in stack '{stack_name}'")


def load_conversations(data_dir: Path) -> list[dict]:
    parquet_path = data_dir / "conversations_50000.parquet"
    json_path    = data_dir / "conversations_50000.json"

    if parquet_path.exists() and PANDAS_AVAILABLE:
        df = pd.read_parquet(parquet_path)
        # Convert NaN to None for clean serialisation
        records = df.where(pd.notna(df), None).to_dict("records")
        print(f"  Loaded {len(records):,} conversations from parquet")
        return records
    elif json_path.exists():
        with open(json_path) as f:
            records = json.load(f)
        print(f"  Loaded {len(records):,} conversations from JSON")
        return records
    else:
        print(f"ERROR: No conversation data found in {data_dir}", file=sys.stderr)
        sys.exit(1)


def to_dynamo_item(c: dict) -> dict:
    """
    Convert a conversation record to a DynamoDB item.
    DynamoDB requires Decimal for numbers; no floats.
    """
    # Parse messages if stored as a JSON string
    messages = c.get("messages", "[]")
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except Exception:
            messages = []

    # Parse product_skus_mentioned if stored as a string
    skus = c.get("product_skus_mentioned", [])
    if isinstance(skus, str):
        try:
            skus = json.loads(skus)
        except Exception:
            skus = []

    item: dict = {
        "customer_id":      {"S": str(c["customer_id"])},
        "conversation_id":  {"S": str(c["conversation_id"])},
        "channel":          {"S": str(c.get("channel", "unknown"))},
        "topic":            {"S": str(c.get("topic", "unknown"))},
        "status":           {"S": str(c.get("status", "unknown"))},
        "num_turns":        {"N": str(int(c.get("num_turns", 0)))},
        "messages":         {"S": json.dumps(messages)},
    }

    if c.get("created_at"):
        item["created_at"] = {"S": str(c["created_at"])}

    if skus:
        item["product_skus_mentioned"] = {"SS": [str(s) for s in skus]}

    if c.get("resolution_type"):
        item["resolution_type"] = {"S": str(c["resolution_type"])}

    # Strip internal keys prefixed with _
    return item


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_conversations(dynamodb, table_name: str, conversations: list[dict]) -> int:
    table = dynamodb.Table(table_name)

    inserted = 0
    errors   = 0
    start    = time.time()

    # DynamoDB batch_writer handles retry and chunking automatically
    with table.batch_writer() as batch:
        for i, c in enumerate(conversations):
            try:
                # Convert to flat Python dict (batch_writer uses resource-style)
                messages = c.get("messages", "[]")
                if isinstance(messages, str):
                    try:
                        messages = json.loads(messages)
                    except Exception:
                        messages = []

                skus = c.get("product_skus_mentioned", [])
                if isinstance(skus, str):
                    try:
                        skus = json.loads(skus)
                    except Exception:
                        skus = []

                item = {
                    "customer_id":     str(c["customer_id"]),
                    "conversation_id": str(c["conversation_id"]),
                    "channel":         str(c.get("channel", "unknown")),
                    "topic":           str(c.get("topic", "unknown")),
                    "status":          str(c.get("status", "unknown")),
                    "num_turns":       int(c.get("num_turns", 0)),
                    "messages":        json.dumps(messages),
                }

                if c.get("created_at"):
                    item["created_at"] = str(c["created_at"])
                if skus:
                    item["product_skus_mentioned"] = list(set(str(s) for s in skus))
                if c.get("resolution_type"):
                    item["resolution_type"] = str(c["resolution_type"])

                batch.put_item(Item=item)
                inserted += 1

            except Exception as exc:
                errors += 1
                if errors <= 5:
                    print(f"\n  Error on {c.get('conversation_id')}: {exc}", file=sys.stderr)

            if (i + 1) % 1000 == 0 or i == len(conversations) - 1:
                elapsed = time.time() - start
                rate    = (i + 1) / elapsed
                eta     = (len(conversations) - i - 1) / rate if rate > 0 else 0
                print(f"  Conversations: {i+1:>6,}/{len(conversations):,}  "
                      f"({(i+1)/len(conversations)*100:.0f}%)  "
                      f"inserted={inserted:,}  errors={errors}  "
                      f"rate={rate:.0f}/s  eta={eta:.0f}s", end="\r")

    print(f"\n  Done: {inserted:,} inserted, {errors} errors in {time.time()-start:.0f}s")
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Meridian conversations into DynamoDB")
    p.add_argument("--profile",     default=AWS_PROFILE)
    p.add_argument("--region",      default=AWS_REGION)
    p.add_argument("--data-dir",    default="data")
    p.add_argument("--environment", default=ENVIRONMENT)
    p.add_argument("--limit",       type=int, default=None,
                   help="Process first N conversations only (for testing)")
    return p.parse_args()


def main() -> None:
    args     = parse_args()
    data_dir = Path(args.data_dir)

    print("Meridian conversation seed")
    print(f"Profile: {args.profile}  Region: {args.region}  Environment: {args.environment}")

    session  = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfn      = session.client("cloudformation")
    dynamodb = session.resource("dynamodb")

    print("\nFetching stack outputs...")
    try:
        table_name = get_stack_output(cfn, STACK_BASE, "ConversationsTableName")
        print(f"  DynamoDB table: {table_name}")
    except Exception as exc:
        print(f"ERROR: Could not get stack outputs: {exc}", file=sys.stderr)
        print("Make sure meridian-base is deployed.", file=sys.stderr)
        sys.exit(1)

    # Verify table exists
    try:
        dynamodb.Table(table_name).load()
    except ClientError as exc:
        print(f"ERROR: Table '{table_name}' not found: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nLoading conversations...")
    conversations = load_conversations(data_dir)

    if args.limit:
        conversations = conversations[:args.limit]
        print(f"  Limited to {args.limit:,} (--limit)")

    print(f"\nSeeding {len(conversations):,} conversations into DynamoDB...")
    seed_conversations(dynamodb, table_name, conversations)

    print("\nSeed complete.")


if __name__ == "__main__":
    main()
