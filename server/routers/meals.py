"""
Meals Router - Handles all meal logging and meal-related endpoints
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Header, Request

router = APIRouter(prefix="/api", tags=["Meals"])

_db_service = None
_auth_service = None
_session_service = None


def init_services(db_service, auth_service, session_service):
    global _db_service, _auth_service, _session_service
    _db_service = db_service
    _auth_service = auth_service
    _session_service = session_service


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


class MealLogRequest(BaseModel):
    meal_type: str = Field("snack")
    food_name: str = Field(...)
    calories: Optional[int] = 0
    protein_g: Optional[float] = 0.0
    carbs_g: Optional[float] = 0.0
    fat_g: Optional[float] = 0.0
    fiber_g: Optional[float] = 0.0
    sugar_g: Optional[float] = 0.0
    serving_size: Optional[str] = "1 serving"
    quantity: Optional[float] = 1.0
    image_url: Optional[str] = None
    source: Optional[str] = "manual"
    micros: Optional[Dict[str, float]] = {}
    
    class Config:
        extra = "ignore"


def _scale_nutrients(nutrition_list: list, quantity: float, weight_grams: float) -> dict:
    scaled = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "sugar": 0}
    multiplier = (weight_grams / 100.0) * quantity
    
    for nutrient in nutrition_list:
        name = nutrient.get("name", "").lower()
        value_str = str(nutrient.get("value", "0"))
        value = float(''.join(c for c in value_str if c.isdigit() or c == '.') or 0)
        scaled_value = round(value * multiplier, 2)
        
        if "calorie" in name or "energy" in name:
            scaled["calories"] = scaled_value
        elif "protein" in name:
            scaled["protein"] = scaled_value
        elif "carb" in name:
            scaled["carbs"] = scaled_value
        elif "fat" in name and "saturated" not in name:
            scaled["fat"] = scaled_value
        elif "fiber" in name:
            scaled["fiber"] = scaled_value
        elif "sugar" in name:
            scaled["sugar"] = scaled_value
    
    return scaled


def create_meal_routes(db_service, auth_service, session_service, get_current_user_fn):
    init_services(db_service, auth_service, session_service)
    
    @router.post("/meals")
    async def log_meal(request: Request, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            body = await request.json()
            
            def safe_int(val, default=0):
                try:
                    return int(float(str(val))) if val else default
                except:
                    return default
            
            def safe_float(val, default=0.0):
                try:
                    return float(str(val)) if val else default
                except:
                    return default
            
            meal_data = {
                "user_id": current_user["user_id"],
                "meal_type": body.get('meal_type', 'snack'),
                "food_name": body.get('food_name', 'Unknown'),
                "calories": safe_int(body.get('calories')),
                "protein_g": safe_float(body.get('protein_g')),
                "carbs_g": safe_float(body.get('carbs_g')),
                "fat_g": safe_float(body.get('fat_g')),
                "fiber_g": safe_float(body.get('fiber_g')),
                "sugar_g": safe_float(body.get('sugar_g')),
                "serving_size": body.get('serving_size', '1 serving'),
                "quantity": safe_float(body.get('quantity', 1.0)),
                "image_url": body.get('image_url'),
                "source": body.get('source', 'manual'),
                "micros": body.get('micros', {}),
            }
            
            meal_id = await _db_service.save_meal(meal_data)
            
            nutrients = {
                "calories": meal_data["calories"], "protein": meal_data["protein_g"],
                "carbs": meal_data["carbs_g"], "fat": meal_data["fat_g"],
                "fiber": meal_data["fiber_g"], "sugar": meal_data["sugar_g"],
            }
            
            await _db_service.update_daily_aggregate(current_user["user_id"], datetime.now().date(), nutrients)
            
            return {"success": True, "id": meal_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/meals")
    async def get_meals(period: str = "today", authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        meals = await _db_service.get_user_meals(current_user["user_id"], period)
        return {"meals": meals}
    
    @router.get("/user/meals")
    async def get_user_meals(period: str = "today", authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            meals = await _db_service.get_user_meals(current_user["user_id"], period)
            return {"success": True, "message": "Meals retrieved", "data": {"meals": meals}}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get meals: {str(e)}")
    
    @router.post("/user/meals")
    async def log_user_meal(request: Request, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            data = await request.json()
            nutrition_data = data.get("nutrition_data", {})
            logged_at_str = data.get("logged_at") or nutrition_data.get("consumed_at")
            
            logged_at = datetime.now()
            if logged_at_str:
                try:
                    clean_str = logged_at_str.replace('Z', '').replace('+00:00', '')
                    if '.' in clean_str:
                        clean_str = clean_str.split('.')[0] + '.' + clean_str.split('.')[1][:6]
                    logged_at = datetime.fromisoformat(clean_str)
                except:
                    logged_at = datetime.now()
            
            log_date = logged_at.date()
            
            meal_data = {
                "user_id": current_user["user_id"],
                "meal_type": data.get("meal_type", "snack"),
                "food_name": data.get("food_name", "Unknown"),
                "nutrition_data": nutrition_data,
                "image_url": data.get("image_url"),
                "source": nutrition_data.get("source", "manual"),
                "logged_at": logged_at.isoformat(),
                "items": nutrition_data.get("items", []),
            }
            
            meal_id = await _db_service.save_meal(meal_data)
            
            nutrients = {
                "calories": int(nutrition_data.get("calories", 0) or 0),
                "protein": float(nutrition_data.get("protein_g", nutrition_data.get("protein", 0)) or 0),
                "carbs": float(nutrition_data.get("carbs_g", nutrition_data.get("carbs", 0)) or 0),
                "fat": float(nutrition_data.get("fat_g", nutrition_data.get("fat", 0)) or 0),
                "fiber": float(nutrition_data.get("fiber_g", nutrition_data.get("fiber", 0)) or 0),
                "sugar": float(nutrition_data.get("sugar_g", nutrition_data.get("sugar", 0)) or 0),
            }
            
            await _db_service.update_daily_aggregate(current_user["user_id"], log_date, nutrients)
            
            return {
                "success": True, "message": "Meal logged successfully",
                "data": {"meal_id": meal_id, "logged_at": logged_at.isoformat(), "nutrients_added": nutrients}
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to log meal: {str(e)}")
    
    @router.delete("/user/meals/{meal_id}")
    async def delete_meal(meal_id: str, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            success = await _db_service.delete_meal(meal_id, current_user["user_id"])
            if success:
                return {"success": True, "message": "Meal deleted successfully"}
            raise HTTPException(status_code=404, detail="Meal not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete meal: {str(e)}")
    
    @router.get("/user/meals/today-summary")
    async def get_today_meal_summary(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            summary = await _db_service.get_meal_summary(current_user["user_id"], "today")
            return {"success": True, "message": "Today's meal summary retrieved", "data": summary}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get meal summary: {str(e)}")
    
    @router.get("/user/meals/daily-nutrition")
    async def get_daily_nutrition_analysis(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            analysis = await _db_service.get_daily_nutrition(current_user["user_id"])
            return {"success": True, "message": "Daily nutrition analysis retrieved", "data": analysis}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get nutrition analysis: {str(e)}")
    
    @router.get("/user/daily-aggregates")
    async def get_daily_aggregates(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        authorization: Optional[str] = Header(None)
    ):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            if not to_date:
                to_date = datetime.now().date().isoformat()
            if not from_date:
                from_date = (datetime.now().date() - timedelta(days=7)).isoformat()
            
            aggregates = await _db_service.get_daily_aggregates_range(current_user["user_id"], from_date, to_date)
            
            return {
                "success": True, "message": "Daily aggregates retrieved",
                "data": {"from_date": from_date, "to_date": to_date, "aggregates": aggregates}
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get daily aggregates: {str(e)}")
    
    @router.post("/scan/{session_id}/add-to-meal")
    async def add_scan_to_meal(session_id: str, request: Request, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            data = await request.json()
            quantity = float(data.get("quantity", 1.0))
            weight_grams = float(data.get("weight_grams", 100.0))
            meal_type = data.get("meal_time", data.get("meal_type", "snack"))
            
            scan_data = await _db_service.get_session(session_id)
            if not scan_data:
                raise HTTPException(status_code=404, detail="Scan session not found")
            
            if not scan_data.get("user_id"):
                raise HTTPException(status_code=400, detail="Cannot add anonymous scan to meal")
            
            if scan_data.get("user_id") != current_user["user_id"]:
                raise HTTPException(status_code=403, detail="This scan does not belong to your account")
            
            nutrition_list = scan_data.get("nutrition", [])
            scaled_nutrients = _scale_nutrients(nutrition_list, quantity, weight_grams)
            
            meal_data = {
                "user_id": current_user["user_id"],
                "meal_type": meal_type,
                "food_name": scan_data.get("food_name", "Unknown"),
                "nutrition_data": scaled_nutrients,
                "image_url": scan_data.get("image_url"),
                "scan_id": session_id,
                "weight_grams": weight_grams,
                "quantity": quantity,
                "nutrients_snapshot": scaled_nutrients,
                "logged_at": datetime.now().isoformat()
            }
            
            meal_id = await _db_service.save_meal(meal_data)
            
            meal_item_id = await _db_service.save_meal_item({
                "meal_id": meal_id,
                "scan_id": session_id,
                "user_id": current_user["user_id"],
                "quantity": quantity,
                "weight_grams": weight_grams,
                "nutrients_snapshot": scaled_nutrients
            })
            
            today = datetime.now().date()
            await _db_service.update_daily_aggregate(current_user["user_id"], today, scaled_nutrients)
            await _db_service.update_session_add_to_meal(session_id, True)
            
            daily_totals = await _db_service.get_daily_aggregate(current_user["user_id"], today)
            
            return {
                "success": True, "message": "Scan added to meal successfully",
                "data": {"meal_id": meal_id, "meal_item_id": meal_item_id, "scaled_nutrients": scaled_nutrients, "daily_totals": daily_totals}
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to add to meal: {str(e)}")
    
    return router
