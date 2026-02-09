"""
Health Calculator Service - Calculates health scores and metrics
Provides BMI, calorie requirements, and health risk assessments
"""

from typing import Dict, List, Optional, Any
from enum import Enum


class ActivityLevel(Enum):
    """Activity level multipliers for calorie calculation"""
    SEDENTARY = 1.2       # Little or no exercise
    LIGHT = 1.375         # Light exercise 1-3 days/week
    MODERATE = 1.55       # Moderate exercise 3-5 days/week
    ACTIVE = 1.725        # Heavy exercise 6-7 days/week
    VERY_ACTIVE = 1.9     # Very heavy exercise, physical job


class Gender(Enum):
    """Gender for BMR calculation"""
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


# ===== BMI Calculations =====

def calculate_bmi(weight_kg: float, height_cm: float) -> float:
    """
    Calculate Body Mass Index.
    
    Args:
        weight_kg: Weight in kilograms
        height_cm: Height in centimeters
        
    Returns:
        BMI value rounded to 1 decimal place
    """
    if height_cm <= 0 or weight_kg <= 0:
        return 0.0
    
    height_m = height_cm / 100
    bmi = weight_kg / (height_m ** 2)
    return round(bmi, 1)


def get_bmi_category(bmi: float) -> str:
    """
    Get BMI category description.
    
    Args:
        bmi: BMI value
        
    Returns:
        Category string: underweight, normal, overweight, obese
    """
    if bmi < 18.5:
        return "underweight"
    elif bmi < 25:
        return "normal"
    elif bmi < 30:
        return "overweight"
    else:
        return "obese"


def get_healthy_weight_range(height_cm: float) -> Dict[str, float]:
    """
    Calculate healthy weight range for a given height.
    Based on BMI 18.5-24.9 range.
    
    Args:
        height_cm: Height in centimeters
        
    Returns:
        Dictionary with min and max healthy weights in kg
    """
    if height_cm <= 0:
        return {"min": 0, "max": 0}
    
    height_m = height_cm / 100
    min_weight = 18.5 * (height_m ** 2)
    max_weight = 24.9 * (height_m ** 2)
    
    return {
        "min": round(min_weight, 1),
        "max": round(max_weight, 1)
    }


# ===== Calorie Calculations =====

def calculate_bmr(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str
) -> float:
    """
    Calculate Basal Metabolic Rate using Mifflin-St Jeor equation.
    More accurate than Harris-Benedict for modern populations.
    
    Args:
        weight_kg: Weight in kilograms
        height_cm: Height in centimeters
        age: Age in years
        gender: Gender string (male, female, other)
        
    Returns:
        BMR in calories per day
    """
    if weight_kg <= 0 or height_cm <= 0 or age <= 0:
        return 0.0
    
    # Mifflin-St Jeor Equation
    # Men: BMR = 10 × weight(kg) + 6.25 × height(cm) - 5 × age(years) + 5
    # Women: BMR = 10 × weight(kg) + 6.25 × height(cm) - 5 × age(years) - 161
    
    base_bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age)
    
    if gender.lower() == "male":
        bmr = base_bmr + 5
    elif gender.lower() == "female":
        bmr = base_bmr - 161
    else:
        # Average for other/unspecified
        bmr = base_bmr - 78
    
    return round(bmr, 0)


def calculate_tdee(bmr: float, activity_level: str) -> float:
    """
    Calculate Total Daily Energy Expenditure.
    
    Args:
        bmr: Basal Metabolic Rate
        activity_level: Activity level string
        
    Returns:
        TDEE in calories per day
    """
    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9
    }
    
    multiplier = activity_multipliers.get(activity_level.lower(), 1.55)
    tdee = bmr * multiplier
    
    return round(tdee, 0)


def calculate_daily_calories(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    goal: str = "maintain"
) -> int:
    """
    Calculate recommended daily calorie intake based on goal.
    
    Args:
        weight_kg: Weight in kilograms
        height_cm: Height in centimeters
        age: Age in years
        gender: Gender string
        activity_level: Activity level string
        goal: Goal string (lose, maintain, gain)
        
    Returns:
        Recommended daily calories
    """
    bmr = calculate_bmr(weight_kg, height_cm, age, gender)
    tdee = calculate_tdee(bmr, activity_level)
    
    # Adjust based on goal
    if goal.lower() in ["lose", "weight_loss", "cut"]:
        # 500 calorie deficit for ~0.5kg/week loss
        calories = tdee - 500
    elif goal.lower() in ["gain", "weight_gain", "bulk"]:
        # 500 calorie surplus for ~0.5kg/week gain
        calories = tdee + 500
    else:
        calories = tdee
    
    # Ensure minimum safe calories
    min_calories = 1200 if gender.lower() == "female" else 1500
    return max(int(calories), min_calories)


# ===== Macronutrient Calculations =====

def calculate_macro_targets(
    daily_calories: int,
    goal: str = "maintain",
    dietary_preference: str = "balanced"
) -> Dict[str, int]:
    """
    Calculate macronutrient targets based on calories and goal.
    
    Args:
        daily_calories: Total daily calories
        goal: Health goal (lose, maintain, gain)
        dietary_preference: Diet type (balanced, low_carb, high_protein)
        
    Returns:
        Dictionary with protein, carbs, fat targets in grams
    """
    # Default balanced macros (30% protein, 40% carbs, 30% fat)
    protein_pct = 0.30
    carb_pct = 0.40
    fat_pct = 0.30
    
    # Adjust based on goal
    if goal.lower() in ["lose", "weight_loss"]:
        protein_pct = 0.35  # Higher protein for satiety
        carb_pct = 0.35
        fat_pct = 0.30
    elif goal.lower() in ["gain", "muscle_gain"]:
        protein_pct = 0.30
        carb_pct = 0.45  # Higher carbs for energy
        fat_pct = 0.25
    
    # Adjust based on dietary preference
    if dietary_preference == "low_carb":
        protein_pct = 0.35
        carb_pct = 0.25
        fat_pct = 0.40
    elif dietary_preference == "high_protein":
        protein_pct = 0.40
        carb_pct = 0.35
        fat_pct = 0.25
    
    # Calculate grams (protein: 4 cal/g, carbs: 4 cal/g, fat: 9 cal/g)
    protein_g = int((daily_calories * protein_pct) / 4)
    carbs_g = int((daily_calories * carb_pct) / 4)
    fat_g = int((daily_calories * fat_pct) / 9)
    
    return {
        "protein": protein_g,
        "carbs": carbs_g,
        "fat": fat_g
    }


def calculate_fiber_target(age: int, gender: str) -> int:
    """
    Calculate daily fiber target based on age and gender.
    Based on dietary guidelines.
    
    Args:
        age: Age in years
        gender: Gender string
        
    Returns:
        Fiber target in grams
    """
    # General recommendations:
    # Men: 38g/day (under 50), 30g/day (over 50)
    # Women: 25g/day (under 50), 21g/day (over 50)
    
    if gender.lower() == "male":
        return 38 if age < 50 else 30
    elif gender.lower() == "female":
        return 25 if age < 50 else 21
    else:
        return 30 if age < 50 else 25


def calculate_water_intake(weight_kg: float, activity_level: str) -> float:
    """
    Calculate recommended daily water intake.
    
    Args:
        weight_kg: Weight in kilograms
        activity_level: Activity level string
        
    Returns:
        Water intake in liters
    """
    # Base: 30-35ml per kg body weight
    base_ml = weight_kg * 33
    
    # Adjust for activity
    activity_multipliers = {
        "sedentary": 1.0,
        "light": 1.1,
        "moderate": 1.2,
        "active": 1.3,
        "very_active": 1.4
    }
    
    multiplier = activity_multipliers.get(activity_level.lower(), 1.2)
    total_ml = base_ml * multiplier
    
    return round(total_ml / 1000, 1)  # Convert to liters


# ===== Health Risk Assessment =====

def assess_health_risks(
    bmi: float,
    age: int,
    health_conditions: List[str]
) -> List[Dict[str, Any]]:
    """
    Assess health risks based on BMI and conditions.
    
    Args:
        bmi: BMI value
        age: Age in years
        health_conditions: List of existing health conditions
        
    Returns:
        List of risk assessment dictionaries
    """
    risks = []
    
    # BMI-related risks
    if bmi < 18.5:
        risks.append({
            "type": "underweight",
            "severity": "moderate",
            "description": "Being underweight may indicate nutritional deficiencies",
            "recommendations": ["Increase calorie intake", "Focus on nutrient-dense foods"]
        })
    elif bmi >= 25 and bmi < 30:
        risks.append({
            "type": "overweight",
            "severity": "low",
            "description": "Slightly elevated health risks",
            "recommendations": ["Regular exercise", "Balanced diet"]
        })
    elif bmi >= 30:
        risks.append({
            "type": "obesity",
            "severity": "moderate",
            "description": "Increased risk of chronic diseases",
            "recommendations": ["Consult healthcare provider", "Gradual weight loss"]
        })
    
    # Condition-specific risks
    condition_risks = {
        "diabetes": {
            "type": "blood_sugar",
            "severity": "high",
            "description": "Monitor carbohydrate intake carefully",
            "recommendations": ["Track carbs", "Avoid sugary foods", "Regular meals"]
        },
        "hypertension": {
            "type": "blood_pressure",
            "severity": "moderate",
            "description": "Monitor sodium intake",
            "recommendations": ["Limit salt", "Eat potassium-rich foods", "Reduce processed foods"]
        },
        "heart_disease": {
            "type": "cardiovascular",
            "severity": "high",
            "description": "Focus on heart-healthy diet",
            "recommendations": ["Limit saturated fats", "Eat omega-3 rich foods", "High fiber diet"]
        },
        "cholesterol": {
            "type": "lipid",
            "severity": "moderate",
            "description": "Monitor fat intake",
            "recommendations": ["Limit trans fats", "Eat soluble fiber", "Include healthy fats"]
        }
    }
    
    for condition in health_conditions:
        condition_lower = condition.lower()
        for key, risk in condition_risks.items():
            if key in condition_lower:
                risks.append(risk)
                break
    
    return risks


# ===== Comprehensive Health Profile =====

def calculate_complete_health_profile(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    health_conditions: List[str] = None,
    health_goals: List[str] = None
) -> Dict[str, Any]:
    """
    Calculate comprehensive health profile with all metrics.
    
    Args:
        weight_kg: Weight in kilograms
        height_cm: Height in centimeters
        age: Age in years
        gender: Gender string
        activity_level: Activity level string
        health_conditions: List of health conditions
        health_goals: List of health goals
        
    Returns:
        Complete health profile dictionary
    """
    health_conditions = health_conditions or []
    health_goals = health_goals or []
    
    # Calculate BMI
    bmi = calculate_bmi(weight_kg, height_cm)
    bmi_category = get_bmi_category(bmi)
    healthy_range = get_healthy_weight_range(height_cm)
    
    # Determine primary goal
    goal = "maintain"
    if "weight_loss" in health_goals or "lose_weight" in health_goals:
        goal = "lose"
    elif "muscle_gain" in health_goals or "gain_weight" in health_goals:
        goal = "gain"
    
    # Calculate calories and macros
    daily_calories = calculate_daily_calories(
        weight_kg, height_cm, age, gender, activity_level, goal
    )
    macros = calculate_macro_targets(daily_calories, goal)
    
    # Calculate other targets
    fiber_target = calculate_fiber_target(age, gender)
    water_intake = calculate_water_intake(weight_kg, activity_level)
    
    # Assess risks
    health_risks = assess_health_risks(bmi, age, health_conditions)
    
    return {
        "bmi": {
            "value": bmi,
            "category": bmi_category,
            "healthy_range": healthy_range
        },
        "daily_targets": {
            "calories": daily_calories,
            "protein": macros["protein"],
            "carbs": macros["carbs"],
            "fat": macros["fat"],
            "fiber": fiber_target,
            "water_liters": water_intake,
            "sugar": int(daily_calories * 0.05 / 4)  # Max 5% of calories from added sugar
        },
        "health_risks": health_risks,
        "recommendations": generate_lifestyle_recommendations(
            bmi_category, health_conditions, health_goals
        )
    }


def generate_lifestyle_recommendations(
    bmi_category: str,
    health_conditions: List[str],
    health_goals: List[str]
) -> List[str]:
    """
    Generate personalized lifestyle recommendations.
    
    Args:
        bmi_category: BMI category string
        health_conditions: List of health conditions
        health_goals: List of health goals
        
    Returns:
        List of recommendation strings
    """
    recommendations = []
    
    # BMI-based recommendations
    if bmi_category == "underweight":
        recommendations.append("Focus on nutrient-dense, calorie-rich foods")
        recommendations.append("Include healthy fats like nuts, avocados, and olive oil")
    elif bmi_category == "overweight":
        recommendations.append("Aim for 150+ minutes of moderate exercise weekly")
        recommendations.append("Focus on portion control and mindful eating")
    elif bmi_category == "obese":
        recommendations.append("Consult a healthcare provider for personalized guidance")
        recommendations.append("Start with low-impact exercises like walking or swimming")
    
    # Condition-based recommendations
    if any("diabetes" in c.lower() for c in health_conditions):
        recommendations.append("Choose low glycemic index foods")
        recommendations.append("Monitor blood sugar regularly")
    
    if any("hypertension" in c.lower() or "blood pressure" in c.lower() for c in health_conditions):
        recommendations.append("Reduce sodium intake to less than 2300mg/day")
        recommendations.append("Include potassium-rich foods like bananas and leafy greens")
    
    # Goal-based recommendations
    if any("muscle" in g.lower() for g in health_goals):
        recommendations.append("Include protein with every meal")
        recommendations.append("Consider strength training 2-3 times per week")
    
    if any("energy" in g.lower() for g in health_goals):
        recommendations.append("Eat small, frequent meals throughout the day")
        recommendations.append("Stay hydrated and limit caffeine after 2 PM")
    
    # General recommendations
    if len(recommendations) < 3:
        recommendations.extend([
            "Eat a variety of colorful fruits and vegetables daily",
            "Get 7-9 hours of quality sleep",
            "Practice stress management techniques"
        ])
    
    return recommendations[:5]  # Return top 5 recommendations

