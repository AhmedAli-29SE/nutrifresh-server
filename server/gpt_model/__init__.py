"""
GPT Model Package - AI-powered nutrition services using Groq LLaMA API

Features:
- Response caching for faster repeated queries
- Parallel API calls for 3x speed improvement
- All nutrition AI services in one module
"""

# All functions from gptapi.py
from .gptapi import (
    # Client
    call_groq_api,
    _get_client,
    
    # Caching utilities
    ResponseCache,
    get_cache_stats,
    clear_cache,
    cached,
    
    # Parallel execution
    parallel_generate,
    parallel_food_analysis,
    
    # Storage recommendations
    generate_storage_recommendations,
    
    # Health suggestions
    generate_health_suggestions,
    
    # Consumption recommendations
    generate_consumption_recommendations,
    
    # Meal recommendations
    generate_meal_recommendations_from_ingredients,
    generate_meal_suggestions_personal,
    
    # Personalized insights
    generate_personalized_insights,
    
    # Nutrition goals
    generate_personalized_nutrition_goals,
    
    # Chat
    generate_chat_response,
)

__all__ = [
    # Client & Utilities
    "call_groq_api",
    
    # Caching
    "ResponseCache",
    "get_cache_stats",
    "clear_cache",
    "cached",
    
    # Parallel Execution
    "parallel_generate",
    "parallel_food_analysis",
    
    # AI Services
    "generate_storage_recommendations",
    "generate_health_suggestions",
    "generate_consumption_recommendations",
    "generate_meal_recommendations_from_ingredients",
    "generate_meal_suggestions_personal",
    "generate_personalized_insights",
    "generate_personalized_nutrition_goals",
    "generate_chat_response",
]
