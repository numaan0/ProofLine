from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from .api import upload, inspect, inspections, notifications, samples
from .device import device_middleware
from .guardrails.middleware import guardrail_exception_handler
from .guardrails.errors import GuardrailViolation, GuardrailValidationError

app = FastAPI(title="ProofLine API", version="1.0.0", description="AI QA Inspector for contractor photo verification")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(device_middleware)

app.add_exception_handler(GuardrailViolation, guardrail_exception_handler)
app.add_exception_handler(GuardrailValidationError, guardrail_exception_handler)

static_path = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(os.path.join(static_path, "uploads"), exist_ok=True)
os.makedirs(os.path.join(static_path, "masks"), exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(inspect.router, prefix="/api", tags=["inspect"])
app.include_router(inspections.router, prefix="/api", tags=["inspections"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(samples.router, prefix="/api", tags=["samples"])

@app.get("/")
def root():
    return {"message": "ProofLine API", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok", "service": "proofline-api"}