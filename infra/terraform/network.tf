locals {
  project = "tinyml-rag"

  # Two public subnets in two AZs — ALB requires >= 2 AZs, and Fargate tasks get
  # public IPs here so they reach ECR / the Anthropic API / the internet WITHOUT a NAT Gateway
  # (the ~$32/mo line item we are deliberately avoiding for this ephemeral demo).
  vpc_cidr     = "10.20.0.0/16"
  subnet_cidrs = ["10.20.1.0/24", "10.20.2.0/24"]
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.project}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.project}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.subnet_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${local.project}-public-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.project}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
