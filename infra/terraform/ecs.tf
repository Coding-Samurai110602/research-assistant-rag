resource "aws_ecs_cluster" "main" {
  name = "${local.project}-cluster"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.project}/api"
  retention_in_days = 7 # short retention — ephemeral demo
}

resource "aws_cloudwatch_log_group" "mcp" {
  name              = "/ecs/${local.project}/mcp"
  retention_in_days = 7
}

locals {
  # Non-secret env shared by both services. POSTGRES_HOST points at the RDS
  # endpoint; EMBEDDING_PROVIDER=local keeps embeddings free (model baked in image).
  common_env = [
    { name = "POSTGRES_HOST", value = aws_db_instance.main.address },
    { name = "POSTGRES_PORT", value = "5432" },
    { name = "POSTGRES_DB", value = var.db_name },
    { name = "POSTGRES_USER", value = var.db_username },
    { name = "EMBEDDING_PROVIDER", value = "local" },
    { name = "LLM_PROVIDER", value = var.llm_provider },
    { name = "LLM_MODEL", value = var.llm_model },
  ]

  # Secret env pulled from SSM at container start.
  common_secrets = [
    { name = "POSTGRES_PASSWORD", valueFrom = aws_ssm_parameter.db_password.arn },
    { name = "ANTHROPIC_API_KEY", valueFrom = aws_ssm_parameter.anthropic_api_key.arn },
  ]
}

# ── api service ───────────────────────────────────────────────────────────────
resource "aws_ecs_task_definition" "api" {
  family                   = "${local.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = local.common_env
    secrets      = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${local.project}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true # public subnets, no NAT → tasks need a public IP for egress
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}

# ── mcp_server service (internal only — no load balancer) ─────────────────────
resource "aws_ecs_task_definition" "mcp" {
  family                   = "${local.project}-mcp"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "mcp"
    image        = "${aws_ecr_repository.mcp.repository_url}:${var.image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8001, protocol = "tcp" }]
    environment  = local.common_env
    secrets      = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.mcp.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mcp"
      }
    }
  }])
}

resource "aws_ecs_service" "mcp" {
  name            = "${local.project}-mcp"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.mcp.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
}
