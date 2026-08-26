# ── ALB security group: public HTTP in from the operator CIDR ─────────────────
resource "aws_security_group" "alb" {
  name        = "${local.project}-alb-sg"
  description = "ALB ingress on :80"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from operator"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ingress_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.project}-alb-sg" }
}

# ── ECS tasks security group ──────────────────────────────────────────────────
# api:8000 reachable only from the ALB. mcp_server:8001 reachable only from within
# this same SG (intra-VPC) — it is deliberately NOT internet-exposed.
resource "aws_security_group" "tasks" {
  name        = "${local.project}-tasks-sg"
  description = "Fargate tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "api from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description = "mcp_server intra-SG only"
    from_port   = 8001
    to_port     = 8001
    protocol    = "tcp"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.project}-tasks-sg" }
}

# ── RDS security group ────────────────────────────────────────────────────────
# 5432 from the tasks SG (runtime) AND from the operator CIDR (local ingestion via
# scripts/setup_db.sh + run_ingestion.sh against the public RDS endpoint).
resource "aws_security_group" "rds" {
  name        = "${local.project}-rds-sg"
  description = "Postgres 5432"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from Fargate tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }

  ingress {
    description = "Postgres from operator (local ingestion)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ingress_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.project}-rds-sg" }
}
