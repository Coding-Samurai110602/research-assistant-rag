resource "aws_ecr_repository" "api" {
  name                 = "${local.project}/api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # allow `terraform destroy` even with images present

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "mcp" {
  name                 = "${local.project}/mcp"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
