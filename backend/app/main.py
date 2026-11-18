from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import admin, auth, customer, ingestion, super_owner, voice_ws
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register V1 API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(customer.router, prefix=settings.API_V1_STR)
app.include_router(ingestion.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)
app.include_router(super_owner.router, prefix=settings.API_V1_STR)
app.include_router(voice_ws.router, prefix=settings.API_V1_STR)
app.include_router(voice_ws.router)  # Also expose directly at /ws/voice/{session_id}


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "mock_voice_enabled": settings.USE_MOCK_VOICE,
    }
