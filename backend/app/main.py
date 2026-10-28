from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from .api import upload, inspect

app = FastAPI(title=\"ProofLine API\", version=\"1.0.0\", description=\"AI QA Inspector for contractor photo verification\")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[\"http://localhost:5173\", \"http://127.0.0.1:5173\"],
    allow_credentials=True,
    allow_methods=[\"*\"],
    allow_headers=[\"*\"],
)

# Mount static files for uploads
static_path = os.path.join(os.path.dirname(__file__), \"static\")
os.makedirs(os.path.join(static_path, \"uploads\"), exist_ok=True)
app.mount(\"/static\", StaticFiles(directory=static_path), name=\"static\")

app.include_router(upload.router, prefix=\"/api\", tags=[\"upload\"])
app.include_router(inspect.router, prefix=\"/api\", tags=[\"inspect\"])

@app.get(\"/\")
def root():
    return {\"message\": \"ProofLine API\", \"docs\": \"/docs\"}

@app.get(\"/health\")
def health():
    return {\"status\": \"ok\", \"service\": \"proofline-api\"}
