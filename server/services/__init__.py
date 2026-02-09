"""
NutriFresh Services Package
Contains business logic and utility services
"""

from .health_calculator import (
    calculate_bmi,
    get_bmi_category,
    get_healthy_weight_range,
    calculate_bmr,
    calculate_tdee,
    calculate_daily_calories,
    calculate_macro_targets,
    calculate_fiber_target,
    calculate_water_intake,
    assess_health_risks,
    calculate_complete_health_profile,
    generate_lifestyle_recommendations
)

from .nutrition_service import (
    fetch_usda_nutrition,
    get_fallback_nutrition,
    get_nutrition_with_cache,
    clear_nutrition_cache,
    get_cache_stats,
    nutrition_map_to_list,
    calculate_nutrition_score
)

__all__ = [
    # Health Calculator
    "calculate_bmi",
    "get_bmi_category",
    "get_healthy_weight_range",
    "calculate_bmr",
    "calculate_tdee",
    "calculate_daily_calories",
    "calculate_macro_targets",
    "calculate_fiber_target",
    "calculate_water_intake",
    "assess_health_risks",
    "calculate_complete_health_profile",
    "generate_lifestyle_recommendations",
    # Nutrition Service
    "fetch_usda_nutrition",
    "get_fallback_nutrition",
    "get_nutrition_with_cache",
    "clear_nutrition_cache",
    "get_cache_stats",
    "nutrition_map_to_list",
    "calculate_nutrition_score"
]
