variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
  default     = "15115821-7ecd-44b9-853d-2b9e9a1a5a76"
}

variable "resource_group_name" {
  description = "Resource group name"
  type        = string
  default     = "kube"
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westus2"
}

variable "openai_location" {
  description = "Azure region for OpenAI (must have gpt-4o availability)"
  type        = string
  default     = "centralus"
}

variable "acr_name" {
  description = "Container registry name (globally unique)"
  type        = string
  default     = "damoyacr"
}

variable "openai_name" {
  description = "Azure OpenAI resource name (globally unique)"
  type        = string
  default     = "damoy-openai3"
}

variable "container_name" {
  description = "Container instance name (becomes <name>.<location>.azurecontainer.io)"
  type        = string
  default     = "codegraph-chatbot"
}

variable "container_cpu" {
  description = "CPU cores for the container (1-4)"
  type        = number
  default     = 2
}

variable "container_memory" {
  description = "Memory in GB for the container (1-16)"
  type        = number
  default     = 4
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "auth_username" {
  description = "HTTP Basic Auth username"
  type        = string
  default     = "ai"
}

variable "auth_password" {
  description = "HTTP Basic Auth password"
  type        = string
  sensitive   = true
  default     = "ai"
}
