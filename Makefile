STACK_PREFIX ?= meridian
REGION ?= eu-west-2
AWS_PROFILE ?= default

deploy-base:
	aws cloudformation deploy \
		--template-file cloudformation/meridian-base.yaml \
		--stack-name $(STACK_PREFIX)-base \
		--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
		--region $(REGION) \
		--profile $(AWS_PROFILE)

deploy-vectors:
	aws cloudformation deploy \
		--template-file cloudformation/meridian-vectors.yaml \
		--stack-name $(STACK_PREFIX)-vectors \
		--capabilities CAPABILITY_IAM \
		--region $(REGION) \
		--profile $(AWS_PROFILE)

deploy-knowledge:
	aws cloudformation deploy \
		--template-file cloudformation/meridian-knowledge.yaml \
		--stack-name $(STACK_PREFIX)-knowledge \
		--capabilities CAPABILITY_IAM \
		--region $(REGION) \
		--profile $(AWS_PROFILE)

deploy-ops:
	aws cloudformation deploy \
		--template-file cloudformation/meridian-ops.yaml \
		--stack-name $(STACK_PREFIX)-ops \
		--capabilities CAPABILITY_IAM \
		--region $(REGION) \
		--profile $(AWS_PROFILE)

destroy-all:
	@echo "Destroying all Meridian stacks. This will delete all data."
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1
	aws cloudformation delete-stack --stack-name $(STACK_PREFIX)-ops --region $(REGION) --profile $(AWS_PROFILE)
	aws cloudformation delete-stack --stack-name $(STACK_PREFIX)-knowledge --region $(REGION) --profile $(AWS_PROFILE)
	aws cloudformation delete-stack --stack-name $(STACK_PREFIX)-vectors --region $(REGION) --profile $(AWS_PROFILE)
	aws cloudformation delete-stack --stack-name $(STACK_PREFIX)-base --region $(REGION) --profile $(AWS_PROFILE)
	@echo "Deletion initiated. Check CloudFormation console for progress."

generate-data:
	cd scripts/data-generation && python generate.py

.PHONY: deploy-base deploy-vectors deploy-knowledge deploy-ops destroy-all generate-data
