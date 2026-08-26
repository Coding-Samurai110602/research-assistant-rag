variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

# ── Access control ────────────────────────────────────────────────────────────
variable "allowed_ingress_cidr" {
  description = <<-EOT
    CIDR allowed to reach the ALB (HTTP :80) AND the RDS endpoint (:5432) directly.
    RDS ingress from this CIDR is what lets you run scripts/setup_db.sh +
    run_ingestion.sh locally against the managed database. Set this to YOUR public
    IP as a /32 (e.g. "203.0.113.7/32"). Do NOT leave it at 0.0.0.0/0 for RDS.
  EOT
  type        = string
}

# ── Container images (pushed to the ECR repos this stack creates) ──────────────
variable "image_tag" {
  description = "Tag for the api and mcp_server images in ECR (e.g. a git short SHA)."
  type        = string
  default     = "latest"
}

# ── Fargate task sizing (start minimal per the cost-discipline plan) ───────────
variable "task_cpu" {
  description = "Fargate task CPU units. 512 = 0.5 vCPU."
  type        = string
  default     = "512"
}

variable "task_memory" {
  description = "Fargate task memory (MiB). 1024 = 1 GB. Bump to 2048 if the model load OOMs."
  type        = string
  default     = "1024"
}

# ── RDS ───────────────────────────────────────────────────────────────────────
variable "db_instance_class" {
  description = "RDS instance class. db.t4g.micro is the smallest viable Graviton burstable."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_name" {
  type    = string
  default = "research_assistant"
}

variable "db_username" {
  type    = string
  default = "ra_user"
}

variable "db_password" {
  description = "Master password for RDS. Provide via TF_VAR_db_password, never commit it."
  type        = string
  sensitive   = true
}

# ── Application secrets (injected into containers via SSM Parameter Store) ─────
variable "anthropic_api_key" {
  description = "Anthropic key — REQUIRED. Sole LLM credential (LLM_PROVIDER defaults to anthropic)."
  type        = string
  sensitive   = true
}

# ── Application config (non-secret) ───────────────────────────────────────────
# Defaults mirror the local, proven-working setup so no override flags are needed.
variable "llm_provider" {
  type    = string
  default = "anthropic"
}

variable "llm_model" {
  type    = string
  default = "claude-sonnet-5"
}
