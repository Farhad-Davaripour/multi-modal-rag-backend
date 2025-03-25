#####################################################
# 0. Define Variables
#####################################################
variable "env_map" {
  type        = map(string)
  description = "Environment variables provided by GitHub Actions, stored as Key Vault secrets."
  default     = {}
}

#####################################################
# A. Remote Backend Configuration
#####################################################
terraform {
  backend "azurerm" {
    resource_group_name  = var.env_map["RESOURCE_GROUP_NAME"] 
    storage_account_name = "tfstatestorageacnt"  # The one you created manually
    container_name       = "tfstate"
    key                  = "terraform.state"

    subscription_id = coalesce(var.env_map["AZURE_SUBSCRIPTION_ID"], "")
    tenant_id       = coalesce(var.env_map["TENANT_ID"], "")
    client_id       = coalesce(var.env_map["AZURE_CLIENT_ID"], "")
    client_secret   = coalesce(var.env_map["AZURE_CLIENT_SECRET"], "")
  }
}

provider "azurerm" {
  subscription_id = coalesce(var.env_map["AZURE_SUBSCRIPTION_ID"], "")
  tenant_id       = coalesce(var.env_map["TENANT_ID"], "")
  client_id       = coalesce(var.env_map["AZURE_CLIENT_ID"], "")
  client_secret   = coalesce(var.env_map["AZURE_CLIENT_SECRET"], "")
  
  features {}
}

#####################################################
# B. (Optional) Manage the Same Resource Group
#####################################################
resource "azurerm_resource_group" "main" {
  name     = var.env_map["RESOURCE_GROUP_NAME"]
  location = "canadacentral"
}

#####################################################
# 2. Existing Azure Cognitive Search (Optional)
#####################################################
resource "azurerm_search_service" "search" {
  name                = "${coalesce(var.env_map["PROJECT_NAME"], "default-project")}-ai-search"
  resource_group_name = azurerm_resource_group.main.name
  location            = "canadacentral"
  sku                 = "free"
}

#####################################################
# 3. Key Vault (No Inline Access Policy)
#####################################################
resource "azurerm_key_vault" "kv" {
  name                = "${coalesce(var.env_map["PROJECT_NAME"], "default-project")}-KeyVault"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = coalesce(var.env_map["TENANT_ID"], "00000000-0000-0000-0000-000000000000")
  sku_name            = "standard"
}

#####################################################
# 4. Convert Each env_map Entry into a Key Vault Secret
#####################################################
resource "azurerm_key_vault_secret" "envsecrets" {
  depends_on = [
    azurerm_key_vault_access_policy.terraform_user
  ]

  for_each = {
    for k, v in var.env_map :
    k => {
      original  = k
      dash_name = replace(k, "_", "-")
      value     = v
    }
  }

  name         = each.value.dash_name
  value        = each.value.value
  key_vault_id = azurerm_key_vault.kv.id
}

#####################################################
# 5. ACR (Existing or Newly Created)
#####################################################
resource "azurerm_container_registry" "acr" {
  name                = coalesce(var.env_map["PROJECT_NAME"], "default-project")
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
}

#####################################################
# 6. App Service Plan (Needed by azurerm_app_service)
#####################################################
resource "azurerm_app_service_plan" "asp" {
  name                = "${coalesce(var.env_map["PROJECT_NAME"], "default-project")}-backend-plan"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  kind                = "Linux"
  reserved            = true

  sku {
    tier = "Basic"
    size = "B1"
  }
}

#####################################################
# 7. App Service with Managed Identity & Key Vault Secrets
#####################################################
resource "azurerm_app_service" "backend" {
  name                = "${coalesce(var.env_map["PROJECT_NAME"], "default-project")}-backend"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  app_service_plan_id = azurerm_app_service_plan.asp.id

  identity {
    type = "SystemAssigned"
  }

  site_config {
    linux_fx_version = "DOCKER|${azurerm_container_registry.acr.login_server}/fastapi-app:v1"
  }

  app_settings = merge(
    {
      "DOCKER_REGISTRY_SERVER_URL"      = "https://${azurerm_container_registry.acr.login_server}"
      "DOCKER_REGISTRY_SERVER_USERNAME" = azurerm_container_registry.acr.admin_username
      "DOCKER_REGISTRY_SERVER_PASSWORD" = azurerm_container_registry.acr.admin_password
    },
    {
      for k, v in azurerm_key_vault_secret.envsecrets :
      k => "@Microsoft.KeyVault(SecretUri=${v.id})"
    }
  )
}

#####################################################
# 8. Key Vault Access Policy for the App Service Identity
#####################################################
resource "azurerm_key_vault_access_policy" "app_service" {
  key_vault_id = azurerm_key_vault.kv.id
  tenant_id    = coalesce(var.env_map["TENANT_ID"], "00000000-0000-0000-0000-000000000000")
  object_id    = azurerm_app_service.backend.identity[0].principal_id

  secret_permissions = [
    "Get",
    "List"
  ]
}

#####################################################
# 9. Key Vault Access Policy for the Terraform Principal
#####################################################
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault_access_policy" "terraform_user" {
  key_vault_id = azurerm_key_vault.kv.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = [
    "Get",
    "List",
    "Set",
    "Delete",
    "Purge",
    "Recover",
    "Backup",
    "Restore"
  ]
}

#####################################################
# 10. Azure OpenAI Service (as a Cognitive Account)
#####################################################
resource "azurerm_cognitive_account" "openai" {
  name                = "AAA-oai-us-east"
  resource_group_name = azurerm_resource_group.main.name
  location            = "eastus"
  kind                = "OpenAI"
  sku_name            = "S0"

  custom_subdomain_name      = "aaa-oai-us-east"
  dynamic_throttling_enabled = false

  network_acls {
    default_action = "Allow"
    ip_rules       = []
  }

  tags = {}
}

#####################################################
# 11. Additional Storage Account
#####################################################
resource "azurerm_storage_account" "additional_storage" {
  name                     = "stragdemopro253585616804"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = "eastus"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  # (Add further settings if needed)
}
