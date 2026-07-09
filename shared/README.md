# Loom Shared Infrastructure

Shared infrastructure-as-code and deployment orchestration for Loom. This directory manages cross-cutting AWS resources (DNS, networking, auth, container registry, ECS cluster, IAM roles) and coordinates container builds and deployments for both the frontend and backend.

## Stacks

| Stack | Template | Description |
|-------|----------|-------------|
| `loom-dns` | `iac/dns.yaml` | Route 53 hosted zone for subdomain delegation |
| `loom-infra` | `iac/infra.yaml` | S3 artifact bucket, ECR repos, ACM certificate, ALB, security groups |
| `loom-cognito` | `iac/cognito.yaml` | Cognito User Pool, groups (including g-admins-registry), 21 scopes, users, app clients |
| `loom-role-*` | `iac/role.yaml` | IAM execution roles for AgentCore agents |
| `loom-ecs-cluster` | `iac/ecs.yaml` | ECS Fargate cluster (shared by frontend and backend services) |

**Note on `role` stacks:** A separate role stack is deployed per application prefix. For example, deploying with prefix `demo` creates an execution role shared by all `demo_*` agents. If you add agents with a different prefix (e.g., `finance_*`), deploy an additional role stack for that prefix.

## Makefile Targets

### Infrastructure Stacks

| Target | Description |
|--------|-------------|
| `make dns` | Deploy Route 53 hosted zone |
| `make infra` | Deploy S3, ECR, ACM, ALB |
| `make cognito` | Deploy Cognito User Pool, groups, scopes |
| `make role` | Deploy IAM execution role (per agent prefix) |
| `make ecs` | Deploy ECS Fargate cluster |
| `make agentcore.init` | Create Bedrock AgentCore service-linked role (once per account) |
| `make ecs.init` | Create ECS service-linked role (once per account) |

### Output Centralization

| Target | Description |
|--------|-------------|
| `make outputs` | Query all stacks, write outputs to `etc/outputs_<profile>.sh` |

`make outputs` captures all CloudFormation stack outputs into a single file (`etc/outputs_<profile>.sh`) that serves as the source of truth for all `O_*` variables. All makefiles across `shared/`, `frontend/`, and `backend/` automatically source this file. It also auto-populates `frontend/.env` with `VITE_COGNITO_USER_CLIENT_ID`.

### Container Deployment

| Target | Description |
|--------|-------------|
| `make deploy` | Build, push, and deploy both frontend and backend |
| `make deploy.frontend` | Build, push, and deploy frontend only |
| `make deploy.backend` | Build, push, and deploy backend only |

Container images are tagged with the git short SHA (`git rev-parse --short HEAD`).

### Cognito User Management

| Target | Description |
|--------|-------------|
| `make cognito.set-passwords` | Set permanent passwords for all provisioned demo users |
| `make cognito.get-client-id` | Print the Cognito app client ID |
| `make cognito.get-tokens` | Get Cognito tokens for the admin user |

## Environment Configuration

Copy the example and fill in your values:

```bash
cp etc/environment.sh.example etc/environment.sh
```

See [`environment.sh.example`](etc/environment.sh.example) for all available variables and descriptions.

## Full Deployment Guide

See the [root README](../README.md) for the complete phased deployment workflow, prerequisites, stack output reference table, and dependency graph.
