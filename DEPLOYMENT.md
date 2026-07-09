# Deployment Guide

The deployment model has three phases:
1. **Local testing** with Cognito authentication (SQLite database)
2. **Hybrid deployment** with RDS PostgreSQL in AWS, accessed via SSM tunnel for local development
3. **Full deployment** with all components (frontend, backend, database) running on Amazon ECS Fargate

## Prerequisites

**Development tools:**
- Python 3.11+ with [uv](https://github.com/astral-sh/uv) for dependency management
- Node.js 18+ with npm
- AWS CLI configured with credentials (environment variables, AWS profile, or instance metadata)
- SAM CLI for deploying infrastructure
- Podman (or Docker) for building container images

**AWS infrastructure** (required for Phase 2 and Phase 3):

**VPC and networking:**
- VPC with at least 1 public subnet for the ALB and at least 2 private subnets in different AZs (required for RDS Multi-AZ and for the EC2 bastion, which runs in a private subnet and uses SSM Session Manager)
- Internet gateway for public subnets
- NAT gateway in a public subnet for private subnet outbound traffic (required for ECR image pulls)

**S3 bucket for SAM deployments:**
- Create an S3 bucket for CloudFormation template artifacts with versioning enabled
- Set the `BUCKET` variable in `shared/etc/common.sh`

**S3 bucket for access logging (prerequisite — create manually before deploying `loom-infra`):**
- Create a dedicated S3 bucket for S3 server access logs (separate from the artifact bucket)
- Enable the [S3 Log Delivery group ACL](https://docs.aws.amazon.com/AmazonS3/latest/userguide/enable-server-access-logging.html) on this bucket so S3 can write access logs to it
- Do **not** enable access logging on the logging bucket itself (circular dependency)
- Set the `LOOM_LOGGING_BUCKET` variable in `shared/etc/common.sh`
- This bucket is intentionally managed outside CloudFormation to avoid log loss during stack teardown

**Domain and Route 53:**
- Parent Route 53 hosted zone must be accessible for NS delegation
- Set the `PUBLIC_FQDN` variable in `shared/etc/common.sh` to the desired subdomain, e.g., `loom.example.com`

**CloudWatch Transaction Search:**
- Enable CloudWatch Transaction Search for AgentCore Observability in the AWS console
- Navigate to CloudWatch > Settings > Transaction Search and enable it for the target region

## Getting Started

**Step 1: Clone the repository**

```bash
git clone <repository-url>
cd loom
```

**Step 2: Configure environment files**

Copy environment file templates:

```bash
# Copy environment files from examples
cp backend/etc/environment.sh.example backend/etc/environment.sh
cp frontend/etc/environment.sh.example frontend/etc/environment.sh
cp shared/etc/common.sh.example shared/etc/common.sh
cp shared/etc/environment.sh.example shared/etc/environment.sh
touch shared/etc/outputs.sh
```

**Step 3: Configure `shared/etc/common.sh`**

Environment configuration is centralized in `shared/etc/common.sh`. Update the following variables:

| Variable | Description |
|----------|-------------|
| `AWS_PROFILE` | AWS CLI profile name |
| `AWS_REGION` | AWS region (e.g., `us-east-1`) |
| `ACCOUNTID` | AWS account ID |
| `BUCKET` | S3 bucket for SAM deployments |
| `VPC_ID` | VPC ID for deployment |
| `PRIVATE_SUBNET_IDS` | Comma-separated list of private subnet IDs (at least 2 in different AZs) |
| `PUBLIC_SUBNET_IDS` | Comma-separated list of public subnet IDs (at least 1) |
| `PUBLIC_FQDN` | Public endpoint FQDN (e.g., `loom.example.com`) |
| `RDS_ALLOWED_CIDR` | CIDR block allowed to connect to RDS instance on port 5432, e.g., `10.0.0.0/16` |
| `COGNITO_POOL_NAME` | Desired Cognito User Pool name |
| `COGNITO_DOMAIN` | Globally unique Cognito domain prefix |
| `LOOM_ARTIFACT_BUCKET` | S3 bucket for Loom deployment artifacts |
| `LOOM_LOGGING_BUCKET` | Pre-existing S3 bucket for artifact bucket access logs (see prerequisite above) |
| `RDS_PASSWORD` | Unique password for RDS admin user |
| `SUPER_ADMIN_PASSWORD` | Unique password for super admin Cognito user |
| `DEMO_USER_*_PASSWORD` | Unique passwords for demo users (1-9) |

**Step 4: Configure tag owner** (only variable that differs per environment file)

Update `P_TAG_OWNER` in each environment file:
- `backend/etc/environment.sh` — Set your owner alias or email
- `frontend/etc/environment.sh` — Set your owner alias or email
- `shared/etc/environment.sh` — Set your owner alias or email

## Phase 1: Local Testing with Cognito

This phase runs the backend and frontend locally using SQLite (zero-config database), with Cognito User Pool for authentication.  
**In this phase, you can** develop and test the full Loom UI locally, deploy and invoke agents, manage memory and MCP servers, and iterate quickly with hot-reload on both frontend and backend.

![Phase 1: Local Testing](assets/loom_p1_local.png)

The backend defaults to SQLite (`sqlite:///./loom.db`) — no database setup required. Tables are auto-created on startup via `app.db:init_db()`. The backend auto-detects the database type from the `LOOM_DATABASE_URL` scheme:
- **SQLite** (`sqlite:///`): uses `check_same_thread=False`
- **PostgreSQL** (`postgresql+psycopg2://`): uses `pool_pre_ping=True` and `pool_recycle=1800`

**Step 1: Deploy Cognito User Pool**

```bash
cd shared
make cognito                   # Deploy Cognito User Pool, groups, scopes, and clients (~1 min)
make outputs                   # Capture outputs
make cognito.set-passwords     # Set permanent passwords for demo users
```

**Cognito groups and scopes (two-dimensional architecture):**

**Type Groups** (determine UI view):
- `t-admin` — Admin UI with full navigation
- `t-user` — User UI with limited navigation

**Resource Groups** (determine access to resources):
- `g-admins-super` — All 19 scopes (catalog:r/w, agent:r/w, memory:r/w, security:r/w, settings:r/w, tagging:r/w, costs:r/w, mcp:r/w, a2a:r/w, invoke)
- `g-admins-demo` — Read-only to all pages + read/write to demo group resources + costs:write
- `g-admins-security` — security:read/write, settings:read
- `g-admins-memory` — memory:read/write, settings:read
- `g-admins-mcp` — mcp:read/write, settings:read
- `g-admins-a2a` — a2a:read/write, settings:read
- `g-users-demo`, `g-users-test`, `g-users-strategics` — invoke + read access to resources in their group

Users are assigned both a type group and one or more resource groups. Resource filtering uses `loom:group` tag matching.

**Step 2: Start the backend**

```bash
cd backend
uv venv .venv && source .venv/bin/activate
make install
make run        # Start FastAPI dev server on LOOM_BACKEND_PORT (default 8000)
```

The backend uses SQLite by default (`sqlite:///./loom.db`). Tables are auto-created on startup.

> **Note:** When running via `make run` or `python -m app.main`, the server binds to `127.0.0.1` by default. Set `LOOM_BACKEND_HOST=0.0.0.0` only if you need to expose the backend on all interfaces (e.g., running in a VM or container locally). In ECS, the backend is started via the Dockerfile `CMD` directly with uvicorn, not via `__main__`, so this variable is not used in production.

**Step 3: Start the frontend**

```bash
cd frontend
make install
make dev        # Start Vite dev server on LOOM_FRONTEND_PORT (default 5173)
```

Open `http://localhost:5173` and log in with a Cognito user with the password you configured in `shared/etc/common.sh`.

## Phase 2: Hybrid Deployment with RDS in AWS

This phase deploys RDS PostgreSQL to AWS and uses an SSM tunnel to connect the local backend to the cloud database.  
**In this phase, you can** test with production-grade PostgreSQL, share a centralized database across team members while still developing locally, validate data persistence and migration strategies, and prepare for full cloud deployment — all while maintaining fast local iteration cycles.

![Phase 2: Hybrid Deployment](assets/loom_p2_hybrid.png)

**SSM VPC endpoints prerequisite:**

The EC2 bastion runs in a private subnet with no public IP. SSM Session Manager requires the following VPC endpoints to be present in the private subnets so the SSM agent can reach the SSM service without internet access:

- `com.amazonaws.<region>.ssm`
- `com.amazonaws.<region>.ssmmessages`
- `com.amazonaws.<region>.ec2messages`

If these endpoints are not already in your VPC, create them before deploying the EC2 stack — otherwise the SSM agent will be unreachable and `make tunnel` will fail.

The security group attached to the `ssmmessages` and `ec2messages` endpoints must allow **inbound TCP 443** from the VPC CIDR (e.g., `10.0.0.0/16`). Without this rule, the SSM agent on the EC2 instance can reach the endpoints at the network level, but the TLS handshake for the session channel is blocked and `start-session` returns `TargetNotConnected`. The `ssm` endpoint (used for API calls) typically uses a broader security group and is not affected by this.

**Step 1: Deploy RDS and EC2 bastion**

```bash
cd backend
make rds        # RDS PostgreSQL + optional RDS Proxy (~25 min)
make ec2        # EC2 bastion for SSM tunneling (~3 min)
```

**Step 2: Update database connection in `backend/etc/environment.sh`**

After RDS deployment, update the following variables:

```bash
# Set database host to localhost when using SSM tunnel
LOOM_DATABASE_HOST="localhost"

# Set database URL (constructed from host, credentials, port, and DB name)
# Example: postgresql+psycopg2://postgres:password@localhost:5432/loom
LOOM_DATABASE_URL="postgresql+psycopg2://${P_RDS_USERNAME}:${P_RDS_PASSWORD}@${LOOM_DATABASE_HOST}:${O_RDS_PORT}/${P_RDS_DB_NAME}"
```

**Step 3: Capture deployment outputs**
```bash
cd shared
make outputs                   # Capture outputs
```

**Step 4: Open SSM tunnel and start backend**

```bash
cd backend
make tunnel              # Port forwards localhost:5432 → RDS via EC2 bastion
make run                 # Start backend (connects to RDS via tunnel)
```

**Step 5: Migrate SQLite data to PostgreSQL (optional)**

If you have existing data in SQLite:

```bash
make migrate-db   # Copies sqlite:///./loom.db → $LOOM_DATABASE_URL
```

The frontend continues to run locally (same as Phase 1).

## Phase 3: Full Deployment to AWS

This phase deploys the rest of the stack (frontend, backend) to Amazon ECS Fargate behind an Application Load Balancer.
**In this phase, you can** run Loom as a production-ready, fully managed service accessible via HTTPS with custom domain, enable your team to access Loom from anywhere without local setup, leverage auto-scaling for the backend, and operate with enterprise-grade security, observability, and high availability.

![Phase 3: Full AWS Deployment](assets/loom_p3_aws.png)

**Multi-stack architecture:**

| Stack | Directory | Description |
|-------|-----------|-------------|
| `loom-dns` | `shared/` | Route 53 hosted zone for subdomain delegation |
| `loom-infra` | `shared/` | S3, ECR, ACM certificate, ALB |
| `loom-cognito` | `shared/` | Cognito User Pool, groups, scopes |
| `loom-role-*` | `shared/` | IAM execution roles for agents |
| `loom-ecs-cluster` | `shared/` | ECS Fargate cluster (shared) |
| `loom-rds` | `backend/` | RDS PostgreSQL + optional RDS Proxy |
| `loom-ec2` | `backend/` | EC2 bastion for SSM tunneling (optional) |
| `loom-ecs-frontend` | `frontend/` | Frontend ECS task definition + service |
| `loom-ecs-backend` | `backend/` | Backend ECS task definition + service + auto-scaling |

### Phase 3.0 — Deploy prerequisites

```bash
cd shared
make agentcore.init    # Create Bedrock AgentCore service-linked role, once per account (~1 min)
make ecs.init          # Create ECS service-linked role, once per account (~1 min)
make dns               # Route 53 hosted zone for subdomain (~1 min)
make dns.outputs       # Capture oHostedZoneId → O_INFRA_HOSTED_ZONE_ID, oNameServers → NS delegation
make outputs           # Capture outputs
```

**DNS prerequisite:** If your domain's parent hosted zone is in a different AWS account, you must add NS delegation records in the parent account before deploying the infra stack. See [Cross-Account DNS Delegation](#cross-account-dns-delegation) below.

Update root domain with the nameserver records displayed by `dns.outputs`.

### Phase 3.1 — Deploy foundation stacks

**Step 1: Deploy infrastructure stack**

```bash
cd shared
make infra       # S3 (with access logging), ECR (KMS-encrypted), ACM, ALB (~3 min)
make outputs     # Capture ECR repository URIs and KMS key ARN (required for ECS cluster)
```

**Step 2: Deploy ECS cluster** (depends on ECR repository from infra stack)

```bash
cd shared
make ecs         # ECS Fargate cluster (~1 min)
```

**Step 3: Deploy IAM execution roles** (can be done in parallel with infra)

```bash
cd shared
make role        # IAM execution roles (~1 min)
```

**Note on `role` stacks:** A separate role stack must be created for each application prefix. For example, deploying a role with the prefix `demo` creates an execution role shared by all `demo_*` agents. If you add agents with a different prefix (e.g., `finance_*`), you must deploy an additional role stack for that prefix.

Create IAM roles as needed for your agents.

### Phase 3.2 — Capture stack outputs

All stack outputs are stored in `shared/etc/outputs.sh` and automatically sourced by environment files.

```bash
cd shared
make outputs     # Query all stacks, write to shared/etc/outputs.sh
```

This writes all `O_*` variables (Cognito IDs, ECR URIs, ECS cluster ARN, ALB target group ARNs, etc.) to one file. No manual copy-paste needed.

| Stack | Output | Variable |
|-------|--------|----------|
| `loom-ecs-cluster` | `oEcsClusterArn` | `O_ECS_CLUSTER_ARN` |
| `loom-ecs-cluster` | `oEcsClusterName` | `O_ECS_CLUSTER_NAME` |
| `loom-dns` | `oHostedZoneId` | `O_INFRA_HOSTED_ZONE_ID` |
| `loom-infra` | `oEcsSecurityGroupId` | `O_INFRA_ECS_SG_ID` |
| `loom-infra` | `oFrontendTargetGroupArn` | `O_INFRA_FRONTEND_TG_ARN` |
| `loom-infra` | `oBackendTargetGroupArn` | `O_INFRA_BACKEND_TG_ARN` |
| `loom-infra` | `oFrontendRepositoryUri` | `O_ECR_FRONTEND_URI` |
| `loom-infra` | `oBackendRepositoryUri` | `O_ECR_BACKEND_URI` |
| `loom-infra` | `oEcrKmsKeyArn` | `O_INFRA_ECR_KMS_KEY_ARN` |
| `loom-cognito` | `oCognitoUserPoolId` | `O_COGNITO_USER_POOL_ID` |
| `loom-cognito` | `oUserClientId` | `O_COGNITO_USER_CLIENT_ID` |
| `loom-rds` | `oRdsSecretArn` | `O_RDS_SECRET_ARN` |
| `loom-rds` | `oConnectEndpoint` | `O_RDS_PROXY_ENDPOINT` |
| `loom-rds` | `oRdsPort` | `O_RDS_PORT` |
| `loom-rds` | `oSecretsKmsKeyArn` | `O_RDS_SECRETS_KMS_KEY_ARN` |
| `loom-ec2` | `oInstanceId` | `O_EC2_INSTANCE_ID` |

### Phase 3.3 — Deploy backend and frontend

```bash
cd shared && make deploy              # Build, push, and deploy both (~1 min build + ~3 min deploy per service)

# Or independently:
cd shared && make deploy.frontend     # Frontend only (~1 min build + ~3 min deploy)
cd shared && make deploy.backend      # Backend only (~1 min build + ~3 min deploy)

# Or deploy ECS services directly (after images are pushed):
cd frontend && make ecs               # Frontend ECS service only
cd backend && make ecs                # Backend ECS service only
```

**Stack dependency graph:**
```
Phase 3.0        Phase 3.1                        Phase 3.3
---------        ----------------------           ------------------
agentcore.init
ecs.init --+     infra    (~3 min)  --+
           |     cognito  (~1 min)  --|
dns -------+     role*    (~1 min)  --+--------> loom-ecs-frontend (~3 min)
                 ecs      (~1 min)  --|          loom-ecs-backend  (~3 min) *
                 rds      (~25 min) --|
                 ec2      (~3 min)  --+ (optional)

* A role stack is deployed per application prefix (e.g., demo -> demo_* agents)
* loom-ecs-backend requires outputs from both loom-infra (O_INFRA_ECR_KMS_KEY_ARN) and
  loom-rds (O_RDS_SECRETS_KMS_KEY_ARN) — run `make outputs` after Phase 3.1 before deploying
```

**Approximate total deployment time:** ~35 minutes end-to-end (dominated by RDS at ~25 min; Phase 3.1 stacks deploy in parallel).

## Cross-Account DNS Delegation

The DNS stack (`loom-dns`) creates a Route 53 hosted zone for `P_INFRA_DOMAIN_NAME`. If your domain's parent hosted zone is in a different AWS account, you must add NS delegation records in the parent account **before** deploying the infra stack (which creates the ACM certificate).

**After deploying the DNS stack**, retrieve the NS records:

```bash
cd shared
make dns.outputs    # Look for oNameServers (comma-separated list of 4 NS records)
```

**In the parent account** (where the domain's hosted zone lives):

Add an NS record in the parent hosted zone that delegates the subdomain to the deployment account:

```bash
aws route53 change-resource-record-sets --hosted-zone-id <parent-hosted-zone-id> --profile <parent-account-profile> --change-batch '{
  "Changes": [{
    "Action": "CREATE",
    "ResourceRecordSet": {
      "Name": "loom.yourdomain.com",
      "Type": "NS",
      "TTL": 300,
      "ResourceRecords": [
        {"Value": "ns-XXXX.awsdns-XX.org"},
        {"Value": "ns-XXXX.awsdns-XX.co.uk"},
        {"Value": "ns-XXXX.awsdns-XX.com"},
        {"Value": "ns-XXXX.awsdns-XX.net"}
      ]
    }
  }]
}'
```

Replace the 4 NS values with the actual name servers from `oNameServers`. Once delegation is active, the ACM certificate will validate automatically and the ALB alias record will resolve through the delegation from the parent zone.

If your domain's hosted zone is already in the deployment account, no delegation is needed — DNS resolution works directly.

**Important:** If doing this in the console, ensure that each record is entered on a separate line, rather than as a comma-separated list. This will cause delegation and certificate validation to fail.

## Cleanup

Remove all stacks in reverse dependency order. Run from the relevant directory for each group.

### Phase 3.3 — Remove ECS services

```bash
cd frontend && make ecs.delete
cd backend && make ecs.delete
```

### Phase 3.2 — Remove backend and shared stacks

```bash
cd backend
make ec2.delete    # EC2 bastion
make rds.delete    # RDS PostgreSQL (~5 min) — data will be lost
```

```bash
cd shared
make ecs.delete      # ECS Fargate cluster
make role.delete     # IAM execution roles (repeat for each prefix deployed)
make infra.delete    # S3, ECR, ACM, ALB
make cognito.delete  # Cognito User Pool
make dns.delete      # Route 53 hosted zone
```

> **Note:** ECR repositories must be empty before the `loom-infra` stack can be deleted. Clear images first:
> ```bash
> aws ecr batch-delete-image --repository-name loom-frontend --image-ids "$(aws ecr list-images --repository-name loom-frontend --query 'imageIds' --output json)" --region us-east-1
> aws ecr batch-delete-image --repository-name loom-backend --image-ids "$(aws ecr list-images --repository-name loom-backend --query 'imageIds' --output json)" --region us-east-1
> ```

> **Note:** S3 buckets (artifact bucket and logging bucket) must be emptied before the stack can delete them. The logging bucket is managed outside CloudFormation and must be deleted manually.

### Phase 3.1 — Remove service-linked roles (optional)

These are shared across all stacks in the account — only remove if no other services depend on them:

```bash
cd shared
make agentcore.delete  # Bedrock AgentCore service-linked role
make ecs.init.delete   # ECS service-linked role
```

### Phase 1 — Remove Cognito (local-only deployment)

```bash
cd shared
make cognito.delete
```

### DNS delegation cleanup

If you added NS delegation records in a parent account, remove them manually:

```bash
aws route53 change-resource-record-sets --hosted-zone-id <parent-hosted-zone-id> --profile <parent-account-profile> --change-batch '{
  "Changes": [{
    "Action": "DELETE",
    "ResourceRecordSet": {
      "Name": "loom.yourdomain.com",
      "Type": "NS",
      "TTL": 300,
      "ResourceRecords": [
        {"Value": "ns-XXXX.awsdns-XX.org"},
        {"Value": "ns-XXXX.awsdns-XX.co.uk"},
        {"Value": "ns-XXXX.awsdns-XX.com"},
        {"Value": "ns-XXXX.awsdns-XX.net"}
      ]
    }
  }]
}'
```
