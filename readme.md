# FastAPI Deployment with Docker & Azure

This repository demonstrates how to containerize a **FastAPI** application, push the image to **Azure Container Registry (ACR)**, and deploy it to **Azure App Service**. Documents and images can also be stored in Azure Blob Storage, and text content indexed using Azure Cognitive Search as needed.

## 1. Run FastAPI Locally

1. **Install dependencies** (optional if not using a virtual environment):
   ```bash
   pip install -r requirements.txt
   ```
2. **Run FastAPI**:
   ```bash
   uvicorn fastapi_app:app --reload
   ```
3. **Test** in a browser or via the API docs:
   - [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Example: Post a Query via Terminal (PowerShell)
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/query" `
  -Method Post `
  -Headers @{
      "accept" = "application/json"
      "Content-Type" = "application/json"
  } `
  -Body '{ "query": "What is the total assets within the balance sheet?" }'
```

---

## 2. Containerize & Push to ACR

1. **Build** Docker image (from the folder containing the Dockerfile):
   ```powershell
   docker build -t fastapi-app .
   ```
2. **Log in** to Azure and ACR:
   ```powershell
   az login
   az acr login -n <ACR_NAME>    # e.g., multimodalrag
   ```
3. **Tag** the image for your ACR:
   ```powershell
   docker tag fastapi-app <ACR_NAME>.azurecr.io/fastapi-app:v1
   ```
4. **Push** the image:
   ```powershell
   docker push <ACR_NAME>.azurecr.io/fastapi-app:v1
   ```

---

## 3. Deploy to Azure App Service (Container)

1. **Create an App Service Plan** (Basic tier):
   ```powershell
   az appservice plan create `
     --name my-fastapi-plan `
     --resource-group rg-genAI-sandbox `
     --is-linux `
     --sku B1
   ```
2. **Create the Web App**:
   ```powershell
   az webapp create `
     --resource-group rg-genAI-sandbox `
     --plan my-fastapi-plan `
     --name my-fastapi-backend `
     --deployment-container-image-name "<ACR_NAME>.azurecr.io/fastapi-app:v1"
   ```
3. **Configure Private Registry Credentials**:
   ```powershell
   $ACRPassword = (az acr credential show --name <ACR_NAME> --query "passwords[0].value" -o tsv)
   $ACRUsername = (az acr credential show --name <ACR_NAME> --query "username" -o tsv)

   az webapp config container set `
     --name my-fastapi-backend `
     --resource-group rg-genAI-sandbox `
     --docker-registry-server-url "https://<ACR_NAME>.azurecr.io" `
     --docker-registry-server-user $ACRUsername `
     --docker-registry-server-password $ACRPassword `
     --docker-custom-image-name "<ACR_NAME>.azurecr.io/fastapi-app:v1"
   ```
4. **(Optional) Add `.env` as App Settings**:
   ```powershell
   foreach ($line in Get-Content .env) {
       if ($line -and $line -notmatch '^#') {
           $parts = $line -split '=', 2
           $key = $parts[0].Trim()
           $value = $parts[1].Trim()

           az webapp config appsettings set `
             --resource-group rg-genAI-sandbox `
             --name my-fastapi-backend `
             --settings "$key=$value"
       }
   }
   ```
5. **Test your Web App**:
   ```powershell
   az webapp browse --resource-group rg-genAI-sandbox --name my-fastapi-backend
   ```

---

## 4. (Optional) Managing Infrastructure with Terraform

### 4.1 Example `main.tf`

```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
  required_version = ">= 1.0"
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "main" {
  name     = "rg-genAI-sandbox"
  location = "canadacentral"
}

resource "azurerm_container_registry" "acr" {
  name                = "multimodalrag"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
}

resource "azurerm_app_service_plan" "asp" {
  name                = "my-fastapi-plan"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  kind                = "Linux"
  reserved            = true

  sku {
    tier = "Basic"
    size = "B1"
  }
}

resource "azurerm_app_service" "backend" {
  name                = "my-fastapi-backend"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  app_service_plan_id = azurerm_app_service_plan.asp.id

  site_config {
    linux_fx_version = "DOCKER|${azurerm_container_registry.acr.login_server}/fastapi-app:v1"
  }

  app_settings = {
    "DOCKER_REGISTRY_SERVER_URL"      = "https://${azurerm_container_registry.acr.login_server}"
    "DOCKER_REGISTRY_SERVER_USERNAME" = azurerm_container_registry.acr.admin_username
    "DOCKER_REGISTRY_SERVER_PASSWORD" = azurerm_container_registry.acr.admin_password

    # Add environment variables from your .env here (or use Key Vault).
    "OPENAI_API_KEY" = "..."
  }
}
```

### 4.2 Basic Terraform Workflow

1. **Initialize**:
   ```powershell
   terraform init
   ```
2. **(Optional) Import Existing Resources** if they already exist:
   ```powershell
   terraform import azurerm_resource_group.main `
   "/subscriptions/<SUB_ID>/resourceGroups/rg-genAI-sandbox"

   # etc. for ACR, App Service, etc.
   ```
3. **Plan**:
   ```powershell
   terraform plan
   ```
4. **Apply**:
   ```powershell
   terraform apply
   ```

---

## Cleanup

To remove all resources (careful!):
```powershell
az group delete --name rg-genAI-sandbox --yes --no-wait
```

---

## Next Steps

- **CI/CD**: Automate Docker builds/tests/pushes with GitHub Actions or Azure DevOps.  
- **Monitoring**: Add Application Insights for performance/telemetry.  
- **Security**: Use Azure Key Vault for secrets instead of storing in `.env`.  
- **Scaling**: Increase App Service plan tier as needed.  
