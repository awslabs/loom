-include etc/environment.sh

LOOM_FRONTEND_PORT ?= 5173
IMAGE_TAG := $(shell git rev-parse --short HEAD)

install:
	npm install

dev:
	npm run dev -- --port $(LOOM_FRONTEND_PORT)

build:
	npm run build

preview:
	npm run preview -- --port $(LOOM_FRONTEND_PORT)

typecheck:
	npx tsc -b --noEmit

clean:
	rm -rf dist node_modules/.tmp

# ECS frontend service
ecs: ecs.package ecs.deploy

ecs.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ECS_FRONTEND_TEMPLATE) \
		--output-template-file $(P_ECS_FRONTEND_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ECS_FRONTEND_STACK)

ecs.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ECS_FRONTEND_OUTPUT) \
		--stack-name $(P_ECS_FRONTEND_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ECS_FRONTEND_STACK) \
		--parameter-overrides \
			pEcsClusterArn=$(O_ECS_CLUSTER_ARN) \
			pEcsSecurityGroupId=$(O_INFRA_ECS_SG_ID) \
			pTargetGroupArn=$(O_INFRA_FRONTEND_TG_ARN) \
			pPublicSubnetIds=$(P_ECS_PUBLIC_SUBNET_IDS) \
			pImageUri=$(O_ECR_FRONTEND_URI):$(IMAGE_TAG) \
			pCpu=$(P_ECS_FRONTEND_CPU) \
			pMemory=$(P_ECS_FRONTEND_MEMORY) \
			pDesiredCount=$(P_ECS_FRONTEND_DESIRED_COUNT) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-confirm-changeset

ecs.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_ECS_FRONTEND_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

ecs.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_ECS_FRONTEND_STACK) \
		--no-prompts
