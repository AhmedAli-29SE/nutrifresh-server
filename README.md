# NutriFresh API Server

[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100.0-green)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue)](https://www.postgresql.org/)

FastAPI server for NutriFresh with PostgreSQL database, machine learning models for food detection, and nutrition tracking.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your PostgreSQL credentials

# Run database migrations
psql -U postgres -d nutrifresh -f schema.sql
psql -U postgres -d nutrifresh -f migrations/001_add_meal_tracking.sql

# Start the server
python main.py
API Endpoints
Authentication
Endpoint	Method	Description
/api/auth/signup	POST	Register new user
/api/auth/login	POST	Login and get JWT token
Food Analysis
Endpoint	Method	Description
/api/analyze-food	POST	Analyze food image
/api/session/{id}	GET	Get scan session by ID
Meals & Nutrition
Endpoint	Method	Description
/api/scan/{id}/add-to-meal	POST	Add scan to meal
/api/user/meals	GET	Get meal history
/api/user/meals	POST	Log meal manually
/api/user/meals/{id}	DELETE	Delete a meal
/api/user/daily-aggregates	GET	Get daily nutrition totals
/api/user/meals/today-summary	GET	Get today’s meal summary
User Data
Endpoint	Method	Description
/api/user/profile	GET/POST	Get/update health profile
/api/user/history	GET	Get scan history
/api/user/saved	GET/POST	Manage favorites
/api/user/ai-insights	GET	AI-generated health insights
Add to Meal Example
POST /api/scan/{session_id}/add-to-meal
Authorization: Bearer <token>
Content-Type: application/json

{
  "meal_time": "breakfast",
  "quantity": 2,
  "weight_grams": 150
}
Response:

{
  "success": true,
  "data": {
    "meal_id": 123,
    "meal_item_id": 456,
    "scaled_nutrients": {
      "calories": 156,
      "protein": 2.1,
      "carbs": 41.7,
      "fat": 0.5
    },
    "daily_totals": {
      "day_date": "2024-12-06",
      "totals": {"calories": 1250, "protein": 45},
      "meals_count": 3
    }
  }
}
Daily Aggregates Example
GET /api/user/daily-aggregates?from_date=2024-12-01&to_date=2024-12-07
Authorization: Bearer <token>
Response:

{
  "success": true,
  "data": {
    "from_date": "2024-12-01",
    "to_date": "2024-12-07",
    "aggregates": [
      {"day_date": "2024-12-01", "totals": {...}, "meals_count": 4},
      {"day_date": "2024-12-02", "totals": {...}, "meals_count": 3}
    ]
  }
}
Environment Variables
Variable	Description
DB_HOST	PostgreSQL host
DB_PORT	PostgreSQL port (default: 5432)
DB_NAME	Database name
DB_USER	Database user
DB_PASSWORD	Database password
GROQ_API_KEY	Groq API key for AI features
USDA_API_KEY	USDA API key for nutrition data
Database Migrations
# Apply migrations
psql -U postgres -d nutrifresh -f migrations/001_add_meal_tracking.sql
Notes
Large ML models are excluded from this repo. Use Git LFS for handling them.

Server is fully compatible with Python 3.13+ and FastAPI.


---

If you want, I can also **add badges for build status, license, and GitHub repo stars** so it looks really professional for recruiters or open-source viewers.  

Do you want me to do that next?