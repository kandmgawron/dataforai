AWS_PROFILE   ?= ridge-course-dev
AWS_REGION    ?= eu-west-2
BEDROCK_REGION ?= eu-west-1
ENVIRONMENT   ?= dev
PROJECT       ?= meridian

STACK_BASE       = meridian-base
STACK_VECTORS    = meridian-vectors
STACK_KNOWLEDGE  = meridian-knowledge
STACK_OPS        = meridian-ops

CFN_DIR = cloudformation
DATA_DIR = data

# Derive account ID and stack outputs
ACCOUNT_ID          := $(shell aws sts get-caller-identity --query Account --output text --profile $(AWS_PROFILE) 2>/dev/null)
DATA_BUCKET         := $(shell aws cloudformation describe-stacks --stack-name $(STACK_BASE) --query "Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null)
POLICY_BUCKET       := $(shell aws cloudformation describe-stacks --stack-name $(STACK_BASE) --query "Stacks[0].Outputs[?OutputKey=='PolicyDocsBucketName'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null)
NOTEBOOK_ROLE_ARN   := $(shell aws cloudformation describe-stacks --stack-name $(STACK_BASE) --query "Stacks[0].Outputs[?OutputKey=='NotebookRoleArn'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null)
LAMBDA_ROLE_ARN     := $(shell aws cloudformation describe-stacks --stack-name $(STACK_BASE) --query "Stacks[0].Outputs[?OutputKey=='LambdaExecutionRoleArn'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null)

.PHONY: deploy-base deploy-vectors deploy-knowledge deploy-ops destroy-all upload-data generate-data check-env help status seed-data seed-products seed-customers seed-reviews seed-conversations seed-policies

help:
	@echo "Meridian course infrastructure"
	@echo ""
	@echo "Targets:"
	@echo "  deploy-base        Deploy VPC, Aurora, S3, IAM, DynamoDB, ElastiCache"
	@echo "  deploy-vectors     Deploy OpenSearch Serverless (requires deploy-base)"
	@echo "  deploy-knowledge   Deploy Neptune, Bedrock KB, Agent (requires deploy-vectors)"
	@echo "  deploy-ops         Deploy Timestream, Step Functions, dashboards (requires deploy-knowledge)"
	@echo "  upload-data        Upload generated data files to S3"
	@echo "  seed-data          Run all seed scripts in order"
	@echo "  seed-products      Seed products into Aurora + OpenSearch (generates embeddings)"
	@echo "  seed-customers     Seed customers into Aurora"
	@echo "  seed-reviews       Seed reviews into Aurora"
	@echo "  seed-conversations Seed conversations into DynamoDB"
	@echo "  seed-policies      Seed policy documents to S3 + Aurora"
	@echo "  status             Show stack deployment status"
	@echo "  destroy-all        Tear down all stacks in reverse order"
	@echo "  generate-data      Run data generation pipeline locally"
	@echo ""
	@echo "Variables (override with VAR=value):"
	@echo "  AWS_PROFILE=$(AWS_PROFILE)"
	@echo "  AWS_REGION=$(AWS_REGION)"
	@echo "  ENVIRONMENT=$(ENVIRONMENT)"

check-env:
	@if [ -z "$(ACCOUNT_ID)" ]; then echo "ERROR: AWS credentials not configured for profile $(AWS_PROFILE)"; exit 1; fi
	@echo "Account: $(ACCOUNT_ID)  Region: $(AWS_REGION)  Profile: $(AWS_PROFILE)"

deploy-base: check-env
	@echo "Deploying $(STACK_BASE)..."
	aws cloudformation deploy \
		--template-file $(CFN_DIR)/meridian-base.yaml \
		--stack-name $(STACK_BASE) \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides ProjectName=$(PROJECT) Environment=$(ENVIRONMENT) \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION) \
		--no-fail-on-empty-changeset
	@echo "Uploading data to S3..."
	$(MAKE) upload-data
	@echo ""
	@echo "Base stack deployed. Next: make deploy-vectors"
	@$(MAKE) _print-outputs STACK=$(STACK_BASE)

deploy-vectors: check-env
	@echo "Deploying $(STACK_VECTORS) to $(BEDROCK_REGION) (OpenSearch Serverless lives alongside Bedrock)..."
	aws cloudformation deploy \
		--template-file $(CFN_DIR)/meridian-vectors.yaml \
		--stack-name $(STACK_VECTORS) \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides \
			ProjectName=$(PROJECT) \
			Environment=$(ENVIRONMENT) \
			NotebookRoleArn=$(NOTEBOOK_ROLE_ARN) \
			LambdaExecutionRoleArn=$(LAMBDA_ROLE_ARN) \
		--profile $(AWS_PROFILE) \
		--region $(BEDROCK_REGION) \
		--no-fail-on-empty-changeset
	@echo ""
	@echo "Vectors stack deployed. Run the seed script next:"
	@echo "  python scripts/seed/seed_products.py"
	@$(MAKE) _print-outputs STACK=$(STACK_VECTORS) REGION=$(BEDROCK_REGION)

deploy-knowledge: check-env
	@echo "Deploying $(STACK_KNOWLEDGE)..."
	aws cloudformation deploy \
		--template-file $(CFN_DIR)/meridian-knowledge.yaml \
		--stack-name $(STACK_KNOWLEDGE) \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides ProjectName=$(PROJECT) Environment=$(ENVIRONMENT) \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION) \
		--no-fail-on-empty-changeset
	@$(MAKE) _print-outputs STACK=$(STACK_KNOWLEDGE)

deploy-ops: check-env
	@echo "Deploying $(STACK_OPS)..."
	aws cloudformation deploy \
		--template-file $(CFN_DIR)/meridian-ops.yaml \
		--stack-name $(STACK_OPS) \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides ProjectName=$(PROJECT) Environment=$(ENVIRONMENT) \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION) \
		--no-fail-on-empty-changeset
	@$(MAKE) _print-outputs STACK=$(STACK_OPS)

upload-data:
	@if [ -z "$(DATA_BUCKET)" ]; then echo "ERROR: Could not determine DATA_BUCKET. Has deploy-base run?"; exit 1; fi
	@echo "Uploading datasets to s3://$(DATA_BUCKET)/raw/ ..."
	aws s3 sync $(DATA_DIR)/ s3://$(DATA_BUCKET)/raw/ \
		--exclude "*.jsonl" \
		--exclude "batch_input_*" \
		--exclude "batch_output/*" \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION)
	@if [ -d "$(DATA_DIR)/policies" ]; then \
		echo "Uploading policy docs to s3://$(POLICY_BUCKET)/..."; \
		aws s3 sync $(DATA_DIR)/policies/ s3://$(POLICY_BUCKET)/ \
			--profile $(AWS_PROFILE) \
			--region $(AWS_REGION); \
	fi
	@echo "Upload complete."

destroy-all: check-env
	@echo "WARNING: This will delete all Meridian stacks and their data."
	@echo "Press Ctrl+C within 5 seconds to cancel..."
	@sleep 5
	@echo "Destroying stacks in reverse order..."
	-aws cloudformation delete-stack --stack-name $(STACK_OPS) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_OPS) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; echo "$(STACK_OPS) deleted."
	-aws cloudformation delete-stack --stack-name $(STACK_KNOWLEDGE) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_KNOWLEDGE) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; echo "$(STACK_KNOWLEDGE) deleted."
	-aws cloudformation delete-stack --stack-name $(STACK_VECTORS) --profile $(AWS_PROFILE) --region $(BEDROCK_REGION) 2>/dev/null; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_VECTORS) --profile $(AWS_PROFILE) --region $(BEDROCK_REGION) 2>/dev/null; echo "$(STACK_VECTORS) deleted."
	-aws cloudformation delete-stack --stack-name $(STACK_BASE) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_BASE) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; echo "$(STACK_BASE) deleted."
	@echo "All stacks destroyed."

generate-data:
	cd scripts/data-generation && \
		/opt/homebrew/opt/python@3.13/bin/python3.13 generate_products.py --count 40000 --output ../../data/ --workers 25

status: check-env
	@echo "Stack status:"
	@printf "  %-25s %s\n" "$(STACK_BASE)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_BASE) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"
	@printf "  %-25s %s\n" "$(STACK_VECTORS)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_VECTORS) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(BEDROCK_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"
	@printf "  %-25s %s\n" "$(STACK_KNOWLEDGE)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_KNOWLEDGE) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"
	@printf "  %-25s %s\n" "$(STACK_OPS)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_OPS) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"

seed-data: seed-products seed-customers seed-reviews seed-conversations seed-policies
	@echo "All seed scripts complete."

seed-products: check-env
	python scripts/seed/seed_products.py --profile $(AWS_PROFILE) --region $(AWS_REGION) --bedrock-region $(BEDROCK_REGION) --data-dir $(DATA_DIR)

seed-customers: check-env
	python scripts/seed/seed_customers.py --profile $(AWS_PROFILE) --region $(AWS_REGION) --data-dir $(DATA_DIR)

seed-reviews: check-env
	python scripts/seed/seed_reviews.py --profile $(AWS_PROFILE) --region $(AWS_REGION) --data-dir $(DATA_DIR)

seed-conversations: check-env
	python scripts/seed/seed_conversations.py --profile $(AWS_PROFILE) --region $(AWS_REGION) --data-dir $(DATA_DIR)

seed-policies: check-env
	python scripts/seed/seed_policies.py --profile $(AWS_PROFILE) --region $(AWS_REGION) --data-dir $(DATA_DIR)

_print-outputs:
	@echo ""
	@echo "Stack outputs:"
	@aws cloudformation describe-stacks --stack-name $(STACK) \
		--query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
		--output table \
		--profile $(AWS_PROFILE) \
		--region $(or $(REGION),$(AWS_REGION)) 2>/dev/null || true
