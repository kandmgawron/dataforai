# From RAG Prototype to Production: AI Data Architecture on AWS

Course repository for the Study From Experts course by Kate Gawron.

---

## What This Repo Contains

```
/cloudformation       CloudFormation stacks for the Meridian environment
/notebooks            Jupyter notebooks, one per hands-on module
/scripts              Utility scripts
  /data-generation    Synthetic dataset generation for Meridian
/data                 Generated sample data (committed after generation)
/docs                 Course planning documents, voice guide, module specs
/slides               HTML slide decks per module
```

---

## The Meridian Scenario

All labs follow Meridian Outdoor Co., a fictional UK outdoor retailer re-architecting a healthy AWS e-commerce stack to add an AI platform called Ridge. Ridge powers two products: Ridge Assist (customer-facing chat) and Ridge Insight (internal tool for staff, buyers, and agents).

---

## Prerequisites

- AWS account with Bedrock model access enabled (Claude, Titan Embeddings, Cohere Embed)
- Python 3.11+
- AWS CLI configured
- Recommended region: eu-west-2 (London)

---

## Deploying the Lab Environment

```bash
# Deploy base stack (VPC, Aurora, ElastiCache, DynamoDB, S3, IAM)
make deploy-base

# Add vector stores (OpenSearch Serverless + pgvector)
make deploy-vectors

# Add knowledge stores (Neptune, Bedrock Knowledge Base, Bedrock Agent)
make deploy-knowledge

# Add operations layer (Timestream, Step Functions, CloudWatch dashboards)
make deploy-ops

# Tear everything down (important: avoids unexpected AWS charges)
make destroy-all
```

Estimated cost per full run-through with daily teardown: £20-35.
Estimated cost if you forget to tear down for a week: £100-180.

---

## Running the Notebooks

Notebooks can be run locally or in SageMaker Studio. Each notebook lists its prerequisites and estimated Bedrock token spend before running anything.

```bash
pip install -r requirements.txt
jupyter notebook notebooks/
```

---

## Course Links

- Publisher: [Study From Experts](https://www.studyfromexperts.com)
- Instructor: [Kate Gawron](https://kategawron.co.uk)

---

## Cost Warning

Several AWS services deployed by this repo have minimum charges regardless of usage. OpenSearch Serverless in particular has a minimum OCU spend. Always run `make destroy-all` when you finish a session.
