terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = local.project
      Environment = "demo"
      ManagedBy   = "terraform"
      # This deployment is demo/verification only — see README, terraform destroy is MANDATORY.
      Lifecycle = "ephemeral"
    }
  }
}
