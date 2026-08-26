# Deployment — ECS Fargate + RDS Postgres (Terraform)

Ephemeral, demo/verification-only deployment of the TinyML Research Assistant.
**This is not an always-on service.** `terraform destroy` after verifying is
**mandatory** (see the last section) — the stack is designed to tear down cleanly
with zero leftover charges.

## Why ECS Fargate + RDS (not EKS / not Lambda)

- **Long-running containers, not functions.** `api` and `mcp_server` each load the
  ~130 MB `BAAI/bge-small-en-v1.5` embedding model into memory at startup (baked
  into the image). Lambda would reload it on every cold start (bad latency) or need
  paid provisioned concurrency. Long-lived Fargate tasks fit the shape.
- **No Kubernetes-scale orchestration needed.** Two simple stateless-ish services +
  a managed DB. No custom scheduling / namespaces / service mesh to justify EKS ops
  overhead. (A separate project already demonstrates EKS + Terraform.)
- **RDS over a self-managed Postgres container.** Managed backups/failover and no
  "who backs up the pgvector data" question for a single-instance deployment.

## What this creates

| Resource | Notes |
|---|---|
| VPC + 2 public subnets + IGW | No NAT Gateway (deliberate — saves ~$32/mo). Tasks get public IPs for egress. |
| ALB (`:80`) → `api:8000` | Stable DNS + `/health` checks. `mcp_server` is **not** internet-exposed. |
| ECS cluster + 2 Fargate services | `api` and `mcp` — 0.5 vCPU / 1 GB each (`var.task_cpu` / `var.task_memory`). |
| RDS Postgres 16 (`db.t4g.micro`) | pgvector via `CREATE EXTENSION vector` in `schema.sql`. Single-AZ, no backups. |
| 2 ECR repos | `tinyml-rag/api`, `tinyml-rag/mcp`. |
| 2 SSM SecureStrings | db password, Anthropic key (free tier vs Secrets Manager). |
| IAM exec + task roles | Exec role reads only our 3 SSM params. Task role has no AWS perms. |

## Prerequisites

- Terraform ≥ 1.6, AWS CLI configured, Docker.
- Your public IP: `curl -s ifconfig.me` → use as `allowed_ingress_cidr` (`x.x.x.x/32`).

## Deploy

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # edit allowed_ingress_cidr, region

export TF_VAR_db_password='<a-strong-password>'
export TF_VAR_anthropic_api_key='sk-ant-...'   # required — LLM_PROVIDER defaults to anthropic

terraform init
terraform apply        # creates VPC, RDS, ECR, ALB, roles, SSM (ECS services will
                       # come up unhealthy until images are pushed — that's expected)
```

### 1. Build + push images to ECR

Run from the repo root. `$(terraform ... output)` pulls the repo URLs.

```bash
cd infra/terraform
API_REPO=$(terraform output -raw ecr_api_repo)
MCP_REPO=$(terraform output -raw ecr_mcp_repo)
REGION=$(terraform output -raw region)
REGISTRY=${API_REPO%/*}
cd ../..

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

docker build -f Dockerfile.api -t "$API_REPO:latest" .
docker build -f Dockerfile.mcp -t "$MCP_REPO:latest" .
docker push "$API_REPO:latest"
docker push "$MCP_REPO:latest"

# Roll the services onto the freshly pushed images
aws ecs update-service --cluster tinyml-rag-cluster --service tinyml-rag-api --force-new-deployment --region "$REGION"
aws ecs update-service --cluster tinyml-rag-cluster --service tinyml-rag-mcp --force-new-deployment --region "$REGION"
```

> Apple-silicon note: Fargate runs x86_64 by default. Build with
> `docker build --platform linux/amd64 …` (or set the task def to ARM64) so the
> image architecture matches.

### 2. Bootstrap the database (schema + ingest 15 papers) — run locally

The RDS endpoint is reachable from your `allowed_ingress_cidr`, so run the existing
scripts against it. `data/metadata.json` already exists, so the arXiv download step
is skipped — this just parses, chunks, embeds, and stores.

```bash
export POSTGRES_HOST=$(terraform -chdir=infra/terraform output -raw rds_endpoint)
export POSTGRES_PORT=5432
export POSTGRES_DB=research_assistant
export POSTGRES_USER=ra_user
export POSTGRES_PASSWORD="$TF_VAR_db_password"
export EMBEDDING_PROVIDER=local

./scripts/setup_db.sh        # applies schema.sql (CREATE EXTENSION vector + tables + HNSW)
./scripts/run_ingestion.sh   # parse → chunk → embed → store, ~15 papers
```

### 3. Verify

First confirm the containers are configured as intended. Terraform renders
`container_definitions` with computed values (SSM ARNs, ECR URLs, the RDS host), so
this is the AWS-authoritative view of the env vars + secret ARNs actually passed to
ECS — expect `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-5`, and exactly two
secrets (`POSTGRES_PASSWORD`, `ANTHROPIC_API_KEY` — no OpenAI):

```bash
REGION=$(terraform -chdir=infra/terraform output -raw region)
aws ecs describe-task-definition --task-definition tinyml-rag-api \
  --query 'taskDefinition.containerDefinitions' --region "$REGION"
aws ecs describe-task-definition --task-definition tinyml-rag-mcp \
  --query 'taskDefinition.containerDefinitions' --region "$REGION"
```

Then exercise the running service:

```bash
API_URL=$(terraform -chdir=infra/terraform output -raw api_url)
curl "$API_URL/health"                       # {"status":"ok"}
curl "$API_URL/papers"                        # 15 papers
curl -X POST "$API_URL/query" -H 'Content-Type: application/json' \
  -d '{"question":"What is quantization-aware training?"}'
```

Point the frontend at it by setting the API base to `$API_URL` (currently hardcoded
to `http://localhost:8000` in `frontend/src/api.js`).

## ⚠️ MANDATORY teardown

Do this as soon as verification is done — RDS + ALB bill hourly even when idle.

```bash
cd infra/terraform
terraform destroy
```

`force_delete` on the ECR repos, `skip_final_snapshot` + `deletion_protection=false`
+ `backup_retention_period=0` on RDS mean destroy completes without manual snapshot
cleanup or leftover charges. After it finishes, confirm nothing lingers:

```bash
aws ecs list-clusters --region "$REGION"
aws rds describe-db-instances --region "$REGION"
aws elbv2 describe-load-balancers --region "$REGION"
```
