#!/usr/bin/env python3
"""
Meridian Outdoor Co. — Product seed script.

Loads the 40,000-product catalogue into Aurora PostgreSQL (via RDS Data API)
and indexes it into OpenSearch Serverless with Titan embeddings.

Run once after `make deploy-vectors`:
    python scripts/seed/seed_products.py

Prerequisites:
    - meridian-base stack deployed
    - meridian-vectors stack deployed
    - data/products_full_40000.parquet exists (or .json)
    - AWS profile ridge-course-dev with access to Bedrock, RDS Data API, OpenSearch

Cost estimate (one-time run):
    ~40,000 x Titan Embed v2 calls ≈ $0.80 USD
    Runtime: 30-45 minutes
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
except ImportError:
    print("ERROR: pandas not installed. Run: pip install pandas pyarrow", file=sys.stderr)
    sys.exit(1)

try:
    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth
    OPENSEARCH_AVAILABLE = True
except ImportError:
    OPENSEARCH_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_PROFILE   = "ridge-course-dev"
AWS_REGION    = "eu-west-1"
EMBED_MODEL   = "amazon.titan-embed-text-v2:0"
EMBED_DIMS    = 1024
STACK_BASE    = "meridian-base"
ENVIRONMENT   = "dev"

# Aurora schema
SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS products (
    sku                VARCHAR(60)  PRIMARY KEY,
    name               VARCHAR(255) NOT NULL,
    l1                 VARCHAR(100),
    l2                 VARCHAR(100),
    l3                 VARCHAR(100),
    brand              VARCHAR(100),
    price_gbp          NUMERIC(10,2),
    sale_price_gbp     NUMERIC(10,2),
    on_sale            BOOLEAN DEFAULT FALSE,
    weight_g           INTEGER,
    short_description  TEXT,
    long_description   TEXT,
    attributes         JSONB,
    activities         TEXT[],
    seasons            TEXT[],
    in_stock           BOOLEAN DEFAULT TRUE,
    stock_total        INTEGER DEFAULT 0,
    embedding          vector({dims}),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_l1   ON products (l1);
CREATE INDEX IF NOT EXISTS idx_products_l2   ON products (l2);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products (brand);
CREATE INDEX IF NOT EXISTS idx_products_price ON products (price_gbp);
CREATE INDEX IF NOT EXISTS idx_products_stock ON products (in_stock);
""".format(dims=EMBED_DIMS)

VECTOR_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_products_embedding
ON products
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
"""

OPENSEARCH_INDEX_BODY = {
    "settings": {
        "index": {
            "number_of_shards": 2,
            "number_of_replicas": 0,
        }
    },
    "mappings": {
        "properties": {
            "sku":               {"type": "keyword"},
            "name":              {"type": "text", "analyzer": "english", "fields": {"keyword": {"type": "keyword"}}},
            "l1":                {"type": "keyword"},
            "l2":                {"type": "keyword"},
            "l3":                {"type": "keyword"},
            "brand":             {"type": "keyword"},
            "price_gbp":         {"type": "float"},
            "on_sale":           {"type": "boolean"},
            "short_description": {"type": "text", "analyzer": "english"},
            "long_description":  {"type": "text", "analyzer": "english"},
            "colours":           {"type": "keyword"},
            "gender":            {"type": "keyword"},
            "activities":        {"type": "keyword"},
            "seasons":           {"type": "keyword"},
            "in_stock":          {"type": "boolean"},
            "stock_total":       {"type": "integer"},
        }
    },
}

# ponytail: knn_vector field added later when embeddings are generated (Module 3).
# Separate index mapping update script handles that.


# ---------------------------------------------------------------------------
# AWS helpers
# ---------------------------------------------------------------------------

def get_stack_output(cfn, stack_name: str, key: str) -> str:
    resp = cfn.describe_stacks(StackName=stack_name)
    outputs = resp["Stacks"][0].get("Outputs", [])
    for o in outputs:
        if o["OutputKey"] == key:
            return o["OutputValue"]
    raise ValueError(f"Output '{key}' not found in stack '{stack_name}'")


def generate_embedding(bedrock_runtime, text: str, max_retries: int = 4) -> list[float] | None:
    """Generate a Titan Embed v2 embedding. Returns None on failure."""
    body = json.dumps({"inputText": text, "dimensions": EMBED_DIMS, "normalize": True})
    for attempt in range(max_retries):
        try:
            resp = bedrock_runtime.invoke_model(
                modelId=EMBED_MODEL,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(resp["body"].read())
            return result["embedding"]
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ThrottlingException" and attempt < max_retries - 1:
                time.sleep((2 ** attempt) + 0.5)
                continue
            print(f"  ⚠ Embedding error: {exc}", file=sys.stderr)
            return None
    return None


def embed_text_for_product(p: dict) -> str:
    """Build the text to embed for a product."""
    parts = [p.get("name", ""), p.get("category_l2") or p.get("l2", ""), p.get("brand", "")]
    if p.get("short_description"):
        parts.append(p["short_description"])
    elif p.get("long_description"):
        parts.append(p["long_description"][:300])
    # Add key attributes
    attrs = p.get("attributes", {})
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except Exception:
            attrs = {}
    for k, v in list(attrs.items())[:4]:
        parts.append(f"{k}: {v}")
    return " | ".join(str(x) for x in parts if x)


# ---------------------------------------------------------------------------
# Aurora seeding (RDS Data API)
# ---------------------------------------------------------------------------

def seed_aurora(rds_data, cluster_arn: str, secret_arn: str, products: list[dict],
                embeddings: dict[str, list[float]], skip_existing: bool = True) -> int:
    """Insert products into Aurora via RDS Data API. Returns number inserted."""

    def sql(statement: str, params=None):
        kwargs = dict(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database="meridian",
            sql=statement,
        )
        if params:
            kwargs["parameters"] = params
        return rds_data.execute_statement(**kwargs)

    # Create schema
    print("  Creating schema...")
    # Run each statement separately (Data API doesn't support multi-statement)
    for stmt in SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                sql(stmt + ";")
            except ClientError as exc:
                if "already exists" not in str(exc):
                    print(f"  Schema warning: {exc}", file=sys.stderr)

    # Count existing
    if skip_existing:
        result = sql("SELECT COUNT(*) FROM products;")
        existing = result["records"][0][0]["longValue"]
        if existing > 0:
            print(f"  {existing:,} products already in Aurora. Skipping existing.")

    inserted = 0
    errors = 0
    batch_size = 25  # RDS Data API batch_execute_statement limit

    upsert_sql = """
INSERT INTO products (
    sku, name, l1, l2, l3, brand, price_gbp, sale_price_gbp, on_sale,
    weight_g, short_description, long_description, attributes,
    activities, seasons, in_stock, stock_total, embedding
) VALUES (
    :sku, :name, :l1, :l2, :l3, :brand, :price, :sale_price, :on_sale,
    :weight, :short_desc, :long_desc, CAST(:attrs AS JSONB),
    CAST(:activities AS TEXT[]), CAST(:seasons AS TEXT[]), :in_stock, :stock_total,
    CAST(:embedding AS vector)
)
ON CONFLICT (sku) DO NOTHING;
""".strip()

    def make_product_params(p):
        sku = p.get("sku", "")
        embedding = embeddings.get(sku)
        embedding_str = f"[{','.join(str(round(v, 6)) for v in embedding)}]" if embedding else None

        attrs = p.get("attributes", {})
        if isinstance(attrs, dict):
            attrs_json = json.dumps(attrs)
        else:
            attrs_json = str(attrs)

        activities = p.get("activity_tags") or p.get("activities", [])
        seasons = p.get("season") or p.get("seasons", [])
        if isinstance(activities, str):
            try:
                activities = json.loads(activities)
            except Exception:
                activities = []
        if isinstance(seasons, str):
            try:
                seasons = json.loads(seasons)
            except Exception:
                seasons = []

        pg_activities = "{" + ",".join(f'"{a}"' for a in activities) + "}"
        pg_seasons    = "{" + ",".join(f'"{s}"' for s in seasons) + "}"

        # Handle NaN in sale_price
        sale_price = p.get("sale_price_gbp")
        has_sale_price = sale_price is not None and str(sale_price) not in ("nan", "")
        try:
            sale_price_val = float(sale_price) if has_sale_price else 0
            if sale_price_val != sale_price_val:  # NaN check
                has_sale_price = False
        except (TypeError, ValueError):
            has_sale_price = False

        return [
            {"name": "sku",         "value": {"stringValue": sku}},
            {"name": "name",        "value": {"stringValue": p.get("name", "")}},
            {"name": "l1",          "value": {"stringValue": p.get("category_l1") or p.get("l1", "")} if (p.get("category_l1") or p.get("l1")) else {"isNull": True}},
            {"name": "l2",          "value": {"stringValue": p.get("category_l2") or p.get("l2", "")} if (p.get("category_l2") or p.get("l2")) else {"isNull": True}},
            {"name": "l3",          "value": {"stringValue": p.get("category_l3") or p.get("l3", "")} if (p.get("category_l3") or p.get("l3")) else {"isNull": True}},
            {"name": "brand",       "value": {"stringValue": p.get("brand", "")} if p.get("brand") else {"isNull": True}},
            {"name": "price",       "value": {"doubleValue": float(p.get("price_gbp", 0))}},
            {"name": "sale_price",  "value": {"doubleValue": sale_price_val} if has_sale_price else {"isNull": True}},
            {"name": "on_sale",     "value": {"booleanValue": bool(p.get("on_sale", False))}},
            {"name": "weight",      "value": {"longValue": int(p.get("weight_grams") or p.get("weight_g", 0) or 0)} if (p.get("weight_grams") or p.get("weight_g")) else {"isNull": True}},
            {"name": "short_desc",  "value": {"stringValue": p.get("short_description", "")} if p.get("short_description") else {"isNull": True}},
            {"name": "long_desc",   "value": {"stringValue": p.get("long_description", "")} if p.get("long_description") else {"isNull": True}},
            {"name": "attrs",       "value": {"stringValue": attrs_json}},
            {"name": "activities",  "value": {"stringValue": pg_activities}},
            {"name": "seasons",     "value": {"stringValue": pg_seasons}},
            {"name": "in_stock",    "value": {"booleanValue": bool(p.get("in_stock", p.get("is_active", True)))}},
            {"name": "stock_total", "value": {"longValue": int(p.get("stock_total", p.get("total_stock", 0)) or 0)}},
            {"name": "embedding",   "value": {"stringValue": embedding_str} if embedding_str else {"isNull": True}},
        ]

    start = time.time()
    for batch_start in range(0, len(products), batch_size):
        batch = products[batch_start:batch_start + batch_size]
        param_sets = [make_product_params(p) for p in batch]

        for attempt in range(3):
            try:
                rds_data.batch_execute_statement(
                    resourceArn=cluster_arn,
                    secretArn=secret_arn,
                    database="meridian",
                    sql=upsert_sql,
                    parameterSets=param_sets,
                )
                inserted += len(batch)
                break
            except ClientError as exc:
                code = str(exc)
                if "ThrottlingException" in code and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                if "DatabaseResumingException" in code and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                errors += len(batch)
                if errors <= batch_size * 3:
                    print(f"\n  ⚠ Batch error at {batch_start}: {exc}", file=sys.stderr)
                break

        processed = batch_start + len(batch)
        if processed % 2500 == 0 or processed >= len(products):
            elapsed = time.time() - start
            rate = processed / elapsed
            eta = (len(products) - processed) / rate if rate > 0 else 0
            print(f"  Aurora: {processed:>6,} / {len(products):,} ({processed/len(products)*100:.0f}%)  "
                  f"inserted={inserted:,}  errors={errors}  "
                  f"rate={rate:.0f}/s  eta={eta:.0f}s", end="\r")

    print(f"\n  Aurora seeding complete: {inserted:,} inserted, {errors} errors")

    # Create vector index after bulk insert
    if inserted > 0 and embeddings:
        print("  Creating vector index (ivfflat)...")
        try:
            sql(VECTOR_INDEX_SQL.strip())
        except ClientError as exc:
            print(f"  Vector index warning: {exc}", file=sys.stderr)

    return inserted


# ---------------------------------------------------------------------------
# OpenSearch indexing
# ---------------------------------------------------------------------------

def seed_opensearch(collection_endpoint: str, session, products: list[dict],
                    embeddings: dict[str, list[float]], region: str = AWS_REGION,
                    index_name: str = "products") -> int:
    """Index products into OpenSearch Serverless. Returns count indexed."""
    if not OPENSEARCH_AVAILABLE:
        print("  Skipping OpenSearch (opensearch-py not installed)")
        print("  Install: pip install opensearch-py requests-aws4auth")
        return 0

    credentials = session.get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        "aoss",
        session_token=credentials.token,
    )

    host = collection_endpoint.replace("https://", "")
    client = OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )

    # Create index
    if not client.indices.exists(index=index_name):
        print(f"  Creating index '{index_name}'...")
        client.indices.create(index=index_name, body=OPENSEARCH_INDEX_BODY)

    # Bulk index
    indexed = 0
    errors = 0
    batch_size = 200
    bulk_body = []

    for i, p in enumerate(products):
        sku = p.get("sku", "")
        embedding = embeddings.get(sku)

        doc = {
            "sku":               sku,
            "name":              p.get("name", ""),
            "l1":                p.get("category_l1") or p.get("l1", ""),
            "l2":                p.get("category_l2") or p.get("l2", ""),
            "l3":                p.get("category_l3") or p.get("l3", ""),
            "brand":             p.get("brand", ""),
            "price_gbp":         float(p.get("price_gbp", 0)),
            "on_sale":           bool(p.get("on_sale", False)),
            "short_description": p.get("short_description", ""),
            "long_description":  p.get("long_description", ""),
            "activities":        p.get("activity_tags") or p.get("activities", []),
            "seasons":           p.get("season") or p.get("seasons", []),
            "in_stock":          bool(p.get("is_active", p.get("in_stock", True))),
            "stock_total":       int(p.get("total_stock", p.get("stock_total", 0)) or 0),
            "gender":            p.get("gender", ""),
        }
        # Extract colours from attributes
        attrs = p.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        if isinstance(attrs, dict):
            doc["colours"] = attrs.get("colours", [])
        if embedding:
            doc["embedding"] = embedding

        bulk_body.append({"index": {"_index": index_name, "_id": sku}})
        bulk_body.append(doc)

        if len(bulk_body) >= batch_size * 2 or i == len(products) - 1:
            resp = client.bulk(body=bulk_body)
            for item in resp.get("items", []):
                if "error" in item.get("index", {}):
                    errors += 1
                else:
                    indexed += 1
            bulk_body = []
            pct = (i + 1) / len(products) * 100
            print(f"  OpenSearch: {i+1:>6,} / {len(products):,} ({pct:.0f}%)  "
                  f"indexed={indexed:,}  errors={errors}", end="\r")

    print(f"\n  OpenSearch indexing complete: {indexed:,} indexed, {errors} errors")
    return indexed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed Meridian product catalogue into Aurora + OpenSearch")
    p.add_argument("--profile",        default=AWS_PROFILE)
    p.add_argument("--region",         default=AWS_REGION)
    p.add_argument("--data-dir",       default="data", help="Directory containing products_full_40000.parquet")
    p.add_argument("--environment",    default=ENVIRONMENT)
    p.add_argument("--skip-aurora",    action="store_true", help="Skip Aurora seeding")
    p.add_argument("--skip-opensearch", action="store_true", help="Skip OpenSearch indexing")
    p.add_argument("--skip-embeddings", action="store_true", help="Insert without embeddings (no Bedrock calls)")
    p.add_argument("--limit",          type=int, default=None, help="Only process first N products (for testing)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)

    print("Meridian product seed")
    print(f"Profile: {args.profile}  Region: {args.region}  Environment: {args.environment}")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfn = session.client("cloudformation")
    rds_data = session.client("rds-data")
    bedrock_runtime = session.client("bedrock-runtime")

    # Get stack outputs
    print("\nFetching stack outputs...")
    try:
        cluster_arn = get_stack_output(cfn, STACK_BASE, "AuroraClusterArn")
        secret_arn  = get_stack_output(cfn, STACK_BASE, "AuroraSecretArn")
        print(f"  Aurora cluster: {cluster_arn.split(':')[-1]}")
    except Exception as exc:
        print(f"ERROR: Could not get base stack outputs: {exc}", file=sys.stderr)
        print("Make sure meridian-base stack is deployed.", file=sys.stderr)
        sys.exit(1)

    opensearch_endpoint = None
    if not args.skip_opensearch:
        try:
            opensearch_endpoint = get_stack_output(cfn, STACK_BASE, "OpenSearchCollectionEndpoint")
            print(f"  OpenSearch: {opensearch_endpoint}")
        except Exception as exc:
            print(f"  ⚠ Could not get vectors stack outputs: {exc}")
            print("  Skipping OpenSearch indexing (run make deploy-vectors first)")
            args.skip_opensearch = True

    # Load products
    print("\nLoading products...")
    parquet_path = data_dir / "products_full_40000.parquet"
    json_path    = data_dir / "products_full_40000.json"

    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
        products = df.to_dict("records")
        print(f"  Loaded {len(products):,} products from parquet")
    elif json_path.exists():
        with open(json_path) as f:
            products = json.load(f)
        print(f"  Loaded {len(products):,} products from JSON")
    else:
        print(f"ERROR: No product data found in {data_dir}", file=sys.stderr)
        sys.exit(1)

    if args.limit:
        products = products[:args.limit]
        print(f"  Limited to {len(products):,} products (--limit)")

    # Generate embeddings
    embeddings: dict[str, list[float]] = {}
    if not args.skip_embeddings:
        print(f"\nGenerating embeddings via Bedrock ({EMBED_MODEL}, {EMBED_DIMS} dims)...")
        print(f"  This will take ~{len(products) // 200} minutes at ~200 embeddings/min")
        failed = 0
        start = time.time()
        for i, p in enumerate(products):
            sku = p.get("sku", "")
            text = embed_text_for_product(p)
            vec = generate_embedding(bedrock_runtime, text)
            if vec:
                embeddings[sku] = vec
            else:
                failed += 1

            if (i + 1) % 100 == 0 or i == len(products) - 1:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed
                remaining = (len(products) - i - 1) / rate
                print(f"  Embeddings: {i+1:>6,}/{len(products):,} "
                      f"({(i+1)/len(products)*100:.0f}%)  "
                      f"rate={rate:.1f}/s  "
                      f"eta={remaining/60:.0f}m  "
                      f"failed={failed}", end="\r")

        print(f"\n  Done: {len(embeddings):,} embeddings generated, {failed} failed")
    else:
        print("\nSkipping embeddings (--skip-embeddings)")

    # --- Intentional drift ---
    # ponytail: 250 products only in Aurora (not in OpenSearch, so search won't find them)
    # 250 products only in OpenSearch (search finds them but detail page 404s from Aurora)
    # This demonstrates the data consistency problem solved by zero-ETL later.
    # Drift products are the last 500 in the dataset (positions 39500-39999)
    aurora_only_start = len(products) - 500
    opensearch_only_start = len(products) - 250

    aurora_products = products[:opensearch_only_start]  # First 39750 go to Aurora
    opensearch_products = products[:aurora_only_start] + products[opensearch_only_start:]  # First 39500 + last 250 go to OpenSearch

    # Seed Aurora
    if not args.skip_aurora:
        print("\nSeeding Aurora PostgreSQL...")
        print(f"  ({len(aurora_products):,} products — 250 intentionally excluded for drift demo)")
        seed_aurora(rds_data, cluster_arn, secret_arn, aurora_products, embeddings)
    else:
        print("\nSkipping Aurora (--skip-aurora)")

    # Seed OpenSearch
    if not args.skip_opensearch and opensearch_endpoint:
        print("\nIndexing into OpenSearch Serverless...")
        print(f"  ({len(opensearch_products):,} products — 250 intentionally excluded for drift demo)")
        seed_opensearch(opensearch_endpoint, session, opensearch_products, embeddings, region=args.region)
    else:
        print("\nSkipping OpenSearch")

    print("\nSeed complete.")


if __name__ == "__main__":
    main()
