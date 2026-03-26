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
  description = "Azure region for resource group and ACR"
  type        = string
  default     = "westus2"
}

variable "aks_location" {
  description = "Azure region for AKS, OpenAI, and public IP (must have gpt-4o availability)"
  type        = string
  default     = "centralus"
}

variable "aks_name" {
  description = "AKS cluster name"
  type        = string
  default     = "damoy-aks"
}

variable "aks_dns_prefix" {
  description = "AKS DNS prefix"
  type        = string
  default     = "damoy-aks"
}

variable "acr_name" {
  description = "Container registry name"
  type        = string
  default     = "damoyacr"
}

variable "openai_name" {
  description = "Azure OpenAI resource name"
  type        = string
  default     = "damoy-openai3"
}
