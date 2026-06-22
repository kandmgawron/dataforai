#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Review seed script.

Loads the pre-generated reviews_200000.parquet into Aurora PostgreSQL
via the RDS Data API. No Bedrock calls. No data generation.

Run after seed_products.py and seed_customers.py:
    python scripts/seed/seed_reviews.py

Prerequisites:
    - meridian-base stack deployed
    - products and customers already seeded (foreign key references)
    - data/reviews_200000.parquet (or .json) exists
    - AWS profile ridge-course-dev configured

Cost estimate: nil (RDS Data API only)
Runtime: ~15-25 minutes (200,000 rows via Data API)
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
BATCH_SIZE   = 25   # rows per batch_execute_statement call

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reviews (
    review_id        VARCHAR(20)    PRIMARY KEY,
    product_sku      VARCHAR(60)    NOT NULL,
    product_name     VARCHAR(255),
    product_l2       VARCHAR(100),
    customer_id      VARCHAR(20),
    rating           SMALLINT       NOT NULL CHECK (rating BETWEEN 1 AND 5),
    sentiment        VARCHAR(20),
    title            VARCHAR(255),
    body             TEXT,
    verified_purchase BOOLEAN       DEFAULT FALSE,
    helpful_votes    INTEGER        DEFAULT 0,
    total_votes      INTEGER        DEFAULT 0,
    created_at       TIMESTAMPTZ,
    source           VARCHAR(20),
    indexed_at       TIMESTAMPTZ    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reviews_product_sku  ON reviews (product_sku);
CREATE INDEX IF NOT EXISTS idx_reviews_customer_id  ON reviews (customer_id);
CREATE INDEX IF NOT EXISTS idx_reviews_rating        ON reviews (rating);
CREATE INDEX IF NOT EXISTS idx_reviews_sentiment     ON reviews (sentiment);
CREATE INDEX IF NOT EXISTS idx_reviews_created_at    ON reviews (created_at);
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


def load_reviews(data_dir: Path) -> list[dict]:
    parquet_path = data_dir / "reviews_200000.parquet"
    json_path    = data_dir / "reviews_200000.json"

    if parquet_path.exists() and PANDAS_AVAILABLE:
        df = pd.read_parquet(parquet_path)
        records = df.to_dict("records")
        print(f"  Loaded {len(records):,} reviews from parquet")
        return records
    elif json_path.exists():
        print(f"  Loading {json_path.name} (111MB — may take a moment)...")
        with open(json_path) as f:
            records = json.load(f)
        print(f"  Loaded {len(records):,} reviews from JSON")
        return records
    else:
        print(f"ERROR: No review data found in {data_dir}", file=sys.stderr)
        sys.exit(1)


def make_params(r: dict) -> list[dict]:
    """Build RDS Data API parameter list for one review."""
    return [
        {"name": "review_id",         "value": {"stringValue": str(r["review_id"])}},
        {"name": "product_sku",       "value": {"stringValue": str(r["product_sku"])}},
        {"name": "product_name",      "value": {"stringValue": str(r["product_name"])} if r.get("product_name") else {"isNull": True}},
        {"name": "product_l2",        "value": {"stringValue": str(r["product_l2"])}   if r.get("product_l2")   else {"isNull": True}},
        {"name": "customer_id",       "value": {"stringValue": str(r["customer_id"])}  if r.get("customer_id")  else {"isNull": True}},
        {"name": "rating",            "value": {"longValue":   int(r["rating"])}},
        {"name": "sentiment",         "value": {"stringValue": str(r["sentiment"])}    if r.get("sentiment")    else {"isNull": True}},
        {"name": "title",             "value": {"stringValue": str(r["title"])[:255]}  if r.get("title")        else {"isNull": True}},
        {"name": "body",              "value": {"stringValue": str(r["body"])}          if r.get("body")         else {"isNull": True}},
        {"name": "verified_purchase", "value": {"booleanValue": bool(r.get("verified_purchase", False))}},
        {"name": "helpful_votes",     "value": {"longValue":   int(r.get("helpful_votes", 0))}},
        {"name": "total_votes",       "value": {"longValue":   int(r.get("total_votes", 0))}},
        {"name": "created_at",        "value": {"stringValue": str(r["created_at"])}   if r.get("created_at")   else {"isNull": True}},
        {"name": "source",            "value": {"stringValue": str(r["source"])}        if r.get("source")       else {"isNull": True}},
    ]


UPSERT_SQL = """
INSERT INTO reviews (
    review_id, product_sku, product_name, product_l2, customer_id,
    rating, sentiment, title, body, verified_purchase,
    helpful_votes, total_votes, created_at, source
) VALUES (
    :review_id, :product_sku, :product_name, :product_l2, :customer_id,
    :rating, :sentiment, :title, :body, :verified_purchase,
    :helpful_votes, :total_votes, CAST(:created_at AS TIMESTAMPTZ), :source
)
ON CONFLICT (review_id) DO NOTHING;
""".strip()


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_reviews(rds_data, cluster_arn: str, secret_arn: str,
                 reviews: list[dict]) -> int:

    def sql(statement, params=None):
        return run_sql(rds_data, cluster_arn, secret_arn, statement, params)

    # Create schema
    print("  Creating schema...")
    for stmt in SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                sql(stmt + ";")
            except ClientError as exc:
                if "already exists" not in str(exc):
                    print(f"  Schema warning: {exc}", file=sys.stderr)

    # Check existing
    result = sql("SELECT COUNT(*) FROM reviews;")
    existing = result["records"][0][0]["longValue"]
    if existing > 0:
        print(f"  {existing:,} reviews already in Aurora — skipping existing (ON CONFLICT DO NOTHING).")

    inserted = 0
    errors   = 0
    start    = time.time()

    # Use batch_execute_statement for throughput
    for batch_start in range(0, len(reviews), BATCH_SIZE):
        batch = reviews[batch_start:batch_start + BATCH_SIZE]
        param_sets = [make_params(r) for r in batch]

        for attempt in range(3):
            try:
                resp = rds_data.batch_execute_statement(
                    resourceArn=cluster_arn,
                    secretArn=secret_arn,
                    database="meridian",
                    sql=UPSERT_SQL,
                    parameterSets=param_sets,
                )
                inserted += len(batch)
                break
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "ThrottlingException" and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                errors += len(batch)
                if errors <= BATCH_SIZE * 3:
                    print(f"\n  Batch error at {batch_start}: {exc}", file=sys.stderr)
                break

        processed = batch_start + len(batch)
        if processed % 2500 == 0 or processed >= len(reviews):
            elapsed = time.time() - start
            rate = processed / elapsed
            eta = (len(reviews) - processed) / rate if rate > 0 else 0
            print(f"  Reviews: {processed:>7,}/{len(reviews):,}  "
                  f"({processed/len(reviews)*100:.0f}%)  "
                  f"inserted={inserted:,}  errors={errors}  "
                  f"rate={rate:.0f}/s  eta={eta:.0f}s", end="\r")

    print(f"\n  Done: {inserted:,} inserted, {errors} errors in {time.time()-start:.0f}s")
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Meridian reviews into Aurora")
    p.add_argument("--profile",     default=AWS_PROFILE)
    p.add_argument("--region",      default=AWS_REGION)
    p.add_argument("--data-dir",    default="data")
    p.add_argument("--environment", default=ENVIRONMENT)
    p.add_argument("--limit",       type=int, default=None,
                   help="Process first N reviews only (for testing)")
    return p.parse_args()


def main() -> None:
    args     = parse_args()
    data_dir = Path(args.data_dir)

    print("Meridian review seed")
    print(f"Profile: {args.profile}  Region: {args.region}  Environment: {args.environment}")

    session  = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfn      = session.client("cloudformation")
    rds_data = session.client("rds-data")

    print("\nFetching stack outputs...")
    try:
        cluster_arn = get_stack_output(cfn, STACK_BASE, "AuroraClusterArn")
        secret_arn  = get_stack_output(cfn, STACK_BASE, "AuroraSecretArn")
        print(f"  Aurora: {cluster_arn.split(':cluster:')[-1]}")
    except Exception as exc:
        print(f"ERROR: Could not get stack outputs: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nLoading reviews...")
    reviews = load_reviews(data_dir)

    if args.limit:
        reviews = reviews[:args.limit]
        print(f"  Limited to {args.limit:,} (--limit)")

    print(f"\nSeeding {len(reviews):,} reviews into Aurora...")
    print(f"  Using batch_execute_statement (batch size {BATCH_SIZE})")
    print(f"  Estimated time: {len(reviews) // 500:.0f}-{len(reviews) // 300:.0f} minutes")
    seed_reviews(rds_data, cluster_arn, secret_arn, reviews)

    print("\nSeed complete.")


if __name__ == "__main__":
    main()
