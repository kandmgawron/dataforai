# Meridian Environment Setup Guide

## From RAG Prototype to Production: AI Data Architecture on AWS

This guide covers everything you need to do before the first notebook. Follow every step in order. If something doesn't work, check the troubleshooting section at the bottom.

---

## What you're setting up

By the end of this guide you will have:

- The course repo cloned to your machine
- Python 3.11+ installed with all dependencies
- An AWS CLI profile called `ridge-course-dev` pointing at your AWS account
- The Meridian CloudFormation stacks deployed (VPC, Aurora, DynamoDB, S3, Valkey, API, frontends)
- All Meridian data loaded (40,000 products, 5,000 customers, 200,000 reviews, 50,000 conversations, 40 policy documents)
- Ridge Assist and Ridge Insight running as static sites

**Estimated time:** 30-45 minutes, most of which is waiting for AWS.

**Estimated cost:** Under £2 to deploy and seed. The ongoing cost is approximately £1.50-2.50 per day if you leave the stacks running. Always run `make destroy-all` when you finish a session.

---

## Prerequisites

Before you start, confirm you have:

- An AWS account with admin-level permissions (or at minimum the permissions listed in the appendix)
- A credit card attached to your AWS account
- Python 3.11 or later installed (`python3 --version`)
- Git installed (`git --version`)
- A terminal (macOS Terminal, iTerm2, Windows Terminal, or WSL2)

---

## Step 1: Clone the repo

```bash
git clone https://github.com/kandmgawron/dataforai.git
cd dataforai
```

Verify the structure looks right:

```bash
ls
```

You should see: `Makefile`, `README.md`, `SETUP.md`, `cloudformation/`, `data/`, `notebooks/`, `scripts/`, `web/`.

---

## Step 2: Set up Python

Create a virtual environment and install dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

pip install --upgrade pip
pip install -r requirements.txt
```

Verify:

```bash
python -c "import boto3, pandas, opensearchpy; print('Dependencies OK')"
```

---

## Step 3: Configure your AWS profile

The course uses a named profile called `ridge-course-dev`. This keeps course activity separate from any other AWS work you do.

### Option A: New AWS account or IAM user you've already created

```bash
aws configure --profile ridge-course-dev
```

You'll be prompted for:

```
AWS Access Key ID:     <your access key>
AWS Secret Access Key: <your secret key>
Default region name:   eu-west-1
Default output format: json
```

### Option B: SSO / AWS Identity Centre

```bash
aws configure sso --profile ridge-course-dev
```

Follow the prompts to authenticate via your browser.

### Verify the profile works

```bash
aws sts get-caller-identity --profile ridge-course-dev
```

You should see your account ID, user ID, and ARN. If you get an error, check your credentials.

---

## Step 4: Deploy the base infrastructure

This deploys the VPC, Aurora PostgreSQL (with pgvector), Valkey, DynamoDB tables, S3 buckets, and IAM roles. It takes approximately 15-20 minutes.

```bash
make deploy-base
```

You'll see CloudFormation output as it runs. Wait for the command to return successfully before continuing.

Verify:

```bash
make status
```

You should see `meridian-base` with status `CREATE_COMPLETE` or `UPDATE_COMPLETE`.

---

## Step 5: Deploy the web layer

This deploys the Ridge Assist (customer shop) and Ridge Insight (internal CRM) frontends, plus the API Gateway and Lambda backend.

```bash
make deploy-web
```

Once complete, the output shows your site URLs. Open Ridge Assist in a browser to confirm it loads (it will show "No products found" until you seed the data).

---

## Step 6: Load the Meridian data

One command loads everything. No Bedrock calls, no generation costs.

```bash
make seed-data
```

This runs the following in order:

1. `seed_products.py`: loads 40,000 products into Aurora (~2 min)
2. `seed_customers.py`: loads 5,000 customers into Aurora (~2 min)
3. `seed_reviews.py`: loads 200,000 reviews into Aurora (~10 min)
4. `seed_conversations.py`: loads 50,000 conversations into DynamoDB (~2 min)
5. `seed_policies.py`: uploads 40 policy documents to S3 and stores metadata in Aurora (~1 min)

You can leave this running and come back to it.

---

## Step 7: Verify the setup

Run a quick sanity check:

```bash
make status
```

Both stacks (`meridian-base` and `meridian-web`) should show `CREATE_COMPLETE` or `UPDATE_COMPLETE`.

Then open Ridge Assist in your browser (URL from the `make deploy-web` output). You should see:

- Product grid with 40 products per page
- Category filters working (Camping, Clothing, Climbing, etc.)
- Search bar returning results
- Chat widget in the bottom-right corner

Open Ridge Insight and verify:

- Customer search returns results
- Conversations queue shows entries
- Policy documents are browsable

---

## Step 8: Bedrock model access (for later modules)

Amazon Bedrock model access for Amazon Titan and Cohere models is enabled by default. No action needed for most models.

If you wish to use Anthropic models (Claude) in later modules, you'll need to request access separately:

1. Sign in to the AWS Console
2. Make sure you're in **eu-west-1 (Ireland)**
3. Go to **Amazon Bedrock** > **Model access**
4. Click **Modify model access** and enable the Anthropic models you want

This is optional and not required for the core course content.

---

## Daily teardown

Every time you finish a session, run:

```bash
make destroy-all
```

This tears down all stacks in reverse dependency order. Aurora data is deleted (it will be re-seeded on your next session).

On your next session:

```bash
make deploy-base
make deploy-web
make seed-data
```

---

## Changing the region

The course defaults to `eu-west-1` (Ireland). If you need a different region, override it:

```bash
make deploy-base AWS_REGION=us-east-1
make deploy-web AWS_REGION=us-east-1
make seed-data AWS_REGION=us-east-1
```

Ensure Bedrock is available in your chosen region with the models used in this course (Amazon Titan Embeddings V2, Cohere Embed).

---

## Troubleshooting

**`aws sts get-caller-identity` returns an error**
Your profile credentials have expired or are incorrect. Re-run `aws configure --profile ridge-course-dev` with fresh credentials.

**CloudFormation deploy fails with `ROLLBACK_COMPLETE`**
The stack failed partway through. Check the Events tab in the CloudFormation console for the specific error. Common causes: insufficient IAM permissions, or a resource name conflict if you've deployed before. Delete the failed stack and retry.

**Aurora auto-pause cold start**
Aurora Serverless v2 auto-pauses after inactivity. The first query takes 10-30 seconds while it resumes. The seed scripts and API handle this with automatic retries.

**`make seed-data` fails with a database error**
If Aurora is resuming from auto-pause, wait 30 seconds and re-run. The scripts use ON CONFLICT DO NOTHING, so re-running is safe.

**The website loads but shows no products**
Run `make seed-data` first. The frontends need data in Aurora to display anything.

**S3 bucket name conflict on deploy**
Bucket names are globally unique. If you get a conflict, it means a bucket with that name exists (possibly from a previous failed deploy in another region). Wait a few minutes for AWS to release the name, or change the region.

---

## Appendix: Minimum IAM permissions

If you're not using an admin account, your IAM user or role needs at minimum:

- `cloudformation:*`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:AttachRolePolicy`, `iam:PassRole`
- `ec2:*` (for VPC resources)
- `rds:*` (for Aurora)
- `rds-data:*` (for RDS Data API)
- `s3:*`
- `dynamodb:*`
- `elasticache:*`
- `secretsmanager:*`
- `kms:*`
- `lambda:*`
- `logs:*`
- `apigateway:*`
- `execute-api:*`
- `bedrock:InvokeModel`, `bedrock:ListFoundationModels`

Using an admin role for the course environment is the simplest option if your organisation allows it.
