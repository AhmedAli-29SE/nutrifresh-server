"""
Recommendations Router - AI-powered meal and health recommendations
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Header, Request

router = APIRouter(prefix="/api", tags=["Recommendations"])

_db_service = None
_auth_service = None
GPT_SEMAPHORE = asyncio.Semaphore(10)


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


class ConsumptionRequest(BaseModel):
    food_name: str = Field(...)


class MealRecommendationRequest(BaseModel):
    meal_type: str = Field("breakfast")
    ingredients: List[str] = Field(default=[])


def _generate_local_recommendations(ingredients: List[str], meal_type: str) -> List[Dict[str, Any]]:
    meal_suggestions = {
        "breakfast": [
            {"name": "Oatmeal with Fresh Fruits", "calories": 350, "protein": 12, "carbs": 55, "fat": 8, "description": "Heart-healthy oatmeal topped with seasonal fruits"},
            {"name": "Greek Yogurt Parfait", "calories": 280, "protein": 18, "carbs": 35, "fat": 6, "description": "Protein-rich yogurt with granola and berries"},
        ],
        "lunch": [
            {"name": "Grilled Chicken Salad", "calories": 420, "protein": 35, "carbs": 20, "fat": 18, "description": "Lean protein with fresh vegetables"},
            {"name": "Quinoa Buddha Bowl", "calories": 480, "protein": 18, "carbs": 65, "fat": 12, "description": "Plant-based complete protein bowl"},
        ],
        "dinner": [
            {"name": "Baked Salmon with Vegetables", "calories": 520, "protein": 42, "carbs": 25, "fat": 22, "description": "Omega-3 rich fish with roasted vegetables"},
            {"name": "Vegetable Curry with Brown Rice", "calories": 450, "protein": 15, "carbs": 70, "fat": 12, "description": "Antioxidant-rich vegetarian option"},
        ],
        "snack": [
            {"name": "Fresh Fruit Mix", "calories": 150, "protein": 2, "carbs": 35, "fat": 1, "description": "Natural sugars and vitamins"},
            {"name": "Mixed Nuts", "calories": 200, "protein": 6, "carbs": 8, "fat": 18, "description": "Healthy fats and protein"},
        ],
    }
    return meal_suggestions.get(meal_type.lower(), meal_suggestions["snack"])


async def _generate_meal_recommendations(meal_type: str, user_profile: Dict, user_id: Optional[int] = None) -> List[Dict]:
    from gpt_model.gptapi import generate_meal_recommendations_from_ingredients
    
    try:
        ingredients = []
        if user_id and _db_service:
            try:
                ingredients = await _db_service.get_user_meal_foods(user_id, limit=30)
            except:
                pass
        
        recommendations = await asyncio.to_thread(
            generate_meal_recommendations_from_ingredients,
            list(set(ingredients)), meal_type, user_profile, 3
        )
        
        return recommendations if recommendations else _generate_local_recommendations(ingredients, meal_type)
    except Exception as e:
        print(f"Error generating meal recommendations: {e}")
        return []


def create_recommendation_routes(db_service, auth_service, get_current_user_fn):
    init_services(db_service, auth_service)
    
    @router.post("/recommendations/consumption")
    async def get_consumption_recommendations(req: ConsumptionRequest, authorization: Optional[str] = Header(None)):
        from gpt_model.gptapi import generate_consumption_recommendations
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        profile = await _db_service.get_health_profile(current_user["user_id"]) or {}
        recs = generate_consumption_recommendations(req.food_name, profile)
        return recs
    
    @router.post("/recommendations/meals")
    async def get_meal_suggestions(authorization: Optional[str] = Header(None)):
        from gpt_model.gptapi import generate_meal_suggestions_personal
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        user_id = current_user.get("user_id")
        profile = await _db_service.get_health_profile(user_id) if user_id else {}
        
        history = await _db_service.get_user_scan_history(user_id, limit=10) if user_id else {}
        food_names = [item["food_name"] for item in history.get("foods", [])]
        
        suggestions = generate_meal_suggestions_personal(profile or {}, food_names)
        return {"suggestions": suggestions}
    
    @router.get("/meals/recommendations")
    async def get_meal_recommendations(meal_type: str = "breakfast", authorization: Optional[str] = Header(None)):
        try:
            current_user = await _get_current_user(authorization)
            user_profile = {}
            user_id = None
            
            if current_user:
                user_id = current_user["user_id"]
                profile_data = await _auth_service.get_user_profile(user_id)
                if profile_data:
                    user_profile = profile_data.get("profile", {})
            
            recommendations = await _generate_meal_recommendations(meal_type, user_profile, user_id)
            
            return {
                "success": True, "message": "Meal recommendations retrieved",
                "data": {"meal_type": meal_type, "recommendations": recommendations, "ai_generated": True}
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get recommendations: {str(e)}")
    
    @router.post("/meals/ai-suggestions")
    async def get_ai_meal_suggestions(request: Request, authorization: Optional[str] = Header(None)):
        try:
            current_user = await _get_current_user(authorization)
            data = await request.json()
            meal_type = data.get("meal_type", "breakfast")
            user_profile = data.get("user_profile", {})
            
            if current_user and not user_profile:
                profile_data = await _auth_service.get_user_profile(current_user["user_id"])
                if profile_data:
                    user_profile = profile_data.get("profile", {})
            
            user_id = current_user["user_id"] if current_user else None
            suggestions = await _generate_meal_recommendations(meal_type, user_profile, user_id)
            
            calorie_goal = 2000
            if user_id:
                stored_goals = await _db_service.get_user_nutrition_goals(user_id, period="daily")
                if stored_goals:
                    calorie_goal = stored_goals.get("calories", 2000)
            
            meal_calorie_target = calorie_goal // 4
            
            for suggestion in suggestions:
                suggestion["personalized"] = True
                suggestion["fits_goal"] = suggestion.get("calories", 0) <= meal_calorie_target * 1.2
            
            return {"success": True, "message": "AI meal suggestions generated", "data": {"suggestions": suggestions}}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get AI suggestions: {str(e)}")
    
    @router.post("/meals/from-saved")
    async def generate_meals_from_saved(authorization: Optional[str] = Header(None)):
        from gpt_model.gptapi import call_groq_api
        import re
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            usable_items = await _db_service.get_usable_saved_items(current_user["user_id"], min_freshness=30)
            
            if not usable_items:
                return {"success": True, "message": "No usable items", "data": {"meals": [], "items_used": []}}
            
            # Build a mapping from food_name (lowercase) to session_id for linking
            food_to_session = {item['food_name'].lower(): item['session_id'] for item in usable_items}
            
            items_info = []
            for item in usable_items:
                freshness_pct = item.get("freshness_percentage", 50)
                freshness_note = " (use soon!)" if freshness_pct < 50 else (" (very fresh)" if freshness_pct >= 80 else "")
                items_info.append(f"- {item['food_name']} ({freshness_pct}% fresh{freshness_note})")
            
            items_str = "\n".join(items_info)
            
            health_profile = await _db_service.get_health_profile(current_user["user_id"])
            health_context = ""
            if health_profile:
                conditions = []
                if health_profile.get("has_diabetes"):
                    conditions.append("diabetes")
                if health_profile.get("has_blood_pressure_issues"):
                    conditions.append("blood pressure issues")
                if health_profile.get("has_heart_issues"):
                    conditions.append("heart issues")
                if conditions:
                    health_context = f"\nUser has: {', '.join(conditions)}. Suggest appropriate meals."
            
            prompt = f"""Based on these available fresh food items:
{items_str}
{health_context}

Suggest 3-4 simple, healthy meal ideas using ONLY these ingredients.
Return ONLY a JSON array: [{{"name": "...", "description": "...", "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "items_used": []}}]"""

            async with GPT_SEMAPHORE:
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: call_groq_api(prompt, max_tokens=2000)
                )
            
            meals = []
            try:
                json_match = re.search(r'\[.*\]', response, re.DOTALL)
                if json_match:
                    meals = json.loads(json_match.group())
            except:
                food_name = usable_items[0]['food_name'] if usable_items else 'Fresh'
                meals = [{"name": f"Fresh {food_name} Salad", "description": f"Simple salad with {food_name}", "items_used": [food_name], "calories": 50, "protein": 2, "carbs": 10, "fat": 1}]
            
            # Add items_session_ids to each meal by matching items_used food names to session IDs
            for meal in meals:
                items_used = meal.get("items_used", [])
                session_ids = []
                for food_name in items_used:
                    # Try to find matching session_id (case-insensitive)
                    food_lower = food_name.lower() if isinstance(food_name, str) else ""
                    for saved_item in usable_items:
                        saved_name = saved_item['food_name'].lower()
                        # Match if the saved food name is in the items_used or vice versa
                        if food_lower in saved_name or saved_name in food_lower:
                            session_ids.append(saved_item['session_id'])
                            break
                # Add the session IDs to the meal for Flutter to use
                meal["items_session_ids"] = session_ids
            
            return {
                "success": True, "message": f"Generated {len(meals)} meal suggestions",
                "data": {"meals": meals, "items_used": [{"id": i["session_id"], "name": i["food_name"], "freshness": i["freshness_percentage"]} for i in usable_items]}
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate meals: {str(e)}")
    
    @router.post("/food/check-health-risk")
    async def check_food_health_risk(request: Request, authorization: Optional[str] = Header(None)):
        from gpt_model.gptapi import call_groq_api
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            data = await request.json()
            food_name = data.get("food_name", "")
            freshness_percentage = data.get("freshness_percentage", 50)
            
            if freshness_percentage < 30:
                return {"success": True, "is_risky": True, "should_discard": True, "warning": f"This {food_name} is too spoiled. Discard it."}
            
            health_profile = await _db_service.get_health_profile(current_user["user_id"])
            is_risky = False
            warning_message = None
            
            if health_profile:
                conditions = []
                if health_profile.get("has_diabetes"):
                    conditions.append("diabetes")
                if health_profile.get("has_blood_pressure_issues"):
                    conditions.append("blood pressure")
                if health_profile.get("has_heart_issues"):
                    conditions.append("heart condition")
                
                if conditions:
                    prompt = f"""User health conditions: {', '.join(conditions)}
Food: {food_name}, Freshness: {freshness_percentage}%
Is this risky? If yes, brief warning. If no, say "SAFE"."""

                    async with GPT_SEMAPHORE:
                        ai_response = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: call_groq_api(prompt, max_tokens=150)
                        )
                    
                    if ai_response and "SAFE" not in ai_response.upper():
                        is_risky = True
                        warning_message = ai_response.strip()
            
            return {"success": True, "is_risky": is_risky, "should_discard": False, "warning": warning_message}
        except Exception as e:
            return {"success": True, "is_risky": False, "warning": None}
    
    return router
