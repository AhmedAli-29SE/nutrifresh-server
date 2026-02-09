NutriFresh API Server

Backend server for an AI based food freshness and nutrition detection system.
Built using FastAPI, PostgreSQL, and deep learning models to analyze food images and track nutritional intake.

This repository contains only the backend (server) code developed as part of the Final Year Project.

Tech Stack

Python (FastAPI)

PostgreSQL

Deep Learning (CNN based image models)

JWT Authentication

USDA FoodData Central API

Groq API for AI powered insights

Project Features

User authentication (signup, login)

Food image analysis for freshness and type detection

Nutrition calculation and scaling based on portion size

Meal logging and history tracking

Daily nutrition aggregates

AI generated health insights

RESTful API design

Quick Start
1. Install dependencies
pip install -r requirements.txt

2. Database setup

Create a PostgreSQL database manually (for example nutrifresh), then run:

psql -U postgres -d nutrifresh -f schema.sql

3. Environment variables

Create a .env file in the server root and add:

DB_HOST=localhost
DB_PORT=5432
DB_NAME=nutrifresh
DB_USER=postgres
DB_PASSWORD=your_password

GROQ_API_KEY=your_groq_api_key
USDA_API_KEY=your_usda_api_key

4. Run the server
python main.py


The API will start on the configured host and port.

ML Models

Due to GitHub file size limits, trained machine learning model files are not included in this repository.

Required models:

Food freshness detection model (.h5)

Fruit detection model (.bin or .safetensors)

To enable inference locally:

Download the trained models from the provided external source (Google Drive or similar)

Place them inside:

server/models/models/


Ensure the filenames match those expected in the code

The exclusion of model files is intentional and does not affect backend code evaluation.

API Endpoints
Authentication
Endpoint	Method	Description
/api/auth/signup	POST	Register a new user
/api/auth/login	POST	Login and receive JWT token
Food Analysis
Endpoint	Method	Description
/api/analyze-food	POST	Analyze uploaded food image
/api/session/{id}	GET	Retrieve scan session details
Meals and Nutrition
Endpoint	Method	Description
/api/scan/{id}/add-to-meal	POST	Add scan result to meal
/api/user/meals	GET	Get user meal history
/api/user/meals	POST	Log a meal manually
/api/user/meals/{id}	DELETE	Delete a meal
/api/user/daily-aggregates	GET	Daily nutrition totals
/api/user/meals/today-summary	GET	Today’s nutrition summary
User Data
Endpoint	Method	Description
/api/user/profile	GET / POST	Get or update health profile
/api/user/history	GET	Get food scan history
/api/user/saved	GET / POST	Manage favorite foods
/api/user/ai-insights	GET	AI generated health insights
Add to Meal Example
Request
POST /api/scan/{session_id}/add-to-meal
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json

{
  "meal_time": "breakfast",
  "quantity": 2,
  "weight_grams": 150
}

Response
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
      "totals": {
        "calories": 1250,
        "protein": 45
      },
      "meals_count": 3
    }
  }
}

Daily Aggregates Example
GET /api/user/daily-aggregates?from_date=2024-12-01&to_date=2024-12-07
Authorization: Bearer <JWT_TOKEN>

Notes for Evaluation

This repository contains backend code only

Frontend and model training are handled separately

Large model files are intentionally excluded

Focus is on API design, data flow, and AI integration