from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import admin, appointments, auth, customer, dataset_admin, ingestion, super_owner, voice_ws
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration - Allow local frontend development origins with credentials
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register V1 API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(auth.router)  # Root alias for /auth/*
app.include_router(customer.router, prefix=settings.API_V1_STR)
app.include_router(customer.router)  # Root alias for /customer/*
app.include_router(ingestion.router, prefix=settings.API_V1_STR)
app.include_router(dataset_admin.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)
app.include_router(appointments.router, prefix=settings.API_V1_STR)
app.include_router(appointments.router)  # Root alias for /appointments/*
app.include_router(super_owner.router, prefix=settings.API_V1_STR)
app.include_router(voice_ws.router, prefix=settings.API_V1_STR)
app.include_router(voice_ws.router)  # Also expose directly at /ws/voice/{session_id}


@app.get("/health", tags=["Health"])
@app.get(f"{settings.API_V1_STR}/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "mock_voice_enabled": settings.USE_MOCK_VOICE,
    }
