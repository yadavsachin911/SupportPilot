variable "region"             { default = "ap-south-1" }
variable "name"               { default = "supportpilot" }
variable "vpc_id"             { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "alb_listener_arn"   { description = "Internal ALB listener that fronts the ECS API service" }
variable "client_security_group_id" {
  description = "Security group of the ECS services (API, agent, n8n) allowed to reach Kafka"
  type        = string
}
