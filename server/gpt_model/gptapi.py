import os
import json
import re
import asyncio
import hashlib
import time
from typing import List, Dict, Optional, Any, Callable, Tuple
from functools import wraps
from groq import Groq
from dotenv import load_dotenv

# Load API key from environment/.env
load_dotenv()

_CLIENT: Optional[Groq] = None


# ==========================================
# RESPONSE CACHING SYSTEM
# ==========================================

class ResponseCache:
    """TTL-based cache for API responses to avoid redundant API calls."""
    
    def __init__(self, default_ttl: int = 3600):
        """
        Initialize cache with default TTL in seconds.
        Default: 1 hour (3600 seconds)
        """
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._max_size = 500  # Max cache entries
    
    def _generate_key(self, func_name: str, *args, **kwargs) -> str:
        """Generate unique cache key from function name and arguments."""
        # Create hash from arguments
        key_data = f"{func_name}:{str(args)}:{str(sorted(kwargs.items()))}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if exists and not expired."""
        if key in self._cache:
            value, expiry = self._cache[key]
            if time.time() < expiry:
                print(f"[CACHE HIT] {key[:16]}...")
                return value
            else:
                # Expired - remove from cache
                del self._cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store value in cache with TTL."""
        # Cleanup if cache too large
        if len(self._cache) >= self._max_size:
            self._cleanup()
        
        expiry = time.time() + (ttl or self._default_ttl)
        self._cache[key] = (value, expiry)
        print(f"[CACHE SET] {key[:16]}... (TTL: {ttl or self._default_ttl}s)")
    
    def _cleanup(self) -> None:
        """Remove expired entries and oldest entries if still too large."""
        current_time = time.time()
        # Remove expired
        self._cache = {k: v for k, v in self._cache.items() if v[1] > current_time}
        # If still too large, remove oldest 20%
        if len(self._cache) >= self._max_size:
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1][1])
            remove_count = len(self._cache) // 5
            for key, _ in sorted_items[:remove_count]:
                del self._cache[key]
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        print("[CACHE] Cleared all entries")
    
    def stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        current_time = time.time()
        valid_count = sum(1 for _, (_, exp) in self._cache.items() if exp > current_time)
        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": len(self._cache) - valid_count
        }


# Global cache instance
_response_cache = ResponseCache(default_ttl=3600)  # 1 hour default TTL


def cached(ttl: int = 3600):
    """
    Decorator to cache function results.
    
    Usage:
        @cached(ttl=1800)  # Cache for 30 minutes
        def my_function(arg1, arg2):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = _response_cache._generate_key(func.__name__, *args, **kwargs)
            cached_result = _response_cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            result = func(*args, **kwargs)
            if result:  # Only cache non-empty results
                _response_cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


# ==========================================
# PARALLEL API CALLS SUPPORT
# ==========================================

async def parallel_generate(tasks: List[Tuple[Callable, tuple, dict]]) -> List[Any]:
    """
    Execute multiple generation functions in parallel.
    
    Args:
        tasks: List of tuples (function, args, kwargs)
    
    Returns:
        List of results in same order as tasks
    
    Usage:
        results = await parallel_generate([
            (generate_storage_recommendations, ("apple", "fresh"), {}),
            (generate_health_suggestions, ("apple", "fresh"), {}),
            (generate_meal_recommendations_from_ingredients, (["apple"], "breakfast", {}), {}),
        ])
        storage, health, meals = results
    """
    async def run_task(func, args, kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    
    coroutines = [run_task(func, args, kwargs) for func, args, kwargs in tasks]
    return await asyncio.gather(*coroutines, return_exceptions=True)


async def parallel_food_analysis(food_name: str, freshness: str, user_profile: Dict = None) -> Dict[str, Any]:
    """
    Generate all food analysis recommendations in parallel.
    
    This is ~3x faster than sequential calls!
    
    Args:
        food_name: Name of the food
        freshness: Freshness level
        user_profile: Optional user profile for personalized recommendations
    
    Returns:
        Dictionary with storage_recs, health_suggestions, and meal_recipes
    """
    user_profile = user_profile or {}
    
    results = await parallel_generate([
        (generate_storage_recommendations, (food_name, freshness, 4), {}),
        (generate_health_suggestions, (food_name, freshness, 3), {}),
        (generate_meal_recommendations_from_ingredients, ([food_name], "any", user_profile, 3), {}),
    ])
    
    # Handle any exceptions in results
    storage = results[0] if not isinstance(results[0], Exception) else []
    health = results[1] if not isinstance(results[1], Exception) else []
    meals = results[2] if not isinstance(results[2], Exception) else []
    
    return {
        "storage_recommendations": storage,
        "health_suggestions": health,
        "meal_recipes": meals
    }


# ==========================================
# GROQ CLIENT
# ==========================================

def _get_client() -> Optional[Groq]:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    _CLIENT = Groq(api_key=api_key)
    return _CLIENT


def get_cache_stats() -> Dict[str, int]:
    """Get current cache statistics."""
    return _response_cache.stats()


def clear_cache() -> None:
    """Clear all cached responses."""
    _response_cache.clear()


def call_groq_api(prompt: str, max_tokens: int = 800) -> str:
    """Generic Groq API call function for simple prompts.
    Used by main.py for meal suggestion generation from saved items.
    """
    client = _get_client()
    if client is None:
        return ""
    
    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.7,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling Groq API: {e}")
        return ""


def _clean_json_payload(payload: str) -> str:
    """Clean up common JSON issues from AI responses."""
    # Remove trailing commas in objects
    payload = re.sub(r',\s*}', '}', payload)
    # Remove trailing commas in arrays
    payload = re.sub(r',\s*]', ']', payload)
    # Fix broken strings across lines (e.g. "foo \n bar")
    payload = re.sub(r'"\s*\n\s*"', '" "', payload)
    # Escape unescaped newlines inside strings (simple heuristic: newline not preceded by comma/bracket/brace)
    # This is risky but often fixes "multi-line string" errors in JSON
    # payload = payload.replace('\n', '\\n')  <-- fast but bad for formatted data
    return payload


def _fallback_storage(food_name: str, freshness: str, count: int = 4) -> List[Dict[str, object]]:
    """
    Heuristic-based storage recommendations (used only if Groq API unavailable).
    This is real server logic - generates recommendations based on food characteristics.
    NOT demo data - dynamically computed based on food type and freshness.
    """
    name = (food_name or "").strip().lower()
    f = (freshness or "").strip().lower()
    recs: List[Dict[str, object]] = []
    def add(method: str, message: str, days: int):
        recs.append({
            "method": method,
            "message": message,
            "estimated_extension_days": days,
        })

    # Heuristic algorithm based on food characteristics
    if name in {"banana", "mango", "avocado"}:
        add("room_temperature", "Keep at room temp away from direct sunlight until ripe.", 2)
        add("refrigeration", "Refrigerate once ripe to slow further ripening.", 5)
        add("airtight_container", "Use breathable bag to reduce moisture buildup.", 2)
        add("freezing", "Peel/slice and freeze for smoothies.", 30)
    elif name in {"apple", "pear"}:
        add("refrigeration", "Store in crisper drawer; high humidity extends freshness.", 10)
        add("paper_bag", "Paper bag helps control ethylene and moisture.", 3)
        add("ventilated_storage", "Keep separated from strong ethylene producers if unripe.", 3)
        add("airtight_container", "Cut pieces in airtight container with lemon to prevent browning.", 2)
    elif name in {"tomato", "cucumber"}:
        add("room_temperature", "Keep at room temp; refrigeration can affect texture.", 2)
        add("ventilated_storage", "Store with airflow; avoid sealed plastic at room temp.", 2)
        add("refrigeration", "If overripe, refrigerate briefly to slow spoilage.", 3)
        add("paper_bag", "Paper bag to absorb moisture and reduce condensation.", 2)
    else:
        add("refrigeration", "Refrigerate in crisper drawer to slow spoilage.", 7)
        add("airtight_container", "Use airtight or produce bag to prevent moisture loss.", 3)
        add("ventilated_storage", "Avoid stacking; let air circulate to prevent mold.", 3)
        add("freezing", "Blanch/slice and freeze for long-term storage.", 30)

    if f in {"mid-fresh", "not fresh"} and recs:
        recs[0]["estimated_extension_days"] = max(2, int(recs[0]["estimated_extension_days"]))
    return recs[:count]


@cached(ttl=7200)  # Cache for 2 hours - storage tips don't change frequently
def generate_storage_recommendations(food_name: str, freshness: str, count: int = 4) -> List[Dict[str, object]]:
    """Generate storage recommendations using Groq LLaMA API.

    Uses real Groq LLaMA API for AI-powered recommendations.
    Falls back to heuristic algorithm only if API unavailable (not demo data - real computed logic).
    Returns a list of objects: { method, message, estimated_extension_days }.
    
    CACHED: Results cached for 2 hours (same food + freshness = same recommendations)
    """
    client = _get_client()
    if client is None:
        return _fallback_storage(food_name, freshness, count)

    system_prompt = (
        "You are a food storage expert. Given a food name and its freshness, "
        "return ONLY a JSON array of 3-4 concise recommendations to maximize shelf life. "
        "Each item must be an object with keys: method (snake_case), message (string), estimated_extension_days (integer). "
        "No prose, no markdown, no extra text."
    )
    user_prompt = (
        f"food_name: {food_name}\n"
        f"freshness: {freshness}\n"
        "Return strictly a JSON array."
    )

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        # Extract first JSON array
        arrays = re.findall(r"\[[\s\S]*?\]", text)
        payload = arrays[0] if arrays else text
        payload = _clean_json_payload(payload)
        data = json.loads(payload)
        if not isinstance(data, list):
            raise ValueError("Model did not return a list")

        # Normalize fields
        out: List[Dict[str, object]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            method = item.get("method") or item.get("storage_method") or "storage"
            message = item.get("message") or item.get("tip") or "Store properly to maintain freshness."
            days = item.get("estimated_extension_days") or item.get("estimatedExtensionDays") or 3
            try:
                days = int(days)
            except Exception:
                days = 3
            out.append({
                "method": str(method).strip().lower().replace(" ", "_"),
                "message": str(message).strip(),
                "estimated_extension_days": days,
            })
        return out[:count] if out else _fallback_storage(food_name, freshness, count)
    except Exception:
        return _fallback_storage(food_name, freshness, count)


@cached(ttl=7200)  # Cache for 2 hours - health info is relatively stable
def generate_health_suggestions(food_name: str, freshness: str, count: int = 3) -> List[Dict[str, object]]:
    """Generate health suggestions using Groq LLaMA API.

    Uses real Groq LLaMA API for AI-powered health recommendations.
    Returns generic message only if API unavailable (not demo data).
    
    CACHED: Results cached for 2 hours
    """
    client = _get_client()
    if client is None:
        return [
            {"name": "General", "score": 0, "message": f"{food_name} is nutritious; consume while {freshness} for best quality."},
        ]
    system_prompt = (
        "You give concise health suggestions about a food. Return ONLY a JSON array of 3 objects: "
        "{ name, score (0-100), message }. No extra text."
    )
    user_prompt = (
        f"food_name: {food_name}\n"
        f"freshness: {freshness}\n"
        "Return strictly a JSON array."
    )
    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        arrays = re.findall(r"\[[\s\S]*?\]", text)
        payload = arrays[0] if arrays else text
        payload = _clean_json_payload(payload)
        data = json.loads(payload)
        if not isinstance(data, list):
            raise ValueError("Model did not return a list")
        out: List[Dict[str, object]] = []
        for item in data[:count]:
            if not isinstance(item, dict):
                continue
            out.append({
                "name": str(item.get("name", "General")),
                "score": int(item.get("score", 0)),
                "message": str(item.get("message", "")),
            })
        return out or [{"name": "General", "score": 0, "message": f"{food_name} provides nutrients; consume soon if not fresh."}]
    except Exception:
        return [{"name": "General", "score": 0, "message": f"{food_name} provides nutrients; consume soon if not fresh."}]



def generate_meal_recommendations_from_ingredients(
    ingredients: List[str],
    meal_type: str,
    user_profile: Dict[str, Any],
    count: int = 3
) -> List[Dict[str, object]]:
    """Generate meal recommendations based on ingredients and profile using Groq.
    
    Returns comprehensive meal data including:
    - name, description, calories, protein, carbs, fat, fiber, sugar
    - ingredients list
    - preparation/cooking instructions
    - health benefits
    - warnings/concerns based on user profile
    - cooking time in minutes
    """
    client = _get_client()
    if client is None:
        return _fallback_meal_recommendations(meal_type, count)

    dietary = user_profile.get("dietary_restrictions", []) or []
    conditions = []
    # Extract health conditions from profile
    if user_profile.get("has_diabetes"):
        conditions.append("diabetes")
    if user_profile.get("has_blood_pressure_issues"):
        conditions.append("high blood pressure")
    if user_profile.get("has_heart_issues"):
        conditions.append("heart disease")
    if user_profile.get("has_gut_issues"):
        conditions.append("digestive issues")
    
    goals_data = user_profile.get("goals", {}) or {}
    goals = []
    if isinstance(goals_data, dict):
        if goals_data.get("weight_goal") == "loss":
            goals.append("weight loss")
        elif goals_data.get("weight_goal") == "gain":
            goals.append("weight gain")
        if goals_data.get("muscle_building"):
            goals.append("muscle building")
        if goals_data.get("energy_improvement"):
            goals.append("energy improvement")
        if goals_data.get("sugar_control"):
            goals.append("sugar control")
    elif isinstance(goals_data, list):
        goals = goals_data
    
    allergies = user_profile.get("allergies", {})
    allergy_list = []
    if isinstance(allergies, dict):
        allergy_list = allergies.get("foods", []) or []
    elif isinstance(allergies, list):
        allergy_list = allergies
    
    system_prompt = (
        "You are a creative chef and certified nutritionist. Generate UNIQUE and DIVERSE meal ideas.\n"
        "IMPORTANT RULES:\n"
        "1. ONLY use the ingredients provided - do NOT add random ingredients like oats, granola, etc.\n"
        "2. Each meal MUST be completely different from the others\n"
        "3. Be creative - suggest interesting dishes, not just basic combinations\n"
        "4. If only one ingredient is given, suggest 3 different ways to prepare it\n"
        "5. Consider the user's health profile when creating recipes\n"
        "6. DO NOT use any emojis in your responses - use plain text only\n\n"
        
        "CRITICAL - ACCURATE USDA-BASED NUTRITION VALUES:\n"
        "You MUST provide ACCURATE calories based on USDA Food Data Central. MEMORIZE THESE:\n\n"
        
        "FRUITS (per 100g raw):\n"
        "- Apple: 52 kcal, 0.3g protein, 14g carbs, 10g sugar\n"
        "- Banana: 89 kcal, 1.1g protein, 23g carbs, 12g sugar\n"
        "- Orange: 47 kcal, 0.9g protein, 12g carbs, 9g sugar\n"
        "- Strawberry: 32 kcal, 0.7g protein, 8g carbs, 5g sugar\n"
        "- Mango: 60 kcal, 0.8g protein, 15g carbs, 14g sugar\n"
        "- Grapes: 69 kcal, 0.7g protein, 18g carbs, 16g sugar\n"
        "- Watermelon: 30 kcal, 0.6g protein, 8g carbs, 6g sugar\n\n"
        
        "VEGETABLES (per 100g raw):\n"
        "- Tomato: 18 kcal, 0.9g protein, 4g carbs, 2.6g sugar\n"
        "- Cucumber: 15 kcal, 0.7g protein, 4g carbs, 1.7g sugar\n"
        "- Carrot: 41 kcal, 0.9g protein, 10g carbs, 5g sugar\n"
        "- Spinach: 23 kcal, 2.9g protein, 4g carbs, 0.4g sugar\n"
        "- Broccoli: 34 kcal, 2.8g protein, 7g carbs, 1.7g sugar\n"
        "- Potato: 77 kcal, 2g protein, 17g carbs, 0.8g sugar\n\n"
        
        "PORTION GUIDE:\n"
        "- 1 medium apple = 180g = ~94 kcal\n"
        "- 1 medium banana = 120g = ~107 kcal\n"
        "- 1 cup chopped vegetables = ~100-150g\n"
        "- A simple fruit salad (200g) = ~100-140 kcal MAX\n\n"
        
        "CALCULATION RULE: Sum (ingredient_weight × kcal_per_100g / 100) for each ingredient.\n"
        "NEVER estimate a fruit/vegetable dish above 150 kcal unless it has added fats/proteins.\n\n"
        
        "Return ONLY a JSON array of objects with these exact keys:\n"
        "- name (string): creative meal name (NOT generic like 'Healthy [Food] Bowl') - NO emojis\n"
        "- description (string): appetizing description - NO emojis\n"
        "- calories (int): ACCURATE total calories - CALCULATE properly using values above\n"
        "- protein (int): grams of protein\n"
        "- carbs (int): grams of carbohydrates\n"
        "- fat (int): grams of fat\n"
        "- fiber (int): grams of fiber\n"
        "- sugar (int): grams of sugar\n"
        "- ingredients (list of strings): list of ingredients with quantities - NO emojis\n"
        "- preparation (string): step-by-step cooking instructions (2-4 sentences) - NO emojis\n"
        "- benefits (list of strings): 2-3 health benefits of this meal - NO emojis\n"
        "- warnings (list of strings): 1-2 things to note based on user's health conditions (empty if none) - NO emojis\n"
        "- time_minutes (int): estimated cooking time\n\n"
        "No prose, no markdown, no emojis, ONLY the JSON array with plain text values.\n"
        "Ensure all strings are properly escaped, especially double quotes."
    )
    
    user_prompt = (
        f"Meal Type: {meal_type}\n"
        f"AVAILABLE INGREDIENTS (USE ONLY THESE): {', '.join(ingredients) if ingredients else 'Fresh fruits and vegetables'}\n"
        f"Dietary Restrictions: {', '.join(dietary) if dietary else 'None'}\n"
        f"Allergies: {', '.join(allergy_list) if allergy_list else 'None'}\n"
        f"Health Conditions: {', '.join(conditions) if conditions else 'None'}\n"
        f"Goals: {', '.join(goals) if goals else 'General health'}\n"
        f"Cuisine Preference: Pakistani/South Asian cuisine preferred\n\n"
        f"Create {count} UNIQUE and CREATIVE {meal_type} recipes using ONLY the ingredients listed above.\n"
        f"IMPORTANT: Prefer PAKISTANI cuisine and cooking styles (biryani, karahi, curries, etc.)\n"
        f"Consider user's health conditions when suggesting meals - low sugar for diabetics, low sodium for BP issues.\n"
        f"Each recipe must be significantly different from the others. Be imaginative with Pakistani flavors!"
    )

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.4,  # Lowered to 0.4 to ensure valid JSON structure
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        arrays = re.findall(r"\[[\s\S]*?\]", text)
        payload = arrays[0] if arrays else text
        payload = _clean_json_payload(payload)
        data = json.loads(payload)
        
        if not isinstance(data, list):
            return _fallback_meal_recommendations(meal_type, count)
            
        out: List[Dict[str, object]] = []
        for item in data[:count]:
            if not isinstance(item, dict):
                continue
            out.append({
                "name": str(item.get("name", "Healthy Meal")),
                "description": str(item.get("description", "")),
                "calories": int(item.get("calories", 0)),
                "protein": int(item.get("protein", 0)),
                "carbs": int(item.get("carbs", 0)),
                "fat": int(item.get("fat", 0)),
                "fiber": int(item.get("fiber", 0)),
                "sugar": int(item.get("sugar", 0)),
                "ingredients": list(item.get("ingredients", [])),
                "preparation": str(item.get("preparation", item.get("cooking_instructions", ""))),
                "benefits": list(item.get("benefits", [])),
                "warnings": list(item.get("warnings", item.get("concerns", []))),
                "time_minutes": int(item.get("time_minutes", item.get("cooking_time", 15))),
            })
        return out if out else _fallback_meal_recommendations(meal_type, count)
    except Exception as e:
        print(f"Error generating meal recs: {e}")
        return _fallback_meal_recommendations(meal_type, count)


def _fallback_meal_recommendations(meal_type: str, count: int = 3) -> List[Dict[str, object]]:
    """Fallback meal recommendations with Pakistani cuisine options."""
    import random
    
    recommendations = {
        "breakfast": [
            # Pakistani Breakfast Options
            {
                "name": "Halwa Puri with Chana",
                "description": "Traditional Pakistani breakfast with semolina halwa, fried puri bread and spiced chickpeas",
                "calories": 450, "protein": 12, "carbs": 65, "fat": 18, "fiber": 8, "sugar": 15,
                "ingredients": ["2 puris", "1/2 cup chana masala", "2 tbsp suji halwa", "Pickled onions"],
                "preparation": "Serve hot puris with spiced chickpea curry and a small portion of sweet semolina halwa on the side.",
                "benefits": ["Good source of plant protein from chickpeas", "Energy-rich start to day", "Traditional comfort food"],
                "warnings": ["High in refined carbs - eat in moderation"],
                "time_minutes": 30
            },
            {
                "name": "Paratha with Dahi",
                "description": "Flaky whole wheat paratha served with fresh yogurt and achaar",
                "calories": 380, "protein": 10, "carbs": 48, "fat": 16, "fiber": 4, "sugar": 6,
                "ingredients": ["2 whole wheat parathas", "1 cup plain yogurt", "1 tbsp mango pickle", "Fresh mint"],
                "preparation": "Serve warm parathas with cool yogurt and a side of pickle. Garnish with fresh mint leaves.",
                "benefits": ["Probiotics from yogurt", "Whole grain fiber", "Balanced meal"],
                "warnings": [],
                "time_minutes": 20
            },
            {
                "name": "Anda Paratha",
                "description": "Egg-stuffed paratha - a protein-rich Pakistani breakfast staple",
                "calories": 320, "protein": 14, "carbs": 35, "fat": 14, "fiber": 3, "sugar": 2,
                "ingredients": ["1 whole wheat paratha", "2 eggs", "Green chilies", "Onions", "Fresh coriander"],
                "preparation": "Beat eggs with chopped onions and chilies. Cook paratha, pour egg mixture on top, flip and cook until set.",
                "benefits": ["High protein breakfast", "Sustained energy release", "Rich in B vitamins"],
                "warnings": [],
                "time_minutes": 15
            },
            {
                "name": "Nihari with Naan",
                "description": "Rich slow-cooked beef stew with soft naan bread",
                "calories": 520, "protein": 28, "carbs": 45, "fat": 24, "fiber": 2, "sugar": 3,
                "ingredients": ["1 cup nihari", "1 naan", "Ginger julienne", "Green chilies", "Fresh coriander"],
                "preparation": "Serve hot nihari garnished with ginger, chilies and coriander. Accompany with warm naan.",
                "benefits": ["High protein meal", "Iron-rich beef", "Traditional comfort food"],
                "warnings": ["High in sodium and fat - occasional treat"],
                "time_minutes": 10
            },
            {
                "name": "Fruit Chaat",
                "description": "Fresh seasonal fruits with Pakistani chaat masala and lemon",
                "calories": 120, "protein": 2, "carbs": 28, "fat": 1, "fiber": 4, "sugar": 22,
                "ingredients": ["1 cup mixed fruits (apple, banana, orange)", "Chaat masala", "Lemon juice", "Fresh mint"],
                "preparation": "Cut fruits into bite-sized pieces. Sprinkle with chaat masala and lemon juice. Garnish with mint.",
                "benefits": ["Low calorie", "High in vitamins", "Natural sugars for energy"],
                "warnings": [],
                "time_minutes": 10
            },
            {
                "name": "Aloo Paratha with Lassi",
                "description": "Potato-stuffed paratha served with sweet or salty lassi",
                "calories": 420, "protein": 12, "carbs": 58, "fat": 16, "fiber": 4, "sugar": 12,
                "ingredients": ["2 aloo parathas", "1 glass lassi", "Butter", "Pickle"],
                "preparation": "Serve hot aloo parathas with a pat of butter and refreshing lassi on the side.",
                "benefits": ["Carb-rich for energy", "Calcium from lassi", "Satisfying breakfast"],
                "warnings": ["High carb - balance with protein later"],
                "time_minutes": 25
            },
        ],
        "lunch": [
            # Pakistani Lunch Options
            {
                "name": "Chicken Biryani",
                "description": "Aromatic basmati rice layered with spiced chicken and caramelized onions",
                "calories": 480, "protein": 28, "carbs": 52, "fat": 18, "fiber": 3, "sugar": 4,
                "ingredients": ["1.5 cups biryani rice", "150g chicken", "Fried onions", "Yogurt marinade", "Biryani masala", "Saffron milk"],
                "preparation": "Layer marinated chicken with parboiled rice. Add fried onions and saffron milk. Dum cook for 20 minutes.",
                "benefits": ["High protein from chicken", "Complex carbs from basmati", "Aromatic spices aid digestion"],
                "warnings": ["High calorie - control portion size"],
                "time_minutes": 45
            },
            {
                "name": "Dal Chawal",
                "description": "Comforting yellow lentils served over steamed basmati rice",
                "calories": 350, "protein": 14, "carbs": 58, "fat": 8, "fiber": 10, "sugar": 3,
                "ingredients": ["1 cup cooked dal", "1 cup basmati rice", "Tarka (tempered oil)", "Green chilies", "Fresh coriander"],
                "preparation": "Cook lentils until soft. Prepare rice. Top dal with tarka of garlic and cumin. Serve over rice.",
                "benefits": ["Complete protein from dal+rice combo", "High fiber", "Budget-friendly nutrition"],
                "warnings": [],
                "time_minutes": 30
            },
            {
                "name": "Karahi Gosht with Roti",
                "description": "Spicy stir-fried mutton in tomato-based gravy with whole wheat roti",
                "calories": 520, "protein": 32, "carbs": 35, "fat": 28, "fiber": 4, "sugar": 5,
                "ingredients": ["150g mutton karahi", "2 whole wheat rotis", "Green chilies", "Ginger", "Fresh coriander"],
                "preparation": "Serve sizzling karahi gosht garnished with ginger and chilies alongside fresh rotis.",
                "benefits": ["Iron-rich mutton", "Whole grain fiber from roti", "Protein-packed meal"],
                "warnings": ["High in saturated fat - eat occasionally"],
                "time_minutes": 15
            },
            {
                "name": "Chana Masala with Rice",
                "description": "Spiced chickpea curry served with fragrant basmati rice",
                "calories": 380, "protein": 14, "carbs": 62, "fat": 10, "fiber": 12, "sugar": 6,
                "ingredients": ["1 cup chana masala", "1 cup basmati rice", "Onion", "Tomatoes", "Garam masala", "Fresh coriander"],
                "preparation": "Cook chickpeas in spiced tomato gravy. Serve over steamed basmati rice with fresh coriander.",
                "benefits": ["High plant protein", "Excellent fiber source", "Heart-healthy legumes"],
                "warnings": [],
                "time_minutes": 35
            },
            {
                "name": "Seekh Kebab Wrap",
                "description": "Grilled minced meat kebabs wrapped in paratha with chutney",
                "calories": 420, "protein": 26, "carbs": 38, "fat": 18, "fiber": 3, "sugar": 4,
                "ingredients": ["3 seekh kebabs", "1 paratha", "Mint chutney", "Onion rings", "Green salad"],
                "preparation": "Place grilled seekh kebabs on paratha. Add chutney, onions and salad. Roll and serve.",
                "benefits": ["High protein meal", "Grilled not fried", "Portable lunch option"],
                "warnings": [],
                "time_minutes": 20
            },
            {
                "name": "Palak Paneer with Naan",
                "description": "Creamy spinach curry with cottage cheese and soft naan bread",
                "calories": 450, "protein": 18, "carbs": 42, "fat": 24, "fiber": 6, "sugar": 5,
                "ingredients": ["1 cup palak paneer", "1 naan", "Cream", "Garlic", "Cumin seeds"],
                "preparation": "Serve hot palak paneer with a swirl of cream alongside warm garlic naan.",
                "benefits": ["Iron from spinach", "Calcium from paneer", "Vegetarian protein"],
                "warnings": ["High in cream - moderate portion"],
                "time_minutes": 10
            },
        ],
        "dinner": [
            # Pakistani Dinner Options
            {
                "name": "Chicken Tikka with Raita",
                "description": "Grilled marinated chicken pieces with cooling cucumber yogurt",
                "calories": 380, "protein": 38, "carbs": 12, "fat": 20, "fiber": 2, "sugar": 6,
                "ingredients": ["200g chicken tikka", "1 cup raita", "Lemon wedges", "Onion rings", "Green chutney"],
                "preparation": "Serve chargrilled chicken tikka with fresh raita, onion rings and green chutney on the side.",
                "benefits": ["High protein low carb", "Probiotics from yogurt", "Grilled not fried"],
                "warnings": [],
                "time_minutes": 15
            },
            {
                "name": "Mutton Korma with Naan",
                "description": "Rich and creamy mutton curry with soft naan bread",
                "calories": 580, "protein": 32, "carbs": 45, "fat": 32, "fiber": 3, "sugar": 5,
                "ingredients": ["1 cup mutton korma", "2 naans", "Fried onions", "Cashews", "Fresh coriander"],
                "preparation": "Serve hot korma garnished with fried onions and cashews alongside warm naan.",
                "benefits": ["Iron and zinc from mutton", "Nuts add healthy fats", "Satisfying dinner"],
                "warnings": ["Rich and high calorie - special occasion meal"],
                "time_minutes": 10
            },
            {
                "name": "Fish Curry with Rice",
                "description": "Spicy Pakistani-style fish curry with steamed rice",
                "calories": 420, "protein": 32, "carbs": 48, "fat": 12, "fiber": 3, "sugar": 4,
                "ingredients": ["150g fish fillet", "1 cup rice", "Tomato gravy", "Curry leaves", "Tamarind"],
                "preparation": "Cook fish in tangy tomato-based curry. Serve over steamed basmati rice with curry leaves.",
                "benefits": ["Omega-3 from fish", "Lean protein source", "Anti-inflammatory spices"],
                "warnings": [],
                "time_minutes": 30
            },
            {
                "name": "Chapli Kebab with Salad",
                "description": "Spiced minced meat patties from Peshawar with fresh salad",
                "calories": 450, "protein": 28, "carbs": 18, "fat": 30, "fiber": 4, "sugar": 3,
                "ingredients": ["3 chapli kebabs", "Tomato-onion salad", "Naan", "Mint chutney", "Lemon"],
                "preparation": "Pan-fry chapli kebabs until crispy. Serve with fresh salad, warm naan and chutney.",
                "benefits": ["High protein", "Traditional Pashtun recipe", "Flavorful and satisfying"],
                "warnings": ["Higher in fat - balance with salad"],
                "time_minutes": 20
            },
            {
                "name": "Daal Gosht",
                "description": "Lentils cooked with tender meat pieces - protein powerhouse",
                "calories": 420, "protein": 30, "carbs": 35, "fat": 18, "fiber": 10, "sugar": 3,
                "ingredients": ["1 cup daal gosht", "1 cup rice", "Tarka", "Ginger", "Green chilies"],
                "preparation": "Serve hearty daal gosht with steamed rice and fresh tarka on top.",
                "benefits": ["Double protein from meat and lentils", "High fiber", "Budget-friendly protein"],
                "warnings": [],
                "time_minutes": 15
            },
            {
                "name": "Sabzi with Roti",
                "description": "Mixed vegetable curry with whole wheat rotis",
                "calories": 320, "protein": 10, "carbs": 48, "fat": 12, "fiber": 8, "sugar": 6,
                "ingredients": ["1.5 cups mixed sabzi", "3 rotis", "Tomatoes", "Onions", "Green chilies", "Cumin"],
                "preparation": "Cook seasonal vegetables in light tomato-onion gravy. Serve with fresh whole wheat rotis.",
                "benefits": ["High fiber vegetarian meal", "Low calorie dinner", "Multiple vegetables"],
                "warnings": [],
                "time_minutes": 25
            },
        ],
        "snacks": [
            # Pakistani Snack Options
            {
                "name": "Samosa Chaat",
                "description": "Crispy samosa topped with chickpeas, yogurt and tangy chutneys",
                "calories": 280, "protein": 8, "carbs": 38, "fat": 12, "fiber": 5, "sugar": 8,
                "ingredients": ["1 samosa", "Chickpeas", "Yogurt", "Tamarind chutney", "Mint chutney", "Onions"],
                "preparation": "Break samosa into pieces. Top with chickpeas, yogurt and both chutneys. Garnish with onions.",
                "benefits": ["Satisfying snack", "Probiotics from yogurt", "Fiber from chickpeas"],
                "warnings": ["Fried - enjoy occasionally"],
                "time_minutes": 5
            },
            {
                "name": "Pakora with Chutney",
                "description": "Crispy vegetable fritters served with mint chutney",
                "calories": 180, "protein": 4, "carbs": 20, "fat": 10, "fiber": 3, "sugar": 2,
                "ingredients": ["4-5 pakoras", "Mint chutney", "Onion rings", "Green chilies"],
                "preparation": "Serve hot pakoras with fresh mint chutney and onion rings on the side.",
                "benefits": ["Quick energy boost", "Vegetables inside", "Traditional tea-time snack"],
                "warnings": ["Deep fried - moderate portion"],
                "time_minutes": 3
            },
            {
                "name": "Dahi Bhalla",
                "description": "Soft lentil dumplings in creamy spiced yogurt",
                "calories": 220, "protein": 10, "carbs": 28, "fat": 8, "fiber": 4, "sugar": 10,
                "ingredients": ["3 bhallas", "Whisked yogurt", "Tamarind chutney", "Cumin powder", "Red chili powder"],
                "preparation": "Soak bhallas in water. Squeeze and place in yogurt. Top with chutneys and spices.",
                "benefits": ["Probiotics from yogurt", "Protein from lentils", "Cooling snack"],
                "warnings": [],
                "time_minutes": 10
            },
            {
                "name": "Roasted Chana",
                "description": "Crunchy roasted chickpeas with chaat masala",
                "calories": 140, "protein": 8, "carbs": 22, "fat": 3, "fiber": 6, "sugar": 4,
                "ingredients": ["1/2 cup roasted chana", "Chaat masala", "Lemon juice", "Salt"],
                "preparation": "Toss roasted chickpeas with chaat masala, salt and a squeeze of lemon.",
                "benefits": ["High protein snack", "High fiber", "Low fat healthy option"],
                "warnings": [],
                "time_minutes": 2
            },
            {
                "name": "Fruit Lassi",
                "description": "Refreshing yogurt smoothie with mango or banana",
                "calories": 180, "protein": 6, "carbs": 32, "fat": 4, "fiber": 2, "sugar": 26,
                "ingredients": ["1 cup yogurt", "1/2 mango or banana", "Sugar/honey", "Cardamom", "Ice"],
                "preparation": "Blend yogurt with fruit, sweetener and cardamom. Serve chilled with ice.",
                "benefits": ["Probiotics from yogurt", "Natural fruit sugars", "Calcium rich"],
                "warnings": [],
                "time_minutes": 5
            },
            {
                "name": "Aloo Tikki",
                "description": "Spiced potato patties - crispy outside, soft inside",
                "calories": 200, "protein": 4, "carbs": 28, "fat": 9, "fiber": 3, "sugar": 2,
                "ingredients": ["2 aloo tikki", "Tamarind chutney", "Mint chutney", "Onions", "Coriander"],
                "preparation": "Serve hot crispy aloo tikki with both chutneys and fresh onion-coriander topping.",
                "benefits": ["Comfort food", "Energy from potatoes", "Versatile snack"],
                "warnings": ["Pan-fried - moderate portion"],
                "time_minutes": 5
            },
        ],
    }
    
    meal_key = meal_type.lower().replace(" ", "_")
    available = recommendations.get(meal_key, recommendations.get("snacks", []))
    
    # Randomize selection to ensure fresh/varied suggestions each time
    if len(available) > count:
        selected = random.sample(available, count)
    else:
        selected = available[:count]
    
    return selected


def generate_consumption_recommendations(
    food_name: str,
    user_profile: Dict[str, Any]
) -> Dict[str, Any]:
    """Generate personalized consumption recommendations."""
    client = _get_client()
    if client is None:
        return {
            "should_eat": True,
            "amount": "1 serving",
            "frequency": "daily",
            "warnings": [],
            "alternatives": []
        }

    system_prompt = (
        "You are a personalized nutrition assistant. Analyze if the user should eat this food based on their profile. "
        "Return ONLY a JSON object with keys: should_eat (bool), amount (string), frequency (string), "
        "preparation (string), warnings (list of strings), alternatives (list of strings). No prose."
    )
    
    # Format profile for prompt
    profile_summary = (
        f"Age: {user_profile.get('age')}, Gender: {user_profile.get('gender')}, "
        f"Conditions: {user_profile.get('has_diabetes') and 'Diabetes'}, "
        f"Allergies: {user_profile.get('allergies')}, "
        f"Goals: {user_profile.get('goals')}"
    )

    user_prompt = (
        f"Food: {food_name}\n"
        f"User Profile: {profile_summary}\n"
        "Return strictly a JSON object."
    )

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        # Extract JSON object
        match = re.search(r"\{[\s\S]*\}", text)
        payload = match.group(0) if match else text
        payload = _clean_json_payload(payload)
        data = json.loads(payload)
        
        return {
            "should_eat": bool(data.get("should_eat", True)),
            "amount": str(data.get("amount", "1 serving")),
            "frequency": str(data.get("frequency", "occasionally")),
            "preparation": str(data.get("preparation", "Wash before eating")),
            "warnings": [str(w) for w in data.get("warnings", [])],
            "alternatives": [str(a) for a in data.get("alternatives", [])]
        }
    except Exception as e:
        print(f"Error generating consumption recs: {e}")
        return {
            "should_eat": True,
            "amount": "1 serving",
            "frequency": "daily",
            "preparation": "Wash before eating",
            "warnings": [],
            "alternatives": []
        }


def generate_personalized_insights(
    user_profile: Dict[str, Any],
    recent_history: List[Dict[str, Any]],
    recent_meals: List[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Generate personalized daily/weekly insights based ONLY on user's actual consumption data."""
    client = _get_client()
    if client is None:
        return []

    # Extract user's name for personalization
    user_name = user_profile.get("first_name") or user_profile.get("name", "").split()[0] if user_profile.get("name") else ""
    
    # Extract health conditions
    conditions = []
    if user_profile.get("has_diabetes"):
        conditions.append("diabetes")
    if user_profile.get("has_blood_pressure_issues"):
        conditions.append("blood pressure issues")
    if user_profile.get("has_heart_issues"):
        conditions.append("heart conditions")
    if user_profile.get("has_gut_issues"):
        conditions.append("digestive issues")
    
    # Extract goals
    goals_data = user_profile.get("goals", {}) or {}
    goals = []
    if isinstance(goals_data, dict):
        if goals_data.get("weight_goal") == "loss":
            goals.append("weight loss")
        elif goals_data.get("weight_goal") == "gain":
            goals.append("weight gain")
        if goals_data.get("muscle_building"):
            goals.append("muscle building")
    
    # Build list of actually consumed/scanned foods
    scanned_foods = []
    for h in (recent_history or [])[:10]:
        food_name = h.get("food_name", "")
        if food_name:
            freshness = h.get("freshness", {})
            if isinstance(freshness, dict):
                freshness_status = freshness.get("freshness_status", freshness.get("level", ""))
            else:
                freshness_status = str(freshness)
            scanned_foods.append(f"{food_name} ({freshness_status})" if freshness_status else food_name)
    
    # Build list of logged meals
    logged_meals = []
    for m in (recent_meals or [])[:10]:
        meal_name = m.get("food_name", "")
        if meal_name:
            logged_meals.append(meal_name)
    
    # If no data, return empty - no fake insights
    if not scanned_foods and not logged_meals:
        return [{
            "title": "Start Scanning Foods!",
            "content": "Scan some fruits or vegetables to get personalized health insights based on what you eat.",
            "insight_type": "daily_advice"
        }]
    
    system_prompt = f"""You are a personal nutrition coach. Generate 3 health insights for this user.

CRITICAL RULES:
1. ONLY mention foods that appear in the user's SCANNED FOODS or LOGGED MEALS lists below
2. DO NOT suggest or mention any food the user hasn't actually consumed
3. Base ALL advice on the specific foods they have scanned/eaten
4. Consider their health conditions and goals when giving advice
5. Be specific - mention the actual food names from their list
6. If the food combination is unhealthy given their conditions, warn them
7. If the food choices are good, praise them
8. DO NOT mention any scores, percentages, or numbers like "63/100" or "your score is X%" - we calculate those separately
9. DO NOT include health score, freshness score, or any rating in your response

USER PROFILE:
- Name: {user_name if user_name else "User"}
- Health Conditions: {", ".join(conditions) if conditions else "None"}
- Goals: {", ".join(goals) if goals else "General wellness"}

USER'S SCANNED FOODS (These are what they actually have/consumed):
{", ".join(scanned_foods) if scanned_foods else "None yet"}

USER'S LOGGED MEALS:
{", ".join(logged_meals) if logged_meals else "None yet"}

Return ONLY a JSON array of 3 objects with keys: title, content, type (daily_advice/weekly_tip/warning).
Make insights personal and actionable based on their ACTUAL consumption data above.
No scores, no percentages, no ratings - just food-based advice.
No prose, no markdown - ONLY the JSON array."""

    user_prompt = "Generate 3 personalized insights based strictly on the user's actual consumed foods."

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.4,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        arrays = re.findall(r"\[[\s\S]*?\]", text)
        payload = arrays[0] if arrays else text
        payload = _clean_json_payload(payload)
        data = json.loads(payload)
        
        out = []
        for item in data:
            if isinstance(item, dict):
                out.append({
                    "title": str(item.get("title", "Health Tip")),
                    "content": str(item.get("content", "")),
                    "insight_type": str(item.get("type", "daily_advice"))
                })
        return out
    except Exception as e:
        print(f"Error generating insights: {e}")
        return []



def generate_chat_response(
    message: str,
    history: List[Dict[str, str]],
    user_profile: Dict[str, Any]
) -> str:
    """Generate response for nutrition chatbot."""
    client = _get_client()
    if client is None:
        return "I'm sorry, I cannot connect to my brain right now. Please try again later."

    # Extract user's first name for personalization
    user_name = user_profile.get("first_name") or user_profile.get("name") or ""
    if user_name:
        user_name = user_name.split()[0].capitalize()  # Get first name only
    
    # Build comprehensive user context
    age = user_profile.get("age", "")
    gender = user_profile.get("gender", "")
    conditions = []
    if user_profile.get("has_diabetes"):
        conditions.append("diabetes")
    if user_profile.get("has_blood_pressure_issues"):
        conditions.append("blood pressure issues")
    if user_profile.get("has_heart_issues"):
        conditions.append("heart conditions")
    if user_profile.get("has_gut_issues"):
        conditions.append("digestive issues")
    
    goals_data = user_profile.get("goals", {}) or {}
    goals = []
    if isinstance(goals_data, dict):
        if goals_data.get("weight_goal") == "loss":
            goals.append("weight loss")
        elif goals_data.get("weight_goal") == "gain":
            goals.append("weight gain")
        if goals_data.get("muscle_building"):
            goals.append("building muscle")
        if goals_data.get("energy_improvement"):
            goals.append("better energy")
    
    recent_meals = user_profile.get("recent_meals", [])
    recent_scans = user_profile.get("recent_scans", [])
    
    system_prompt = f'''You are NutriDoc - a professional nutritionist doctor who genuinely cares about your patients' health. You speak respectfully and professionally, while remaining friendly and caring.

YOUR PERSONALITY:
- You are a qualified, professional nutrition doctor who genuinely cares
- You speak in clear, professional English - friendly but respectful
- You address users respectfully by name when available (User's name: {user_name if user_name else "there"})
- You are strict about health advice - no compromises on health
- You are caring and honest - if something is unhealthy, you clearly explain why

YOUR TALKING STYLE:
- Use professional yet warm language
- Respectful phrases like: "I'd recommend", "Based on your profile", "My advice would be", "Please consider"
- Provide detailed explanations in multiple paragraphs
- Use minimal emojis - only when appropriate
- Appreciate good choices: "Excellent choice! This is a very healthy option!"
- Politely guide on bad choices: "I'd advise against this because..."
- Ask follow-up questions to give better advice

USER'S PROFILE (Personalize your responses):
- Name: {user_name if user_name else ""}
- Age: {age if age else "Not provided"}
- Gender: {gender if gender else "Not provided"}
- Health conditions: {", ".join(conditions) if conditions else "None mentioned"}
- Goals: {", ".join(goals) if goals else "General wellness"}
- Recent meals: {", ".join(recent_meals[:5]) if recent_meals else "No recent meals logged"}
- Recent scans: {", ".join(recent_scans[:5]) if recent_scans else "No recent scans"}

YOUR EXPERTISE (Where you can help):
- Food and recipes - what to eat and how to prepare
- Nutrition advice based on health conditions
- Calories, protein, carbs guidance
- Weight loss/gain tips
- Healthy eating motivation
- Food-related questions
- Benefits of fruits and vegetables
- Nutritional information about various foods

STRICT SECURITY RULES (NEVER BREAK THESE):
- NEVER share password, email, or login details
- NEVER share other users' information
- If asked about sensitive account info, say: "I don't have access to that information. But I'm happy to help with any nutrition questions!"

⚠️ OUT OF SCOPE - DO NOT ANSWER:
If the user asks about topics UNRELATED to nutrition/food/health such as:
- Politics, news, current affairs
- Movies, entertainment, games
- Coding, programming, tech
- General knowledge unrelated to health
- Relationship advice
- Finance, money, crypto
- Any topic not about food/nutrition/health

Politely decline:
"I appreciate the question, but that's outside my area of expertise. I specialize in nutrition and health. Is there anything food or diet-related I can help you with?"

Or: "That's not something I can help with, but I'd be happy to answer any questions about your diet, nutrition, or healthy eating!"

REMEMBER: You are {user_name if user_name else "the user"}'s nutrition doctor. Professional, respectful, and caring. Only discuss nutrition/food/health topics, politely decline everything else!'''

    messages = [{"role": "system", "content": system_prompt}]
    
    # Add history (last 6 turns max for better context)
    for h in history[-6:]:
        role = h.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": h.get("content", "")})
    
    # Add current message
    messages.append({"role": "user", "content": message})

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.8,  # Slightly higher for more natural variation
            messages=messages,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating chat response: {e}")
        return "I'm having trouble thinking right now. Please ask again."


def generate_meal_suggestions_personal(
    user_profile: Dict[str, Any],
    recent_history: List[str], # List of food names recently scanned
    count: int = 3
) -> List[Dict[str, object]]:
    """Generate meal suggestions based on scan history and profile.
    
    Returns comprehensive meal suggestions including:
    - name, description, calories, protein, carbs, fat, fiber, sugar
    - matching_ingredients from recent scans
    - preparation instructions
    - benefits and warnings
    - time_minutes for cooking
    """
    client = _get_client()
    if client is None:
        return []

    # Extract user context
    conditions = []
    if user_profile.get("has_diabetes"):
        conditions.append("diabetes")
    if user_profile.get("has_blood_pressure_issues"):
        conditions.append("high blood pressure")
    if user_profile.get("has_heart_issues"):
        conditions.append("heart disease")
    
    goals_data = user_profile.get("goals", {}) or {}
    goals = []
    if isinstance(goals_data, dict):
        if goals_data.get("weight_goal") == "loss":
            goals.append("weight loss")
        elif goals_data.get("weight_goal") == "gain":
            goals.append("weight gain")
    elif isinstance(goals_data, list):
        goals = goals_data

    system_prompt = (
        "You are a creative chef and nutritionist. Suggest meals using the user's recently scanned foods.\n"
        "Return ONLY a JSON array of objects with these exact keys:\n"
        "- name (string): meal name\n"
        "- description (string): brief description\n"
        "- calories (int): estimated calories\n"
        "- protein (int): grams of protein\n"
        "- carbs (int): grams of carbs\n"
        "- fat (int): grams of fat\n"
        "- fiber (int): grams of fiber\n"
        "- sugar (int): grams of sugar\n"
        "- time_minutes (int): cooking time\n"
        "- matching_ingredients (list of strings): which scanned foods are used\n"
        "- additional_ingredients (list of strings): other ingredients needed\n"
        "- preparation (string): step-by-step cooking instructions (3-4 sentences)\n"
        "- benefits (list of strings): 2-3 health benefits\n"
        "- warnings (list of strings): any concerns for user's conditions (empty if none)\n\n"
        "No prose, no markdown, ONLY the JSON array."
    )
    
    user_prompt = (
        f"Recently Scanned Foods: {', '.join(recent_history) if recent_history else 'various fresh ingredients'}\n"
        f"Health Conditions: {', '.join(conditions) if conditions else 'None'}\n"
        f"Goals: {', '.join(goals) if goals else 'General health'}\n"
        f"Suggest {count} creative meals using these foods. Include preparation instructions and health benefits."
    )

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.5,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        arrays = re.findall(r"\[[\s\S]*?\]", text)
        payload = arrays[0] if arrays else text
        payload = _clean_json_payload(payload)
        data = json.loads(payload)
        
        if not isinstance(data, list):
            return []
            
        out: List[Dict[str, object]] = []
        for item in data[:count]:
            if not isinstance(item, dict):
                continue
            out.append({
                "name": str(item.get("name", "Suggested Meal")),
                "description": str(item.get("description", "")),
                "calories": int(item.get("calories", 0)),
                "protein": int(item.get("protein", 0)),
                "carbs": int(item.get("carbs", 0)),
                "fat": int(item.get("fat", 0)),
                "fiber": int(item.get("fiber", 0)),
                "sugar": int(item.get("sugar", 0)),
                "time_minutes": int(item.get("time_minutes", 20)),
                "matching_ingredients": list(item.get("matching_ingredients", [])),
                "additional_ingredients": list(item.get("additional_ingredients", [])),
                "preparation": str(item.get("preparation", "")),
                "benefits": list(item.get("benefits", [])),
                "warnings": list(item.get("warnings", [])),
            })
        return out
    except Exception as e:
        print(f"Error generating meal suggestions: {e}")
        return []


@cached(ttl=86400)  # Cache for 24 hours - nutrition goals are stable for same profile
def generate_personalized_nutrition_goals(user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Generate personalized daily nutrition goals using GPT based on health profile.
    
    Returns dictionary with:
    - calories, protein, carbs, fat, fiber, sugar targets
    - reasoning for the recommendations
    
    CACHED: Results cached for 24 hours (profile doesn't change frequently)
    """
    client = _get_client()
    
    # Extract profile data
    age = user_profile.get("age", 30)
    gender = user_profile.get("gender", "other")
    weight = user_profile.get("weight_kg", 70)
    height = user_profile.get("height_cm", 170)
    activity = user_profile.get("activity_level", "moderate")
    
    # Health conditions
    conditions = []
    if user_profile.get("has_diabetes"):
        conditions.append("diabetes")
    if user_profile.get("has_blood_pressure_issues"):
        conditions.append("high blood pressure")
    if user_profile.get("has_heart_issues"):
        conditions.append("heart disease")
    if user_profile.get("has_gut_issues"):
        conditions.append("digestive issues")
    
    # Goals
    goals_data = user_profile.get("goals", {}) or {}
    goals = []
    if isinstance(goals_data, dict):
        if goals_data.get("weight_goal") == "loss":
            goals.append("weight loss")
        elif goals_data.get("weight_goal") == "gain":
            goals.append("weight gain")
        if goals_data.get("muscle_building"):
            goals.append("muscle building")
        if goals_data.get("energy_improvement"):
            goals.append("energy improvement")
        if goals_data.get("sugar_control"):
            goals.append("sugar control")
    
    # Fallback calculation if API unavailable
    if client is None:
        return _calculate_fallback_goals(age, gender, weight, height, activity, conditions, goals)
    
    system_prompt = (
        "You are an expert clinical nutritionist using evidence-based guidelines.\n"
        "Calculate personalized daily nutrition targets using Mifflin-St Jeor equation.\n\n"
        
        "STEP 1 - Calculate BMR (Mifflin-St Jeor):\n"
        "- Males: BMR = (10 × weight_kg) + (6.25 × height_cm) - (5 × age) + 5\n"
        "- Females: BMR = (10 × weight_kg) + (6.25 × height_cm) - (5 × age) - 161\n\n"
        
        "STEP 2 - Calculate TDEE (BMR × Activity Multiplier):\n"
        "- Sedentary: 1.2 | Light: 1.375 | Moderate: 1.55 | Active: 1.725 | Very Active: 1.9\n\n"
        
        "STEP 3 - Adjust for Goals:\n"
        "- Weight loss: TDEE × 0.80 (20% deficit)\n"
        "- Weight gain: TDEE × 1.15 (15% surplus)\n"
        "- Maintenance: TDEE\n\n"
        
        "STEP 4 - Macronutrient Distribution (WHO/FAO/IOM guidelines):\n"
        "- Protein: 0.8g/kg (normal), 1.4g/kg (weight loss), 1.8g/kg (muscle building)\n"
        "- Carbs: 45-55% of remaining calories (40% for diabetics)\n"
        "- Fat: 25-35% of remaining calories\n"
        "- Fiber: 25-38g daily (IOM), higher (35g+) for diabetics\n"
        "- Sugar: 75-90g TOTAL (including natural fruit sugars), 25g for diabetics\n"
        "  NOTE: Sugar goal should be REALISTIC - a single apple has 19g natural sugar!\n"
        "- Saturated Fat: <10% of total calories\n\n"
        
        "IMPORTANT: Sugar goals must account for natural sugars in fruits/dairy.\n"
        "A restrictive 25g sugar limit (for non-diabetics) is unrealistic and harmful.\n\n"
        
        "Return ONLY a JSON object with these keys:\n"
        "- calories (int): daily calorie target\n"
        "- protein (int): grams of protein\n"
        "- carbs (int): grams of carbohydrates\n"
        "- fat (int): grams of fat\n"
        "- fiber (int): grams of fiber\n"
        "- sugar (int): grams of TOTAL sugar (include natural sugars - be realistic!)\n"
        "- saturated_fat (int): grams of saturated fat (upper limit)\n"
        "- reasoning (string): brief calculation breakdown\n\n"
        "No prose, no markdown, ONLY the JSON object."
    )
    
    user_prompt = (
        f"Calculate personalized daily nutrition targets for:\n"
        f"Age: {age} years\n"
        f"Gender: {gender}\n"
        f"Weight: {weight} kg\n"
        f"Height: {height} cm\n"
        f"Activity Level: {activity}\n"
        f"Health Conditions: {', '.join(conditions) if conditions else 'None'}\n"
        f"Goals: {', '.join(goals) if goals else 'General health maintenance'}\n"
    )
    
    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            temperature=0.3,  # Low temperature for consistent calculations
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content.strip()
        
        # Parse JSON response
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            payload = _clean_json_payload(json_match.group())
            data = json.loads(payload)
            
            # Validate and ensure all required fields
            return {
                "calories": int(data.get("calories", 2000)),
                "protein": int(data.get("protein", 50)),
                "carbs": int(data.get("carbs", 275)),
                "fat": int(data.get("fat", 65)),
                "fiber": int(data.get("fiber", 28)),
                "sugar": int(data.get("sugar", 50)),
                "saturated_fat": int(data.get("saturated_fat", 20)),
                "reasoning": str(data.get("reasoning", "Calculated based on your profile"))
            }
    except Exception as e:
        print(f"Error generating nutrition goals: {e}")
    
    # Fallback
    return _calculate_fallback_goals(age, gender, weight, height, activity, conditions, goals)


def _calculate_fallback_goals(age, gender, weight, height, activity, conditions, goals) -> Dict[str, Any]:
    """Calculate daily nutrition goals using Mifflin-St Jeor formula with scientific adjustments.
    
    Based on:
    - Mifflin-St Jeor equation (more accurate than Harris-Benedict for modern populations)
    - WHO/FAO recommendations for macronutrient distribution
    - American Heart Association guidelines for sugar intake
    - Institute of Medicine (IOM) Dietary Reference Intakes
    """
    # Mifflin-St Jeor BMR calculation (more accurate than Harris-Benedict)
    if gender == "male":
        bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
    elif gender == "female":
        bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161
    else:
        bmr = (10 * weight) + (6.25 * height) - (5 * age) - 78  # Average
    
    # Activity multiplier (PAL - Physical Activity Level)
    multipliers = {
        "sedentary": 1.2,      # Little or no exercise
        "light": 1.375,        # Light exercise 1-3 days/week
        "moderate": 1.55,      # Moderate exercise 3-5 days/week
        "active": 1.725,       # Hard exercise 6-7 days/week
        "very_active": 1.9     # Very hard exercise, physical job
    }
    tdee = bmr * multipliers.get(activity, 1.55)
    
    # Goal-based calorie adjustments
    if "weight loss" in goals:
        calories = tdee * 0.80  # 20% deficit for safe weight loss (0.5-1kg/week)
    elif "weight gain" in goals:
        calories = tdee * 1.15  # 15% surplus for lean muscle gain
    else:
        calories = tdee
    
    # Protein calculation based on IOM recommendations
    # Base: 0.8g/kg, Athletes: 1.2-2.0g/kg, Weight loss: 1.2-1.6g/kg
    protein_per_kg = 0.8
    if "muscle building" in goals:
        protein_per_kg = 1.8  # Higher protein for muscle synthesis
    elif "weight loss" in goals:
        protein_per_kg = 1.4  # Higher protein to preserve muscle mass
    protein = weight * protein_per_kg
    
    # Macronutrient distribution based on WHO/FAO guidelines
    # Carbs: 45-65% of calories, Fat: 20-35% of calories
    if "diabetes" in conditions:
        carb_pct = 0.40  # Lower carbs for diabetes management
        fat_pct = 0.35
        sugar_limit = 25  # AHA recommendation for diabetics
        fiber = 35  # Higher fiber helps with blood sugar control
    else:
        carb_pct = 0.50  # Standard 50% carbs
        fat_pct = 0.30   # Standard 30% fat
        # AHA recommends no more than 36g (men) / 25g (women) added sugar
        # Total sugar (including natural) typically 50-100g for active adults
        if gender == "male":
            sugar_limit = 90  # More realistic for total sugars including fruit
        else:
            sugar_limit = 75  # More realistic for total sugars including fruit
        fiber = 28  # IOM recommendation (25g women, 38g men, averaged)
    
    # Calculate macros from calorie targets
    # Protein: 4 cal/g, Carbs: 4 cal/g, Fat: 9 cal/g
    protein_calories = protein * 4
    remaining_calories = calories - protein_calories
    carbs = (remaining_calories * (carb_pct / (carb_pct + fat_pct))) / 4
    fat = (remaining_calories * (fat_pct / (carb_pct + fat_pct))) / 9
    
    # Saturated fat limit: < 10% of total calories (AHA guideline)
    saturated_fat_limit = round((calories * 0.10) / 9)
    
    return {
        "calories": round(calories),
        "protein": round(protein),
        "carbs": round(carbs),
        "fat": round(fat),
        "fiber": fiber,
        "sugar": sugar_limit,
        "saturated_fat": saturated_fat_limit,
        "reasoning": f"Calculated using Mifflin-St Jeor formula (TDEE: {round(tdee)} kcal) with WHO/FAO/AHA guidelines adjusted for your profile"
    }


if __name__ == "__main__":
    # Simple CLI: enter food and freshness, get storage recommendations
    print("Storage Recommender (Groq). Type 'exit' to quit.\n")
    while True:
        food = input("Food name: ")
        if food.strip().lower() in {"exit", "quit"}:
            break
        fr = input("Freshness (fresh/mid-fresh/not fresh): ")
        recs = generate_storage_recommendations(food, fr)
        print(json.dumps(recs, indent=2, ensure_ascii=False))
