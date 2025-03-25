# FastAPI Deployment with Docker & Azure

This repository shows how to build a **FastAPI** application, containerize it with Docker, and deploy it to **Azure** using Terraform. The code also demonstrates using Azure services like Container Registry, App Service, Key Vault, Cognitive Search, and (optionally) Azure Blob Storage for documents and images. Below is a concise guide to get started.

---

## 1. Prerequisites

1. **Azure CLI** installed locally or running in GitHub Actions.
2. **Terraform** installed locally or set up in CI.
3. **Docker** installed locally (to build the FastAPI container image).
4. **Azure Subscription** (with permission to create resource groups, app services, etc.).

---

## 2. Why Two Storage Accounts?

- **App/Project Storage**: For application files, documents, or other general data.  
- **Terraform State Storage**: A dedicated storage account used purely by Terraform to store its state files.  
  - This separation ensures your Terraform state is not accidentally altered by other operations, keeping your infrastructure definitions stable and isolated.

---

## 3. Create a Storage Account for Terraform State

Before running Terraform, ensure you have created a storage account for storing the Terraform backend state:

1. **Create a Resource Group** (or use an existing one):
   ```bash
   az group create --name <myResourceGroup> --location <myLocation>
   ```
2. **Create the Storage Account** (only for Terraform state):
   ```bash
   az storage account create \
     --name <tfStateStorageName> \
     --resource-group <myResourceGroup> \
     --location <myLocation> \
     --sku Standard_LRS
   ```
3. **Create a Blob Container** for the state:
   ```bash
   az storage container create \
     --name tfstate \
     --account-name <tfStateStorageName>
   ```

You will reference this storage account and container in the `main.tf` backend configuration to safely store the Terraform state.

---

## 4. Steps to Deploy

1. **Clone this Repository** and navigate into it.
2. **Configure Secrets** (in GitHub Actions or your environment) for your Azure credentials and any other required values (API keys, etc.). Make sure not to expose them publicly.
3. **Build and Push Docker Image** (manually or via GitHub Actions):
   ```bash
   docker build -t fastapi-app .
   docker tag fastapi-app <YOUR_ACR_NAME>.azurecr.io/fastapi-app:<VERSION>
   docker push <YOUR_ACR_NAME>.azurecr.io/fastapi-app:<VERSION>
   ```
4. **Run Terraform** (locally or in your CI workflow):
   ```bash
   cd infra
   terraform init
   terraform plan -var="env_map={...}"  # Provide your secrets/vars
   terraform apply -auto-approve
   ```
   - Terraform uses the backend storage account you created for its state.
5. **Validate** that:
   - **App Service** is up and running.
   - **Container** is pulled from ACR.
   - **Key Vault** is storing secrets properly.
   - **(Optional) Cognitive Services** (e.g., Search, OpenAI) are accessible.

---

## 5. List of Key Resources

1. **Azure Resource Group**  
2. **Container Registry (ACR)**  
3. **App Service Plan & App Service** (Runs the Docker container)  
4. **Azure Key Vault** (Securely store secrets)  
5. **Azure Cognitive Search** (Optional for indexing/search)  
6. **Azure OpenAI Service** (Optional for LLM usage)  
7. **Storage Account** (For App/Project data)  
8. **Separate Storage Account** (For Terraform state files)

---

## 6. FastAPI Local Testing (Optional)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run FastAPI:
   ```bash
   uvicorn fastapi_app:app --reload
   ```
3. Visit [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to test or explore the API.

---

## 7. Project Structure Overview

- **fastapi_app**: Core FastAPI code.
- **tools.py**: Helper functions (document parsing, storage upload, etc.).
- **main.tf**: Terraform configuration (resources, variables, secrets).
- **Workflow YAML**: CI/CD pipeline definition for building/pushing Docker images and applying Terraform.

---

## 8. Security & Next Steps

- Store sensitive values (like IDs and keys) in secure secret managers (e.g., GitHub Actions secrets, Azure Key Vault).
- Consider enabling role-based access control (RBAC) for tighter security on each Azure service.
- Integrate monitoring and logs (e.g., Application Insights) for production scenarios.

```