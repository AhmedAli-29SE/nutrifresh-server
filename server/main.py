"""
NutriFresh API Server - Main Entry Point
========================================
A FastAPI-based nutrition tracking and food analysis server.

Features:
- Food image analysis with ML models (TensorFlow/Keras)
- Nutritional data from USDA FoodData Central
- AI-powered recommendations via Groq LLaMA
- User authentication with JWT
- PostgreSQL database integration

Architecture:
- Routers: API endpoints organized by domain (auth, meals, saved, etc.)
- Services: Database, Auth, Session management
- GPT Model: AI generation services via Groq API
- Models: ML models for food detection and freshness analysis
"""

import os
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==========================================
# SERVICE IMPORTS
# ==========================================

from services.database_service import DatabaseService
from services.auth_service import AuthService
from services.session_service import SessionService

# ==========================================
# ROUTER IMPORTS
# ==========================================

from routers import (
    food_analysis_router,
    init_food_analysis,
    create_auth_routes,
    create_user_routes,
    create_meal_routes,
    create_saved_routes,
    create_summary_routes,
    create_recommendation_routes,
    create_chat_routes,
)

# ==========================================
# CONFIGURATION
# ==========================================

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# ==========================================
# SERVICE INSTANCES
# ==========================================

db_service = DatabaseService()  # Uses env vars for connection
auth_service = AuthService(db_service)  # JWT_SECRET read from env
session_service = SessionService()


# ==========================================
# DEPENDENCY FUNCTIONS
# ==========================================

async def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency to extract and verify JWT token from Authorization header.
    Returns user dict if valid token, None otherwise.
    """
    if not authorization:
        return None
    
    try:
        parts = authorization.split()
        if len(parts) != 2:
            return None
        
        scheme, token = parts
        if scheme.lower() != "bearer":
            return None
        
        # Ensure db_service is connected
        if not db_service.pool:
            print("[AUTH] Database not connected, cannot verify token")
            return None
        
        user = await auth_service.verify_token(token)
        if user:
            user["token"] = token  # Store token for logout
        return user
    except Exception as e:
        print(f"[AUTH] Token verification error: {e}")
        return None


async def require_auth(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    FastAPI dependency that requires authentication.
    Raises HTTPException if not authenticated.
    """
    user = await get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# ==========================================
# APPLICATION LIFESPAN
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown handlers"""
    # STARTUP
    print("=" * 50)
    print("[SERVER] NutriFresh API Server Starting...")
    print("=" * 50)
    
    # Connect to database
    try:
        await db_service.connect()
        print("[OK] Database connected")
    except Exception as e:
        print(f"[WARN] Database connection failed: {e}")
        print("   Server will run with limited functionality")
    
    # Initialize services
    try:
        auth_service.db_service = db_service
        print("[OK] Auth service initialized")
    except Exception as e:
        print(f"[WARN] Auth service init failed: {e}")
    
    # Initialize router services
    init_food_analysis(db_service, auth_service, session_service)
    print("[OK] Food analysis router initialized")
    
    # Load ML models in background
    asyncio.create_task(_load_ml_models())
    
    print("=" * 50)
    print("[OK] Server ready at http://localhost:3001")
    print("[DOCS] API docs at http://localhost:3001/docs")
    print("=" * 50)
    
    yield  # Server is running
    
    # SHUTDOWN
    print("\n[SERVER] Shutting down...")
    try:
        await db_service.disconnect()
        print("[OK] Database disconnected")
    except Exception as e:
        print(f"[WARN] Database disconnect error: {e}")
    
    print("[SERVER] Server stopped")


async def _load_ml_models():
    """Load ML models in background"""
    try:
        from models.app import load_fruit_detection_model, load_freshness_model
        await asyncio.to_thread(load_fruit_detection_model)
        await asyncio.to_thread(load_freshness_model)
        print("[OK] ML models loaded")
    except Exception as e:
        print(f"[WARN] ML model loading error: {e}")


# ==========================================
# APPLICATION INSTANCE
# ==========================================

app = FastAPI(
    title="NutriFresh API",
    description="Food Analysis & Nutrition Tracking API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# ==========================================
# MIDDLEWARE
# ==========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# STATIC FILES
# ==========================================

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ==========================================
# REGISTER ROUTERS
# ==========================================

# Food Analysis (scan endpoints)
app.include_router(food_analysis_router)

# Authentication
auth_router = create_auth_routes(auth_service, db_service, get_current_user)
app.include_router(auth_router)

# Users (profile, history, goals)
users_router = create_user_routes(db_service, auth_service, get_current_user)
app.include_router(users_router)

# Meals (logging, tracking)
meals_router = create_meal_routes(db_service, auth_service, session_service, get_current_user)
app.include_router(meals_router)

# Saved Items (storage, favorites)
saved_router = create_saved_routes(db_service, auth_service, get_current_user)
app.include_router(saved_router)

# Summary (dashboard, daily/weekly summaries)
summary_router = create_summary_routes(db_service, auth_service, get_current_user)
app.include_router(summary_router)

# Recommendations (meal suggestions, consumption advice)
recommendations_router = create_recommendation_routes(db_service, auth_service, get_current_user)
app.include_router(recommendations_router)

# Chat (AI nutrition chatbot)
chat_router = create_chat_routes(db_service, auth_service, get_current_user)
app.include_router(chat_router)


# ==========================================
# HEALTH & UTILITY ENDPOINTS
# ==========================================

@app.get("/")
async def root():
    """Root endpoint - API info"""
    return {
        "name": "NutriFresh API",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    db_status = "connected" if db_service.pool else "disconnected"
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/health")
async def api_health():
    """API health check"""
    return await health_check()


@app.get("/api/ping")
async def ping():
    """Simple ping endpoint"""
    return {"ping": "pong", "timestamp": datetime.now().isoformat()}


# ==========================================
# RUN SERVER
# ==========================================

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 3001))
    
    print(f"\n[SERVER] Starting on {host}:{port}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
