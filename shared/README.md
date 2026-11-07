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
| `loom-guardrail` | `iac/guardrail.yaml` | Amazon Bedrock guardrail and a published version for agents (optional; one stack per guardrail) |

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
| `make guardrail` | Deploy a Bedrock guardrail and publish a version |
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

## Bedrock Guardrails

Guardrail policies are managed here as code, **outside Loom**. Loom only references a guardrail by ID and version (Settings → Models → Guardrails, the agent wizard, or the `guardrail` key in an agent manifest), and its backend only has read access (`ListGuardrails`/`GetGuardrail`). Policy changes therefore go through code review, and a Loom admin can't weaken the policy that constrains agents.

`iac/guardrail.yaml` deploys:
- **Content filters:** hate, insults, sexual, violence and misconduct (`P_GUARDRAIL_CONTENT_FILTER_STRENGTH`), plus prompt-attack detection on prompts.
- **Sensitive information** (every entity sets `InputAction`/`OutputAction` explicitly: with only the general `Action`, Bedrock applies `ANONYMIZE` to responses only and never masks prompts):
  - always blocked: SSNs, card numbers and CVVs, AWS keys, passwords
  - masked or blocked (`P_GUARDRAIL_PII_MASK_ACTION`): email, phone, address, bank account numbers
- **Word filter:** the AWS-managed profanity list.
- **Denied topic:** an optional sample (investment advice). Denied topics are use-case specific, so replace it with your own in the template.
- **A published version**, which agents should pin.

Things to know:
- **Detect-only mode** (`P_GUARDRAIL_DETECT_ONLY=true`): every policy reports what it found without blocking or masking. This is how to observe managed (harness) agents, which have no Loom monitor mode.
- **Publishing a new version:** change the policy and `P_GUARDRAIL_VERSION_DESCRIPTION` in the same `make guardrail`. Superseded versions are **retained**, so agents pinned to them keep working. Delete them in the Bedrock console once no agent uses them.
- **Using it in Loom:** after `make guardrail` and `make outputs`, `O_GUARDRAIL_ID` and `O_GUARDRAIL_VERSION` are available. Set `P_GUARDRAIL_ID=$(O_GUARDRAIL_ID)` and `P_GUARDRAIL_VERSION=$(O_GUARDRAIL_VERSION)` in `backend/etc/environment.sh` to make it the deployment-wide default, or pick it in Settings.
- **Region:** deploy the guardrail in the same region as your agents.
- **IAM:** agent roles need `bedrock:ApplyGuardrail`. `iac/role.yaml` grants it.
- **Stack deletion:** `make guardrail.delete` deletes the guardrail and all its versions, which breaks any agent still using it.

