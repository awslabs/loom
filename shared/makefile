include etc/environment.sh

# role
role: role.package role.deploy
role.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ROLE_TEMPLATE) \
		--output-template-file $(P_ROLE_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ROLE_STACK)

role.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ROLE_OUTPUT) \
		--stack-name $(P_ROLE_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ROLE_STACK) \
		--parameter-overrides \
			pAgentName=$(P_AGENT_NAME) \
			pRoleSuffix=$(P_AGENT_NAME_SANITIZED) \
			pBedrockModelArns=$(P_BEDROCK_MODEL_ARNS) \
			pAgentCoreRegions=$(P_AGENTCORE_REGIONS) \
			pLogsRegion=$(P_LOGS_REGION) \
			pMemoryArn=${P_MEMORY_ARN} \
			pEnableCodeInterpreter=$(P_ENABLE_CODE_INTERPRETER) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-confirm-changeset

role.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_ROLE_STACK) \
		--no-prompts

# code interpreter role
ci-role: ci-role.package ci-role.deploy
ci-role.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_CI_ROLE_TEMPLATE) \
		--output-template-file $(P_CI_ROLE_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_CI_ROLE_STACK)

ci-role.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_CI_ROLE_OUTPUT) \
		--stack-name $(P_CI_ROLE_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_CI_ROLE_STACK) \
		--parameter-overrides \
			pRoleSuffix=$(P_AGENT_NAME_SANITIZED) \
			pCodeInterpreterRegions=$(P_CI_REGIONS) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-confirm-changeset

ci-role.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_CI_ROLE_STACK) \
		--no-prompts

# cognito
cognito: cognito.package cognito.deploy
cognito.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_COGNITO_TEMPLATE) \
		--output-template-file $(P_COGNITO_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_COGNITO_STACK)

cognito.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_COGNITO_OUTPUT) \
		--stack-name $(P_COGNITO_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_COGNITO_STACK) \
		--parameter-overrides \
			pPoolName=$(P_COGNITO_POOL_NAME) \
			pDomain=$(P_COGNITO_DOMAIN) \
			pResourceServerIdentifier=$(P_COGNITO_RESOURCE_SERVER) \
			pScopes=$(P_COGNITO_SCOPES) \
			pCallbackUrls="$(P_COGNITO_CALLBACK_URLS)" \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--capabilities CAPABILITY_NAMED_IAM \
		--no-confirm-changeset

cognito.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_COGNITO_STACK) \
		--no-prompts

# cognito user management
cognito.set-passwords:
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username admin --password '$(P_COGNITO_PERMANENT_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username security-admin --password '$(P_COGNITO_PERMANENT_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username integration-admin --password '$(P_COGNITO_PERMANENT_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username test-user --password '$(P_COGNITO_PERMANENT_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-1 --password '$(P_COGNITO_DEMO_USER_1_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-1 --password '$(P_COGNITO_DEMO_USER_1_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-2 --password '$(P_COGNITO_DEMO_USER_2_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-2 --password '$(P_COGNITO_DEMO_USER_2_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-3 --password '$(P_COGNITO_DEMO_USER_3_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-3 --password '$(P_COGNITO_DEMO_USER_3_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-4 --password '$(P_COGNITO_DEMO_USER_4_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-4 --password '$(P_COGNITO_DEMO_USER_4_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-5 --password '$(P_COGNITO_DEMO_USER_5_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-5 --password '$(P_COGNITO_DEMO_USER_5_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-6 --password '$(P_COGNITO_DEMO_USER_6_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-6 --password '$(P_COGNITO_DEMO_USER_6_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-7 --password '$(P_COGNITO_DEMO_USER_7_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-7 --password '$(P_COGNITO_DEMO_USER_7_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-8 --password '$(P_COGNITO_DEMO_USER_8_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-8 --password '$(P_COGNITO_DEMO_USER_8_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-user-9 --password '$(P_COGNITO_DEMO_USER_9_PASSWORD)' --permanent
	aws cognito-idp admin-set-user-password --profile $(PROFILE) --region $(REGION) --user-pool-id $(O_COGNITO_USER_POOL_ID) --username demo-admin-9 --password '$(P_COGNITO_DEMO_USER_9_PASSWORD)' --permanent

cognito.get-client-id:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_COGNITO_STACK) \
		--query 'Stacks[0].Outputs[?OutputKey==`oUserClientId`].OutputValue' \
		--output text

cognito.get-tokens:
	@echo "Getting tokens for admin user..."
	@CLIENT_ID=$$(aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_COGNITO_STACK) \
		--query 'Stacks[0].Outputs[?OutputKey==`oUserClientId`].OutputValue' \
		--output text); \
	echo "Using client ID: $$CLIENT_ID"; \
	aws cognito-idp admin-initiate-auth \
		--profile $(PROFILE) \
		--region $(REGION) \
		--user-pool-id $(O_COGNITO_USER_POOL_ID) \
		--client-id $$CLIENT_ID \
		--auth-flow ADMIN_NO_SRP_AUTH \
		--auth-parameters USERNAME=admin,PASSWORD='$(P_COGNITO_PERMANENT_PASSWORD)' \
		--output json | jq -r '.AuthenticationResult | "=== Cognito Tokens ===\n\nIdToken:\n\(.IdToken)\n\nAccessToken:\n\(.AccessToken)\n\nRefreshToken:\n\(.RefreshToken)\n\nExpires in: \(.ExpiresIn) seconds"'

# DNS — Route 53 hosted zone for subdomain delegation
dns: dns.package dns.deploy

dns.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_DNS_TEMPLATE) \
		--output-template-file $(P_DNS_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_DNS_STACK)

dns.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_DNS_OUTPUT) \
		--stack-name $(P_DNS_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_DNS_STACK) \
		--parameter-overrides \
			pDomainName=$(P_INFRA_DOMAIN_NAME) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--no-confirm-changeset

dns.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_DNS_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

dns.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_DNS_STACK) \
		--no-prompts

# Shared infrastructure (S3, ECR, ACM, ALB)
infra: infra.package infra.deploy

infra.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_INFRA_TEMPLATE) \
		--output-template-file $(P_INFRA_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_INFRA_STACK)

infra.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_INFRA_OUTPUT) \
		--stack-name $(P_INFRA_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_INFRA_STACK) \
		--parameter-overrides \
			pArtifactBucketName=$(P_LOOM_ARTIFACT_BUCKET) \
			pLoggingBucketName=$(P_LOOM_LOGGING_BUCKET) \
			pVpcId=$(P_INFRA_VPC_ID) \
			pPublicSubnetIds=$(P_INFRA_PUBLIC_SUBNET_IDS) \
			pDomainName=$(P_INFRA_DOMAIN_NAME) \
			pHostedZoneId=$(O_INFRA_HOSTED_ZONE_ID) \
			pFrontendRepoName=$(P_ECR_FRONTEND_REPO) \
			pBackendRepoName=$(P_ECR_BACKEND_REPO) \
			pAlbIngressCidr=$(P_INFRA_ALB_INGRESS_CIDR) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--no-confirm-changeset

infra.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_INFRA_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

infra.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_INFRA_STACK) \
		--no-prompts

# PrivateLink ingress (NLB + VPC Endpoint Service — deployed separately by networking team)
privatelink: privatelink.package privatelink.deploy

privatelink.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_PRIVATELINK_TEMPLATE) \
		--output-template-file $(P_PRIVATELINK_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_PRIVATELINK_STACK)

privatelink.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_PRIVATELINK_OUTPUT) \
		--stack-name $(P_PRIVATELINK_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_PRIVATELINK_STACK) \
		--parameter-overrides \
			pVpcId=$(P_INFRA_VPC_ID) \
			pPrivateSubnetIds=$(P_PRIVATELINK_PRIVATE_SUBNET_IDS) \
			pStackName=$(P_PRIVATELINK_STACK) \
			pLoggingBucketName=$(P_LOOM_LOGGING_BUCKET) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--no-confirm-changeset

privatelink.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_PRIVATELINK_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

privatelink.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_PRIVATELINK_STACK) \
		--no-prompts

# Agent security group (ingress rules for VPC-deployed AgentCore Runtime agents)
security-group: security-group.package security-group.deploy

security-group.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_AGENT_SG_TEMPLATE) \
		--output-template-file $(P_AGENT_SG_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_AGENT_SG_STACK)

security-group.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_AGENT_SG_OUTPUT) \
		--stack-name $(P_AGENT_SG_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_AGENT_SG_STACK) \
		--parameter-overrides \
			pVpcId=$(P_INFRA_VPC_ID) \
			pStackName=$(P_AGENT_SG_STACK) \
			$(if $(P_AGENT_SG_HTTPS_CIDR),pAllowHttpsCidr=$(P_AGENT_SG_HTTPS_CIDR)) \
			$(if $(P_AGENT_SG_HTTP_CIDR),pAllowHttpCidr=$(P_AGENT_SG_HTTP_CIDR)) \
			$(if $(P_AGENT_SG_MCP_CIDR),pAllowMcpCidr=$(P_AGENT_SG_MCP_CIDR)) \
			$(if $(P_AGENT_SG_A2A_CIDR),pAllowA2aCidr=$(P_AGENT_SG_A2A_CIDR)) \
			$(if $(P_AGENT_SG_HTTPS_SOURCE_SG),pAllowHttpsFromSg=$(P_AGENT_SG_HTTPS_SOURCE_SG)) \
			$(if $(P_AGENT_SG_HTTP_SOURCE_SG),pAllowHttpFromSg=$(P_AGENT_SG_HTTP_SOURCE_SG)) \
			$(if $(P_AGENT_SG_MCP_SOURCE_SG),pAllowMcpFromSg=$(P_AGENT_SG_MCP_SOURCE_SG)) \
			$(if $(P_AGENT_SG_A2A_SOURCE_SG),pAllowA2aFromSg=$(P_AGENT_SG_A2A_SOURCE_SG)) \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--no-confirm-changeset

security-group.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_AGENT_SG_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

security-group.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_AGENT_SG_STACK) \
		--no-prompts

# Bedrock AgentCore service-linked role (run once per account before first agent deployment)
agentcore.init:
	aws iam create-service-linked-role \
		--profile $(PROFILE) \
		--aws-service-name runtime-identity.bedrock-agentcore.amazonaws.com || true

# ECS service-linked role (run once per account before first ECS deployment)
ecs.init:
	aws iam create-service-linked-role \
		--profile $(PROFILE) \
		--aws-service-name ecs.amazonaws.com || true

# ECS cluster (shared by frontend and backend services)
ecs: ecs.package ecs.deploy

ecs.package:
	sam package \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ECS_TEMPLATE) \
		--output-template-file $(P_ECS_OUTPUT) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ECS_STACK)

ecs.deploy:
	sam deploy \
		--profile $(PROFILE) \
		--region $(REGION) \
		--template-file $(P_ECS_OUTPUT) \
		--stack-name $(P_ECS_STACK) \
		--s3-bucket $(BUCKET) \
		--s3-prefix $(P_ECS_STACK) \
		--parameter-overrides \
			pTagApplication=$(P_TAG_APPLICATION) \
			pTagGroup=$(P_TAG_GROUP) \
			pTagOwner=$(P_TAG_OWNER) \
		--no-confirm-changeset

ecs.outputs:
	@aws cloudformation describe-stacks \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_ECS_STACK) \
		--query 'Stacks[0].Outputs' \
		--output json | jq .

ecs.delete:
	sam delete \
		--profile $(PROFILE) \
		--region $(REGION) \
		--stack-name $(P_ECS_STACK) \
		--no-prompts

# Image tag: git short SHA
IMAGE_TAG := $(shell git rev-parse --short HEAD)

# Podman build
podman.build: podman.build.backend podman.build.frontend

podman.build.backend:
	podman build --platform linux/amd64 -f ../backend/Dockerfile -t $(P_ECR_BACKEND_REPO):$(IMAGE_TAG) ..

podman.build.frontend:
	podman build --platform linux/amd64 --build-arg VITE_COGNITO_USER_CLIENT_ID=$(O_COGNITO_USER_CLIENT_ID) -t $(P_ECR_FRONTEND_REPO):$(IMAGE_TAG) ../frontend

# Podman push
podman.push: podman.login podman.push.backend podman.push.frontend

podman.login:
	aws ecr get-login-password --profile $(PROFILE) --region $(REGION) | \
		podman login --username AWS --password-stdin $(ACCOUNTID).dkr.ecr.$(REGION).amazonaws.com

podman.push.backend:
	podman tag $(P_ECR_BACKEND_REPO):$(IMAGE_TAG) $(ACCOUNTID).dkr.ecr.$(REGION).amazonaws.com/$(P_ECR_BACKEND_REPO):$(IMAGE_TAG)
	podman push $(ACCOUNTID).dkr.ecr.$(REGION).amazonaws.com/$(P_ECR_BACKEND_REPO):$(IMAGE_TAG)

podman.push.frontend:
	podman tag $(P_ECR_FRONTEND_REPO):$(IMAGE_TAG) $(ACCOUNTID).dkr.ecr.$(REGION).amazonaws.com/$(P_ECR_FRONTEND_REPO):$(IMAGE_TAG)
	podman push $(ACCOUNTID).dkr.ecr.$(REGION).amazonaws.com/$(P_ECR_FRONTEND_REPO):$(IMAGE_TAG)

# Capture all stack outputs and write to shared/etc/outputs_<profile>.sh
outputs:
	#@python3 scripts/capture_outputs.py $(PROFILE) $(REGION) $(PROFILE)
	@python3 scripts/capture_outputs.py $(PROFILE) $(REGION)

# Full deployment
deploy: podman.build podman.push
	$(MAKE) -C ../backend ecs
	$(MAKE) -C ../frontend ecs

deploy.backend: podman.build.backend podman.login podman.push.backend
	$(MAKE) -C ../backend ecs

deploy.frontend: podman.build.frontend podman.login podman.push.frontend
	$(MAKE) -C ../frontend ecs
