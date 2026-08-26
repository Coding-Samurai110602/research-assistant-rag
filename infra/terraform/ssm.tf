# Secrets are stored as SSM Parameter Store SecureStrings (standard tier = free,
# vs Secrets Manager at $0.40/secret/mo — deliberate cost choice for a demo).
# The ECS task definitions reference these ARNs in their `secrets` blocks so the
# values are injected as env vars at container start and never appear in the task def.

resource "aws_ssm_parameter" "db_password" {
  name  = "/${local.project}/db_password"
  type  = "SecureString"
  value = var.db_password
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name  = "/${local.project}/anthropic_api_key"
  type  = "SecureString"
  value = var.anthropic_api_key
}
