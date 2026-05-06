# CLAUDE.md — dataforai

Project-level context for Claude Code. Read this before touching any file in the repo.

---

## Project

**Course title:** From RAG Prototype to Production: AI Data Architecture on AWS
**Publisher:** Study From Experts
**Instructor:** Kate Gawron (kate.gawron@doit.com)
**Format:** ~3 hours of video, 30 content modules, 22 hands-on Jupyter notebooks, one layered CloudFormation stack, synthetic dataset.

This repo is the production source for an AWS 300–400 level course on building AI data architectures. Everything here is either course content (slides, notebooks), infrastructure (CloudFormation), or tooling (data generation, Makefile).

---

## The Meridian Scenario

**Meridian Outdoor Co.** is the fictional company used throughout the course. Every module, notebook, and lab is framed around Meridian's real-world engineering decisions.

- Mid-sized UK outdoor retailer, ~£80M annual revenue, 40,000 SKUs, 500,000 active customers, 12 physical stores
- Existing AWS stack: ECS Fargate app layer, Aurora PostgreSQL (system of record), DynamoDB (sessions/carts), OpenSearch (keyword search), ElastiCache (caching), Kinesis + S3 (analytics)
- Problem: search fails on intent, recommendations cold-start badly, customer service agents span three systems

**The AI product — Ridge** — has two surfaces:

- **Ridge Assist** — customer-facing chat (web + mobile): finds products, answers questions, remembers preferences, handles post-purchase queries
- **Ridge Insight** — internal tool for store staff, buyers, and CS agents: unified query across product, policy, and customer data

The Ridge split is a deliberate teaching device: the same technology (caching, memory, retrieval) has different tuning priorities depending on whether it serves customers or internal staff.

**Synthetic dataset (generated once, committed to repo):**

| Dataset | Volume |
|---|---|
| Products | 40,000 SKUs with full attribute JSON, category hierarchy, pricing, stock |
| Reviews | 200,000 — glowing, critical, neutral, contradictory |
| Policy documents | 30–50 (returns, warranty, sizing guides, shipping, FAQs) |
| Customers | 5,000 — heavy buyers, one-time, recent, dormant |
| Conversations | 50,000 — for memory extraction, personalisation, cold-start modules |

---

## AWS Configuration

**Region:** `eu-west-2` (London)
**AWS profile:** `ridge-course-dev`

The Makefile defaults `AWS_PROFILE` to `default`; always override it explicitly:

```bash
make deploy-base AWS_PROFILE=ridge-course-dev
make destroy-all AWS_PROFILE=ridge-course-dev
```

Or export it for the session:

```bash
export AWS_PROFILE=ridge-course-dev
```

Bedrock model access required before any stack deployment: Claude (claude.amazon.com), Titan Embeddings, Cohere Embed.

---

## Repo Structure

```
/cloudformation          CloudFormation stacks
  meridian-base.yaml     VPC, IAM, Aurora+pgvector, ElastiCache, DynamoDB, S3, KMS
  meridian-vectors.yaml  OpenSearch Serverless collection
  meridian-knowledge.yaml  Neptune, Bedrock Knowledge Base, Bedrock Agent
  meridian-ops.yaml      Timestream, Step Functions, CloudWatch dashboards

/notebooks               Jupyter notebooks — one per hands-on module (22 total)
/scripts
  /data-generation       Synthetic dataset generation scripts (run once)

/data                    Generated Parquet/SQL output — committed after generation
                         Large files (.parquet, .csv, .sql, .json) are gitignored

/docs                    Planning documents, voice guide, module specifications
/slides                  HTML slide decks per module

Makefile                 deploy-base / deploy-vectors / deploy-knowledge / deploy-ops / destroy-all
requirements.txt         Python dependencies for notebooks and scripts
```

---

## Key Make Commands

```bash
make deploy-base        # Deploy VPC, Aurora, ElastiCache, DynamoDB, S3, IAM
make deploy-vectors     # Add OpenSearch Serverless + pgvector (after base)
make deploy-knowledge   # Add Neptune, Bedrock KB, Bedrock Agent (after vectors)
make deploy-ops         # Add Timestream, Step Functions, CloudWatch (after knowledge)
make destroy-all        # Tear everything down — always run after a session
make generate-data      # Run the data generation pipeline
```

---

## CloudFormation Stack Names

| Make target | Stack name |
|---|---|
| deploy-base | meridian-base |
| deploy-vectors | meridian-vectors |
| deploy-knowledge | meridian-knowledge |
| deploy-ops | meridian-ops |

Stacks are deployed and destroyed in dependency order. Destroy reverses the order.

---

## Notebook Conventions

Every notebook follows the same structure: what you'll do → prerequisites → cost estimate → setup → the lesson → what you've built → optional extensions.

- Use direct `boto3` — no course-specific SDK wrapper
- Every notebook states its Bedrock model version and estimated token spend before running
- Notebooks are teaching artefacts; `/scripts` holds production-shaped reference code

**Module-to-notebook map (22 notebooks):**

| Section | Modules with notebooks |
|---|---|
| Section 1 — Foundations | 2, 3, 5, 6, 7 |
| Section 2 — Making It Smart | 8, 9, 10, 11, 13, 14, 15 |
| Section 3 — Making It Fast & Cheap | 16, 17, 19, 20, 21 |
| Section 4 — Making It Reliable | 22, 23, 25, 27, 29 |

Modules 12, 18, 24, 26, 28, 30 are slide + demo (no notebook).

---

## Cost Awareness

OpenSearch Serverless has a minimum OCU charge regardless of usage. Always run `make destroy-all` at the end of a session.

- Full run-through with daily teardown: **£20–35**
- Forgotten teardown for a week: **£100–180**
- One-time data generation run (Bedrock): **£40–60**

Every notebook includes a cost estimate cell. Do not remove it.

---

## Docs

| File | Purpose |
|---|---|
| `docs/meridian-course-outline.md` | Full course outline (publisher review draft) |
| `docs/meridian-asset-inventory-v2.md` | Production plan, 8-week schedule, scope decisions |
| `docs/kate-voice-guide.md` | Instructor voice and style guide — follow this for any written content |
| `docs/module-1-specification.md` | Detailed spec for Module 1 |
| `docs/section-1-and-module-5-pilot.md` | Section 1 lab plan and Module 5 pilot spec |
