output "api_url" {
  description = "Public URL of the API (via ALB)."
  value       = "http://${aws_lb.api.dns_name}"
}

output "rds_endpoint" {
  description = "RDS endpoint host — set POSTGRES_HOST to this for local ingestion."
  value       = aws_db_instance.main.address
}

output "ecr_api_repo" {
  description = "ECR repo URL for the api image."
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_mcp_repo" {
  description = "ECR repo URL for the mcp image."
  value       = aws_ecr_repository.mcp.repository_url
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "region" {
  value = var.aws_region
}
