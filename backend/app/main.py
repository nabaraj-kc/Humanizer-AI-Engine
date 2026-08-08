"""
backend/app/main.py
===================
Main entry point for the FastAPI Humanizer AI Engine application.
Configures middleware, route registration, and global exception handlers.
"""

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO / aiohttp
import typing

class SubscriptableObject:
    def __class_getitem__(cls, item):
        return object
    def __init__(self, *args, **kwargs):
        pass

# Force override draft types that raise TypeErrors in early 3.11 alphas
typing.Unpack = SubscriptableObject
typing.TypeVarTuple = SubscriptableObject
typing.Required = object
typing.NotRequired = object
typing.Self = object

try:
    import typing_extensions
    typing_extensions.Unpack = SubscriptableObject
    typing_extensions.TypeVarTuple = SubscriptableObject
    typing_extensions.Required = object
    typing_extensions.NotRequired = object
    typing_extensions.Self = object
except ImportError:
    pass


import sys
from pathlib import Path
# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

from backend.app.core.config import get_settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("humanizer_api")

settings = get_settings()

from backend.app.api.websockets import router as ws_router
from backend.app.api.upload import router as upload_router
from backend.app.api.stats import router as stats_router

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
)

app.include_router(ws_router)
app.include_router(upload_router)
app.include_router(stats_router)

# Apply CORS Middleware
# Allow localhost origins for dev frontend configurations
origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global Exception Handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Catches Pydantic validation errors (HTTP 422) and formats them cleanly,
    avoiding leaks of internal details or unformatted tracebacks.
    """
    logger.warning(f"Validation error occurred on path {request.url.path}: {exc}")
    errors = exc.errors()
    formatted_errors = []
    for err in errors:
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        formatted_errors.append({
            "field": loc,
            "type": err.get("type"),
            "message": err.get("msg")
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation Error",
            "errors": formatted_errors
        }
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Passes standard HTTPExceptions through to the client with their custom
    status code and detail message.
    """
    logger.info(f"HTTPException on path {request.url.path}: code={exc.status_code}, detail={exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Intercepts unexpected internal exceptions (HTTP 500), prevents
    unformatted stack trace leaks, and returns a clean error payload.
    """
    logger.exception(f"Unexpected internal server error on path {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal Server Error",
            "message": str(exc)
        }
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint to verify backend initialization."""
    return {
        "status": "ok",
        "title": settings.APP_TITLE,
        "version": settings.APP_VERSION,
    }


@app.get("/")
async def root_status():
    """Welcome API message returning status health check metrics."""
    return {
        "status": "online",
        "service": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "frontend": "http://localhost:8080"
    }


# Temporary route to test global exception handler (500)
@app.get("/test-error")
async def trigger_error():
    raise RuntimeError("Intentional database connection timeout")


# Temporary POST route to test validation validation error (422)
from pydantic import BaseModel, Field

class TestPayload(BaseModel):
    item_id: int = Field(..., description="Must be an integer")
    name: str = Field(..., min_length=3)

@app.post("/test-validation")
async def trigger_validation(payload: TestPayload):
    return {"status": "success", "payload": payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()}


# ---------------------------------------------------------------------------
# Stage 15 Verification Test Guardrail
# ---------------------------------------------------------------------------

def run_tests():
    from fastapi.testclient import TestClient
    print("=== Stage 15: FastAPI Core App Verification ===")
    print()

    client = TestClient(app, raise_server_exceptions=False)

    # 1. Health check verification
    print("  --- Test 1: GET /health check ---")
    response = client.get("/health")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "ok"
    assert data["title"] == settings.APP_TITLE
    assert data["version"] == settings.APP_VERSION
    print(f"  [PASS] GET /health returned {data}")
    print()

    # 2. Trigger intentional internal error (500)
    print("  --- Test 2: Internal Server Error handler ---")
    response_err = client.get("/test-error")
    assert response_err.status_code == 500, f"Expected 500, got {response_err.status_code}"
    data_err = response_err.json()
    assert "detail" in data_err
    assert data_err["detail"] == "Internal Server Error"
    assert "Intentional database connection" in data_err["message"]
    print(f"  [PASS] GET /test-error was intercepted and returned: {data_err}")
    print()

    # 3. Trigger validation error (422) with broken payload
    print("  --- Test 3: Input Validation Error handler ---")
    # Broken payload: item_id is a string that cannot be coerced to int, name is too short
    broken_payload = {
        "item_id": "not-an-int",
        "name": "ab"
    }
    response_val = client.post("/test-validation", json=broken_payload)
    assert response_val.status_code == 422, f"Expected 422, got {response_val.status_code}"
    data_val = response_val.json()
    assert data_val["detail"] == "Validation Error"
    assert "errors" in data_val
    errors = data_val["errors"]
    assert len(errors) == 2, f"Expected 2 validation errors, got {len(errors)}"
    
    # Confirm exact field mappings are captured cleanly
    fields = [err["field"] for err in errors]
    assert any("item_id" in f for f in fields)
    assert any("name" in f for f in fields)
    
    print(f"  [PASS] POST /test-validation validation errors formatted cleanly: {data_val}")
    print()

    print("Stage 15 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
