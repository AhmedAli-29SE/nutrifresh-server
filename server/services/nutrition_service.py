"""
Nutrition Service - Handles USDA API and nutrition data retrieval
Provides cached nutrition lookups and data normalization
"""

import asyncio
import httpx
from typing import Dict, List, Optional, Any
from functools import lru_cache
import os

# USDA API configuration
USDA_API_KEY = os.getenv("USDA_API_KEY", "")
USDA_API_BASE = "https://api.nal.usda.gov/fdc/v1"

# In-memory cache for nutrition data
_nutrition_cache: Dict[str, Dict[str, Any]] = {}


# ===== USDA API Functions =====

async def fetch_usda_nutrition(food_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch nutrition data from USDA FoodData Central API.
    
    Args:
        food_name: Name of the food to search
        
    Returns:
        Nutrition data dictionary or None if not found
    """
    if not USDA_API_KEY:
        print("[USDA] API key not configured")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Search for food
            search_url = f"{USDA_API_BASE}/foods/search"
            params = {
                "api_key": USDA_API_KEY,
                "query": food_name,
                "pageSize": 5,
                "dataType": ["Foundation", "SR Legacy"]
            }
            
            response = await client.get(search_url, params=params)
            
            if response.status_code != 200:
                print(f"[USDA] Search failed: {response.status_code}")
                return None
            
            data = response.json()
            foods = data.get("foods", [])
            
            if not foods:
                print(f"[USDA] No results for: {food_name}")
                return None
            
            # Get first matching food
            food = foods[0]
            fdc_id = food.get("fdcId")
            
            # Fetch detailed nutrition
            detail_url = f"{USDA_API_BASE}/food/{fdc_id}"
            detail_response = await client.get(
                detail_url,
                params={"api_key": USDA_API_KEY}
            )
            
            if detail_response.status_code != 200:
                # Use search result nutrients if detail fails
                return parse_search_nutrients(food)
            
            detail_data = detail_response.json()
            return parse_detail_nutrients(detail_data)
            
    except Exception as e:
        print(f"[USDA] Error fetching nutrition: {e}")
        return None


def parse_search_nutrients(food: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse nutrients from USDA search result.
    
    Args:
        food: Food item from search results
        
    Returns:
        Normalized nutrition dictionary
    """
    nutrients = {}
    food_nutrients = food.get("foodNutrients", [])
    
    # Nutrient ID mapping
    nutrient_map = {
        "Energy": "calories",
        "Protein": "protein",
        "Total lipid (fat)": "fat",
        "Carbohydrate, by difference": "carbohydrates",
        "Fiber, total dietary": "fiber",
        "Sugars, total including NLEA": "sugar",
        "Sugars, Total": "sugar",
        "Sodium, Na": "sodium",
        "Potassium, K": "potassium",
        "Vitamin C, total ascorbic acid": "vitamin_c",
        "Vitamin A, RAE": "vitamin_a"
    }
    
    for nutrient in food_nutrients:
        name = nutrient.get("nutrientName", "")
        value = nutrient.get("value", 0)
        unit = nutrient.get("unitName", "g")
        
        for usda_name, our_name in nutrient_map.items():
            if usda_name.lower() in name.lower():
                nutrients[our_name] = {
                    "value": round(value, 1),
                    "unit": unit.lower()
                }
                break
    
    return nutrients


def parse_detail_nutrients(food: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse nutrients from USDA detail response.
    
    Args:
        food: Detailed food data
        
    Returns:
        Normalized nutrition dictionary
    """
    nutrients = {}
    food_nutrients = food.get("foodNutrients", [])
    
    # Nutrient number mapping (more reliable than names)
    nutrient_ids = {
        1008: "calories",      # Energy (kcal)
        1003: "protein",       # Protein
        1004: "fat",           # Total lipid (fat)
        1005: "carbohydrates", # Carbohydrate
        1079: "fiber",         # Fiber
        2000: "sugar",         # Sugars
        1093: "sodium",        # Sodium
        1092: "potassium",     # Potassium
        1162: "vitamin_c",     # Vitamin C
        1106: "vitamin_a"      # Vitamin A
    }
    
    for nutrient in food_nutrients:
        nutrient_obj = nutrient.get("nutrient", {})
        nutrient_id = nutrient_obj.get("id") or nutrient_obj.get("number")
        
        if nutrient_id in nutrient_ids:
            name = nutrient_ids[nutrient_id]
            value = nutrient.get("amount", 0)
            unit = nutrient_obj.get("unitName", "g")
            
            nutrients[name] = {
                "value": round(value, 1),
                "unit": unit.lower()
            }
    
    return nutrients


# ===== Fallback Nutrition Data =====

def get_fallback_nutrition(food_name: str) -> Dict[str, Any]:
    """
    Get fallback nutrition data for common foods.
    Based on USDA database averages per 100g.
    
    Args:
        food_name: Name of the food
        
    Returns:
        Nutrition dictionary with estimated values
    """
    # Common fruits (per 100g)
    fruits = {
        "apple": {"calories": 52, "protein": 0.3, "carbohydrates": 14, "fat": 0.2, "fiber": 2.4, "sugar": 10},
        "banana": {"calories": 89, "protein": 1.1, "carbohydrates": 23, "fat": 0.3, "fiber": 2.6, "sugar": 12},
        "orange": {"calories": 47, "protein": 0.9, "carbohydrates": 12, "fat": 0.1, "fiber": 2.4, "sugar": 9},
        "strawberry": {"calories": 32, "protein": 0.7, "carbohydrates": 8, "fat": 0.3, "fiber": 2.0, "sugar": 5},
        "grape": {"calories": 69, "protein": 0.7, "carbohydrates": 18, "fat": 0.2, "fiber": 0.9, "sugar": 16},
        "mango": {"calories": 60, "protein": 0.8, "carbohydrates": 15, "fat": 0.4, "fiber": 1.6, "sugar": 14},
        "pineapple": {"calories": 50, "protein": 0.5, "carbohydrates": 13, "fat": 0.1, "fiber": 1.4, "sugar": 10},
        "watermelon": {"calories": 30, "protein": 0.6, "carbohydrates": 8, "fat": 0.2, "fiber": 0.4, "sugar": 6},
        "kiwi": {"calories": 61, "protein": 1.1, "carbohydrates": 15, "fat": 0.5, "fiber": 3.0, "sugar": 9},
        "peach": {"calories": 39, "protein": 0.9, "carbohydrates": 10, "fat": 0.3, "fiber": 1.5, "sugar": 8},
        "pear": {"calories": 57, "protein": 0.4, "carbohydrates": 15, "fat": 0.1, "fiber": 3.1, "sugar": 10},
        "plum": {"calories": 46, "protein": 0.7, "carbohydrates": 11, "fat": 0.3, "fiber": 1.4, "sugar": 10},
        "cherry": {"calories": 50, "protein": 1.0, "carbohydrates": 12, "fat": 0.3, "fiber": 1.6, "sugar": 8},
        "blueberry": {"calories": 57, "protein": 0.7, "carbohydrates": 14, "fat": 0.3, "fiber": 2.4, "sugar": 10},
        "raspberry": {"calories": 52, "protein": 1.2, "carbohydrates": 12, "fat": 0.7, "fiber": 6.5, "sugar": 4},
        "papaya": {"calories": 43, "protein": 0.5, "carbohydrates": 11, "fat": 0.3, "fiber": 1.7, "sugar": 8},
        "guava": {"calories": 68, "protein": 2.6, "carbohydrates": 14, "fat": 1.0, "fiber": 5.4, "sugar": 9},
        "lemon": {"calories": 29, "protein": 1.1, "carbohydrates": 9, "fat": 0.3, "fiber": 2.8, "sugar": 2.5},
        "lime": {"calories": 30, "protein": 0.7, "carbohydrates": 11, "fat": 0.2, "fiber": 2.8, "sugar": 1.7},
        "pomegranate": {"calories": 83, "protein": 1.7, "carbohydrates": 19, "fat": 1.2, "fiber": 4.0, "sugar": 14},
    }
    
    # Common vegetables (per 100g)
    vegetables = {
        "tomato": {"calories": 18, "protein": 0.9, "carbohydrates": 4, "fat": 0.2, "fiber": 1.2, "sugar": 2.6},
        "carrot": {"calories": 41, "protein": 0.9, "carbohydrates": 10, "fat": 0.2, "fiber": 2.8, "sugar": 5},
        "potato": {"calories": 77, "protein": 2.0, "carbohydrates": 17, "fat": 0.1, "fiber": 2.2, "sugar": 0.8},
        "onion": {"calories": 40, "protein": 1.1, "carbohydrates": 9, "fat": 0.1, "fiber": 1.7, "sugar": 4},
        "cucumber": {"calories": 15, "protein": 0.7, "carbohydrates": 4, "fat": 0.1, "fiber": 0.5, "sugar": 2},
        "lettuce": {"calories": 15, "protein": 1.4, "carbohydrates": 3, "fat": 0.2, "fiber": 1.3, "sugar": 0.8},
        "spinach": {"calories": 23, "protein": 2.9, "carbohydrates": 4, "fat": 0.4, "fiber": 2.2, "sugar": 0.4},
        "broccoli": {"calories": 34, "protein": 2.8, "carbohydrates": 7, "fat": 0.4, "fiber": 2.6, "sugar": 1.7},
        "capsicum": {"calories": 31, "protein": 1.0, "carbohydrates": 6, "fat": 0.3, "fiber": 2.1, "sugar": 4},
        "cauliflower": {"calories": 25, "protein": 1.9, "carbohydrates": 5, "fat": 0.3, "fiber": 2.0, "sugar": 2},
        "cabbage": {"calories": 25, "protein": 1.3, "carbohydrates": 6, "fat": 0.1, "fiber": 2.5, "sugar": 3},
        "eggplant": {"calories": 25, "protein": 1.0, "carbohydrates": 6, "fat": 0.2, "fiber": 3.0, "sugar": 3.5},
        "zucchini": {"calories": 17, "protein": 1.2, "carbohydrates": 3, "fat": 0.3, "fiber": 1.0, "sugar": 2.5},
        "okra": {"calories": 33, "protein": 1.9, "carbohydrates": 7, "fat": 0.2, "fiber": 3.2, "sugar": 1.5},
        "peas": {"calories": 81, "protein": 5.4, "carbohydrates": 14, "fat": 0.4, "fiber": 5.1, "sugar": 6},
        "corn": {"calories": 86, "protein": 3.3, "carbohydrates": 19, "fat": 1.4, "fiber": 2.7, "sugar": 3.2},
        "mushroom": {"calories": 22, "protein": 3.1, "carbohydrates": 3, "fat": 0.3, "fiber": 1.0, "sugar": 2},
        "ginger": {"calories": 80, "protein": 1.8, "carbohydrates": 18, "fat": 0.8, "fiber": 2.0, "sugar": 1.7},
        "garlic": {"calories": 149, "protein": 6.4, "carbohydrates": 33, "fat": 0.5, "fiber": 2.1, "sugar": 1},
    }
    
    # Normalize food name for lookup
    food_lower = food_name.lower().strip()
    
    # Check fruits first
    for fruit_name, nutrition in fruits.items():
        if fruit_name in food_lower or food_lower in fruit_name:
            return format_nutrition_output(nutrition)
    
    # Check vegetables
    for veg_name, nutrition in vegetables.items():
        if veg_name in food_lower or food_lower in veg_name:
            return format_nutrition_output(nutrition)
    
    # Default generic produce values
    return format_nutrition_output({
        "calories": 50,
        "protein": 1.0,
        "carbohydrates": 12,
        "fat": 0.3,
        "fiber": 2.0,
        "sugar": 8
    })


def format_nutrition_output(nutrition: Dict[str, float]) -> Dict[str, Any]:
    """
    Format nutrition values into standard output format.
    
    Args:
        nutrition: Raw nutrition values
        
    Returns:
        Formatted nutrition dictionary
    """
    return {
        "calories": {"value": nutrition.get("calories", 0), "unit": "kcal"},
        "protein": {"value": nutrition.get("protein", 0), "unit": "g"},
        "carbohydrates": {"value": nutrition.get("carbohydrates", 0), "unit": "g"},
        "fat": {"value": nutrition.get("fat", 0), "unit": "g"},
        "fiber": {"value": nutrition.get("fiber", 0), "unit": "g"},
        "sugar": {"value": nutrition.get("sugar", 0), "unit": "g"},
        "sodium": {"value": nutrition.get("sodium", 0), "unit": "mg"},
        "potassium": {"value": nutrition.get("potassium", 0), "unit": "mg"},
        "vitamin_c": {"value": nutrition.get("vitamin_c", 0), "unit": "mg"},
        "vitamin_a": {"value": nutrition.get("vitamin_a", 0), "unit": "mcg"}
    }


# ===== Cached Nutrition Lookup =====

async def get_nutrition_with_cache(food_name: str) -> Dict[str, Any]:
    """
    Get nutrition data with caching.
    First checks cache, then USDA API, then fallback data.
    
    Args:
        food_name: Name of the food
        
    Returns:
        Nutrition dictionary
    """
    # Check cache first
    cache_key = food_name.lower().strip()
    if cache_key in _nutrition_cache:
        print(f"[NUTRITION] Cache hit for: {food_name}")
        return _nutrition_cache[cache_key]
    
    # Try USDA API
    usda_data = await fetch_usda_nutrition(food_name)
    
    if usda_data and len(usda_data) > 0:
        _nutrition_cache[cache_key] = usda_data
        print(f"[NUTRITION] USDA data cached for: {food_name}")
        return usda_data
    
    # Use fallback data
    fallback_data = get_fallback_nutrition(food_name)
    _nutrition_cache[cache_key] = fallback_data
    print(f"[NUTRITION] Using fallback data for: {food_name}")
    return fallback_data


def clear_nutrition_cache():
    """Clear the nutrition cache."""
    global _nutrition_cache
    _nutrition_cache = {}
    print("[NUTRITION] Cache cleared")


def get_cache_stats() -> Dict[str, int]:
    """Get nutrition cache statistics."""
    return {
        "cached_items": len(_nutrition_cache),
        "cache_keys": list(_nutrition_cache.keys())[:10]  # First 10 keys
    }


# ===== Nutrition Helpers =====

def nutrition_map_to_list(nutrition_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert nutrition map to list format for API response.
    
    Args:
        nutrition_map: Dictionary of nutrition values
        
    Returns:
        List of nutrition objects
    """
    nutrition_list = []
    
    display_names = {
        "calories": "Calories",
        "protein": "Protein",
        "carbohydrates": "Carbohydrates",
        "fat": "Fat",
        "fiber": "Fiber",
        "sugar": "Sugar",
        "sodium": "Sodium",
        "potassium": "Potassium",
        "vitamin_c": "Vitamin C",
        "vitamin_a": "Vitamin A"
    }
    
    for key, data in nutrition_map.items():
        if isinstance(data, dict):
            nutrition_list.append({
                "name": key,
                "display_name": display_names.get(key, key.replace("_", " ").title()),
                "value": data.get("value", 0),
                "unit": data.get("unit", "g")
            })
    
    return nutrition_list


def calculate_nutrition_score(nutrition: Dict[str, Any]) -> int:
    """
    Calculate a nutrition score (0-100) based on nutrient density.
    
    Args:
        nutrition: Nutrition dictionary
        
    Returns:
        Nutrition score
    """
    score = 50  # Base score
    
    # Positive factors (add points)
    fiber = nutrition.get("fiber", {}).get("value", 0)
    protein = nutrition.get("protein", {}).get("value", 0)
    vitamin_c = nutrition.get("vitamin_c", {}).get("value", 0)
    
    score += min(fiber * 3, 15)      # Up to 15 points for fiber
    score += min(protein * 2, 15)    # Up to 15 points for protein
    score += min(vitamin_c / 5, 10)  # Up to 10 points for vitamin C
    
    # Negative factors (subtract points)
    sugar = nutrition.get("sugar", {}).get("value", 0)
    sodium = nutrition.get("sodium", {}).get("value", 0)
    
    score -= min(sugar * 0.5, 10)    # Up to -10 for sugar
    score -= min(sodium / 100, 10)   # Up to -10 for sodium
    
    return max(0, min(100, int(score)))

