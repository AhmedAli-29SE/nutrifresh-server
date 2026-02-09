-- NutriFresh Database Schema
-- Optimized for Personalization and Scalability

-- ==========================================
-- 1. Users & Authentication
-- ==========================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    profile_image_url VARCHAR(500),
    is_onboarding_completed BOOLEAN DEFAULT FALSE,
    guides_seen JSONB DEFAULT '[]', -- List of guide IDs seen by user
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 2. Health Profile (Multi-step Assessment)
-- ==========================================

CREATE TABLE IF NOT EXISTS user_health_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    
    -- 1. Personal Health
    age INTEGER,
    gender VARCHAR(50), -- Male, Female, Other
    height_cm DECIMAL(5,2),
    weight_kg DECIMAL(5,2),
    
    -- 2. Medical Conditions
    has_diabetes BOOLEAN DEFAULT FALSE,
    has_blood_pressure_issues BOOLEAN DEFAULT FALSE,
    has_heart_issues BOOLEAN DEFAULT FALSE,
    has_gut_issues BOOLEAN DEFAULT FALSE,
    other_chronic_diseases TEXT, -- Comma separated or description
    
    -- 3. Allergies (Stored as JSONB for flexibility with lists)
    -- Structure: { "foods": ["peanuts", "shellfish"], "ingredients": ["gluten"], "intolerances": ["lactose"] }
    allergies JSONB DEFAULT '{}',
    
    -- 4. Lifestyle
    is_smoker BOOLEAN DEFAULT FALSE,
    is_drinker BOOLEAN DEFAULT FALSE,
    drinking_frequency VARCHAR(50), -- None, Occasional, Regular, Frequent
    activity_level VARCHAR(50), -- None, Light, Moderate, Intense
    sleep_quality VARCHAR(50), -- Poor, Fair, Good, Excellent
    daily_water_intake_liters DECIMAL(3,1),
    
    -- 5. Eating Habits (JSONB)
    -- Structure: { "frequent_foods": [], "avoided_foods": [], "favorite_foods": [], "junk_food_frequency": "", "sugar_intake": "", "carb_intake": "" }
    eating_habits JSONB DEFAULT '{}',
    
    -- 6. Goals (JSONB)
    -- Structure: { "weight_goal": "loss/gain/maintain", "energy_improvement": true, "muscle_building": true, "digestive_health": true, "sugar_control": true }
    goals JSONB DEFAULT '{}',
    
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 3. Food Analysis & Scan History
-- ==========================================

CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    
    -- Detection Results
    food_name VARCHAR(255),
    category VARCHAR(100), -- Fruit, Vegetable, etc.
    
    -- Analysis Data (JSONB for rich structure)
    freshness JSONB, -- { "status": "Fresh", "confidence": 0.95, "percentage": 95 }
    nutrition JSONB, -- { "calories": 52, "protein": 0.3, ... }
    
    -- AI Generated Content
    storage_recommendations JSONB, -- List of recommendations
    consumption_recommendations JSONB, -- { "should_eat": true, "amount": "1 medium", "frequency": "daily", "warnings": [], "alternatives": [] }
    health_risk_factors JSONB, -- List of health risk factors
    
    image_url VARCHAR(500),
    status VARCHAR(50) DEFAULT 'completed',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scan_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE CASCADE,
    
    food_name VARCHAR(255),
    category VARCHAR(100),
    freshness_score INTEGER, -- 0-100
    image_url VARCHAR(500),
    
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 4. Meals & Nutrition Logs
-- ==========================================

CREATE TABLE IF NOT EXISTS meals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    
    meal_type VARCHAR(50), -- breakfast, lunch, dinner, snack
    food_name VARCHAR(255),
    
    -- Detailed Nutrition for this specific entry
    calories INTEGER,
    protein_g DECIMAL(5,1),
    carbs_g DECIMAL(5,1),
    fat_g DECIMAL(5,1),
    fiber_g DECIMAL(5,1),
    sugar_g DECIMAL(5,1),
    saturated_fat_g DECIMAL(5,1) DEFAULT 0, -- Saturated fat for heart health tracking
    sodium_mg DECIMAL(8,2) DEFAULT 0, -- Sodium for heart health tracking
    
    serving_size VARCHAR(100),
    quantity DECIMAL(4,2) DEFAULT 1.0,
    
    image_url VARCHAR(500), -- Optional, if added from scan
    source VARCHAR(50) DEFAULT 'manual', -- manual, scan, quick_add
    
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 5. AI Insights & Recommendations
-- ==========================================

CREATE TABLE IF NOT EXISTS ai_health_insights (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    
    insight_type VARCHAR(50), -- daily_advice, weekly_tip, nutritional_warning, goal_progress
    title VARCHAR(255),
    content TEXT,
    
    is_read BOOLEAN DEFAULT FALSE,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- saved_items table is defined below in section 10 with full features

-- ==========================================
-- 6. Indexes for Performance
-- ==========================================

CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, logged_at);
CREATE INDEX IF NOT EXISTS idx_scan_history_user_date ON scan_history(user_id, analyzed_at);
CREATE INDEX IF NOT EXISTS idx_ai_insights_user_date ON ai_health_insights(user_id, generated_at);

-- ==========================================
-- 7. Meal Items (Link scans to meals with nutrient snapshot)
-- ==========================================

CREATE TABLE IF NOT EXISTS meal_items (
    id SERIAL PRIMARY KEY,
    meal_id INTEGER REFERENCES meals(id) ON DELETE CASCADE,
    scan_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE SET NULL,
    item_name VARCHAR(255),        -- For manual items or AI recommendations lacking a scan_id
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    quantity DECIMAL(6,2) DEFAULT 1.0,        -- servings/pieces
    weight_grams DECIMAL(8,2) DEFAULT 100.0,  -- grams per serving
    nutrients_snapshot JSONB,                  -- computed: {calories, protein, carbs, fat, ...}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_meal_items_meal_id ON meal_items(meal_id);
CREATE INDEX IF NOT EXISTS idx_meal_items_user_id ON meal_items(user_id);
CREATE INDEX IF NOT EXISTS idx_meal_items_scan_id ON meal_items(scan_id);

-- ==========================================
-- 8. Daily Nutrition Aggregates (Pre-computed for charts)
-- ==========================================

CREATE TABLE IF NOT EXISTS daily_nutrition_aggregates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    day_date DATE NOT NULL,
    totals JSONB DEFAULT '{}',  -- {calories: 0, protein: 0, carbs: 0, fat: 0, ...}
    meals_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, day_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_aggregates_user_day ON daily_nutrition_aggregates(user_id, day_date);
CREATE INDEX IF NOT EXISTS idx_daily_aggregates_date ON daily_nutrition_aggregates(day_date DESC);

-- ==========================================
-- 9. User Nutrition Goals (AI-Generated Personalized Targets)
-- ==========================================

CREATE TABLE IF NOT EXISTS user_nutrition_goals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    
    -- Daily targets (base values from AI)
    daily_calories INTEGER,
    daily_protein INTEGER,
    daily_carbs INTEGER,
    daily_fat INTEGER,
    daily_fiber INTEGER,
    daily_sugar INTEGER,
    daily_saturated_fat INTEGER,
    
    -- Weekly targets (daily × 7)
    weekly_calories INTEGER,
    weekly_protein INTEGER,
    weekly_carbs INTEGER,
    weekly_fat INTEGER,
    weekly_fiber INTEGER,
    weekly_sugar INTEGER,
    weekly_saturated_fat INTEGER,
    
    -- Monthly targets (daily × 30)
    monthly_calories INTEGER,
    monthly_protein INTEGER,
    monthly_carbs INTEGER,
    monthly_fat INTEGER,
    monthly_fiber INTEGER,
    monthly_sugar INTEGER,
    monthly_saturated_fat INTEGER,
    
    -- Yearly targets (daily × 365)
    yearly_calories INTEGER,
    yearly_protein INTEGER,
    yearly_carbs INTEGER,
    yearly_fat INTEGER,
    yearly_fiber INTEGER,
    yearly_sugar INTEGER,
    yearly_saturated_fat INTEGER,
    
    reasoning TEXT,
    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nutrition_goals_user_date ON user_nutrition_goals(user_id, effective_from DESC);

-- ==========================================
-- 10. Saved Items (User's saved foods with consumed/warning states)
-- ==========================================

CREATE TABLE IF NOT EXISTS saved_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE CASCADE,
    
    -- State tracking
    is_consumed BOOLEAN DEFAULT FALSE,
    consumed_at TIMESTAMP,
    is_risky BOOLEAN DEFAULT FALSE,         -- Health risk for user
    health_warning TEXT,                     -- AI-generated warning message
    
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(user_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_items_user ON saved_items(user_id, is_consumed);

-- ==========================================
-- 11. Additional columns for enhanced tracking
-- ==========================================

-- Add to sessions table (run via migration if table exists)
-- ALTER TABLE sessions ADD COLUMN IF NOT EXISTS add_to_meal BOOLEAN DEFAULT FALSE;
-- ALTER TABLE sessions ADD COLUMN IF NOT EXISTS raw_response JSONB;

-- Add to meals table (run via migration if table exists)
-- ALTER TABLE meals ADD COLUMN IF NOT EXISTS scan_id VARCHAR(255);
-- ALTER TABLE meals ADD COLUMN IF NOT EXISTS weight_grams DECIMAL(8,2);
-- ALTER TABLE meals ADD COLUMN IF NOT EXISTS nutrients_snapshot JSONB;

-- Add consumed/health tracking to saved_items (run if table already exists)
ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS is_consumed BOOLEAN DEFAULT FALSE;
ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMP;
ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS is_risky BOOLEAN DEFAULT FALSE;
ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS health_warning TEXT;

-- Add saturated fat and sodium to meals table (migration)
ALTER TABLE meals ADD COLUMN IF NOT EXISTS saturated_fat_g DECIMAL(5,1) DEFAULT 0;
ALTER TABLE meals ADD COLUMN IF NOT EXISTS sodium_mg DECIMAL(8,2) DEFAULT 0;
