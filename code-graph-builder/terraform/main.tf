# =============================================================================
# Code Graph Chatbot — Azure Infrastructure (Container Apps)
# =============================================================================
# Resources that cost money:
#   - Container App (2 vCPU, 4 GB)              ~$5/mo (consumption plan)
#   - ACR (container storage)                    ~$5/mo (Basic)
#   - Azure OpenAI (S0 + per-token)              varies
#   - Log Analytics Workspace                    free tier
#
# Total: ~$10/mo + OpenAI usage
#
# Usage:
#   terraform init
#   terraform plan
#   terraform apply
#
# After apply, run: ..\scripts\deploy.ps1

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
  admin_enabled       = true
}

# =============================================================================
# Azure OpenAI
# =============================================================================

resource "azurerm_cognitive_account" "openai" {
  name                  = var.openai_name
  resource_group_name   = azurerm_resource_group.rg.name
  location              = var.openai_location
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
# User-Assigned Managed Identity (for OpenAI access)
# =============================================================================

resource "azurerm_user_assigned_identity" "chatbot" {
  name                = "codegraph-identity"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
}

# Grant the identity OpenAI User role
resource "azurerm_role_assignment" "openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.chatbot.principal_id
}

# =============================================================================
# Log Analytics (required by Container Apps Environment)
# =============================================================================

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "codegraph-logs"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# =============================================================================
# Container Apps Environment + App
# =============================================================================

resource "azurerm_container_app_environment" "env" {
  name                       = "codegraph-env"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
}

resource "azurerm_container_app" "chatbot" {
  name                         = var.container_name
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.chatbot.id]
  }

  registry {
    server               = azurerm_container_registry.acr.login_server
    username             = azurerm_container_registry.acr.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.acr.admin_password
  }

  secret {
    name  = "auth-password"
    value = var.auth_password
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "chatbot"
      image  = "${azurerm_container_registry.acr.login_server}/code-graph-chatbot:${var.image_tag}"
      cpu    = var.container_cpu
      memory = "${var.container_memory}Gi"

      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = "2025-01-01-preview"
      }
      env {
        name  = "AZURE_DEPLOYMENT_NAME"
        value = "gpt-4o"
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.chatbot.client_id
      }
      env {
        name  = "GRAPH_PATH"
        value = "output/code-graph-full.json"
      }
      env {
        name  = "DOCS_INDEX_DB"
        value = "output/doc-index.db"
      }
      env {
        name  = "REPO_ROOT"
        value = "/data/kubernetes"
      }
      env {
        name  = "DOCS_ROOT"
        value = "/data/docs"
      }
      env {
        name  = "GITHUB_REPO_URL"
        value = "https://github.com/kubernetes/kubernetes"
      }
      env {
        name  = "GITHUB_BRANCH"
        value = "master"
      }
      env {
        name  = "DOCS_BASE_URL"
        value = "https://kubernetes.io"
      }
      env {
        name  = "MAX_TOKENS"
        value = "4000"
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = "*"
      }
      env {
        name  = "AUTH_USERNAME"
        value = var.auth_username
      }
      env {
        name        = "AUTH_PASSWORD"
        secret_name = "auth-password"
      }

      liveness_probe {
        transport        = "HTTP"
        path             = "/health"
        port             = 8000
        initial_delay    = 10
        interval_seconds = 30
      }

      startup_probe {
        transport        = "HTTP"
        path             = "/health"
        port             = 8000
        initial_delay    = 5
        interval_seconds = 10
        failure_count_threshold = 10
      }
    }
  }

  depends_on = [azurerm_role_assignment.openai_user]
}
