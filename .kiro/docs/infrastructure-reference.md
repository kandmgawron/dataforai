# Meridian Infrastructure Reference

Current deployment details for the Ridge course environment.

---

## Region and Profile

| Setting | Value |
|---------|-------|
| AWS Region | eu-west-1 (Ireland) |
| AWS Profile | katepersonal (dev), ridge-course-dev (learner default) |
| Account ID | 771834037671 |

---

## CloudFormation Stacks

| Stack | Purpose | Status |
|-------|---------|--------|
| meridian-base | VPC, Aurora, OpenSearch Serverless (NextGen, scale-to-zero), Valkey, DynamoDB, S3, IAM, KMS | Deployed |
| meridian-web | Frontends (S3), API Gateway, Lambda | Deployed |
| meridian-vectors | ~~Folded into meridian-base~~ | N/A |
| meridian-knowledge | Neptune, Bedrock KB | Not built |
| meridian-agents | Agents for Amazon Bedrock / AgentCore | Not built |
| meridian-ops | Timestream, Step Functions, CloudWatch dashboards | Not built |

---

## Websites

| Site | URL |
|------|-----|
| Ridge Assist (customer shop) | http://meridian-assist-771834037671-eu-west-1-dev.s3-website-eu-west-1.amazonaws.com |
| Ridge Insight (internal CRM) | http://meridian-insight-771834037671-eu-west-1-dev.s3-website-eu-west-1.amazonaws.com |
| API Gateway | https://uda566thw9.execute-api.eu-west-1.amazonaws.com |

### API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | /products | List products (params: search, l1, colour, price_min, price_max, gender, limit, offset) |
| GET | /products/{sku} | Product detail (all fields) |
| GET | /customers | Search customers (params: search, limit) |
| GET | /customers/{customer_id} | Customer detail with conversations |
| GET | /conversations | List pending conversations |
| POST | /conversations | Submit chat question (body: {message, customer_id?, channel?}) |
| GET | /policies | List policy documents |
| GET | /policies/{doc_id} | Get policy content from S3 |
| GET | /reviews/{sku} | Get reviews for a product |

---

## Aurora PostgreSQL (RDS Data API)

| Resource | Value |
|----------|-------|
| Cluster ARN | arn:aws:rds:eu-west-1:771834037671:cluster:meridian-base-auroracluster-ygatnonly4ov |
| Cluster Endpoint | meridian-base-auroracluster-ygatnonly4ov.cluster-cni2uc86i8fj.eu-west-1.rds.amazonaws.com |
| Secret ARN | arn:aws:secretsmanager:eu-west-1:771834037671:secret:meridian/aurora/dev-DliI6p |
| Database | meridian |
| Engine | Aurora PostgreSQL Serverless v2 (with pgvector extension) |
| Auto-pause | Enabled (resumes on first query, ~10-30s cold start) |

### Table: products (22,550 rows)

| Column | Type | Notes |
|--------|------|-------|
| sku | varchar(60) | PK |
| name | varchar(255) | NOT NULL |
| l1 | varchar(100) | Top-level category (e.g. "Clothing", "Tents & Shelters") |
| l2 | varchar(100) | Sub-category (e.g. "Jackets & Coats") |
| l3 | varchar(100) | Leaf category (e.g. "Waterproof Jackets") |
| brand | varchar(100) | |
| price_gbp | numeric(10,2) | |
| sale_price_gbp | numeric(10,2) | NULL if not on sale |
| on_sale | boolean | |
| weight_g | integer | |
| short_description | text | |
| long_description | text | |
| attributes | jsonb | Supplier-provided structured data (colours, sizes, waterproof_rating, etc.) |
| activities | text[] | e.g. {"hiking","mountaineering"} |
| seasons | text[] | e.g. {"all_season"} |
| in_stock | boolean | |
| stock_total | integer | |
| embedding | vector(1024) | NULL until Module 3 (Titan Embed v2) |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**Indexes:** l1, l2, brand, price_gbp, in_stock, embedding (ivfflat, created when embeddings exist)

**Data quality notes (intentional for teaching):**
- `attributes.colours` uses inconsistent naming: "red" vs "fiery_red", "forest_green", "storm_grey"
- `gender` exists in source parquet but is NOT in Aurora schema (supplier data not fully captured)
- `materials` exists in source parquet but is NOT in Aurora schema
- Some products have colour info only in the description, not in structured attributes
- `sale_price_gbp` was NaN for ~4,800 products (cleaned to NULL in Aurora)

**Intentional drift between Aurora and OpenSearch (for teaching):**
- 250 products exist ONLY in Aurora (not searchable via OpenSearch)
- 250 products exist ONLY in OpenSearch (search finds them but detail page returns 404)
- This demonstrates the data consistency problem solved by zero-ETL integration later

Aurora-only demo SKUs (not found by search):
- MER-GLV-NOR-0352 — Affric Plus Gloves, £50.99, Accessories
- MER-GLV-CAI-0353 — Strathmore Ultra Gloves, £76.99, Accessories
- MER-GLV-STO-0354 — Dartmoor Trail Gloves, £58.99, Accessories
- MER-GLV-CAI-0355 — Affric Gloves, £63.99, Accessories
- MER-GLV-STO-0356 — Langdale Gloves, £34.99, Accessories

OpenSearch-only demo SKUs (search finds them, detail 404s):
- MER-GLV-STO-0744 — Langdale Gloves, £20.99
- MER-GLV-STO-0608 — Cheviot Pro Gloves, £54.99
- MER-GLV-MER-0699 — Galloway Comp Gloves, £23.99
- MER-GLV-MER-0662 — Cheviot Gloves, £26.99
- MER-GLV-NOR-0714 — Torridon Advance Gloves, £66.99

### Table: customers (5,000 rows)

| Column | Type | Notes |
|--------|------|-------|
| customer_id | varchar(20) | PK (e.g. "CUST-00001") |
| first_name | varchar(100) | NOT NULL |
| last_name | varchar(100) | NOT NULL |
| email | varchar(255) | |
| phone | varchar(20) | |
| postcode | varchar(10) | |
| country | char(2) | Default 'GB' |
| registration_date | date | |
| segment | varchar(50) | e.g. "premium", "standard", "new" |
| loyalty_tier | varchar(20) | gold, silver, bronze, platinum |
| lifetime_value_gbp | numeric(12,2) | |
| order_count | integer | |
| avg_order_value_gbp | numeric(10,2) | |
| last_purchase_date | date | |
| days_since_purchase | integer | |
| favourite_categories | text[] | |
| preferred_store | varchar(50) | |
| marketing_opt_in | boolean | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**Indexes:** segment, loyalty_tier, last_purchase_date

### Table: reviews (200,000 rows)

| Column | Type | Notes |
|--------|------|-------|
| review_id | varchar(20) | PK |
| product_sku | varchar(60) | NOT NULL |
| product_name | varchar(255) | |
| product_l2 | varchar(100) | |
| customer_id | varchar(20) | |
| rating | smallint | 1-5, NOT NULL |
| sentiment | varchar(20) | positive, negative, neutral, mixed |
| title | varchar(255) | |
| body | text | |
| verified_purchase | boolean | |
| helpful_votes | integer | |
| total_votes | integer | |
| created_at | timestamptz | |
| source | varchar(20) | |
| indexed_at | timestamptz | |

**Indexes:** product_sku, customer_id, rating, sentiment, created_at

### Table: policy_documents (40 rows)

| Column | Type | Notes |
|--------|------|-------|
| doc_id | varchar(20) | PK (e.g. "POL-001") |
| title | varchar(255) | NOT NULL |
| doc_type | varchar(50) | |
| applies_to | varchar(100) | |
| tags | text[] | |
| s3_key | varchar(500) | Path in policies bucket |
| word_count | integer | |
| version | varchar(10) | |
| last_updated | date | |
| indexed_at | timestamptz | |

---

## DynamoDB Tables

### meridian-conversations-dev (50,000 items)

| Key | Type | Role |
|-----|------|------|
| customer_id | S | Partition key |
| conversation_id | S | Sort key |

Attributes: channel, topic, status, num_turns, messages (JSON string), created_at, product_skus_mentioned, resolution_type

### meridian-sessions-dev

| Key | Type | Role |
|-----|------|------|
| session_id | S | Partition key |

Used for live two-way chat between Ridge Assist (customer) and Ridge Insight (staff). Also stores session state for later modules.

### meridian-memory-dev

| Key | Type | Role |
|-----|------|------|
| customer_id | S | Partition key |
| memory_key | S | Sort key |

Used for structured memory in Modules 8-9.

---

## ElastiCache (Valkey)

| Resource | Value |
|----------|-------|
| Endpoint | master.meridian-valkey-dev.injcsc.euw1.cache.amazonaws.com |
| Engine | Valkey 8.0 |
| Node type | cache.t3.micro |
| TLS | Enabled |
| Port | 6379 |

Used for semantic caching and memory in Modules 16-17.

---

## S3 Buckets

| Bucket | Purpose |
|--------|---------|
| meridian-data-771834037671-eu-west-1-dev | Raw data files (parquet, JSON) |
| meridian-policies-771834037671-eu-west-1-dev | Policy .txt documents (documents/ prefix) |
| meridian-exports-771834037671-eu-west-1-dev | Export/output bucket |
| meridian-assist-771834037671-eu-west-1-dev | Ridge Assist static frontend |
| meridian-insight-771834037671-eu-west-1-dev | Ridge Insight static frontend |

---

## IAM Roles

| Role | Used by |
|------|---------|
| meridian-lambda-role-dev | API Lambda, future course Lambdas |
| meridian-notebook-role-dev | SageMaker notebooks, local notebook execution |

---

## VPC

| Resource | Value |
|----------|-------|
| VPC ID | vpc-0e83ec9e46c570c1c |
| Public Subnet 1 | subnet-09890eb2a8bb96d09 |
| Public Subnet 2 | subnet-02769dcbddde6753f |
| Private Subnet 1 | subnet-0e3994bbed94600fa |
| Private Subnet 2 | subnet-07c42bb9c39250d93 |
| Lambda SG | sg-02f7770efe8f32669 |

---

## L1 Product Categories (10 categories, 22,550 products total)

Category distribution across 12 brands (house + specialist). Exact counts depend on seed run.

---

## OpenSearch Serverless

| Resource | Value |
|----------|-------|
| Collection type | NextGen (scale-to-zero) |
| Purpose | Product BM25 search (keyword/hybrid) |
| Deployed in | meridian-base stack |

Used for product search. Aurora holds product detail (intentional drift for teaching). 250 products exist only in OpenSearch (no Aurora record), 250 exist only in Aurora (not searchable).

---

## Data Volumes

| Dataset | Target | Actual in DB |
|---------|--------|--------------|
| Products | 22,550 | 22,550 |
| Customers | 5,000 | 5,000 |
| Reviews | 200,000 | 200,000 |
| Conversations | 50,000 | 50,000 |
| Policy docs | 40 | 40 |

**Brands:** 12 (house brands + specialist brands)

---

## Makefile Commands

```bash
make deploy-base AWS_PROFILE=katepersonal       # Base infrastructure (VPC, Aurora, OpenSearch, Valkey, DynamoDB, S3, IAM, KMS)
make deploy-web AWS_PROFILE=katepersonal        # Frontends + API Gateway + Lambda
make upload-web AWS_PROFILE=katepersonal        # Re-upload frontends/Lambda only (no stack update)
make seed-data AWS_PROFILE=katepersonal         # Run all seed scripts in order
make seed-products AWS_PROFILE=katepersonal     # Products into Aurora + OpenSearch (skips embeddings)
make seed-customers AWS_PROFILE=katepersonal    # Customers into Aurora
make seed-reviews AWS_PROFILE=katepersonal      # Reviews into Aurora
make seed-conversations AWS_PROFILE=katepersonal # Conversations into DynamoDB
make seed-policies AWS_PROFILE=katepersonal     # Policies to S3 + Aurora metadata
make status AWS_PROFILE=katepersonal            # Check stack status
make destroy-all AWS_PROFILE=katepersonal       # Empty versioned S3 buckets, then tear down all stacks
```

All commands default to `AWS_REGION=eu-west-1`. Override with `AWS_REGION=<region>` if needed.

**Notes:**
- `seed-products` loads into both Aurora and OpenSearch, skips embedding generation
- `destroy-all` empties versioned S3 buckets before deleting stacks
- Seed scripts handle Aurora auto-pause resume with retry, and create the `meridian` database if it doesn't exist
