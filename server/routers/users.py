"""
Users Router - User profile, history, guides, and nutrition goals
Handles all user-related endpoints except authentication
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Header, Request

# Create router instance
router = APIRouter(prefix="/api", tags=["Users"])

# Service references
_db_service = None
_auth_service = None


def init_services(db_service, auth_service):
    """Initialize service references"""
    global _db_service, _auth_service
    _db_service = db_service
    _auth_service = auth_service


async def _get_current_user(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """Get current user from authorization header"""
    if not authorization or not _auth_service:
        return None
    try:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        token = parts[1]
        user = await _auth_service.verify_token(token)
        if user:
            user["token"] = token
        return user
    except Exception:
        return None


def _generate_data_driven_insights(totals: dict, goals: dict, meals_count: int, weekly_totals: dict, days_tracked: int, profile: dict) -> List[Dict]:
    """Generate insights based on actual user data when AI is unavailable"""
    insights = []
    
    # No data case
    if meals_count == 0 and all(totals.get(k, 0) == 0 for k in ["calories", "protein"]):
        insights.append({
            "title": "Start Tracking Today!",
            "content": "You haven't logged any meals today. Scan some food or log a meal to get personalized nutrition insights.",
            "insight_type": "info"
        })
        if days_tracked == 0:
            insights.append({
                "title": "Welcome!",
                "content": "Begin your nutrition journey by scanning fruits and vegetables or logging your meals.",
                "insight_type": "tip"
            })
        return insights
    
    # Calorie insight
    cal_consumed = totals.get("calories", 0)
    cal_goal = goals.get("calories", 2000)
    if cal_consumed > 0:
        cal_pct = round(cal_consumed / cal_goal * 100)
        if cal_pct < 50:
            insights.append({
                "title": "Calorie Intake Low",
                "content": f"You've consumed {cal_consumed} kcal ({cal_pct}% of goal). Consider having a nutritious snack.",
                "insight_type": "warning"
            })
        elif cal_pct <= 100:
            insights.append({
                "title": "On Track",
                "content": f"Great job! You've consumed {cal_consumed} kcal ({cal_pct}% of your {cal_goal} kcal goal).",
                "insight_type": "info"
            })
        else:
            insights.append({
                "title": "Calorie Goal Exceeded",
                "content": f"You've consumed {cal_consumed} kcal, which is {cal_pct - 100}% over your goal. Consider lighter options for remaining meals.",
                "insight_type": "warning"
            })
    
    # Protein insight
    protein = totals.get("protein", 0)
    protein_goal = goals.get("protein", 50)
    if protein_goal > 0:
        protein_pct = round(protein / protein_goal * 100)
        if protein_pct < 60:
            insights.append({
                "title": "Protein Needed",
                "content": f"Only {protein}g protein today ({protein_pct}% of goal). Add eggs, chicken, fish, or legumes.",
                "insight_type": "tip"
            })
        elif protein_pct >= 80:
            insights.append({
                "title": "Protein Goal",
                "content": f"Excellent! You've had {protein}g protein ({protein_pct}% of goal).",
                "insight_type": "info"
            })
    
    # Fiber insight
    fiber = totals.get("fiber", 0)
    fiber_goal = goals.get("fiber", 25)
    if fiber < fiber_goal * 0.5:
        insights.append({
            "title": "More Fiber Recommended",
            "content": f"Only {fiber}g fiber today. Add fruits, vegetables, or whole grains for better digestion.",
            "insight_type": "tip"
        })
    
    # Weekly trend
    if days_tracked >= 3:
        avg_cal = weekly_totals.get("calories", 0) / days_tracked
        insights.append({
            "title": "Weekly Average",
            "content": f"You're averaging {round(avg_cal)} kcal/day over {days_tracked} days this week.",
            "insight_type": "info"
        })
    
    # Health condition tips
    if profile.get("has_diabetes"):
        sugar = totals.get("sugar", 0)
        if sugar > 30:
            insights.append({
                "title": "Sugar Alert",
                "content": f"You've consumed {sugar}g sugar today. Consider reducing sugary foods.",
                "insight_type": "warning"
            })
    
    if profile.get("has_blood_pressure_issues"):
        insights.append({
            "title": "Heart Health",
            "content": "Monitor sodium intake. Choose fresh foods over processed ones.",
            "insight_type": "tip"
        })
    
    return insights[:5]  # Limit to 5 insights


class ProfileUpdateRequest(BaseModel):
    """Request model for profile updates"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    has_diabetes: Optional[bool] = None
    has_blood_pressure_issues: Optional[bool] = None
    has_heart_issues: Optional[bool] = None
    has_gut_issues: Optional[bool] = None
    other_chronic_diseases: Optional[str] = None
    allergies: Optional[List[str]] = None
    is_smoker: Optional[bool] = None
    is_drinker: Optional[bool] = None
    drinking_frequency: Optional[str] = None
    activity_level: Optional[str] = None
    sleep_quality: Optional[str] = None
    daily_water_intake_liters: Optional[float] = None
    eating_habits: Optional[str] = None
    goals: Optional[str] = None
    health_goal: Optional[str] = None
    dietary_restrictions: Optional[List[str]] = None


class NutritionGoalsRequest(BaseModel):
    """Request model for custom nutrition goals"""
    calories: Optional[int] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    fiber: Optional[float] = None
    period: str = Field("daily", description="Goals period: daily, weekly")


def _calculate_bmr_tdee(profile: Dict) -> Dict[str, float]:
    """Calculate BMR and TDEE using Mifflin-St Jeor equation"""
    weight = float(profile.get("weight_kg") or profile.get("weight", 70))
    height = float(profile.get("height_cm") or profile.get("height", 170))
    age = int(profile.get("age", 30))
    gender = str(profile.get("gender", "male")).lower()
    
    if gender in ["male", "m"]:
        bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else:
        bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161
    
    activity_multipliers = {
        "sedentary": 1.2, "light": 1.375, "lightly_active": 1.375,
        "moderate": 1.55, "moderately_active": 1.55,
        "active": 1.725, "very_active": 1.9, "extra_active": 1.9
    }
    
    activity = str(profile.get("activity_level", "moderate")).lower()
    multiplier = activity_multipliers.get(activity, 1.55)
    tdee = bmr * multiplier
    
    return {"bmr": round(bmr), "tdee": round(tdee)}


def create_user_routes(db_service, auth_service, get_current_user_fn):
    """Factory function to create user routes with dependencies"""
    init_services(db_service, auth_service)
    
    @router.get("/user/profile")
    async def get_profile(authorization: Optional[str] = Header(None)):
        """Get user health profile"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        # Map stored values to Flutter dropdown display values
        ACTIVITY_LEVEL_MAP = {
            "sedentary": "Sedentary",
            "light": "Lightly active", "lightly_active": "Lightly active",
            "moderate": "Moderately active", "moderately_active": "Moderately active",
            "active": "Very active", "very_active": "Very active", "extra_active": "Very active"
        }
        
        GENDER_MAP = {
            "male": "Male", "m": "Male",
            "female": "Female", "f": "Female",
            "other": "Other"
        }
        
        SLEEP_QUALITY_MAP = {
            "poor": "Poor",
            "fair": "Fair",
            "good": "Good",
            "excellent": "Excellent"
        }
        
        DRINKING_FREQUENCY_MAP = {
            "occasional": "Occasional",
            "regular": "Regular",
            "frequent": "Frequent"
        }
        
        WEIGHT_GOAL_MAP = {
            "loss": "Loss",
            "gain": "Gain",
            "maintain": "Maintain"
        }
        
        try:
            profile = await _auth_service.get_user_profile(current_user["user_id"])
            if profile:
                # Map values for Flutter dropdown compatibility
                profile_data = profile.get("profile", {})
                if profile_data:
                    # Map activity_level
                    stored_activity = str(profile_data.get("activity_level", "")).lower()
                    if stored_activity in ACTIVITY_LEVEL_MAP:
                        profile_data["activity_level"] = ACTIVITY_LEVEL_MAP[stored_activity]
                    
                    # Map gender
                    stored_gender = str(profile_data.get("gender", "")).lower()
                    if stored_gender in GENDER_MAP:
                        profile_data["gender"] = GENDER_MAP[stored_gender]
                    
                    # Map sleep_quality (default to "Good" if null/empty)
                    stored_sleep = str(profile_data.get("sleep_quality") or "good").lower()
                    profile_data["sleep_quality"] = SLEEP_QUALITY_MAP.get(stored_sleep, "Good")
                    
                    # Map drinking_frequency (default to "Occasional" if null/empty)
                    stored_drinking = str(profile_data.get("drinking_frequency") or "occasional").lower()
                    profile_data["drinking_frequency"] = DRINKING_FREQUENCY_MAP.get(stored_drinking, "Occasional")
                    
                    # Map goals.weight_goal (default to "Maintain" if null/empty)
                    goals_data = profile_data.get("goals")
                    if isinstance(goals_data, dict):
                        stored_weight_goal = str(goals_data.get("weight_goal") or "maintain").lower()
                        goals_data["weight_goal"] = WEIGHT_GOAL_MAP.get(stored_weight_goal, "Maintain")
                        profile_data["goals"] = goals_data
                    
                    profile["profile"] = profile_data
                
                return {"success": True, "message": "Profile retrieved", "data": profile}
            else:
                return {"success": True, "message": "No profile set", "data": {"profile": {}}}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")
    
    @router.post("/user/profile")
    async def update_profile(request: dict, authorization: Optional[str] = Header(None)):
        """Update user profile"""
        from fastapi import Request
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        # Map Flutter dropdown values to storage format
        ACTIVITY_LEVEL_REVERSE_MAP = {
            "Sedentary": "sedentary",
            "Lightly active": "light",
            "Moderately active": "moderate",
            "Very active": "active"
        }
        
        GENDER_REVERSE_MAP = {
            "Male": "male",
            "Female": "female",
            "Other": "other"
        }
        
        SLEEP_QUALITY_REVERSE_MAP = {
            "Poor": "poor",
            "Fair": "fair",
            "Good": "good",
            "Excellent": "excellent"
        }
        
        DRINKING_FREQUENCY_REVERSE_MAP = {
            "Occasional": "occasional",
            "Regular": "regular",
            "Frequent": "frequent"
        }
        
        WEIGHT_GOAL_REVERSE_MAP = {
            "Loss": "loss",
            "Gain": "gain",
            "Maintain": "maintain"
        }
        
        try:
            profile_data = request.get('profile', request)
            
            # Normalize activity_level
            if "activity_level" in profile_data:
                activity = profile_data["activity_level"]
                if activity in ACTIVITY_LEVEL_REVERSE_MAP:
                    profile_data["activity_level"] = ACTIVITY_LEVEL_REVERSE_MAP[activity]
            
            # Normalize gender
            if "gender" in profile_data:
                gender = profile_data["gender"]
                if gender in GENDER_REVERSE_MAP:
                    profile_data["gender"] = GENDER_REVERSE_MAP[gender]
            
            # Normalize sleep_quality
            if "sleep_quality" in profile_data:
                sleep = profile_data["sleep_quality"]
                if sleep in SLEEP_QUALITY_REVERSE_MAP:
                    profile_data["sleep_quality"] = SLEEP_QUALITY_REVERSE_MAP[sleep]
            
            # Normalize drinking_frequency
            if "drinking_frequency" in profile_data:
                drinking = profile_data["drinking_frequency"]
                if drinking in DRINKING_FREQUENCY_REVERSE_MAP:
                    profile_data["drinking_frequency"] = DRINKING_FREQUENCY_REVERSE_MAP[drinking]
            
            # Normalize goals.weight_goal
            if "goals" in profile_data and isinstance(profile_data["goals"], dict):
                goals = profile_data["goals"]
                if "weight_goal" in goals:
                    wg = goals["weight_goal"]
                    if wg in WEIGHT_GOAL_REVERSE_MAP:
                        goals["weight_goal"] = WEIGHT_GOAL_REVERSE_MAP[wg]
                    profile_data["goals"] = goals
            
            basic_info_fields = {'first_name', 'last_name'}
            health_profile_fields = {
                'age', 'gender', 'height_cm', 'weight_kg', 'height', 'weight',
                'has_diabetes', 'has_blood_pressure_issues', 'has_heart_issues', 'has_gut_issues',
                'other_chronic_diseases', 'allergies', 'is_smoker', 'is_drinker',
                'drinking_frequency', 'activity_level', 'sleep_quality', 'daily_water_intake_liters',
                'eating_habits', 'goals', 'health_goal', 'dietary_restrictions'
            }
            
            provided_fields = set(profile_data.keys())
            has_basic_info = bool(provided_fields & basic_info_fields)
            has_health_info = bool(provided_fields & health_profile_fields)
            
            success = True
            
            if has_basic_info:
                first_name = profile_data.get('first_name')
                last_name = profile_data.get('last_name')
                basic_success = await _auth_service.update_user_basic_info(
                    current_user["user_id"], first_name=first_name, last_name=last_name
                )
                success = success and basic_success
            
            if has_health_info:
                health_data = {k: v for k, v in profile_data.items() if k in health_profile_fields}
                health_success = await _auth_service.update_user_profile(current_user["user_id"], health_data)
                success = success and health_success
            
            if success:
                response = {"success": True, "message": "Profile updated successfully"}
                if has_health_info:
                    try:
                        goals = await _db_service.get_all_nutrition_goals(current_user["user_id"])
                        if goals:
                            response["nutrition_goals"] = goals
                    except:
                        pass
                return response
            else:
                raise HTTPException(status_code=400, detail="Failed to update profile")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")
    
    @router.get("/user/history")
    async def get_user_history(
        limit: int = 10,
        offset: int = 0,
        since: Optional[str] = None,
        authorization: Optional[str] = Header(None)
    ):
        """Get user's scan history"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            history = await _db_service.get_user_scan_history(current_user["user_id"], limit=limit, offset=offset, since=since)
            return {"success": True, "message": "History retrieved", "data": history, "sync_time": datetime.now().isoformat()}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get history: {str(e)}")
    
    @router.get("/user/guides")
    async def get_user_guides(authorization: Optional[str] = Header(None)):
        """Get list of guides seen by user"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            guides = await _db_service.get_seen_guides(current_user["user_id"])
            return {"success": True, "message": "Guides retrieved", "data": guides}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get guides: {str(e)}")
    
    @router.post("/user/guides/{guide_id}")
    async def mark_guide_seen(guide_id: str, authorization: Optional[str] = Header(None)):
        """Mark a guide as seen"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            success = await _db_service.mark_guide_seen(current_user["user_id"], guide_id)
            return {"success": success, "message": "Guide marked as seen" if success else "Failed"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to mark guide: {str(e)}")
    
    @router.get("/user/nutrition-goals")
    async def get_nutrition_goals(period: str = "daily", authorization: Optional[str] = Header(None)):
        """Get user's nutrition goals"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            goals = await _db_service.get_user_nutrition_goals(current_user["user_id"], period=period)
            
            if goals:
                return {"success": True, "message": "Goals retrieved", "data": goals}
            
            profile = await _db_service.get_health_profile(current_user["user_id"])
            
            if profile:
                calc = _calculate_bmr_tdee(profile)
                tdee = calc["tdee"]
                default_goals = {
                    "calories": tdee,
                    "protein": round(tdee * 0.2 / 4),
                    "carbs": round(tdee * 0.5 / 4),
                    "fat": round(tdee * 0.3 / 9),
                    "fiber": 30 if profile.get("gender", "male").lower() == "male" else 25
                }
            else:
                default_goals = {"calories": 2000, "protein": 50, "carbs": 250, "fat": 65, "fiber": 25}
            
            return {"success": True, "message": "Default goals generated", "data": default_goals, "generated": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get goals: {str(e)}")
    
    @router.post("/user/nutrition-goals")
    async def set_nutrition_goals(req: NutritionGoalsRequest, authorization: Optional[str] = Header(None)):
        """Set custom nutrition goals"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            goals_data = {k: v for k, v in {
                "calories": req.calories, "protein": req.protein, "carbs": req.carbs,
                "fat": req.fat, "fiber": req.fiber
            }.items() if v is not None}
            
            success = await _db_service.save_nutrition_goals(current_user["user_id"], goals_data, req.period)
            
            if success:
                return {"success": True, "message": "Nutrition goals saved"}
            raise HTTPException(status_code=400, detail="Failed to save goals")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save goals: {str(e)}")
    
    @router.post("/user/generate-goals")
    async def generate_ai_goals(authorization: Optional[str] = Header(None)):
        """Generate AI-powered personalized nutrition goals"""
        from gpt_model.gptapi import generate_personalized_nutrition_goals
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            profile = await _db_service.get_health_profile(current_user["user_id"])
            
            if not profile:
                raise HTTPException(status_code=400, detail="Please complete your health profile first")
            
            ai_goals = await asyncio.to_thread(generate_personalized_nutrition_goals, profile)
            
            if ai_goals:
                await _db_service.save_nutrition_goals(current_user["user_id"], ai_goals.get("daily", {}), "daily")
                return {"success": True, "message": "Personalized goals generated", "data": ai_goals}
            
            calc = _calculate_bmr_tdee(profile)
            fallback_goals = {"daily": {
                "calories": calc["tdee"], "protein": round(calc["tdee"] * 0.2 / 4),
                "carbs": round(calc["tdee"] * 0.5 / 4), "fat": round(calc["tdee"] * 0.3 / 9), "fiber": 30
            }}
            
            await _db_service.save_nutrition_goals(current_user["user_id"], fallback_goals["daily"], "daily")
            return {"success": True, "message": "Goals generated based on profile", "data": fallback_goals}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate goals: {str(e)}")
    
    @router.get("/user/stats")
    async def get_user_stats(authorization: Optional[str] = Header(None)):
        """Get user statistics overview"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            
            history = await _db_service.get_user_scan_history(user_id, limit=1000)
            scan_count = len(history.get("foods", [])) if history else 0
            
            saved = await _db_service.get_saved_items(user_id)
            saved_count = len(saved) if saved else 0
            
            today = datetime.now().date()
            week_start = today - timedelta(days=6)
            aggregates = await _db_service.get_daily_aggregates_range(user_id, week_start, today)
            days_tracked = len(aggregates) if aggregates else 0
            
            streak = 0
            check_date = today
            while True:
                day_data = await _db_service.get_daily_aggregate(user_id, check_date)
                if day_data and day_data.get("totals", {}).get("calories", 0) > 0:
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break
                if streak > 365:
                    break
            
            return {
                "success": True,
                "data": {
                    "total_scans": scan_count, "saved_items": saved_count,
                    "days_tracked_this_week": days_tracked, "current_streak": streak,
                    "member_since": current_user.get("created_at", "Unknown")
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
    
    # ============= NEW MISSING ENDPOINTS =============
    
    @router.get("/user/summary")
    async def get_user_summary(period: str = "today", authorization: Optional[str] = Header(None)):
        """Get user nutrition summary for a period"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            
            totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "sugar": 0}
            meals_count = 0
            
            if period == "today" or period == "daily":
                daily_data = await _db_service.get_daily_aggregate(user_id, today)
                if daily_data:
                    totals = daily_data.get("totals", totals)
                    meals_count = daily_data.get("meals_count", 0)
            elif period == "week" or period == "weekly":
                week_start = today - timedelta(days=6)
                aggregates = await _db_service.get_daily_aggregates_range(user_id, week_start, today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
                    meals_count += agg.get("meals_count", 0)
            elif period == "month" or period == "monthly":
                month_start = today - timedelta(days=29)
                aggregates = await _db_service.get_daily_aggregates_range(user_id, month_start, today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
                    meals_count += agg.get("meals_count", 0)
            elif period == "year" or period == "yearly":
                year_start = today - timedelta(days=364)
                aggregates = await _db_service.get_daily_aggregates_range(user_id, year_start, today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
                    meals_count += agg.get("meals_count", 0)
            elif period == "all":
                # Get all data from user's first meal
                aggregates = await _db_service.get_daily_aggregates_range(user_id, today - timedelta(days=3650), today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
                    meals_count += agg.get("meals_count", 0)
            
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {
                "calories": 2000, "protein": 50, "carbs": 250, "fat": 65
            }
            
            return {
                "success": True,
                "data": {
                    "period": period,
                    "date": str(today),
                    "totals": totals,  # Flutter expects 'totals' not 'nutrition'
                    "nutrition": totals,  # Keep for backward compatibility
                    "goals": goals,
                    "meals_count": meals_count,
                    "progress": {
                        "calories": round(totals.get("calories", 0) / max(goals.get("calories", 2000), 1) * 100, 1),
                        "protein": round(totals.get("protein", 0) / max(goals.get("protein", 50), 1) * 100, 1),
                        "carbs": round(totals.get("carbs", 0) / max(goals.get("carbs", 250), 1) * 100, 1),
                        "fat": round(totals.get("fat", 0) / max(goals.get("fat", 65), 1) * 100, 1)
                    }
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get summary: {str(e)}")
    
    @router.get("/user/health-indicators")
    async def get_health_indicators(period: str = "today", authorization: Optional[str] = Header(None)):
        """Get health indicators based on nutrition data"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            
            daily_data = await _db_service.get_daily_aggregate(user_id, today)
            totals = daily_data.get("totals", {}) if daily_data else {}
            
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {
                "calories": 2000, "protein": 50, "carbs": 250, "fat": 65, "fiber": 25
            }
            
            profile = await _db_service.get_health_profile(user_id) or {}
            
            indicators = []
            
            # Calorie balance
            cal_ratio = totals.get("calories", 0) / max(goals.get("calories", 2000), 1)
            if cal_ratio < 0.5:
                indicators.append({"name": "Calorie Intake", "status": "low", "value": round(cal_ratio * 100), "message": "You're under your calorie goal"})
            elif cal_ratio <= 1.1:
                indicators.append({"name": "Calorie Intake", "status": "good", "value": round(cal_ratio * 100), "message": "On track with calories"})
            else:
                indicators.append({"name": "Calorie Intake", "status": "high", "value": round(cal_ratio * 100), "message": "Exceeded calorie goal"})
            
            # Protein intake
            protein_ratio = totals.get("protein", 0) / max(goals.get("protein", 50), 1)
            indicators.append({
                "name": "Protein",
                "status": "good" if protein_ratio >= 0.8 else "low",
                "value": round(protein_ratio * 100),
                "message": "Good protein intake" if protein_ratio >= 0.8 else "Need more protein"
            })
            
            # Fiber intake
            fiber_ratio = totals.get("fiber", 0) / max(goals.get("fiber", 25), 1)
            indicators.append({
                "name": "Fiber",
                "status": "good" if fiber_ratio >= 0.8 else "low",
                "value": round(fiber_ratio * 100),
                "message": "Good fiber intake" if fiber_ratio >= 0.8 else "Eat more fiber-rich foods"
            })
            
            # Sugar check
            sugar = totals.get("sugar", 0)
            indicators.append({
                "name": "Sugar",
                "status": "good" if sugar < 50 else ("warning" if sugar < 75 else "high"),
                "value": round(sugar),
                "message": "Sugar intake is fine" if sugar < 50 else "Watch your sugar intake"
            })
            
            # Calculate REAL scores based on actual data
            
            # Nutrition score: Average of all nutrient ratios (clamped to 100)
            nutrient_scores = []
            for key, goal_val in [("calories", 2000), ("protein", 50), ("carbs", 250), ("fat", 65), ("fiber", 25)]:
                actual = totals.get(key, 0)
                goal = goals.get(key, goal_val)
                if goal > 0:
                    ratio = min(actual / goal, 1.2)  # Cap at 120%
                    score = ratio * 100 if ratio <= 1 else max(0, 100 - (ratio - 1) * 100)  # Penalize overconsumption
                    nutrient_scores.append(score)
            nutrition_score = round(sum(nutrient_scores) / len(nutrient_scores)) if nutrient_scores else 0
            
            # Freshness score: Based on user's saved items freshness
            freshness_score = 50  # Default
            try:
                saved_items = await _db_service.get_saved_items(user_id)
                if saved_items:
                    avg_freshness = sum(item.get("freshness_percentage", 50) for item in saved_items) / len(saved_items)
                    freshness_score = round(avg_freshness)
            except:
                pass
            
            # Variety score: Based on unique foods consumed
            variety_score = 0
            try:
                meals = await _db_service.get_user_meals(user_id, period=period)
                if meals:
                    unique_foods = set()
                    for meal in meals:
                        food_name = meal.get("food_name", "")
                        if food_name:
                            unique_foods.add(food_name.lower())
                    # 10+ unique foods = 100%, less = proportional
                    variety_score = min(len(unique_foods) * 10, 100)
            except:
                pass
            
            # Overall score: Weighted average
            overall = round(
                (nutrition_score * 0.4) + 
                (freshness_score * 0.3) + 
                (variety_score * 0.3)
            )
            
            return {
                "success": True,
                "data": {
                    "indicators": indicators,
                    "overall_score": overall,
                    "nutrition_score": nutrition_score,
                    "freshness_score": freshness_score,
                    "variety_score": variety_score,
                    "period": period,
                    "recommendations": [i["message"] for i in indicators if i["status"] != "good"]
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get health indicators: {str(e)}")
    
    @router.get("/user/nutrient-sources")
    async def get_nutrient_sources(period: str = "today", authorization: Optional[str] = Header(None)):
        """Get breakdown of nutrient sources from meals"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            meals = await _db_service.get_user_meals(user_id, period=period)
            
            sources = {
                "protein": [], "carbs": [], "fat": [], "fiber": [], "vitamins": []
            }
            
            food_contributions = {}
            
            for meal in (meals or []):
                for item in meal.get("items", []):
                    food_name = item.get("food_name", "Unknown")
                    nutrition = item.get("nutrition", {})
                    
                    if food_name not in food_contributions:
                        food_contributions[food_name] = {
                            "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0
                        }
                    
                    for key in food_contributions[food_name]:
                        food_contributions[food_name][key] += nutrition.get(key, 0)
            
            # Sort by contribution
            for nutrient in ["protein", "carbs", "fat", "fiber"]:
                sorted_foods = sorted(
                    food_contributions.items(),
                    key=lambda x: x[1].get(nutrient, 0),
                    reverse=True
                )[:5]
                sources[nutrient] = [
                    {"food": f[0], "amount": round(f[1].get(nutrient, 0), 1)}
                    for f in sorted_foods if f[1].get(nutrient, 0) > 0
                ]
            
            # Flutter expects data to be the sources map directly
            return {
                "success": True,
                "data": sources  # Return sources directly, not wrapped
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get nutrient sources: {str(e)}")
    
    @router.get("/user/meal-timing")
    async def get_meal_timing(authorization: Optional[str] = Header(None)):
        """Get meal timing analytics"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            meals = await _db_service.get_user_meals(user_id, period="week")
            
            timing_data = {
                "breakfast": {"count": 0, "avg_time": None, "avg_calories": 0},
                "lunch": {"count": 0, "avg_time": None, "avg_calories": 0},
                "dinner": {"count": 0, "avg_time": None, "avg_calories": 0},
                "snack": {"count": 0, "avg_time": None, "avg_calories": 0}
            }
            
            meal_times = {"breakfast": [], "lunch": [], "dinner": [], "snack": []}
            
            for meal in (meals or []):
                meal_type = meal.get("meal_type", "snack").lower()
                if meal_type in timing_data:
                    timing_data[meal_type]["count"] += 1
                    timing_data[meal_type]["avg_calories"] += meal.get("total_nutrition", {}).get("calories", 0)
                    
                    if meal.get("logged_at"):
                        try:
                            logged = datetime.fromisoformat(str(meal["logged_at"]).replace("Z", "+00:00"))
                            meal_times[meal_type].append(logged.hour + logged.minute / 60)
                        except:
                            pass
            
            for meal_type in timing_data:
                if timing_data[meal_type]["count"] > 0:
                    timing_data[meal_type]["avg_calories"] = round(
                        timing_data[meal_type]["avg_calories"] / timing_data[meal_type]["count"]
                    )
                if meal_times[meal_type]:
                    avg_hour = sum(meal_times[meal_type]) / len(meal_times[meal_type])
                    hours = int(avg_hour)
                    minutes = int((avg_hour - hours) * 60)
                    timing_data[meal_type]["avg_time"] = f"{hours:02d}:{minutes:02d}"
            
            # Flutter expects breakfast, lunch, dinner, efficiency directly
            total_meals = sum(t["count"] for t in timing_data.values())
            # Calculate efficiency based on meal regularity
            efficiency = min(100, (timing_data["breakfast"]["count"] + timing_data["lunch"]["count"] + timing_data["dinner"]["count"]) * 15)
            
            return {
                "success": True,
                "data": {
                    "breakfast": "on_time" if timing_data["breakfast"]["count"] > 0 else "skipped",
                    "lunch": "on_time" if timing_data["lunch"]["count"] > 0 else "skipped",
                    "dinner": "on_time" if timing_data["dinner"]["count"] > 0 else "skipped",
                    "efficiency": efficiency,
                    "timing": timing_data,
                    "total_meals": total_meals,
                    "recommendation": "Try to maintain consistent meal times for better digestion"
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get meal timing: {str(e)}")
    
    @router.get("/user/food-classification")
    async def get_food_classification(period: str = "today", authorization: Optional[str] = Header(None)):
        """Get food classification breakdown (fruits, vegetables, grains, etc.)"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            meals = await _db_service.get_user_meals(user_id, period=period)
            
            categories = {
                "fruits": {"count": 0, "items": []},
                "vegetables": {"count": 0, "items": []},
                "grains": {"count": 0, "items": []},
                "proteins": {"count": 0, "items": []},
                "dairy": {"count": 0, "items": []},
                "other": {"count": 0, "items": []}
            }
            
            category_keywords = {
                "fruits": ["apple", "banana", "orange", "mango", "grape", "berry", "melon", "papaya", "guava", "pineapple", "fruit"],
                "vegetables": ["carrot", "spinach", "broccoli", "tomato", "potato", "onion", "cabbage", "lettuce", "cucumber", "vegetable", "salad"],
                "grains": ["rice", "bread", "wheat", "pasta", "noodle", "cereal", "oat", "roti", "chapati", "grain"],
                "proteins": ["chicken", "fish", "meat", "egg", "beef", "mutton", "prawn", "shrimp", "tofu", "lentil", "dal", "bean"],
                "dairy": ["milk", "cheese", "yogurt", "curd", "butter", "paneer", "cream", "dairy"]
            }
            
            for meal in (meals or []):
                for item in meal.get("items", []):
                    food_name = item.get("food_name", "").lower()
                    category = item.get("category", "").lower()
                    
                    classified = False
                    for cat, keywords in category_keywords.items():
                        if any(kw in food_name or kw in category for kw in keywords):
                            categories[cat]["count"] += 1
                            if food_name not in categories[cat]["items"]:
                                categories[cat]["items"].append(food_name.title())
                            classified = True
                            break
                    
                    if not classified:
                        categories["other"]["count"] += 1
                        if food_name not in categories["other"]["items"]:
                            categories["other"]["items"].append(food_name.title())
            
            total = sum(c["count"] for c in categories.values())
            
            # Build healthy and risky lists for Flutter compatibility
            healthy_categories = ["fruits", "vegetables", "proteins"]
            risky_categories = ["other"]
            
            healthy = []
            risky = []
            
            for cat, data in categories.items():
                for item in data["items"][:3]:
                    food_entry = {"food": item, "category": cat}
                    if cat in healthy_categories:
                        healthy.append(food_entry)
                    elif cat in risky_categories:
                        risky.append(food_entry)
            
            return {
                "success": True,
                "data": {
                    "healthy": healthy,
                    "risky": risky,
                    "classification": {
                        cat: {
                            "count": data["count"],
                            "percentage": round(data["count"] / max(total, 1) * 100, 1),
                            "items": data["items"][:5]
                        }
                        for cat, data in categories.items()
                    },
                    "total_items": total,
                    "period": period
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get food classification: {str(e)}")
    
    @router.get("/user/ai-insights")
    async def get_ai_insights(force_refresh: bool = False, authorization: Optional[str] = Header(None)):
        """Get AI-powered nutrition insights based on ACTUAL user data"""
        from gpt_model.gptapi import generate_health_suggestions
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            
            # Get COMPREHENSIVE data for insights
            today = datetime.now().date()
            week_start = today - timedelta(days=6)
            
            # Get daily aggregate
            daily_data = await _db_service.get_daily_aggregate(user_id, today)
            totals = daily_data.get("totals", {}) if daily_data else {}
            meals_count = daily_data.get("meals_count", 0) if daily_data else 0
            
            # Get weekly aggregates for trend analysis
            weekly_aggregates = await _db_service.get_daily_aggregates_range(user_id, week_start, today)
            weekly_totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}
            days_with_data = 0
            for agg in (weekly_aggregates or []):
                agg_totals = agg.get("totals", {})
                if any(agg_totals.get(k, 0) > 0 for k in weekly_totals):
                    days_with_data += 1
                for key in weekly_totals:
                    weekly_totals[key] += agg_totals.get(key, 0)
            
            # Get user profile and goals
            profile = await _db_service.get_health_profile(user_id) or {}
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {
                "calories": 2000, "protein": 50, "carbs": 250, "fat": 65, "fiber": 25
            }
            
            # Get recent meals for context
            recent_meals = []
            try:
                meals_data = await _db_service.get_user_meals(user_id, period="today")
                recent_meals = [m.get("food_name", "") for m in (meals_data or []) if m.get("food_name")]
            except:
                pass
            
            # Build comprehensive context for AI
            context = {
                "today": totals,
                "weekly_totals": weekly_totals,
                "days_tracked": days_with_data,
                "meals_today": meals_count,
                "recent_foods": recent_meals[:10],
                "goals": goals,
                "profile": profile
            }
            
            # Generate AI insights with full context
            insights_list = []
            try:
                insights = await asyncio.to_thread(
                    generate_health_suggestions,
                    context, profile, goals
                )
                
                if insights and isinstance(insights, dict):
                    if insights.get("summary"):
                        insights_list.append({
                            "title": "Today's Summary",
                            "content": insights["summary"],
                            "insight_type": "info"
                        })
                    
                    for i, tip in enumerate(insights.get("tips", [])[:3]):
                        insights_list.append({
                            "title": f"Health Tip {i+1}",
                            "content": tip,
                            "insight_type": "tip"
                        })
                    
                    for area in insights.get("focus_areas", [])[:2]:
                        insights_list.append({
                            "title": "Focus Area",
                            "content": area,
                            "insight_type": "warning"
                        })
            except Exception as ai_err:
                print(f"AI insights generation error: {ai_err}")
            
            # Generate data-driven insights if AI fails or returns empty
            if not insights_list:
                insights_list = _generate_data_driven_insights(totals, goals, meals_count, weekly_totals, days_with_data, profile)
            
            return {
                "success": True,
                "data": {
                    "insights": insights_list,
                    "generated_at": datetime.now().isoformat(),
                    "based_on": {
                        "calories_today": totals.get("calories", 0),
                        "meals_logged": meals_count,
                        "days_tracked_this_week": days_with_data
                    }
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get AI insights: {str(e)}")
    
    @router.get("/user/comprehensive-nutrition")
    async def get_comprehensive_nutrition(period: str = "today", authorization: Optional[str] = Header(None)):
        """Get comprehensive nutrition data including micro and macro nutrients"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            
            totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "sugar": 0, "saturated_fat": 0}
            
            if period == "today" or period == "daily":
                daily_data = await _db_service.get_daily_aggregate(user_id, today)
                if daily_data:
                    totals = daily_data.get("totals", totals)
            elif period == "week" or period == "weekly":
                week_start = today - timedelta(days=6)
                aggregates = await _db_service.get_daily_aggregates_range(user_id, week_start, today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
            elif period == "month" or period == "monthly":
                month_start = today - timedelta(days=29)
                aggregates = await _db_service.get_daily_aggregates_range(user_id, month_start, today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
            elif period == "year" or period == "yearly":
                year_start = today - timedelta(days=364)
                aggregates = await _db_service.get_daily_aggregates_range(user_id, year_start, today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
            elif period == "all":
                aggregates = await _db_service.get_daily_aggregates_range(user_id, today - timedelta(days=3650), today)
                for agg in (aggregates or []):
                    agg_totals = agg.get("totals", {})
                    for key in totals:
                        totals[key] += agg_totals.get(key, 0)
            
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {
                "calories": 2000, "protein": 50, "carbs": 250, "fat": 65, "fiber": 25
            }
            
            # Macro breakdown
            total_macros = totals.get("protein", 0) + totals.get("carbs", 0) + totals.get("fat", 0)
            macro_distribution = {
                "protein": round(totals.get("protein", 0) / max(total_macros, 1) * 100, 1),
                "carbs": round(totals.get("carbs", 0) / max(total_macros, 1) * 100, 1),
                "fat": round(totals.get("fat", 0) / max(total_macros, 1) * 100, 1)
            }
            
            # Flutter expects flat numbers for macros/micros, not objects
            # Calculate period multiplier
            period_multiplier = 1
            if period == "week" or period == "weekly":
                period_multiplier = 7
            elif period == "month" or period == "monthly":
                period_multiplier = 30
            
            daily_goals = {
                "calories": goals.get("calories", 2000),
                "protein": goals.get("protein", 50),
                "carbs": goals.get("carbs", 275),
                "fat": goals.get("fat", 65),
                "fiber": goals.get("fiber", 28),
                "sugar": 50,
                "saturated_fat": 20
            }
            
            micro_goals = {
                "vitamin_a": 900, "vitamin_c": 90, "vitamin_d": 20,
                "vitamin_b12": 2.4, "calcium": 1000, "iron": 18,
                "potassium": 3500, "magnesium": 400, "sodium": 2300,
                "zinc": 11, "selenium": 55
            }
            
            period_goals = {k: v * period_multiplier for k, v in daily_goals.items()}
            period_micro_goals = {k: v * period_multiplier for k, v in micro_goals.items()}
            
            return {
                "success": True,
                "data": {
                    "period": period,
                    "period_multiplier": period_multiplier,
                    # Flat macros for Flutter compatibility
                    "macros": {
                        "calories": totals.get("calories", 0),
                        "protein": totals.get("protein", 0),
                        "carbs": totals.get("carbs", 0),
                        "fat": totals.get("fat", 0),
                        "fiber": totals.get("fiber", 0),
                        "sugar": totals.get("sugar", 0),
                        "saturated_fat": totals.get("saturated_fat", 0)
                    },
                    "distribution": macro_distribution,
                    # Flat micros for Flutter compatibility
                    "micros": {
                        "vitamin_a": totals.get("vitamin_a", 0),
                        "vitamin_c": totals.get("vitamin_c", 0),
                        "vitamin_d": totals.get("vitamin_d", 0),
                        "vitamin_b12": totals.get("vitamin_b12", 0),
                        "calcium": totals.get("calcium", 0),
                        "iron": totals.get("iron", 0),
                        "potassium": totals.get("potassium", 0),
                        "magnesium": totals.get("magnesium", 0),
                        "sodium": totals.get("sodium", 0),
                        "zinc": totals.get("zinc", 0),
                        "selenium": totals.get("selenium", 0)
                    },
                    "daily_goals": daily_goals,
                    "period_goals": period_goals,
                    "micro_goals": micro_goals,
                    "period_micro_goals": period_micro_goals
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get comprehensive nutrition: {str(e)}")
    
    @router.get("/favorites")
    async def get_favorites(authorization: Optional[str] = Header(None)):
        """Get user's favorite/saved foods (alias for saved items)"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            items = await _db_service.get_saved_items(current_user["user_id"])
            return {
                "success": True,
                "data": {"items": items or []},  # Flutter expects items inside data
                "items": items or [],  # Backward compatibility
                "count": len(items) if items else 0
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get favorites: {str(e)}")
    
    @router.delete("/favorites/{session_id}")
    async def delete_favorite(session_id: str, authorization: Optional[str] = Header(None)):
        """Remove item from favorites"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            success = await _db_service.remove_from_storage(current_user["user_id"], session_id, "removed")
            if success:
                return {"success": True, "message": "Item removed from favorites"}
            else:
                raise HTTPException(status_code=404, detail="Item not found in favorites")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete favorite: {str(e)}")
    
    # ============= ALIAS ENDPOINTS FOR FLUTTER COMPATIBILITY =============
    
    @router.get("/user/saved")
    async def get_user_saved(authorization: Optional[str] = Header(None)):
        """Get user's saved items (alias for /saved/all)"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            items = await _db_service.get_saved_items(current_user["user_id"])
            return {
                "success": True,
                "message": "Saved items retrieved",
                "data": {"items": items or []},  # Flutter expects items inside data
                "items": items or []  # Backward compatibility
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get saved items: {str(e)}")
    
    @router.post("/user/saved")
    async def save_user_item(request: Request, authorization: Optional[str] = Header(None)):
        """Save an item to favorites"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            body = await request.json()
            session_id = body.get("session_id")
            if not session_id:
                raise HTTPException(status_code=400, detail="session_id is required")
            
            # Get session data to save
            session_data = await _db_service.get_session(session_id)
            if not session_data:
                raise HTTPException(status_code=404, detail="Session not found")
            
            # Build saved item data
            freshness_info = session_data.get("freshness", {})
            saved_item = {
                "user_id": current_user["user_id"],
                "session_id": session_id,
                "food_name": session_data.get("food_name", "Unknown"),
                "storage_type": body.get("storage_type", "fridge"),
                "freshness_percentage": freshness_info.get("percentage", 50),
                "initial_freshness": freshness_info.get("percentage", 50),
                "freshness_level": freshness_info.get("level_normalized", "fresh"),
                "nutrition": session_data.get("nutrition", []),
                "image_url": session_data.get("image_url"),
                "saved_at": datetime.now().isoformat(),
            }
            
            item_id = await _db_service.save_to_storage(saved_item)
            
            return {
                "success": True,
                "message": "Item saved to favorites",
                "data": {"id": item_id, "session_id": session_id}
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save item: {str(e)}")
    
    @router.post("/user/saved/{session_id}/consumed")
    async def mark_saved_item_consumed(session_id: str, authorization: Optional[str] = Header(None)):
        """Mark a saved item as consumed"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            success = await _db_service.mark_item_consumed(user_id, session_id)
            
            if success:
                return {
                    "success": True,
                    "message": "Item marked as consumed",
                    "data": {"session_id": session_id, "is_consumed": True}
                }
            else:
                raise HTTPException(status_code=404, detail="Saved item not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to mark item as consumed: {str(e)}")
    
    @router.put("/saved-items/{session_id}/consume")
    async def consume_saved_item(session_id: str, authorization: Optional[str] = Header(None)):
        """Mark a saved item as consumed (alias endpoint for meals_service)"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            success = await _db_service.mark_item_consumed(user_id, session_id)
            
            if success:
                return {
                    "success": True,
                    "message": "Item marked as consumed",
                    "data": {"session_id": session_id, "is_consumed": True}
                }
            else:
                raise HTTPException(status_code=404, detail="Saved item not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to mark item as consumed: {str(e)}")
    
    @router.get("/user/dashboard")
    async def get_user_dashboard(authorization: Optional[str] = Header(None)):
        """Get user dashboard data (alias for /dashboard)"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            
            # Get today's data
            daily_data = await _db_service.get_daily_aggregate(user_id, today)
            totals = daily_data.get("totals", {}) if daily_data else {}
            meals_count = daily_data.get("meals_count", 0) if daily_data else 0
            
            # Get goals
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {
                "calories": 2000, "protein": 50, "carbs": 250, "fat": 65
            }
            
            # Get saved items count
            saved_items = await _db_service.get_saved_items(user_id)
            
            return {
                "success": True,
                "data": {
                    "today": {
                        "calories": totals.get("calories", 0),
                        "protein": totals.get("protein", 0),
                        "carbs": totals.get("carbs", 0),
                        "fat": totals.get("fat", 0),
                        "meals_count": meals_count
                    },
                    "goals": goals,
                    "progress": {
                        "calories": round(totals.get("calories", 0) / max(goals.get("calories", 2000), 1) * 100, 1),
                        "protein": round(totals.get("protein", 0) / max(goals.get("protein", 50), 1) * 100, 1),
                        "carbs": round(totals.get("carbs", 0) / max(goals.get("carbs", 250), 1) * 100, 1),
                        "fat": round(totals.get("fat", 0) / max(goals.get("fat", 65), 1) * 100, 1)
                    },
                    "saved_items_count": len(saved_items) if saved_items else 0,
                    "date": str(today)
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get dashboard: {str(e)}")
    
    @router.get("/user/advanced-dashboard")
    async def get_advanced_dashboard(authorization: Optional[str] = Header(None)):
        """Get advanced dashboard with more detailed stats"""
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            week_start = today - timedelta(days=6)
            
            # Get daily data
            daily_data = await _db_service.get_daily_aggregate(user_id, today)
            daily_totals = daily_data.get("totals", {}) if daily_data else {}
            
            # Get weekly data
            weekly_aggregates = await _db_service.get_daily_aggregates_range(user_id, week_start, today)
            weekly_totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
            weekly_meals = 0
            for agg in (weekly_aggregates or []):
                agg_totals = agg.get("totals", {})
                for key in weekly_totals:
                    weekly_totals[key] += agg_totals.get(key, 0)
                weekly_meals += agg.get("meals_count", 0)
            
            # Get goals
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {
                "calories": 2000, "protein": 50, "carbs": 250, "fat": 65
            }
            
            # Calculate averages
            daily_avg = {k: round(v / 7, 1) for k, v in weekly_totals.items()}
            
            return {
                "success": True,
                "data": {
                    "today": daily_totals,
                    "weekly": {
                        "totals": weekly_totals,
                        "meals_count": weekly_meals,
                        "daily_average": daily_avg
                    },
                    "goals": goals,
                    "streaks": {
                        "current": weekly_meals // 3 if weekly_meals > 0 else 0,
                        "best": 7
                    },
                    "insights": {
                        "most_eaten": "Fruits & Vegetables",
                        "nutrition_trend": "improving" if daily_totals.get("calories", 0) > 0 else "no data"
                    }
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get advanced dashboard: {str(e)}")
    
    return router
