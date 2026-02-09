import requests

API_KEY = "Z7yPFQiFgzYfMwzlgAwaCLw1blcmYoI2nAcc3Qs7"


NUTRIENT_IDS = {
    "Energy (kcal)": 1008,
    "Carbohydrates (g)": 1005,
    "Sugars (g)": 2000,
    "Dietary Fiber (g)": 1079,
    "Protein (g)": 1003,
    "Total Fat (g)": 1004,
    "Vitamin C (mg)": 1162,
    "Vitamin A (µg)": 1106,
    "Vitamin K (µg)": 1185,
    "Folate (µg)": 1177,
    "Vitamin B6 (mg)": 1175,
    "Niacin (mg)": 1166,
    "Riboflavin (mg)": 1167,
    "Thiamin (mg)": 1165,
    "Vitamin E (mg)": 1109,
    "Potassium (mg)": 1092,
    "Calcium (mg)": 1087,
    "Magnesium (mg)": 1090,
    "Phosphorus (mg)": 1091,
    "Iron (mg)": 1089,
    "Zinc (mg)": 1095,
    "Sodium (mg)": 1093,
    "Copper (mg)": 1098,
    "Manganese (mg)": 1101,
    "Selenium (µg)": 1103
}

def get_food_id(food_name):
    """Search food by name and return the first FDC ID."""
    url = f"https://api.nal.usda.gov/fdc/v1/foods/search?api_key={API_KEY}"
    params = {"query": food_name, "pageSize": 1, "dataType": ["Foundation", "SR Legacy", "FNDDS"]}
    response = requests.get(url, params=params)
    data = response.json()
    if data.get("foods"):
        return data["foods"][0]["fdcId"], data["foods"][0]["description"]
    return None, None

def get_nutrient_data(fdc_id):
    """Fetch nutrient data for a food ID."""
    url = f"https://api.nal.usda.gov/fdc/v1/food/{fdc_id}?api_key={API_KEY}"
    response = requests.get(url)
    data = response.json()
    nutrients = data.get("foodNutrients", [])

    # Map nutrients by ID for quick lookup (with safe access)
    nutrient_dict = {}
    for n in nutrients:
        nutrient_info = n.get("nutrient", {})
        nutrient_id = nutrient_info.get("id")
        if nutrient_id is not None:
            nutrient_dict[nutrient_id] = n.get("amount", 0.0)

    # Build final result with 0.0 for missing nutrients
    result = {}
    for name, nid in NUTRIENT_IDS.items():
        result[name] = nutrient_dict.get(nid, 0.0)

    return result

def main():
    food_name = input("Enter fruit or vegetable name: ")
    fdc_id, official_name = get_food_id(food_name)

    if not fdc_id:
        print(" Food not found in USDA database.")
        return

    print(f"\n Nutritional values for: {official_name}\n")
    nutrient_data = get_nutrient_data(fdc_id)
    for nutrient, value in nutrient_data.items():
        print(f"{nutrient}: {value}")

if __name__ == "__main__":
    main()
