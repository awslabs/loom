include etc/environment.sh

IMAGE_TAG := $(shell git rev-parse --short HEAD)

install:
	source .venv/bin/activate && uv pip install -r requirements.txt

test:
	source .venv/bin/activate && python -m pytest tests/ -v

run:
	source .venv/bin/activate && uvicorn app.main:app --reload --port $${LOOM_BACKEND_PORT:-8000}
run.debug:
	source .venv/bin/activate && LOG_LEVEL=DEBUG uvicorn app.main:app --reload --port $${LOOM_BACKEND_PORT:-8000} --log-level debug

# Setup and migration
migrate: migrate-db fix-sequences

reset-db:
	source .venv/bin/activate && python scripts/reset_db.py

migrate-db:
	source .venv/bin/activate && python scripts/migrate_sqlite_to_postgres.py \
		--source sqlite:///./loom.db \
		--dest $${LOOM_DATABASE_URL}

fix-sequences:
	source .venv/bin/activate && python scripts/fix_sequences.py

# AgentCore credential providers
agentcore.credentials.list:
	aws bedrock-agentcore-control list-oauth2-credential-providers \
		--profile $(PROFILE) \
		--region $(REGION) | jq

agentcore.credentials.delete-all:
	@for name in $$(aws bedrock-agentcore-control list-oauth2-credential-providers \
		--profile $(PROFILE) \
		--region $(REGION) | jq -r '.credentialProviders[].name'); do \
		echo "Deleting $$name..."; \
		aws bedrock-agentcore-control delete-oauth2-credential-provider \
			--profile $(PROFILE) \
			--region $(REGION) \
			--name "$$name"; \
	done

# AgentCore memory queries
# Usage: Set P_MEMORY_ID in your environment file (e.g. test-mY9W6S5gdE)
#        Set P_MEMORY_ACTOR_ID to scope records to a specific user (e.g. test-user)
agentcore.memory.list:
	aws bedrock-agentcore-control list-memories \
		--profile $(PROFILE) \
		--region $(REGION) | jq

agentcore.memory.get:
	aws bedrock-agentcore-control get-memory \
		--profile $(PROFILE) \
		--region $(REGION) \
		--memory-id $(P_MEMORY_ID) | jq

agentcore.memory.records:
	@source .venv/bin/activate && python scripts/query_memory_records.py \
		--memory-id $(P_MEMORY_ID) \
		--actor-id $(P_MEMORY_ACTOR_ID) \
		--region $(REGION)

agentcore.memory.records-by-namespace:
	@source .venv/bin/activate && python scripts/list_memory_records.py \
		--memory-id $(P_MEMORY_ID) \
		--namespace $(P_MEMORY_NAMESPACE) \
		--region $(REGION)

agentcore.memory.extraction-jobs:
	@source .venv/bin/activate && python -c "\
	import boto3, json;\
	client = boto3.client('bedrock-agentcore', region_name='$(REGION)');\
	resp = client.list_memory_extraction_jobs(memoryId='$(P_MEMORY_ID)', maxResults=10);\
	print(json.dumps(resp.get('memoryExtractionJobs', []), indent=2, default=str))"

# RDS infrastructure
rds: rds.package rds.deploy

rds.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_RDS_TEMPLATE) \
		--output-template-file $(P_RDS_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_RDS_STACK)

rds.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_RDS_OUTPUT) \
		--stack-name $(P_RDS_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_RDS_STACK) \
		--parameter-overrides \
			pDbName=$(P_RDS_DB_NAME) \
			pDbUsername=$(P_RDS_USERNAME) \
			pDbPassword=$(P_RDS_PASSWORD) \
			pDbInstanceClass=$(P_RDS_INSTANCE_CLASS) \
			pDbAllocatedStorage=$(P_RDS_ALLOCATED_STORAGE) \
			pDbMultiAZ=$(P_RDS_MULTI_AZ) \
			pEnableProxy=$(P_RDS_ENABLE_PROXY) \
			pVpcId=$(P_RDS_VPC_ID) \
			pSubnetIds=$(P_RDS_PRIVATE_SUBNET_IDS) \
			pAllowedCidr=$(P_RDS_ALLOWED_CIDR) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-confirm-changeset

rds.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_RDS_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

rds.get-url:
	@aws secretsmanager get-secret-value \
		--profile $(PROFILE) \
		--region $(REGION) \
		--secret-id $(P_RDS_STACK)/database-url \
		--query SecretString \
		--output text | jq -r .url

rds.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_RDS_STACK) \
		--no-prompts

# EC2 infrastructure (SSM tunnel)
ec2: ec2.package ec2.deploy

ec2.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_EC2_TEMPLATE) \
		--output-template-file $(P_EC2_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_EC2_STACK)

ec2.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_EC2_OUTPUT) \
		--stack-name $(P_EC2_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_EC2_STACK) \
		--parameter-overrides \
			pVpcId=$(P_RDS_VPC_ID) \
			pSubnetId=$(P_EC2_PRIVATE_SUBNET_ID) \
			pInstanceType=$(P_EC2_INSTANCE_TYPE) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-confirm-changeset

ec2.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_EC2_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

ec2.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_EC2_STACK) \
		--no-prompts

# ECS backend service
ecs: ecs.package ecs.deploy

ecs.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ECS_BACKEND_TEMPLATE) \
		--output-template-file $(P_ECS_BACKEND_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ECS_BACKEND_STACK)

ecs.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ECS_BACKEND_OUTPUT) \
		--stack-name $(P_ECS_BACKEND_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ECS_BACKEND_STACK) \
		--parameter-overrides \
			pEcsClusterArn=$(O_ECS_CLUSTER_ARN) \
			pEcsClusterName=$(O_ECS_CLUSTER_NAME) \
			pEcsSecurityGroupId=$(O_INFRA_ECS_SG_ID) \
			pEcrKmsKeyArn=$(or $(O_INFRA_ECR_KMS_KEY_ARN),$(ECR_KMS_KEY_ARN)) \
			pSecretsKmsKeyArn=$(or $(O_RDS_SECRETS_KMS_KEY_ARN),$(SECRETS_KMS_KEY_ARN)) \
			pTargetGroupArn=$(O_INFRA_BACKEND_TG_ARN) \
			pPrivateSubnetIds=$(P_ECS_PRIVATE_SUBNET_IDS) \
			pImageUri=$(O_ECR_BACKEND_URI):$(IMAGE_TAG) \
			pCpu=$(P_ECS_BACKEND_CPU) \
			pMemory=$(P_ECS_BACKEND_MEMORY) \
			pDesiredCount=$(P_ECS_BACKEND_DESIRED_COUNT) \
			pMaxCount=$(P_ECS_BACKEND_MAX_COUNT) \
			pDatabaseSecretArn=$(O_RDS_SECRET_ARN) \
			pArtifactBucket=$(P_LOOM_ARTIFACT_BUCKET) \
			pCognitoUserPoolId=$(O_COGNITO_USER_POOL_ID) \
			pCognitoRegion=$(P_LOOM_COGNITO_REGION) \
			$(if $(P_LOOM_ALLOWED_ORIGINS),pAllowedOrigins=$(P_LOOM_ALLOWED_ORIGINS)) \
			$(if $(P_LITELLM_PROXY_BASE_URL),pLitellmProxyBaseUrl=$(P_LITELLM_PROXY_BASE_URL)) \
			$(if $(P_LITELLM_DISCOVERY_BASE_URL),pLitellmDiscoveryBaseUrl=$(P_LITELLM_DISCOVERY_BASE_URL)) \
			$(if $(P_LITELLM_PROXY_API_KEY_SECRET_ARN),pLitellmProxyApiKeySecretArn=$(P_LITELLM_PROXY_API_KEY_SECRET_ARN)) \
			$(if $(P_LITELLM_PROXY_API_KEY_SECRET_KMS_KEY_ARN),pLitellmProxyApiKeySecretKmsKeyArn=$(P_LITELLM_PROXY_API_KEY_SECRET_KMS_KEY_ARN)) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-confirm-changeset

ecs.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_ECS_BACKEND_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

ecs.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_ECS_BACKEND_STACK) \
		--no-prompts

# SSM tunnel
tunnel:
	aws ssm start-session \
		--profile $(PROFILE) \
		--region $(REGION) \
		--target $(O_EC2_INSTANCE_ID) \
		--document-name AWS-StartPortForwardingSessionToRemoteHost \
		--parameters '{"host":["$(O_RDS_PROXY_ENDPOINT)"],"portNumber":["$(O_RDS_PORT)"],"localPortNumber":["$(O_RDS_PORT)"]}'
