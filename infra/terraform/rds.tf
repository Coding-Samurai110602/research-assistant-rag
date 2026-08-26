resource "aws_db_subnet_group" "main" {
  name       = "${local.project}-db-subnets"
  subnet_ids = aws_subnet.public[*].id
  tags       = { Name = "${local.project}-db-subnets" }
}

# Single-instance Postgres 16 with pgvector available as an extension.
# The app creates the extension itself via schema.sql: `CREATE EXTENSION vector`
# (pgvector is on the RDS extension allowlist for the master/rds_superuser role).
#
# Cost-discipline / clean-destroy settings for an ephemeral demo:
#   - publicly_accessible: needed so you can run ingestion locally (SG still gates it)
#   - backup_retention_period = 0: no automated snapshots to store/clean up
#   - skip_final_snapshot = true + deletion_protection = false: `terraform destroy`
#     tears it down with no leftover snapshot charges or manual unblocking.
#
# Connectivity note: the app's DSN (postgresql+psycopg://…) sets no sslmode, so
# psycopg3 uses libpq default sslmode=prefer — it negotiates TLS with RDS (which
# always offers it) and connects encrypted. No custom parameter group required.
resource "aws_db_instance" "main" {
  identifier     = "${local.project}-pg"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage = 20 # GiB — RDS gp3 minimum
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = true
  multi_az               = false

  backup_retention_period = 0
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true

  tags = { Name = "${local.project}-pg" }
}
