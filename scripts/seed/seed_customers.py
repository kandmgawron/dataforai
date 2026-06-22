#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Customer seed script.

Loads the pre-generated customers_5000.json into Aurora PostgreSQL
via the RDS Data API. No Bedrock calls. No data generation.

Run after `make deploy-base`:
    python scripts/seed/seed_customers.py

Prerequisites:
    - meridian-base stack deployed
    - data/customers_5000.json (or .parquet) exists
    - AWS profile ridge-course-dev configured

Cost estimate: nil (RDS Data API only)
Runtime: ~2 minutes
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

AWS_PROFILE = "ridge-course-dev"
AWS_REGION   = "eu-west-1"
STACK_BASE   = "meridian-base"
ENVIRONMENT  = "dev"
BATCH_SIZE   = 25   # RDS Data API batch_execute_statement limit

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id             VARCHAR(20)    PRIMARY KEY,
    first_name              VARCHAR(100)   NOT NULL,
    last_name               VARCHAR(100)   NOT NULL,
    email                   VARCHAR(255),
    phone                   VARCHAR(20),
    postcode                VARCHAR(10),
    country                 CHAR(2)        DEFAULT 'GB',
    registration_date       DATE,
    segment                 VARCHAR(50),
    loyalty_tier            VARCHAR(20),
    lifetime_value_gbp      NUMERIC(12,2)  DEFAULT 0,
    order_count             INTEGER        DEFAULT 0,
    avg_order_value_gbp     NUMERIC(10,2)  DEFAULT 0,
    last_purchase_date      DATE,
    days_since_purchase     INTEGER,
    favourite_categories    TEXT[],
    preferred_store         VARCHAR(50),
    marketing_opt_in        BOOLEAN        DEFAULT FALSE,
    created_at              TIMESTAMPTZ    DEFAULT NOW(),
    updated_at              TIMESTAMPTZ    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_segment      ON customers (segment);
CREATE INDEX IF NOT EXISTS idx_customers_loyalty_tier ON customers (loyalty_tier);
CREATE INDEX IF NOT EXISTS idx_customers_last_purchase ON customers (last_purchase_date);
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
    for attempt in range(6):
        try:
            return rds_data.execute_statement(**kwargs)
        except ClientError as exc:
            if "DatabaseResumingException" in str(exc) and attempt < 5:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def load_customers(data_dir: Path) -> list[dict]:
    parquet_path = data_dir / "customers_5000.parquet"
    json_path    = data_dir / "customers_5000.json"

    if parquet_path.exists() and PANDAS_AVAILABLE:
        df = pd.read_parquet(parquet_path)
        records = df.to_dict("records")
        print(f"  Loaded {len(records):,} customers from parquet")
        return records
    elif json_path.exists():
        with open(json_path) as f:
            records = json.load(f)
        print(f"  Loaded {len(records):,} customers from JSON")
        return records
    else:
        print(f"ERROR: No customer data found in {data_dir}", file=sys.stderr)
        sys.exit(1)


def pg_array(values: list) -> str:
    """Format a Python list as a PostgreSQL array literal."""
    if not values:
        return "{}"
    return "{" + ",".join(f'"{v}"' for v in values) + "}"


def _valid_str(val) -> str | None:
    """Return string value or None if null/NaN."""
    if val is None:
        return None
    if isinstance(val, float) and (val != val):  # NaN check
        return None
    s = str(val)
    if s in ("", "nan", "None", "NaT"):
        return None
    return s


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_customers(rds_data, cluster_arn: str, secret_arn: str,
                   customers: list[dict], skip_existing: bool = True) -> int:

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
    if skip_existing:
        result = sql("SELECT COUNT(*) FROM customers;")
        existing = result["records"][0][0]["longValue"]
        if existing > 0:
            print(f"  {existing:,} customers already in Aurora — skipping existing (ON CONFLICT DO NOTHING).")

    inserted = 0
    errors   = 0
    start    = time.time()

    upsert_sql = """
INSERT INTO customers (
    customer_id, first_name, last_name, email, phone, postcode, country,
    registration_date, segment, loyalty_tier, lifetime_value_gbp, order_count,
    avg_order_value_gbp, last_purchase_date, days_since_purchase,
    favourite_categories, preferred_store, marketing_opt_in
) VALUES (
    :customer_id, :first_name, :last_name, :email, :phone, :postcode, :country,
    CAST(:registration_date AS DATE), :segment, :loyalty_tier, :lifetime_value_gbp,
    :order_count, :avg_order_value_gbp,
    CAST(:last_purchase_date AS DATE), :days_since_purchase,
    CAST(:favourite_categories AS TEXT[]), :preferred_store, :marketing_opt_in
)
ON CONFLICT (customer_id) DO NOTHING;
""".strip()

    for i, c in enumerate(customers):
        fav_cats = c.get("favourite_categories", [])
        if isinstance(fav_cats, str):
            try:
                fav_cats = json.loads(fav_cats)
            except Exception:
                fav_cats = []

        params = [
            {"name": "customer_id",          "value": {"stringValue": str(c["customer_id"])}},
            {"name": "first_name",            "value": {"stringValue": str(c.get("first_name", ""))}},
            {"name": "last_name",             "value": {"stringValue": str(c.get("last_name", ""))}},
            {"name": "email",                 "value": {"stringValue": _valid_str(c.get("email"))} if _valid_str(c.get("email")) else {"isNull": True}},
            {"name": "phone",                 "value": {"stringValue": _valid_str(c.get("phone"))} if _valid_str(c.get("phone")) else {"isNull": True}},
            {"name": "postcode",              "value": {"stringValue": _valid_str(c.get("postcode"))} if _valid_str(c.get("postcode")) else {"isNull": True}},
            {"name": "country",               "value": {"stringValue": str(c.get("country", "GB"))}},
            {"name": "registration_date",     "value": {"stringValue": str(c["registration_date"])} if _valid_str(c.get("registration_date")) else {"isNull": True}},
            {"name": "segment",               "value": {"stringValue": _valid_str(c.get("segment"))} if _valid_str(c.get("segment")) else {"isNull": True}},
            {"name": "loyalty_tier",          "value": {"stringValue": _valid_str(c.get("loyalty_tier"))} if _valid_str(c.get("loyalty_tier")) else {"isNull": True}},
            {"name": "lifetime_value_gbp",    "value": {"doubleValue": float(c.get("lifetime_value_gbp", 0) or 0)}},
            {"name": "order_count",           "value": {"longValue": int(c.get("order_count", 0) or 0)}},
            {"name": "avg_order_value_gbp",   "value": {"doubleValue": float(c.get("avg_order_value_gbp", 0) or 0)}},
            {"name": "last_purchase_date",    "value": {"stringValue": str(c["last_purchase_date"])} if _valid_str(c.get("last_purchase_date")) else {"isNull": True}},
            {"name": "days_since_purchase",   "value": {"longValue": int(c["days_since_purchase"])} if c.get("days_since_purchase") is not None and str(c["days_since_purchase"]) not in ("nan", "") else {"isNull": True}},
            {"name": "favourite_categories",  "value": {"stringValue": pg_array(fav_cats)}},
            {"name": "preferred_store",       "value": {"stringValue": _valid_str(c.get("preferred_store"))} if _valid_str(c.get("preferred_store")) else {"isNull": True}},
            {"name": "marketing_opt_in",      "value": {"booleanValue": bool(c.get("marketing_opt_in", False))}},
        ]
        try:
            sql(upsert_sql, params)
            inserted += 1
        except ClientError as exc:
            errors += 1
            if errors <= 5:
                print(f"\n  Insert error for {c.get('customer_id')}: {exc}", file=sys.stderr)

        if (i + 1) % 100 == 0 or i == len(customers) - 1:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            eta = (len(customers) - i - 1) / rate
            print(f"  Customers: {i+1:>5,}/{len(customers):,}  "
                  f"inserted={inserted:,}  errors={errors}  "
                  f"eta={eta:.0f}s", end="\r")

    print(f"\n  Done: {inserted:,} inserted, {errors} errors in {time.time()-start:.0f}s")
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Meridian customers into Aurora")
    p.add_argument("--profile",     default=AWS_PROFILE)
    p.add_argument("--region",      default=AWS_REGION)
    p.add_argument("--data-dir",    default="data")
    p.add_argument("--environment", default=ENVIRONMENT)
    p.add_argument("--limit",       type=int, default=None)
    return p.parse_args()


def main() -> None:
    args   = parse_args()
    data_dir = Path(args.data_dir)

    print("Meridian customer seed")
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
        print("Make sure meridian-base is deployed.", file=sys.stderr)
        sys.exit(1)

    print("\nLoading customers...")
    customers = load_customers(data_dir)

    if args.limit:
        customers = customers[:args.limit]
        print(f"  Limited to {args.limit:,} (--limit)")

    print("\nSeeding Aurora...")
    seed_customers(rds_data, cluster_arn, secret_arn, customers)

    print("\nSeed complete.")


if __name__ == "__main__":
    main()
