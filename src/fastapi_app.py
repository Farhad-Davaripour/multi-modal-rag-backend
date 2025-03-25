import os
import importlib
import logging
import requests
import jwt
import base64
from fastapi import Request, FastAPI, HTTPException, Depends, Security, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from typing import Dict, Any
from cryptography import x509
from dotenv import load_dotenv

# Azure OpenAI Imports
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.core.settings import Settings

# Custom tools and utility functions
import src.tools as tools
importlib.reload(tools)
from src.tools import (
    download_sharepoint_files,
    get_index_docs_summary,
    multimodal_query_engine,
    get_uploaded_index_n_docs_summary_n_document_url
)

# Load environment variables
load_dotenv(override=True)

# Logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# -----------------------------------------------------------------------------------------
# Azure OpenAI / LlamaIndex Configuration
# -----------------------------------------------------------------------------------------
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME = os.getenv("AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME")
AZURE_OPENAI_EMBEDDING_DEPLOYED_MODEL_NAME = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYED_MODEL_NAME")

# Derived Configuration
azure_openai_endpoint = (
    f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/"
    f"{AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME}/chat/completions?api-version=2024-08-01-preview"
)

llm = AzureOpenAI(
    model=AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME,
    deployment_name=AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME,
    api_key=AZURE_OPENAI_API_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version="2024-08-01-preview",
)

Settings.llm = llm
# -----------------------------------------------------------------------------------------
# Azure AD Authentication Configuration
# -----------------------------------------------------------------------------------------
TENANT_ID = os.getenv("TENANT_ID")    # Your Azure AD tenant ID
aud = os.getenv("AUD")    # The 'Application (client) ID' from your app registration
logger.info(f"aud: {aud}")
JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

bearer_scheme = HTTPBearer()

def verify_jwt(creds: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    """
    FastAPI dependency for verifying Azure AD-issued JWT tokens.
    Expects an Authorization: Bearer <token> header.
    """
    token = creds.credentials
    try:
        logger.info(f"Received token: {token[:20]}...")  # Log the beginning of the token

        # Decode the token header
        unverified_header = jwt.get_unverified_header(token)
        logger.info(f"Decoded token header: {unverified_header}")
        kid = unverified_header.get("kid")
        logger.info(f"KID from token header: {kid}")

        # Fetch public keys from JWKS URI
        jwks = requests.get(JWKS_URI).json()
        logger.info(f"Fetched JWKS: {jwks}")

        matching_key = None
        for key in jwks["keys"]:
            if key["kid"] == kid:
                matching_key = key
                break

        if not matching_key:
            logger.error("No matching key ID (kid) found in JWKS.")
            raise HTTPException(status_code=401, detail="No matching key ID in token header.")

        # Convert the x5c certificate to a PEM public key
        if "x5c" not in matching_key or not matching_key["x5c"]:
            logger.error("No valid x5c certificate found.")
            raise HTTPException(status_code=401, detail="No valid x5c certificate found.")
        x5c_value = matching_key["x5c"][0]
        der_data = base64.b64decode(x5c_value)
        cert_obj = x509.load_der_x509_certificate(der_data)
        public_key_obj = cert_obj.public_key()

        # Decode the token
        payload = jwt.decode(
            token,
            public_key_obj,
            audience=aud,  # Ensure this matches the aud claim
            algorithms=["RS256"]
        )

        logger.info(f"Decoded token payload: {payload}")
        logger.info(f"Audience (aud) claim from token: {payload.get('aud')}")

        expected_iss = f"https://sts.windows.net/{TENANT_ID}/"
        if payload.get("iss") != expected_iss:
            raise HTTPException(status_code=401, detail="Invalid issuer.")

        return payload

    except jwt.ExpiredSignatureError:
        logger.error("Token has expired.")
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidAudienceError:
        logger.error("Token audience (aud) claim mismatch.")
        raise HTTPException(status_code=401, detail="Token audience mismatch.")
    except jwt.PyJWTError as exc:
        logger.error(f"JWT decode error: {exc}")
        raise HTTPException(status_code=401, detail=str(exc))
    except HTTPException as e:
        logger.error(f"HTTP Exception: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")

# -----------------------------------------------------------------------------------------
# FastAPI App Setup
# -----------------------------------------------------------------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://multimodalrag-frontend.azurewebsites.net"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Make sure the OpenAPI doc includes a BearerAuth scheme
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Multi Modal RAG",
        version="1.0.0",
        description="This API requires a Bearer token for protected routes.",
        routes=app.routes,
    )
    # Add bearerAuth to the OpenAPI schema
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    # Setting global security requirements so all endpoints use it
    for path in openapi_schema["paths"].values():
        for method in path.values():
            method.setdefault("security", [{"BearerAuth": []}])
    app.openapi_schema = openapi_schema
    return openapi_schema

app.openapi = custom_openapi

# -----------------------------------------------------------------------------------------
# Models and Endpoints
# -----------------------------------------------------------------------------------------
class QueryModel(BaseModel):
    query: str  # The user query

@app.options("/query", include_in_schema=False)
def options_query():
    """
    Return 200 so the browser's CORS preflight can succeed.
    """
    return Response(status_code=200)

@app.post(
    "/query",
    summary="Handle Query",
    description="An endpoint that requires a valid Bearer token",
    tags=["Protected"],
    openapi_extra={"security": [{"BearerAuth": []}]},
)
def handle_query(
    input_data: QueryModel,
    user_payload: dict = Depends(verify_jwt),  # Actually enforces Azure AD token
):
    document_url_dict: Dict[str, Any] = {}
    document_summary_dict: Dict[str, str] = {}
    indexes: Dict[str, Any] = {}

    logger.info("Starting up and preparing environment...")

    # 1. load indexes and summaries
    indexes, document_summary_dict, document_url_dict = get_uploaded_index_n_docs_summary_n_document_url()
    if not indexes:
        logger.warning("No indexes were created. Check if documents were successfully processed.")
    else:
        logger.info("Indexes and summaries prepared successfully.")

    # 3. Ensure the query is not empty
    query = input_data.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    if not document_summary_dict:
        logger.error("Document summaries are empty. Ensure indexes were built successfully.")
        raise HTTPException(status_code=500, detail="No document summaries found.")

    # Prompt to select an index
    prompt = (
        f"Given the query '{query}', determine the most appropriate index (key) in the dictionary "
        f"based on the description (value) that corresponds best to the query. "
        f"Return only the index (key) as the output, nothing else. "
        f"Options: {', '.join([f'Index: {key}, Description: {value}' for key, value in document_summary_dict.items()])}"
    )

    try:
        selected_index = llm.complete(prompt).text.strip()
        logger.info(f"Selected index: {selected_index}")

        if selected_index not in indexes:
            logger.warning(f"LLM returned an invalid index: {selected_index}. Using a fallback if available.")
            if len(indexes) == 1:
                selected_index = next(iter(indexes))
                logger.info(f"Falling back to the only available index: {selected_index}")
            else:
                raise HTTPException(status_code=500, detail="LLM did not return a valid index.")

        index = indexes[selected_index]

        # Create and initialize the query engine
        query_engine = multimodal_query_engine(index)
        logger.info("Query engine has been initialized.")

        # Execute the query
        response = query_engine.query(query)
        
        # Extract image URLs from the response
        image_nodes = response.metadata.get("image_nodes", [])
        image_urls = [scored_img.node.image_url for scored_img in image_nodes if scored_img.node.image_url]

        retrieved_document = document_url_dict[selected_index]

        return {"response": response.response, "images": image_urls, "retrieved_document": retrieved_document}

    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while processing the query.")

@app.post(
    "/index_new_documents",
    summary="Index new documents",
    description="Endpoint to download documents and build new indexes",
    tags=["Protected"],
    openapi_extra={"security": [{"BearerAuth": []}]},
)
def handle_index_new_documents(
    input_data: QueryModel,
    user_payload: dict = Depends(verify_jwt),
):
    logger.info("Starting up and preparing environment to index new docs...")

    # 1. Download files from SharePoint
    document_url_dict = download_sharepoint_files()
    logger.info(f"Downloaded documents. Found {len(document_url_dict)} files.")

    # 2. Build or load indexes and summaries
    indexes, document_summary_dict = get_index_docs_summary()
    if not indexes:
        logger.warning("No indexes were created. Check if documents were successfully processed.")
    else:
        logger.info("Indexes and summaries prepared successfully.")

    # Simply return the summaries without any query logic:
    return {"document_summary_dict": document_summary_dict}

@app.get(
    "/status",
    summary="API Status Check",
    description="An endpoint to check the status of the API.",
    tags=["Status"],
    openapi_extra={"security": [{"BearerAuth": []}]},
)
def check_status(user_payload: dict = Depends(verify_jwt)):
    """
    Endpoint to check the status of the API.
    """
    return {"status": "API is running", "version": "1.0.0"}

@app.get("/")
def read_root():
    return {"message": "Hello from root!"}
