data "azurerm_client_config" "current" {}

# Random suffix: globally unique names, and no clash with soft-deleted accounts.
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
  numeric = true
}

locals {
  name = "${var.project}-${var.environment}-${random_string.suffix.result}"
  tags = merge(
    {
      project    = var.project
      env        = var.environment
      managed_by = "terraform"
      data       = "synthetic-only"
    },
    var.tags,
  )
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

# Azure AI Language: PII detection, sentiment, key phrases.
# A custom subdomain is required for Entra ID (token) authentication.
resource "azurerm_cognitive_account" "language" {
  name                  = "lang-${local.name}"
  location              = azurerm_resource_group.rg.location
  resource_group_name   = azurerm_resource_group.rg.name
  kind                  = "TextAnalytics"
  sku_name              = var.language_sku
  custom_subdomain_name = "lang-${local.name}"
  local_auth_enabled    = var.local_auth_enabled
  tags                  = local.tags
}

# Azure AI Services (Foundry) account that hosts the model deployment.
resource "azurerm_cognitive_account" "ai" {
  name                  = "ai-${local.name}"
  location              = azurerm_resource_group.rg.location
  resource_group_name   = azurerm_resource_group.rg.name
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = "ai-${local.name}"
  local_auth_enabled    = var.local_auth_enabled
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "model" {
  count                = var.deploy_model ? 1 : 0
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.ai.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = var.model_sku
    capacity = var.model_capacity
  }
}

# Least privilege: data-plane roles for the signed-in identity, scoped to each
# account (never the subscription). Role propagation can take a few minutes.
resource "azurerm_role_assignment" "language_user" {
  count                = var.assign_roles ? 1 : 0
  scope                = azurerm_cognitive_account.language.id
  role_definition_name = "Cognitive Services User"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "ai_user" {
  count                = var.assign_roles ? 1 : 0
  scope                = azurerm_cognitive_account.ai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
}
