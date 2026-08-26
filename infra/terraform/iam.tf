data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ── Task EXECUTION role: used by the ECS agent to pull images, read the SSM
#    secrets, and write logs. (Distinct from the task role the app runs as.) ─────
resource "aws_iam_role" "execution" {
  name = "${local.project}-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow the execution role to read exactly our three SecureString parameters.
resource "aws_iam_role_policy" "execution_ssm" {
  name = "${local.project}-exec-ssm"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ssm:GetParameters"]
        Resource = [
          aws_ssm_parameter.db_password.arn,
          aws_ssm_parameter.anthropic_api_key.arn,
        ]
      },
      {
        # Decrypt SecureStrings encrypted under the default aws/ssm KMS key.
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = ["arn:aws:kms:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
      },
    ]
  })
}

# ── Task role: the identity the application code runs as. It needs no AWS API
#    access (all state is in RDS; secrets arrive as env vars) so it stays empty. ─
resource "aws_iam_role" "task" {
  name = "${local.project}-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}
