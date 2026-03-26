# =============================================================================
# Code Graph Chatbot — Azure Infrastructure
# =============================================================================
# Resources that cost money:
#   - AKS cluster (VMs, load balancer)       ~$400/mo (3x Standard_D4d_v4)
#   - ACR (container storage)                ~$5/mo (Basic)
#   - Public IP (static)                     ~$4/mo
#   - Azure OpenAI (S0 + per-token)          varies
#
# Usage:
#   terraform init
#   terraform plan
#   terraform apply    # ~10-15 min to create AKS
#   terraform destroy  # tear down everything
#
# After apply, run: ..\scripts\rebuild.ps1

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# =============================================================================
# Resource Group
# =============================================================================

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location
}

# =============================================================================
# Azure Container Registry
# =============================================================================

resource "azurerm_container_registry" "acr" {
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
}

# =============================================================================
# Azure OpenAI
# =============================================================================

resource "azurerm_cognitive_account" "openai" {
  name                  = var.openai_name
  resource_group_name   = azurerm_resource_group.rg.name
  location              = var.aks_location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = var.openai_name

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = "2024-11-20"
  }

  sku {
    name     = "Standard"
    capacity = 50
  }
}

# =============================================================================
# Static Public IP
# =============================================================================

resource "azurerm_public_ip" "chatbot" {
  name                = "codegraph-ip"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.aks_location
  allocation_method   = "Static"
  sku                 = "Standard"
}

# =============================================================================
# User-Assigned Managed Identity (for workload identity)
# =============================================================================

resource "azurerm_user_assigned_identity" "chatbot" {
  name                = "codegraph-identity"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.aks_location
}

# Grant the identity OpenAI User role
resource "azurerm_role_assignment" "openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.chatbot.principal_id
}

# =============================================================================
# AKS Cluster
# =============================================================================

resource "azurerm_kubernetes_cluster" "aks" {
  name                = var.aks_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.aks_location
  dns_prefix          = var.aks_dns_prefix
  kubernetes_version  = "1.33"

  sku_tier = "Standard"

  default_node_pool {
    name       = "systempool"
    vm_size    = "Standard_D4d_v4"
    node_count = 3

    only_critical_addons_enabled = true
  }

  identity {
    type = "SystemAssigned"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
  }
}

# Grant AKS identity ACR pull
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
}

# Grant AKS identity Network Contributor on RG (for static IP)
resource "azurerm_role_assignment" "aks_network" {
  scope                = azurerm_resource_group.rg.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.aks.identity[0].principal_id
}

# Federated credential for workload identity
resource "azurerm_federated_identity_credential" "chatbot" {
  name      = "codegraph-fed"
  parent_id = azurerm_user_assigned_identity.chatbot.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject   = "system:serviceaccount:code-graph:code-graph-sa"
}
