AWS_PROFILE   ?= ridge-course-dev
AWS_REGION    ?= eu-west-1
ENVIRONMENT   ?= dev
PROJECT       ?= meridian

STACK_BASE       = meridian-base
STACK_WEB        = meridian-web
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

.PHONY: deploy-base deploy-web deploy-knowledge deploy-ops destroy-all upload-data generate-data check-env help status seed-data seed-products seed-customers seed-reviews seed-conversations seed-policies

help:
	@echo "Meridian course infrastructure"
	@echo ""
	@echo "Targets:"
	@echo "  deploy-base        Deploy VPC, Aurora, OpenSearch, S3, IAM, DynamoDB, ElastiCache"
	@echo "  deploy-web         Deploy web frontends and API (requires deploy-base)"
	@echo "  deploy-knowledge   Deploy Neptune, Bedrock KB (requires deploy-base)"
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
	@echo "Base stack deployed. Next: make deploy-web"
	@$(MAKE) _print-outputs STACK=$(STACK_BASE)

deploy-web: check-env
	@echo "Deploying $(STACK_WEB)..."
	aws cloudformation deploy \
		--template-file $(CFN_DIR)/meridian-web.yaml \
		--stack-name $(STACK_WEB) \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides ProjectName=$(PROJECT) Environment=$(ENVIRONMENT) \
		--profile $(AWS_PROFILE) \
		--region $(AWS_REGION) \
		--no-fail-on-empty-changeset
	@echo "Uploading frontends and API code..."
	$(MAKE) upload-web
	@echo ""
	@echo "Web stack deployed."
	@$(MAKE) _print-outputs STACK=$(STACK_WEB)

upload-web: check-env
	$(eval ASSIST_BUCKET := $(shell aws cloudformation describe-stacks --stack-name $(STACK_WEB) --query "Stacks[0].Outputs[?OutputKey=='AssistBucketName'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null))
	$(eval INSIGHT_BUCKET := $(shell aws cloudformation describe-stacks --stack-name $(STACK_WEB) --query "Stacks[0].Outputs[?OutputKey=='InsightBucketName'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null))
	$(eval API_FUNCTION := $(shell aws cloudformation describe-stacks --stack-name $(STACK_WEB) --query "Stacks[0].Outputs[?OutputKey=='ApiFunctionName'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null))
	$(eval API_URL := $(shell aws cloudformation describe-stacks --stack-name $(STACK_WEB) --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null))
	@echo "  Injecting API URL into frontends..."
	@sed 's|window.RIDGE_API_BASE.*|window.RIDGE_API_BASE = "$(API_URL)";|' web/ridge-assist/app.js > /tmp/ridge-assist-app.js
	@sed 's|window.RIDGE_API_BASE.*|window.RIDGE_API_BASE = "$(API_URL)";|' web/ridge-insight/app.js > /tmp/ridge-insight-app.js
	@echo "  Uploading Ridge Assist to s3://$(ASSIST_BUCKET)/ ..."
	@aws s3 sync web/ridge-assist/ s3://$(ASSIST_BUCKET)/ --exclude "app.js" --profile $(AWS_PROFILE) --region $(AWS_REGION)
	@aws s3 cp /tmp/ridge-assist-app.js s3://$(ASSIST_BUCKET)/app.js --profile $(AWS_PROFILE) --region $(AWS_REGION)
	@echo "  Uploading Ridge Insight to s3://$(INSIGHT_BUCKET)/ ..."
	@aws s3 sync web/ridge-insight/ s3://$(INSIGHT_BUCKET)/ --exclude "app.js" --profile $(AWS_PROFILE) --region $(AWS_REGION)
	@aws s3 cp /tmp/ridge-insight-app.js s3://$(INSIGHT_BUCKET)/app.js --profile $(AWS_PROFILE) --region $(AWS_REGION)
	@echo "  Updating Lambda function code..."
	@cd web/api && zip -q /tmp/meridian-api.zip handler.py
	@aws lambda update-function-code --function-name $(API_FUNCTION) --zip-file fileb:///tmp/meridian-api.zip --profile $(AWS_PROFILE) --region $(AWS_REGION) > /dev/null
	@rm -f /tmp/ridge-assist-app.js /tmp/ridge-insight-app.js /tmp/meridian-api.zip
	@echo "  Done."

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
	-aws cloudformation delete-stack --stack-name $(STACK_WEB) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_WEB) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; echo "$(STACK_WEB) deleted."
	-aws cloudformation delete-stack --stack-name $(STACK_BASE) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; \
		aws cloudformation wait stack-delete-complete --stack-name $(STACK_BASE) --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null; echo "$(STACK_BASE) deleted."
	@echo "All stacks destroyed."

generate-data:
	cd scripts/data-generation && \
		/opt/homebrew/opt/python@3.13/bin/python3.13 generate_products.py --count 40000 --output ../../data/ --workers 25

status: check-env
	@echo "Stack status:"
	@printf "  %-25s %s\n" "$(STACK_BASE)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_BASE) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"
	@printf "  %-25s %s\n" "$(STACK_WEB)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_WEB) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"
	@printf "  %-25s %s\n" "$(STACK_KNOWLEDGE)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_KNOWLEDGE) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"
	@printf "  %-25s %s\n" "$(STACK_OPS)" "$$(aws cloudformation describe-stacks --stack-name $(STACK_OPS) --query 'Stacks[0].StackStatus' --output text --profile $(AWS_PROFILE) --region $(AWS_REGION) 2>/dev/null || echo 'NOT DEPLOYED')"

seed-data: seed-products seed-customers seed-reviews seed-conversations seed-policies
	@echo "All seed scripts complete."

seed-products: check-env
	python scripts/seed/seed_products.py --profile $(AWS_PROFILE) --region $(AWS_REGION) --data-dir $(DATA_DIR) --skip-embeddings --skip-opensearch

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
