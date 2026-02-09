"""
Chat Router - AI-powered nutrition chatbot
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Header

router = APIRouter(prefix="/api", tags=["Chat"])

_db_service = None
_auth_service = None


def init_services(db_service, auth_service):
    global _db_service, _auth_service
    _db_service = db_service
    _auth_service = auth_service


async def _get_current_user(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    if not authorization or not _auth_service:
        return None
    try:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        user = await _auth_service.verify_token(parts[1])
        if user:
            user["token"] = parts[1]
        return user
    except:
        return None


class ChatRequest(BaseModel):
    message: str = Field(...)
    history: Optional[List[Dict[str, str]]] = Field(default=[])


def create_chat_routes(db_service, auth_service, get_current_user_fn):
    init_services(db_service, auth_service)
    
    @router.post("/chat")
    async def chat_endpoint(req: ChatRequest, authorization: Optional[str] = Header(None)):
        from gpt_model.gptapi import generate_chat_response
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user.get("id") or current_user.get("user_id")
            
            profile = {}
            if user_id and _db_service:
                profile = await _db_service.get_health_profile(user_id) or {}
            
            consumption_context = ""
            if user_id and _db_service:
                try:
                    today = datetime.now().date()
                    from_date = today - timedelta(days=6)
                    aggregates = await _db_service.get_daily_aggregates_range(user_id, from_date, today)
                    
                    total = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}
                    for agg in (aggregates or []):
                        totals_data = agg.get("totals", {}) or {}
                        for key in total:
                            val = totals_data.get(key, 0)
                            total[key] += float(val) if val else 0
                    
                    days_count = len(aggregates) if aggregates else 1
                    avg = {k: round(v / days_count, 1) for k, v in total.items()}
                    
                    consumption_context = f"Weekly avg: {avg.get('calories', 0)} cal, {avg.get('protein', 0)}g protein"
                except:
                    pass
            
            user_first_name = current_user.get("first_name", "")
            if not user_first_name and current_user.get("name"):
                user_first_name = current_user.get("name", "").split()[0]
            
            enhanced_profile = {
                **(profile or {}),
                "consumption_context": consumption_context,
                "user_id": user_id,
                "first_name": user_first_name
            }

            if user_id and _db_service:
                try:
                    recent_meals_data = await _db_service.get_recent_meals(user_id, limit=5)
                    if recent_meals_data:
                        enhanced_profile["recent_meals"] = [m.get("food_name", "") for m in recent_meals_data if m.get("food_name")]
                except:
                    pass
                
                try:
                    scan_history = await _db_service.get_user_scan_history(user_id, limit=5)
                    if scan_history:
                        enhanced_profile["recent_scans"] = [f.get("food_name", "") for f in scan_history.get("foods", []) if f.get("food_name")]
                except:
                    pass
            
            if profile:
                if profile.get("dietary_restrictions"):
                    enhanced_profile["dietary_info"] = f"Dietary restrictions: {', '.join(profile['dietary_restrictions'])}"
                if profile.get("allergies"):
                    enhanced_profile["allergy_info"] = f"Allergies: {', '.join(profile['allergies'])}"
                if profile.get("health_goal"):
                    enhanced_profile["goal_info"] = f"Health goal: {profile['health_goal']}"
            
            response = generate_chat_response(req.message, req.history or [], enhanced_profile)
            return {"success": True, "response": response}
            
        except Exception as e:
            print(f"Chat error: {e}")
            return {"success": False, "response": "Sorry, I encountered an error. Please try again."}
    
    return router
