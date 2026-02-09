"""
Saved Items Router - Handles food saving/favorites and storage management
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Header, Request

router = APIRouter(prefix="/api", tags=["Saved Items"])

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


class SaveItemRequest(BaseModel):
    session_id: str = Field(...)
    storage_type: str = Field("fridge")
    notes: Optional[str] = None


class RemoveItemRequest(BaseModel):
    session_id: str = Field(...)
    reason: Optional[str] = Field("consumed")


def _estimate_expiration_days(freshness_level: str, storage_type: str) -> int:
    base_days = {"fresh": 7, "mid_fresh": 4, "not_fresh": 1}
    storage_multiplier = {"freezer": 4, "fridge": 1, "pantry": 0.7}
    base = base_days.get(freshness_level.lower(), 5)
    mult = storage_multiplier.get(storage_type.lower(), 1)
    return max(1, int(base * mult))


def create_saved_routes(db_service, auth_service, get_current_user_fn):
    init_services(db_service, auth_service)
    
    @router.post("/saved/add")
    async def add_to_saved(req: SaveItemRequest, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            session_data = await _db_service.get_session(req.session_id)
            if not session_data:
                raise HTTPException(status_code=404, detail="Session not found")
            
            freshness_info = session_data.get("freshness", {})
            freshness_level = freshness_info.get("level_normalized", "fresh")
            freshness_pct = freshness_info.get("percentage", 50)
            
            expiration_days = _estimate_expiration_days(freshness_level, req.storage_type)
            
            saved_item = {
                "user_id": current_user["user_id"],
                "session_id": req.session_id,
                "food_name": session_data.get("food_name", "Unknown"),
                "storage_type": req.storage_type,
                "freshness_percentage": freshness_pct,
                "initial_freshness": freshness_pct,
                "freshness_level": freshness_level,
                "nutrition": session_data.get("nutrition", []),
                "image_url": session_data.get("image_url"),
                "notes": req.notes,
                "estimated_expiration_days": expiration_days,
                "saved_at": datetime.now().isoformat(),
            }
            
            item_id = await _db_service.save_to_storage(saved_item)
            
            return {
                "success": True, "message": f"Saved to {req.storage_type}",
                "data": {"id": item_id, "expiration_days": expiration_days, "freshness": freshness_pct}
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save item: {str(e)}")
    
    @router.post("/saved/remove")
    async def remove_from_saved(req: RemoveItemRequest, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            success = await _db_service.remove_from_storage(current_user["user_id"], req.session_id, req.reason)
            
            if success:
                return {"success": True, "message": f"Item removed ({req.reason})"}
            else:
                raise HTTPException(status_code=404, detail="Item not found in storage")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to remove item: {str(e)}")
    
    @router.get("/saved/all")
    async def get_all_saved(storage_type: Optional[str] = None, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            items = await _db_service.get_saved_items(current_user["user_id"])
            
            for item in items:
                saved_at_str = item.get("saved_at")
                if saved_at_str:
                    try:
                        saved_at = datetime.fromisoformat(saved_at_str.replace('Z', ''))
                        days_stored = (datetime.now() - saved_at).days
                        initial = item.get("initial_freshness", 100)
                        decay_rates = {"freezer": 0.5, "fridge": 3, "pantry": 5}
                        decay_rate = decay_rates.get(item.get("storage_type", "fridge"), 3)
                        current_freshness = max(0, initial - (days_stored * decay_rate))
                        item["current_freshness"] = round(current_freshness, 1)
                        item["days_stored"] = days_stored
                    except:
                        item["current_freshness"] = item.get("freshness_percentage", 50)
            
            return {"success": True, "message": "Saved items retrieved", "data": items}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get saved items: {str(e)}")
    
    @router.get("/user/saved-foods")
    async def get_saved_foods(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            items = await _db_service.get_saved_items(current_user["user_id"])
            return {"success": True, "message": "Saved foods retrieved", "data": items}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get saved foods: {str(e)}")
    
    @router.post("/user/saved-foods")
    async def save_food_item(request: Request, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            data = await request.json()
            session_id = data.get("session_id") or str(uuid.uuid4())
            storage_type = data.get("storage_type", "fridge")
            
            session_data = None
            if data.get("session_id"):
                session_data = await _db_service.get_session(data["session_id"])
            
            food_name = data.get("food_name") or (session_data.get("food_name") if session_data else "Unknown")
            
            freshness_info = data.get("freshness", {})
            if session_data and not freshness_info:
                freshness_info = session_data.get("freshness", {})
            
            freshness_pct = freshness_info.get("percentage", 50)
            freshness_level = freshness_info.get("level_normalized", "fresh")
            
            expiration_days = _estimate_expiration_days(freshness_level, storage_type)
            
            saved_item = {
                "user_id": current_user["user_id"],
                "session_id": session_id,
                "food_name": food_name,
                "storage_type": storage_type,
                "freshness_percentage": freshness_pct,
                "initial_freshness": freshness_pct,
                "freshness_level": freshness_level,
                "nutrition": data.get("nutrition", []) or (session_data.get("nutrition") if session_data else []),
                "image_url": data.get("image_url") or (session_data.get("image_url") if session_data else None),
                "notes": data.get("notes"),
                "estimated_expiration_days": expiration_days,
                "saved_at": datetime.now().isoformat(),
            }
            
            item_id = await _db_service.save_to_storage(saved_item)
            
            return {
                "success": True, "message": f"Food saved to {storage_type}",
                "data": {"id": item_id, "session_id": session_id, "expiration_days": expiration_days}
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save food: {str(e)}")
    
    @router.delete("/user/saved-foods/{session_id}")
    async def delete_saved_food(session_id: str, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            success = await _db_service.remove_from_storage(current_user["user_id"], session_id, "removed")
            
            if success:
                return {"success": True, "message": "Food item removed"}
            else:
                raise HTTPException(status_code=404, detail="Food item not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to remove food: {str(e)}")
    
    @router.get("/storage/summary")
    async def get_storage_summary(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            items = await _db_service.get_saved_items(current_user["user_id"])
            
            summary = {
                "total_items": len(items),
                "by_storage": {"fridge": 0, "freezer": 0, "pantry": 0},
                "expiring_soon": [],
                "spoiled": []
            }
            
            for item in items:
                storage = item.get("storage_type", "fridge")
                summary["by_storage"][storage] = summary["by_storage"].get(storage, 0) + 1
                
                saved_at_str = item.get("saved_at")
                if saved_at_str:
                    try:
                        saved_at = datetime.fromisoformat(saved_at_str.replace('Z', ''))
                        days_stored = (datetime.now() - saved_at).days
                        expiration_days = item.get("estimated_expiration_days", 7)
                        days_until_expiry = expiration_days - days_stored
                        
                        if days_until_expiry <= 0:
                            summary["spoiled"].append({
                                "food_name": item.get("food_name"),
                                "session_id": item.get("session_id"),
                                "days_overdue": abs(days_until_expiry)
                            })
                        elif days_until_expiry <= 2:
                            summary["expiring_soon"].append({
                                "food_name": item.get("food_name"),
                                "session_id": item.get("session_id"),
                                "days_remaining": days_until_expiry
                            })
                    except:
                        pass
            
            return {"success": True, "data": summary}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get storage summary: {str(e)}")
    
    return router
