"""
Summary Router - Dashboard, nutrition summary, and insights endpoints
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Header

router = APIRouter(prefix="/api", tags=["Summary & Dashboard"])

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


def create_summary_routes(db_service, auth_service, get_current_user_fn):
    init_services(db_service, auth_service)
    
    @router.get("/summary/daily")
    async def get_daily_summary(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            
            daily_data = await _db_service.get_daily_aggregate(user_id, today)
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {}
            totals = daily_data.get("totals", {}) if daily_data else {}
            
            summary = {
                "date": today.isoformat(),
                "consumed": {
                    "calories": int(totals.get("calories", 0)),
                    "protein": round(float(totals.get("protein", 0)), 1),
                    "carbs": round(float(totals.get("carbs", 0)), 1),
                    "fat": round(float(totals.get("fat", 0)), 1),
                    "fiber": round(float(totals.get("fiber", 0)), 1),
                },
                "goals": {
                    "calories": goals.get("calories", 2000),
                    "protein": goals.get("protein", 50),
                    "carbs": goals.get("carbs", 250),
                    "fat": goals.get("fat", 65),
                    "fiber": goals.get("fiber", 25),
                },
                "progress": {}
            }
            
            for key in ["calories", "protein", "carbs", "fat", "fiber"]:
                goal = summary["goals"][key]
                consumed = summary["consumed"][key]
                summary["progress"][key] = {
                    "percentage": round((consumed / goal * 100) if goal > 0 else 0, 1),
                    "remaining": max(0, round(goal - consumed, 1))
                }
            
            return {"success": True, "message": "Daily summary retrieved", "data": summary}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get daily summary: {str(e)}")
    
    @router.get("/summary/weekly")
    async def get_weekly_summary(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            week_start = today - timedelta(days=6)
            
            aggregates = await _db_service.get_daily_aggregates_range(user_id, week_start, today)
            
            daily_breakdown = []
            totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}
            
            for agg in (aggregates or []):
                day_totals = agg.get("totals", {})
                date_str = agg.get("date", "")
                
                for key in totals:
                    val = float(day_totals.get(key, 0) or 0)
                    totals[key] += val
                
                daily_breakdown.append({
                    "date": date_str,
                    "calories": int(day_totals.get("calories", 0) or 0),
                    "protein": round(float(day_totals.get("protein", 0) or 0), 1),
                    "carbs": round(float(day_totals.get("carbs", 0) or 0), 1),
                    "fat": round(float(day_totals.get("fat", 0) or 0), 1),
                })
            
            days_count = max(len(aggregates or []), 1)
            averages = {k: round(v / days_count, 1) for k, v in totals.items()}
            
            return {
                "success": True, "message": "Weekly summary retrieved",
                "data": {
                    "period": {"start": week_start.isoformat(), "end": today.isoformat()},
                    "totals": {k: round(v, 1) for k, v in totals.items()},
                    "daily_averages": averages,
                    "daily_breakdown": daily_breakdown,
                    "days_tracked": days_count
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get weekly summary: {str(e)}")
    
    @router.get("/summary/insights")
    async def get_nutrition_insights(authorization: Optional[str] = Header(None)):
        from gpt_model.gptapi import generate_personalized_insights
        
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            week_start = today - timedelta(days=6)
            
            aggregates = await _db_service.get_daily_aggregates_range(user_id, week_start, today)
            profile = await _db_service.get_health_profile(user_id) or {}
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {}
            
            totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}
            for agg in (aggregates or []):
                day_totals = agg.get("totals", {})
                for key in totals:
                    totals[key] += float(day_totals.get(key, 0) or 0)
            
            days = max(len(aggregates or []), 1)
            averages = {k: round(v / days, 1) for k, v in totals.items()}
            
            # Get recent history and meals for insights
            recent_history = []
            try:
                history_data = await _db_service.get_user_scan_history(user_id, limit=10)
                if history_data and isinstance(history_data, dict):
                    foods = history_data.get("foods", [])
                    if isinstance(foods, list):
                        recent_history = foods
            except Exception as hist_err:
                print(f"Error getting scan history: {hist_err}")
            
            recent_meals = []
            try:
                meals_data = await _db_service.get_recent_meals(user_id, limit=10)
                if isinstance(meals_data, list):
                    recent_meals = meals_data
            except Exception as meal_err:
                print(f"Error getting recent meals: {meal_err}")
            
            # Build profile context for insights with averages
            profile_context = {
                **(profile or {}),
                "weekly_averages": averages,
                "goals": goals,
                "days_tracked": days
            }
            
            try:
                insights = await asyncio.to_thread(
                    generate_personalized_insights, 
                    profile_context, 
                    list(recent_history) if recent_history else [],
                    list(recent_meals) if recent_meals else []
                )
            except Exception as ai_err:
                print(f"Error generating insights: {ai_err}")
                # Return fallback insights
                insights = [{
                    "title": "Keep Tracking!",
                    "content": "Continue logging your meals to get personalized insights.",
                    "insight_type": "daily_advice"
                }]
            
            return {
                "success": True, "message": "Insights generated",
                "data": {"insights": insights, "weekly_averages": averages, "days_analyzed": days}
            }
        except Exception as e:
            print(f"Summary insights error: {e}")
            import traceback
            traceback.print_exc()
            # Return success with fallback data instead of HTTP 500
            return {
                "success": True, "message": "Insights generated (fallback)",
                "data": {
                    "insights": [{
                        "title": "Start Tracking",
                        "content": "Log your meals to get personalized insights.",
                        "insight_type": "daily_advice"
                    }],
                    "weekly_averages": {},
                    "days_analyzed": 0
                }
            }
    
    @router.get("/dashboard")
    async def get_dashboard(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            today = datetime.now().date()
            
            daily_data = await _db_service.get_daily_aggregate(user_id, today)
            totals = daily_data.get("totals", {}) if daily_data else {}
            
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {
                "calories": 2000, "protein": 50, "carbs": 250, "fat": 65
            }
            
            recent_meals = await _db_service.get_recent_meals(user_id, limit=5)
            saved_items = await _db_service.get_saved_items(user_id)
            
            calories_consumed = int(totals.get("calories", 0))
            calories_goal = goals.get("calories", 2000)
            progress_pct = round((calories_consumed / calories_goal * 100) if calories_goal > 0 else 0, 1)
            
            return {
                "success": True, "message": "Dashboard data retrieved",
                "data": {
                    "today": {
                        "calories": calories_consumed,
                        "protein": round(float(totals.get("protein", 0)), 1),
                        "carbs": round(float(totals.get("carbs", 0)), 1),
                        "fat": round(float(totals.get("fat", 0)), 1),
                    },
                    "goals": goals,
                    "progress": {
                        "calories_percentage": min(progress_pct, 100),
                        "calories_remaining": max(0, calories_goal - calories_consumed)
                    },
                    "recent_meals_count": len(recent_meals) if recent_meals else 0,
                    "saved_items_count": len(saved_items) if saved_items else 0,
                    "last_updated": datetime.now().isoformat()
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get dashboard: {str(e)}")
    
    @router.get("/nutrition-summary")
    async def get_nutrition_summary(date: Optional[str] = None, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user_id = current_user["user_id"]
            target_date = datetime.strptime(date, "%Y-%m-%d").date() if date else datetime.now().date()
            
            daily_data = await _db_service.get_daily_aggregate(user_id, target_date)
            goals = await _db_service.get_user_nutrition_goals(user_id, period="daily") or {}
            totals = daily_data.get("totals", {}) if daily_data else {}
            
            return {
                "success": True,
                "data": {
                    "date": target_date.isoformat(),
                    "nutrition": {
                        "calories": int(totals.get("calories", 0)),
                        "protein": round(float(totals.get("protein", 0)), 1),
                        "carbs": round(float(totals.get("carbs", 0)), 1),
                        "fat": round(float(totals.get("fat", 0)), 1),
                        "fiber": round(float(totals.get("fiber", 0)), 1),
                    },
                    "goals": goals
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get nutrition summary: {str(e)}")
    
    return router
