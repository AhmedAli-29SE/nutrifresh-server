"""
NutriFresh API Routers Package
All API routes are organized into modular router files
"""

from .food_analysis import router as food_analysis_router, init_services as init_food_analysis
from .auth import router as auth_router, create_auth_routes
from .users import router as users_router, create_user_routes
from .meals import router as meals_router, create_meal_routes
from .saved import router as saved_router, create_saved_routes
from .summary import router as summary_router, create_summary_routes
from .recommendations import router as recommendations_router, create_recommendation_routes
from .chat import router as chat_router, create_chat_routes

__all__ = [
    # Routers
    "food_analysis_router",
    "auth_router",
    "users_router",
    "meals_router",
    "saved_router",
    "summary_router",
    "recommendations_router",
    "chat_router",
    
    # Init functions
    "init_food_analysis",
    "create_auth_routes",
    "create_user_routes",
    "create_meal_routes",
    "create_saved_routes",
    "create_summary_routes",
    "create_recommendation_routes",
    "create_chat_routes",
]
