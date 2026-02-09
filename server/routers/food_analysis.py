"""
Food Analysis Router - Handles food image analysis endpoints
Includes ML model inference for food detection and freshness analysis
"""

import uuid
import asyncio
import base64
import numpy as np
import cv2
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import aiofiles

# Create router instance
router = APIRouter(prefix="/api", tags=["Food Analysis"])

# Upload directory for images
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Service references (set by init_services)
_db_service = None
_auth_service = None
_session_service = None


class Base64AnalyzeRequest(BaseModel):
    """Request model for base64 image analysis"""
    image: str = Field(..., description="Base64 encoded image data")
    session_id: Optional[str] = Field(None, description="Optional session ID")


def init_services(db_service, auth_service, session_service):
    """Initialize service references"""
    global _db_service, _auth_service, _session_service
    _db_service = db_service
    _auth_service = auth_service
    _session_service = session_service


async def _get_user_from_auth_header(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """Extract and verify JWT token from Authorization header"""
    if not authorization or not _auth_service:
        return None
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return None
        return await _auth_service.verify_token(token)
    except Exception:
        return None


def _normalize_freshness_label(label: str) -> str:
    """Normalize freshness label to snake_case"""
    l = (label or '').strip().lower()
    if l in ("fresh", "freshness.fresh"):
        return "fresh"
    if l in ("mid fresh", "mid-fresh", "mid_fresh", "medium"):
        return "mid_fresh"
    if l in ("spoiled", "rotten", "stale", "not fresh", "not_fresh"):
        return "spoiled"
    return l or "fresh"


def _build_unified_response(
    *,
    session_id: str,
    image_url: str,
    food_name: str,
    top_predictions: List[Dict[str, Any]],
    freshness_class: str,
    freshness_label_raw: str,
    freshness_confidence: float,
    nutrition_map: Dict[str, float],
    storage_recs: List[Dict[str, Any]],
    health_suggestions: List[Dict[str, Any]],
    recipes: List[Dict[str, Any]] = [],
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build unified response format for food analysis"""
    
    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, v))
    
    pct = _clamp(int(round(freshness_confidence)), 0, 100)
    
    freshness_obj = {
        "level": freshness_label_raw if isinstance(freshness_label_raw, str) else (freshness_class or "fresh"),
        "level_normalized": freshness_class if isinstance(freshness_class, str) else "fresh",
        "percentage": pct,
    }
    
    def unit_for(name: str) -> str:
        lower = name.lower()
        if any(x in lower for x in ["calorie", "energy"]):
            return "kcal"
        if any(x in lower for x in ["vitamin a", "vitamin k", "folate", "selenium"]):
            return "µg"
        if any(x in lower for x in ["vitamin",]):
            return "mg"
        if any(x in lower for x in ["protein", "carbo", "sugar", "fiber", "fat"]):
            return "g"
        if any(x in lower for x in ["sodium", "potassium", "calcium", "magnesium", "phosphorus", "iron", "zinc", "copper", "manganese"]):
            return "mg"
        return ""
    
    nutrition_list = [
        {"name": k, "value": f"{v} {unit_for(k)}".strip(), "icon": "nutrition"}
        for k, v in nutrition_map.items()
    ]
    
    storage_list = [
        {
            "method": rec.get("method", "storage"),
            "icon": "storage",
            "estimated_extension_days": rec.get("estimated_extension_days", 3),
            "message": rec.get("message", "Store properly to maintain freshness."),
        }
        for rec in storage_recs[:5]
    ]
    
    health_list = [
        {
            "name": h.get("name", "General"),
            "score": int(h.get("score", 0)),
            "icon": "warning",
            "message": h.get("message", ""),
        }
        for h in health_suggestions[:5]
    ]
    
    return {
        "food_name": food_name,
        "category": "Produce",
        "freshness": freshness_obj,
        "nutrition": nutrition_list,
        "storage_recommendations": storage_list,
        "health_risk_factors": health_list,
        "recipes": recipes,
        "session_id": session_id,
        "user_id": user_id,
        "image_url": image_url,
        "timestamp": datetime.now().isoformat(),
        "status": "completed",
        "top_predictions": top_predictions,
    }


# Nutrition cache
_nutrition_cache: Dict[str, Dict[str, float]] = {}
_nutrition_cache_times: Dict[str, float] = {}
_nutrition_cache_ttl = 60 * 60 * 24  # 24 hours


async def _get_nutrition_with_cache(food_name: str) -> Dict[str, float]:
    """Get nutrition data from USDA API with caching"""
    from usda_foodcentral.usdaapi import get_food_id, get_nutrient_data
    
    cache_key = food_name.lower().strip()
    now = datetime.now().timestamp()
    
    if cache_key in _nutrition_cache:
        if (now - _nutrition_cache_times.get(cache_key, 0)) < _nutrition_cache_ttl:
            return _nutrition_cache[cache_key]
    
    try:
        fdc_id, _ = await asyncio.to_thread(get_food_id, food_name)
        if fdc_id:
            nutrition_data = await asyncio.to_thread(get_nutrient_data, fdc_id)
            _nutrition_cache[cache_key] = nutrition_data
            _nutrition_cache_times[cache_key] = now
            return nutrition_data
    except Exception as e:
        print(f"Error fetching nutrition data: {e}")
    return {}


async def _generate_groq_suggestions(food_name: str, freshness: str, nutrition: Dict, user_profile: Dict = None):
    """Generate AI suggestions via Groq API using PARALLEL calls for 3x speed improvement."""
    from gpt_model.gptapi import parallel_food_analysis
    
    try:
        # Use parallel API calls - 3x faster than sequential!
        results = await parallel_food_analysis(food_name, freshness, user_profile or {})
        return (
            results.get("storage_recommendations", []),
            results.get("health_suggestions", []),
            results.get("meal_recipes", [])
        )
    except Exception as e:
        print(f"Error generating suggestions: {e}")
        return ([], [], [])


# Model loading
_models_loaded = False


def _ensure_models_loaded():
    """Ensure ML models are loaded"""
    global _models_loaded
    if _models_loaded:
        return
    from models.app import load_fruit_detection_model, load_freshness_model
    load_fruit_detection_model()
    load_freshness_model()
    _models_loaded = True


@router.post("/analyze-food")
async def analyze_food_upload(
    image: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """Analyze food image upload (multipart/form-data)"""
    from models.app import analyze_image
    from gpt_model.gptapi import generate_consumption_recommendations
    
    # Get current user if token provided
    current_user = None
    if authorization:
        current_user = await _get_user_from_auth_header(authorization)
        if current_user:
            user_id = str(current_user["user_id"])
    
    session_id = session_id or str(uuid.uuid4())
    
    # Get file from either 'image' or 'file' field
    upload_file = image or file
    if not upload_file:
        raise HTTPException(status_code=400, detail="No image file provided")
    
    # Read image data
    try:
        image_bytes = await upload_file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read image: {str(e)}")
    
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large, maximum size is 10MB")
    
    # Save uploaded file
    timestamp = int(datetime.now().timestamp() * 1000)
    unique_filename = f"image-{timestamp}-{uuid.uuid4().hex[:8]}.jpg"
    file_path = UPLOAD_DIR / unique_filename
    
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(image_bytes)
    
    # Process image
    try:
        np_arr = np.frombuffer(image_bytes, np.uint8)
        cv_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if cv_img is None:
            raise ValueError("Invalid image content")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {str(e)}")
    
    _t0 = datetime.now()
    _ensure_models_loaded()
    
    # Detect fruit and freshness (Unified)
    analysis_result, analysis_error = analyze_image(cv_img)
    if analysis_error:
        raise HTTPException(status_code=500, detail=f"Analysis error: {analysis_error}")
    
    # Extract results
    top_name = analysis_result.get("fruit_name", "Unknown")
    top_confidence = analysis_result.get("fruit_confidence", 0)
    
    # Construct top_predictions for response compatibility
    top_predictions = analysis_result.get("top_5_predictions", [])
    if not top_predictions:
        top_predictions = [{"name": top_name, "confidence": top_confidence}]

    print(f"[FOOD_DETECTION] Top: {top_name} ({top_confidence}%)")
    
    # NOT A FOOD CHECK
    MIN_FOOD_CONFIDENCE = 30.0 # Threshold lowered to 30% to catch apples (35%) and oranges (49%)
    if top_confidence < MIN_FOOD_CONFIDENCE:
        print(f"[NOT_A_FOOD] Confidence {top_confidence}% < {MIN_FOOD_CONFIDENCE}%")
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "error": "not_a_food",
                "message": "The uploaded image does not appear to be a recognizable food item.",
                "session_id": session_id,
                "confidence": top_confidence
            }
        )
    

    # Use the freshness score/status directly from the model
    freshness_conf = analysis_result.get("freshness_confidence", 0)
    freshness_class_raw = analysis_result.get("freshness_status", "Fresh")
    freshness_class = _normalize_freshness_label(freshness_class_raw)
    
    # Get nutrition data
    nutrition_map = await _get_nutrition_with_cache(top_name)
    
    # Generate recommendations
    storage_recs, health_suggestions, recipes = await _generate_groq_suggestions(
        top_name, freshness_class, nutrition_map
    )
    
    # Generate consumption recommendations ONLY for logged-in users
    consumption_recs = None
    if user_id and _auth_service:
        try:
            user_profile_data = await _auth_service.get_user_profile(int(user_id))
            user_profile = user_profile_data.get("profile", {}) if user_profile_data else {}
            consumption_recs = generate_consumption_recommendations(top_name, user_profile)
        except Exception as e:
            print(f"Error generating consumption recs: {e}")
    
    # Build response
    response = _build_unified_response(
        session_id=session_id,
        image_url=f"/uploads/{unique_filename}",
        food_name=top_name,
        top_predictions=top_predictions,
        freshness_class=freshness_class,
        freshness_label_raw=freshness_class_raw,
        freshness_confidence=freshness_conf,
        nutrition_map=nutrition_map,
        storage_recs=storage_recs,
        health_suggestions=health_suggestions,
        recipes=recipes if user_id else [],  # Only for logged-in users
        user_id=user_id,
    )
    
    if consumption_recs and user_id:
        response["consumption_recommendations"] = consumption_recs
    
    response["processing_time_ms"] = int((datetime.now() - _t0).total_seconds() * 1000)
    
    # Save to session service
    if _session_service:
        await _session_service.store_session(session_id, response)
    
    # Save to database ONLY for logged-in users
    if _db_service and _db_service.pool and user_id:
        try:
            session_data = {
                "user_id": int(user_id),
                "food_name": top_name,
                "category": response.get("category", "Produce"),
                "freshness": response.get("freshness", {}),
                "nutrition": response.get("nutrition", []),
                "storage_recommendations": response.get("storage_recommendations", []),
                "consumption_recommendations": response.get("consumption_recommendations"),
                "health_risk_factors": response.get("health_risk_factors", []),
                "image_url": response.get("image_url"),
                "timestamp": datetime.now().isoformat(),
                "status": "completed"
            }
            await _db_service.save_session(session_id, session_data)
            print(f"[SCAN] Saved for user {user_id}")
        except Exception as e:
            print(f"Error saving session: {e}")
    elif not user_id:
        print(f"[SCAN] Skipping save for unlogged user")
    
    return response


@router.post("/analyze-base64")
async def analyze_food_base64(
    request: Base64AnalyzeRequest,
    authorization: Optional[str] = Header(None)
):
    """Analyze food from base64 image data"""
    from models.app import analyze_image
    from gpt_model.gptapi import generate_consumption_recommendations
    
    session_id = request.session_id or str(uuid.uuid4())
    user_id = None
    
    if authorization:
        current_user = await _get_user_from_auth_header(authorization)
        if current_user:
            user_id = str(current_user["user_id"])
    
    if not request.image:
        raise HTTPException(status_code=400, detail="No image data provided")
    
    try:
        base64_data = request.image
        if base64_data.startswith('data:image/'):
            base64_data = base64_data.split(',')[1]
        image_bytes = base64.b64decode(base64_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {str(e)}")
    
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large, maximum size is 10MB")
    
    # Save file
    timestamp = int(datetime.now().timestamp() * 1000)
    filename = f"base64-{timestamp}.jpg"
    file_path = UPLOAD_DIR / filename
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(image_bytes)
    
    # Decode image
    try:
        np_arr = np.frombuffer(image_bytes, np.uint8)
        cv_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if cv_img is None:
            raise ValueError("Invalid image content")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {str(e)}")
    
    _t0 = datetime.now()
    _ensure_models_loaded()
    
    analysis_result, analysis_error = analyze_image(cv_img)
    if analysis_error:
        raise HTTPException(status_code=500, detail=f"Analysis error: {analysis_error}")
    
    # Extract results
    top_name = analysis_result.get("fruit_name", "Unknown")
    top_confidence = analysis_result.get("fruit_confidence", 0)
    
    top_predictions = analysis_result.get("top_5_predictions", [])
    if not top_predictions:
        top_predictions = [{"name": top_name, "confidence": top_confidence}]
    
    MIN_FOOD_CONFIDENCE = 40.0
    if top_confidence < MIN_FOOD_CONFIDENCE:
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "error": "not_a_food",
                "message": "The uploaded image does not appear to be a recognizable food item.",
                "session_id": session_id,
                "confidence": top_confidence
            }
        )
    
    freshness_conf = analysis_result.get("freshness_confidence", 0)
    freshness_class_raw = analysis_result.get("freshness_status", "Fresh")
    freshness_class = _normalize_freshness_label(freshness_class_raw)
    
    nutrition_map = await _get_nutrition_with_cache(top_name)
    storage_recs, health_suggestions, recipes = await _generate_groq_suggestions(
        top_name, freshness_class, nutrition_map
    )
    
    consumption_recs = None
    if user_id and _auth_service:
        try:
            user_profile_data = await _auth_service.get_user_profile(int(user_id))
            user_profile = user_profile_data.get("profile", {}) if user_profile_data else {}
            consumption_recs = generate_consumption_recommendations(top_name, user_profile)
        except Exception as e:
            print(f"Error generating consumption recs: {e}")
    
    response = _build_unified_response(
        session_id=session_id,
        image_url=f"/uploads/{filename}",
        food_name=top_name,
        top_predictions=top_predictions,
        freshness_class=freshness_class,
        freshness_label_raw=freshness_class_raw,
        freshness_confidence=freshness_conf,
        nutrition_map=nutrition_map,
        storage_recs=storage_recs,
        health_suggestions=health_suggestions,
        recipes=recipes if user_id else [],
        user_id=user_id,
    )
    
    if consumption_recs and user_id:
        response["consumption_recommendations"] = consumption_recs
    
    response["processing_time_ms"] = int((datetime.now() - _t0).total_seconds() * 1000)
    
    if _session_service:
        await _session_service.store_session(session_id, response)
    
    if _db_service and _db_service.pool and user_id:
        session_data = {
            "user_id": int(user_id),
            "food_name": top_name,
            "category": response.get("category", "Produce"),
            "freshness": response.get("freshness", {}),
            "nutrition": response.get("nutrition", []),
            "storage_recommendations": response.get("storage_recommendations", []),
            "consumption_recommendations": response.get("consumption_recommendations"),
            "health_risk_factors": response.get("health_risk_factors", []),
            "image_url": response.get("image_url"),
            "timestamp": datetime.now().isoformat(),
            "status": "completed"
        }
        await _db_service.save_session(session_id, session_data)
    
    return response


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get session data by ID"""
    try:
        if _db_service and _db_service.pool:
            db_session = await _db_service.get_session(session_id)
            if db_session:
                return db_session
        
        if _session_service:
            session_data = await _session_service.get_session(session_id)
            if session_data:
                return session_data
        
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/food-history")
async def get_food_history(limit: int = 10, offset: int = 0):
    """Get food analysis history (legacy endpoint)"""
    if _session_service:
        history = await _session_service.get_food_history(limit, offset)
        return {"success": True, "data": history}
    return {"success": True, "data": []}
