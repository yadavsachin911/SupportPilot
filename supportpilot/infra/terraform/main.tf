terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" { region = var.region }

# ------------------------------------------------------------------ Kafka (MSK Serverless, IAM auth)
resource "aws_security_group" "msk" {
  name   = "${var.name}-msk"
  vpc_id = var.vpc_id

  ingress {
    description     = "Kafka IAM port from app services"
    from_port       = 9098
    to_port         = 9098
    protocol        = "tcp"
    security_groups = [var.client_security_group_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_msk_serverless_cluster" "kafka" {
  cluster_name = "${var.name}-kafka"
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.msk.id]
  }
  client_authentication {
    sasl { iam { enabled = true } }
  }
}

# ------------------------------------------------------------------ Secrets (value is set out-of-band)
resource "aws_secretsmanager_secret" "anthropic_key" {
  name = "${var.name}/anthropic-api-key"
}

# ------------------------------------------------------------------ Auth (Cognito)
resource "aws_cognito_user_pool" "users" {
  name = "${var.name}-users"
}

resource "aws_cognito_user_pool_client" "web" {
  name                = "${var.name}-web"
  user_pool_id        = aws_cognito_user_pool.users.id
  generate_secret     = false
  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}

# ------------------------------------------------------------------ API Gateway (HTTP API -> VPC Link -> internal ALB)
resource "aws_security_group" "vpc_link" {
  name   = "${var.name}-vpclink"
  vpc_id = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_apigatewayv2_vpc_link" "this" {
  name               = "${var.name}-vpclink"
  subnet_ids         = var.private_subnet_ids
  security_group_ids = [aws_security_group.vpc_link.id]
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  name             = "cognito-jwt"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://${aws_cognito_user_pool.users.endpoint}"
  }
}

resource "aws_apigatewayv2_integration" "alb" {
  api_id             = aws_apigatewayv2_api.http.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = var.alb_listener_arn
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.this.id
}

# Only public-facing routes are exposed. PATCH /tickets, /orders, /kb, /refund stay internal.
resource "aws_apigatewayv2_route" "public" {
  for_each           = toset(["POST /tickets", "GET /tickets/{ticket_id}"])
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.alb.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }
}

output "api_url"           { value = aws_apigatewayv2_api.http.api_endpoint }
data "aws_msk_bootstrap_brokers" "kafka" {
  cluster_arn = aws_msk_serverless_cluster.kafka.arn
}

output "kafka_bootstrap"   { value = data.aws_msk_bootstrap_brokers.kafka.bootstrap_brokers_sasl_iam }
output "cognito_client_id" { value = aws_cognito_user_pool_client.web.id }
