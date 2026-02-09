"""
Database service for PostgreSQL integration.
Provides async database operations for users, sessions, and scan history.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import asyncpg
import os
import json
from dotenv import load_dotenv

load_dotenv()

class DatabaseService:
    """Service for PostgreSQL database operations"""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        # Connection parameters - using postgres user with the provided password
        self._db_host = os.getenv("DB_HOST", "localhost")
        self._db_port = int(os.getenv("DB_PORT", "5432"))
        self._db_name = os.getenv("DB_NAME", "nutrifresh")
        self._db_user = os.getenv("DB_USER", "postgres")
        self._db_password = os.getenv("DB_PASSWORD", "")
    
    async def _init_connection(self, conn):
        """Initialize database connection with JSONB codec"""
        await conn.set_type_codec(
            'jsonb',
            encoder=json.dumps,
            decoder=json.loads,
            schema='pg_catalog'
        )

    async def connect(self):
        """Create database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(
                host=self._db_host,
                port=self._db_port,
                database=self._db_name,
                user=self._db_user,
                password=self._db_password,
                min_size=5,      # Increased for concurrent requests
                max_size=25,     # Increased to handle multiple devices
                command_timeout=120,  # Increased timeout for complex queries
                init=self._init_connection
            )
            print("[OK] PostgreSQL connection pool created")
            await self._ensure_tables()
        except Exception as e:
            print(f"✗ Failed to connect to PostgreSQL: {e}")
            print("  CRITICAL: Database connection required. Server cannot start without database.")
            raise e
    
    async def disconnect(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            print("[OK] PostgreSQL connection pool closed")
    
    async def _ensure_tables(self):
        """Create database tables from schema.sql"""
        if not self.pool:
            return
        
        try:
            # Read schema.sql
            schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
            with open(schema_path, "r") as f:
                schema_sql = f.read()
            
            async with self.pool.acquire() as conn:
                # Split by statements (simple split by ;)
                # Note: This is a simple implementation. For complex schemas with functions/triggers, 
                # a more robust parser might be needed, but this works for standard CREATE TABLE.
                # However, asyncpg execute can handle multiple statements if they are simple.
                # Let's try executing the whole block.
                await conn.execute(schema_sql)
                
            print("[OK] Database schema applied successfully")
        except Exception as e:
            print(f"✗ Failed to apply database schema: {e}")
            
        # Run migrations for existing tables
        await self._run_migrations()

    async def _run_migrations(self):
        """Run specific migrations for schema updates"""
        if not self.pool:
            return

        async with self.pool.acquire() as conn:
            try:
                # 1. Add guides_seen to users if missing
                # Check if column exists
                row = await conn.fetchrow("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='users' AND column_name='guides_seen'
                """)
                if not row:
                    print("  Migrating: Adding guides_seen to users table...")
                    await conn.execute("ALTER TABLE users ADD COLUMN guides_seen JSONB DEFAULT '[]'")
                    print("  [OK] Added guides_seen column")

                # 2. Add health_risk_factors to sessions if missing (just in case)
                row = await conn.fetchrow("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='sessions' AND column_name='health_risk_factors'
                """)
                if not row:
                    print("  Migrating: Adding health_risk_factors to sessions table...")
                    await conn.execute("ALTER TABLE sessions ADD COLUMN health_risk_factors JSONB")
                    print("  [OK] Added health_risk_factors column")

            except Exception as e:
                print(f"✗ Migration failed: {e}")

            try:
                # 3. Add item_name to meal_items if missing
                row = await conn.fetchrow("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='meal_items' AND column_name='item_name'
                """)
                if not row:
                    print("  Migrating: Adding item_name to meal_items table...")
                    await conn.execute("ALTER TABLE meal_items ADD COLUMN item_name VARCHAR(255)")
                    print("  [OK] Added item_name column")
            except Exception as e:
                print(f"✗ Migration for meal_items failed: {e}")
            
            try:
                # 4. Add consumed/risky tracking to saved_items if missing
                row = await conn.fetchrow("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='saved_items' AND column_name='is_consumed'
                """)
                if not row:
                    print("  Migrating: Adding consumed/risky columns to saved_items...")
                    await conn.execute("ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS is_consumed BOOLEAN DEFAULT FALSE")
                    await conn.execute("ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS consumed_at TIMESTAMP")
                    await conn.execute("ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS is_risky BOOLEAN DEFAULT FALSE")
                    await conn.execute("ALTER TABLE saved_items ADD COLUMN IF NOT EXISTS health_warning TEXT")
                    print("  [OK] Added consumed/risky columns to saved_items")
            except Exception as e:
                print(f"✗ Migration for saved_items failed: {e}")

            try:
                # 5. Add micros JSONB column to meals if missing
                row = await conn.fetchrow("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='meals' AND column_name='micros'
                """)
                if not row:
                    print("  Migrating: Adding micros column to meals table...")
                    await conn.execute("ALTER TABLE meals ADD COLUMN micros JSONB DEFAULT '{}'::jsonb")
                    print("  [OK] Added micros column to meals")
            except Exception as e:
                print(f"✗ Migration for meals failed: {e}")
            
    # User Health Profile Operations
    async def create_health_profile(self, user_id: int, profile_data: Dict[str, Any]) -> bool:
        """Create or update user health profile"""
        if not self.pool:
            return False
        
        # Helper functions to sanitize data types
        def safe_int(val, default=None):
            """Convert to int, return None for empty/invalid values"""
            if val is None or val == '':
                return default
            try:
                return int(val)
            except (ValueError, TypeError):
                return default
        
        def safe_float(val, default=None):
            """Convert to float, return None for empty/invalid values"""
            if val is None or val == '':
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        
        def safe_str(val, default=None):
            """Convert to string, return None for empty values"""
            if val is None or val == '':
                return default
            return str(val)
        
        def safe_bool(val, default=False):
            """Convert to bool safely"""
            if val is None:
                return default
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() in ('true', '1', 'yes')
            return bool(val)
            
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO user_health_profiles (
                        user_id, age, gender, height_cm, weight_kg,
                        has_diabetes, has_blood_pressure_issues, has_heart_issues, has_gut_issues, other_chronic_diseases,
                        allergies,
                        is_smoker, is_drinker, drinking_frequency, activity_level, sleep_quality, daily_water_intake_liters,
                        eating_habits, goals, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9, $10,
                        $11,
                        $12, $13, $14, $15, $16, $17,
                        $18, $19, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (user_id) DO UPDATE SET
                        age = COALESCE(EXCLUDED.age, user_health_profiles.age),
                        gender = COALESCE(EXCLUDED.gender, user_health_profiles.gender),
                        height_cm = COALESCE(EXCLUDED.height_cm, user_health_profiles.height_cm),
                        weight_kg = COALESCE(EXCLUDED.weight_kg, user_health_profiles.weight_kg),
                        has_diabetes = EXCLUDED.has_diabetes,
                        has_blood_pressure_issues = EXCLUDED.has_blood_pressure_issues,
                        has_heart_issues = EXCLUDED.has_heart_issues,
                        has_gut_issues = EXCLUDED.has_gut_issues,
                        other_chronic_diseases = COALESCE(EXCLUDED.other_chronic_diseases, user_health_profiles.other_chronic_diseases),
                        allergies = EXCLUDED.allergies,
                        is_smoker = EXCLUDED.is_smoker,
                        is_drinker = EXCLUDED.is_drinker,
                        drinking_frequency = COALESCE(EXCLUDED.drinking_frequency, user_health_profiles.drinking_frequency),
                        activity_level = COALESCE(EXCLUDED.activity_level, user_health_profiles.activity_level),
                        sleep_quality = COALESCE(EXCLUDED.sleep_quality, user_health_profiles.sleep_quality),
                        daily_water_intake_liters = COALESCE(EXCLUDED.daily_water_intake_liters, user_health_profiles.daily_water_intake_liters),
                        eating_habits = EXCLUDED.eating_habits,
                        goals = EXCLUDED.goals,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    user_id,
                    safe_int(profile_data.get("age")),
                    safe_str(profile_data.get("gender")),
                    safe_float(profile_data.get("height_cm") or profile_data.get("height")),
                    safe_float(profile_data.get("weight_kg") or profile_data.get("weight")),
                    safe_bool(profile_data.get("has_diabetes"), False),
                    safe_bool(profile_data.get("has_blood_pressure_issues"), False),
                    safe_bool(profile_data.get("has_heart_issues"), False),
                    safe_bool(profile_data.get("has_gut_issues"), False),
                    safe_str(profile_data.get("other_chronic_diseases")),
                    profile_data.get("allergies") if isinstance(profile_data.get("allergies"), dict) else {},
                    safe_bool(profile_data.get("is_smoker"), False),
                    safe_bool(profile_data.get("is_drinker"), False),
                    safe_str(profile_data.get("drinking_frequency")),
                    safe_str(profile_data.get("activity_level")),
                    safe_str(profile_data.get("sleep_quality")),
                    safe_float(profile_data.get("daily_water_intake_liters")),
                    profile_data.get("eating_habits") if isinstance(profile_data.get("eating_habits"), dict) else {},
                    profile_data.get("goals") if isinstance(profile_data.get("goals"), dict) else {}
                )
                
                # After successful profile save, generate and store personalized nutrition goals
                try:
                    # Get the full profile for AI analysis
                    full_profile = await self.get_health_profile(user_id)
                    if full_profile:
                        from gpt_model.gptapi import generate_personalized_nutrition_goals
                        print(f"[GOALS] Generating personalized nutrition goals for user {user_id}...")
                        daily_goals = generate_personalized_nutrition_goals(full_profile)
                        await self.save_user_nutrition_goals(user_id, daily_goals)
                        print(f"[GOALS] Successfully generated and saved goals for user {user_id}")
                except Exception as goals_err:
                    # Don't fail profile save if goals generation fails
                    print(f"[GOALS] Warning: Could not generate goals: {goals_err}")
                
                return True
            except Exception as e:
                print(f"Error saving health profile: {e}")
                import traceback
                traceback.print_exc()
                return False

    async def get_health_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user health profile"""
        if not self.pool:
            return None
            
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM user_health_profiles WHERE user_id = $1
            """, user_id)
            
            if not row:
                return None
                
            return dict(row)
    
    # User Nutrition Goals Operations (AI-Generated Personalized Targets)
    async def save_user_nutrition_goals(self, user_id: int, daily_goals: Dict[str, Any]) -> int:
        """
        Save AI-generated nutrition goals for a user.
        Creates a new version with effective_from = today.
        Calculates weekly/monthly/yearly from daily values.
        """
        if not self.pool:
            raise RuntimeError("Database not connected")
        
        # Extract daily values
        daily = {
            "calories": int(daily_goals.get("calories", 2000)),
            "protein": int(daily_goals.get("protein", 50)),
            "carbs": int(daily_goals.get("carbs", 275)),
            "fat": int(daily_goals.get("fat", 65)),
            "fiber": int(daily_goals.get("fiber", 28)),
            "sugar": int(daily_goals.get("sugar", 50)),
            "saturated_fat": int(daily_goals.get("saturated_fat", 20))
        }
        
        # Calculate other timeframes
        weekly = {k: v * 7 for k, v in daily.items()}
        monthly = {k: v * 30 for k, v in daily.items()}
        yearly = {k: v * 365 for k, v in daily.items()}
        
        reasoning = str(daily_goals.get("reasoning", "AI-generated based on profile"))
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO user_nutrition_goals (
                    user_id,
                    daily_calories, daily_protein, daily_carbs, daily_fat, daily_fiber, daily_sugar, daily_saturated_fat,
                    weekly_calories, weekly_protein, weekly_carbs, weekly_fat, weekly_fiber, weekly_sugar, weekly_saturated_fat,
                    monthly_calories, monthly_protein, monthly_carbs, monthly_fat, monthly_fiber, monthly_sugar, monthly_saturated_fat,
                    yearly_calories, yearly_protein, yearly_carbs, yearly_fat, yearly_fiber, yearly_sugar, yearly_saturated_fat,
                    reasoning, effective_from
                ) VALUES (
                    $1,
                    $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13, $14, $15,
                    $16, $17, $18, $19, $20, $21, $22,
                    $23, $24, $25, $26, $27, $28, $29,
                    $30, CURRENT_DATE
                )
                RETURNING id
            """,
                user_id,
                daily["calories"], daily["protein"], daily["carbs"], daily["fat"], daily["fiber"], daily["sugar"], daily["saturated_fat"],
                weekly["calories"], weekly["protein"], weekly["carbs"], weekly["fat"], weekly["fiber"], weekly["sugar"], weekly["saturated_fat"],
                monthly["calories"], monthly["protein"], monthly["carbs"], monthly["fat"], monthly["fiber"], monthly["sugar"], monthly["saturated_fat"],
                yearly["calories"], yearly["protein"], yearly["carbs"], yearly["fat"], yearly["fiber"], yearly["sugar"], yearly["saturated_fat"],
                reasoning
            )
            print(f"[GOALS] Saved nutrition goals for user {user_id}, id={row['id']}")
            return row["id"]
    
    async def get_user_nutrition_goals(self, user_id: int, for_date=None, period: str = "daily") -> Optional[Dict[str, Any]]:
        """
        Get nutrition goals that were active on a specific date.
        Returns goals where effective_from <= for_date (most recent).
        
        Args:
            user_id: User ID
            for_date: Date to get goals for (default: today)
            period: 'daily', 'weekly', 'monthly', or 'yearly'
        """
        if not self.pool:
            return None
        
        from datetime import date as date_type
        if for_date is None:
            for_date = date_type.today()
        elif isinstance(for_date, str):
            for_date = date_type.fromisoformat(for_date)
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM user_nutrition_goals
                WHERE user_id = $1 AND effective_from <= $2
                ORDER BY effective_from DESC
                LIMIT 1
            """, user_id, for_date)
            
            if not row:
                return None
            
            # Build response based on requested period
            prefix = period.lower() if period.lower() in ("daily", "weekly", "monthly", "yearly") else "daily"
            
            return {
                "calories": row[f"{prefix}_calories"],
                "protein": row[f"{prefix}_protein"],
                "carbs": row[f"{prefix}_carbs"],
                "fat": row[f"{prefix}_fat"],
                "fiber": row[f"{prefix}_fiber"],
                "sugar": row[f"{prefix}_sugar"],
                "saturated_fat": row[f"{prefix}_saturated_fat"],
                "period": prefix,
                "effective_from": str(row["effective_from"]),
                "reasoning": row["reasoning"]
            }
    
    async def get_all_nutrition_goals(self, user_id: int, for_date=None) -> Optional[Dict[str, Any]]:
        """Get all timeframe goals (daily, weekly, monthly, yearly) for a date."""
        if not self.pool:
            return None
        
        from datetime import date as date_type
        if for_date is None:
            for_date = date_type.today()
        elif isinstance(for_date, str):
            for_date = date_type.fromisoformat(for_date)
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM user_nutrition_goals
                WHERE user_id = $1 AND effective_from <= $2
                ORDER BY effective_from DESC
                LIMIT 1
            """, user_id, for_date)
            
            if not row:
                return None
            
            return {
                "daily": {
                    "calories": row["daily_calories"], "protein": row["daily_protein"],
                    "carbs": row["daily_carbs"], "fat": row["daily_fat"],
                    "fiber": row["daily_fiber"], "sugar": row["daily_sugar"],
                    "saturated_fat": row["daily_saturated_fat"]
                },
                "weekly": {
                    "calories": row["weekly_calories"], "protein": row["weekly_protein"],
                    "carbs": row["weekly_carbs"], "fat": row["weekly_fat"],
                    "fiber": row["weekly_fiber"], "sugar": row["weekly_sugar"],
                    "saturated_fat": row["weekly_saturated_fat"]
                },
                "monthly": {
                    "calories": row["monthly_calories"], "protein": row["monthly_protein"],
                    "carbs": row["monthly_carbs"], "fat": row["monthly_fat"],
                    "fiber": row["monthly_fiber"], "sugar": row["monthly_sugar"],
                    "saturated_fat": row["monthly_saturated_fat"]
                },
                "yearly": {
                    "calories": row["yearly_calories"], "protein": row["yearly_protein"],
                    "carbs": row["yearly_carbs"], "fat": row["yearly_fat"],
                    "fiber": row["yearly_fiber"], "sugar": row["yearly_sugar"],
                    "saturated_fat": row["yearly_saturated_fat"]
                },
                "effective_from": str(row["effective_from"]),
                "reasoning": row["reasoning"]
            }
    
    # User operations
    async def create_user(self, user_data: Dict[str, Any]) -> int:
        """Create a new user and return user ID"""
        if not self.pool:
            raise RuntimeError("Database not connected")
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO users (email, password_hash, first_name, last_name)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, 
                user_data["email"],
                user_data["password_hash"],
                user_data["first_name"],
                user_data["last_name"]
            )
            return row["id"]
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        if not self.pool:
            return None
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, email, password_hash, first_name, last_name, created_at
                FROM users WHERE email = $1
            """, email.lower())
            
            if not row:
                return None
            
            return {
                "user_id": row["id"],
                "id": row["id"],
                "email": row["email"],
                "password_hash": row["password_hash"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            }
    
    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        if not self.pool:
            return None
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, email, password_hash, first_name, last_name, created_at
                FROM users WHERE id = $1
            """, user_id)
            
            if not row:
                return None
            
            return {
                "user_id": row["id"],
                "id": row["id"],
                "email": row["email"],
                "password_hash": row["password_hash"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            }

    async def mark_guide_seen(self, user_id: int, guide_id: str) -> bool:
        """Mark a user guide as seen by the user"""
        if not self.pool:
            return False
            
        async with self.pool.acquire() as conn:
            # Append guide_id to guides_seen list if not already present
            # We use jsonb_set to append, but first need to ensure it's an array
            # A simpler way with PG JSONB is to use || operator but we need to ensure distinctness
            # Let's read, modify, update for safety or use a smart query
            
            try:
                # Using a query that appends if not exists
                await conn.execute("""
                    UPDATE users
                    SET guides_seen = (
                        CASE 
                            WHEN guides_seen IS NULL THEN '[]'::jsonb
                            WHEN guides_seen @> jsonb_build_array($2::text) THEN guides_seen
                            ELSE guides_seen || jsonb_build_array($2::text)
                        END
                    )
                    WHERE id = $1
                """, user_id, guide_id)
                return True
            except Exception as e:
                print(f"Error marking guide seen: {e}")
                return False

    async def get_seen_guides(self, user_id: int) -> List[str]:
        """Get list of guides seen by user"""
        if not self.pool:
            return []
            
        async with self.pool.acquire() as conn:
            val = await conn.fetchval("SELECT guides_seen FROM users WHERE id = $1", user_id)
            if val:
                return json.loads(val) if isinstance(val, str) else val
            return []
    
    async def update_user_profile(self, user_id: int, profile_data: Dict[str, Any]) -> bool:
        """Update user health profile - delegates to create_health_profile"""
        # Profile data is stored in user_health_profiles table, not users table
        return await self.create_health_profile(user_id, profile_data)
    
    async def update_user_basic_info(self, user_id: int, first_name: str = None, last_name: str = None) -> bool:
        """Update user's basic info (first_name, last_name) in users table"""
        if not self.pool:
            return False
        
        try:
            updates = []
            values = []
            idx = 1
            
            if first_name is not None:
                updates.append(f"first_name = ${idx}")
                values.append(first_name)
                idx += 1
            
            if last_name is not None:
                updates.append(f"last_name = ${idx}")
                values.append(last_name)
                idx += 1
            
            if not updates:
                return True  # Nothing to update
            
            values.append(user_id)
            query = f"UPDATE users SET {', '.join(updates)} WHERE id = ${idx}"
            
            async with self.pool.acquire() as conn:
                await conn.execute(query, *values)
            return True
        except Exception as e:
            print(f"Error updating user basic info: {e}")
            return False
    
    async def update_user_password(self, user_id: int, password_hash: str) -> bool:
        """Update user's password hash"""
        if not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET password_hash = $1 WHERE id = $2",
                    password_hash, user_id
                )
            return True
        except Exception as e:
            print(f"Error updating user password: {e}")
            return False
    
    async def delete_user(self, user_id: int) -> bool:
        """Delete user and all associated data"""
        if not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                # Delete in order due to foreign key constraints
                await conn.execute("DELETE FROM meal_items WHERE meal_id IN (SELECT id FROM meals WHERE user_id = $1)", user_id)
                await conn.execute("DELETE FROM meals WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM scan_history WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM saved_foods WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM user_nutrition_goals WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM user_health_profiles WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            return True
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False
    
    # Session operations
    async def save_session(self, session_id: str, data: Dict[str, Any]) -> None:
        """Save session data to database"""
        if not self.pool:
            return
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO sessions (
                        session_id, user_id, food_name, category, freshness, nutrition,
                        storage_recommendations, consumption_recommendations, health_risk_factors, image_url, status, timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (session_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        food_name = EXCLUDED.food_name,
                        category = EXCLUDED.category,
                        freshness = EXCLUDED.freshness,
                        nutrition = EXCLUDED.nutrition,
                        storage_recommendations = EXCLUDED.storage_recommendations,
                        consumption_recommendations = EXCLUDED.consumption_recommendations,
                        health_risk_factors = EXCLUDED.health_risk_factors,
                        image_url = EXCLUDED.image_url,
                        status = EXCLUDED.status,
                        timestamp = EXCLUDED.timestamp
                """,
                    session_id,
                    data.get("user_id"),
                    data.get("food_name"),
                    data.get("category"),
                    data.get("freshness", {}),
                    data.get("nutrition", []),
                    data.get("storage_recommendations", []),
                    data.get("consumption_recommendations"),
                    data.get("health_risk_factors", []),
                    data.get("image_url"),
                    data.get("status", "completed"),
                    datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
                )
                
                # Also save to scan history if user_id is present
                if data.get("user_id"):
                    freshness_data = data.get("freshness", {})
                    freshness_score = freshness_data.get("percentage", 0) if isinstance(freshness_data, dict) else 0
                    
                    await conn.execute("""
                        INSERT INTO scan_history (user_id, session_id, food_name, category, freshness_score, image_url, analyzed_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT DO NOTHING
                    """,
                        data.get("user_id"),
                        session_id,
                        data.get("food_name"),
                        data.get("category"),
                        freshness_score,
                        data.get("image_url"),
                        datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
                    )
        except Exception as e:
            print(f"Error saving session to database: {e}")
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        if not self.pool:
            return None
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM sessions WHERE session_id = $1
            """, session_id)
            
            if not row:
                return None
            
            return {
                "session_id": row["session_id"],
                "user_id": row["user_id"],
                "food_name": row["food_name"],
                "category": row["category"],
                "freshness": row["freshness"] or {},
                "nutrition": row["nutrition"] or [],
                "storage_recommendations": row["storage_recommendations"] or [],
                "consumption_recommendations": row["consumption_recommendations"] or {},
                "health_risk_factors": row["health_risk_factors"] or [],
                "image_url": row["image_url"],
                "status": row["status"],
                "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None
            }
    
    async def get_user_scan_history(self, user_id: int, limit: int = 10, offset: int = 0, since: str = None) -> Dict[str, Any]:
        """Get user's scan history with full original details from sessions table
        
        Args:
            user_id: User ID
            limit: Max items to return
            offset: Pagination offset
            since: ISO datetime string - return only items created after this time
        """
        if not self.pool:
            return {"foods": [], "total": 0}
        
        async with self.pool.acquire() as conn:
            # Build WHERE clause with optional since filter
            where_clause = "WHERE s.user_id = $1"
            params = [user_id]
            
            if since:
                try:
                    from datetime import datetime
                    since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
                    where_clause += " AND s.created_at > $4"
                    params.append(since_dt)
                except ValueError:
                    pass  # Invalid datetime, ignore since filter
            
            # Get total count
            count_query = f"SELECT COUNT(*) as total FROM sessions s {where_clause}"
            total_row = await conn.fetchrow(count_query, *params[:len(params)])
            total = total_row["total"] if total_row else 0
            
            # Get paginated results with FULL session data
            query = f"""
                SELECT 
                    s.session_id,
                    s.food_name,
                    s.category,
                    s.freshness,
                    s.nutrition,
                    s.storage_recommendations,
                    s.consumption_recommendations,
                    s.health_risk_factors,
                    s.image_url,
                    s.status,
                    s.timestamp,
                    s.created_at
                FROM sessions s
                {where_clause}
                ORDER BY s.created_at DESC
                LIMIT $2 OFFSET $3
            """
            rows = await conn.fetch(query, user_id, limit, offset, *params[1:])
            
            foods = []
            for row in rows:
                # Parse freshness data - could be JSONB or stored directly
                freshness_data = row["freshness"]
                if isinstance(freshness_data, str):
                    import json
                    try:
                        freshness_data = json.loads(freshness_data)
                    except:
                        freshness_data = {}
                
                if not freshness_data:
                    freshness_data = {"percentage": 0, "level": "Unknown", "level_normalized": "unknown"}
                
                # Parse nutrition data
                nutrition_data = row["nutrition"]
                if isinstance(nutrition_data, str):
                    import json
                    try:
                        nutrition_data = json.loads(nutrition_data)
                    except:
                        nutrition_data = []
                
                # Parse storage recommendations
                storage_data = row["storage_recommendations"]
                if isinstance(storage_data, str):
                    import json
                    try:
                        storage_data = json.loads(storage_data)
                    except:
                        storage_data = []
                
                # Parse consumption recommendations
                consumption_data = row["consumption_recommendations"]
                if isinstance(consumption_data, str):
                    import json
                    try:
                        consumption_data = json.loads(consumption_data)
                    except:
                        consumption_data = {}
                
                # Parse health risk factors
                health_risks = row["health_risk_factors"]
                if isinstance(health_risks, str):
                    import json
                    try:
                        health_risks = json.loads(health_risks)
                    except:
                        health_risks = []
                
                timestamp = row["created_at"] or row["timestamp"]
                
                foods.append({
                    "session_id": row["session_id"],
                    "food_name": row["food_name"],
                    "category": row["category"],
                    "freshness": freshness_data,
                    "nutrition": nutrition_data or [],
                    "storage_recommendations": storage_data or [],
                    "consumption_recommendations": consumption_data or {},
                    "health_risk_factors": health_risks or [],
                    "image_url": row["image_url"],
                    "thumbnail_url": row["image_url"],
                    "status": row["status"] or "completed",
                    "analyzed_at": timestamp.isoformat() if timestamp else None,
                    "timestamp": timestamp.isoformat() if timestamp else None,
                })
            
            return {
                "foods": foods,
                "total": total
            }
    
    async def get_user_meal_foods(self, user_id: int, limit: int = 30) -> List[str]:
        """Get food names from scans that were specifically added to meals (add_to_meal = TRUE)
        
        Used for meal recommendations to suggest meals based on foods the user has actually 
        added to their meal log, not just scanned.
        """
        if not self.pool:
            return []
        
        async with self.pool.acquire() as conn:
            # Get foods from sessions where add_to_meal is TRUE
            # These are foods the user has explicitly added to their meal tracking
            rows = await conn.fetch("""
                SELECT DISTINCT s.food_name, s.freshness
                FROM sessions s
                WHERE s.user_id = $1 
                  AND s.add_to_meal = TRUE
                  AND s.food_name IS NOT NULL
                  AND s.food_name != ''
                ORDER BY s.food_name
                LIMIT $2
            """, user_id, limit)
            
            food_names = []
            for row in rows:
                food_name = row["food_name"]
                # Parse freshness data to filter out not-fresh items
                freshness_data = row["freshness"]
                if isinstance(freshness_data, str):
                    import json
                    try:
                        freshness_data = json.loads(freshness_data)
                    except:
                        freshness_data = {}
                
                if not freshness_data:
                    freshness_data = {}
                
                # Get freshness status
                freshness_status = freshness_data.get("freshness_status", freshness_data.get("level", "")).lower()
                
                # Include if fresh or medium fresh (exclude "not fresh", "rotten")
                if "not" not in freshness_status and "rotten" not in freshness_status:
                    food_names.append(food_name)
            
            return food_names
    
    # Meals operations
    async def get_user_meals(self, user_id: int, period: str = "today") -> List[Dict[str, Any]]:
        """Get user's meal history for a period"""
        if not self.pool:
            return []
        
        # Calculate date range
        from datetime import datetime, timedelta
        now = datetime.now()
        
        if period == "today" or period == "daily":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week" or period == "weekly":
            start_date = now - timedelta(days=7)
        elif period == "month" or period == "monthly":
            start_date = now - timedelta(days=30)
        elif period == "year" or period == "yearly":
            start_date = now - timedelta(days=365)
        elif period == "all":
            start_date = now - timedelta(days=3650)  # ~10 years
        else:
            start_date = now - timedelta(days=1)
        
        print(f"[DB] get_user_meals: user_id={user_id}, period={period}, start_date={start_date}")
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM meals
                WHERE user_id = $1 AND logged_at >= $2
                ORDER BY logged_at DESC
            """, user_id, start_date)
            
            print(f"[DB] Found {len(rows)} meal rows for user {user_id}")
            
            meals = []
            for row in rows:
                nutrition = {
                        "calories": int(row["calories"] or 0),
                        "protein": float(row["protein_g"] or 0),
                        "carbs": float(row["carbs_g"] or 0),
                        "fat": float(row["fat_g"] or 0),
                        "fiber": float(row["fiber_g"] or 0),
                        "sugar": float(row["sugar_g"] or 0),
                        "saturated_fat": float(row.get("saturated_fat_g") or 0),
                        "sodium": float(row.get("sodium_mg") or 0)
                }
                
                # Merge dynamic micros if available
                micros = row.get("micros")
                if micros and isinstance(micros, str):
                    try:
                        micros = json.loads(micros)
                    except:
                        micros = {}
                
                if micros and isinstance(micros, dict):
                    nutrition.update(micros)

                meals.append({
                    "id": row["id"],
                    "meal_type": row["meal_type"],
                    "food_name": row["food_name"],
                    "nutrition_data": nutrition,
                    "serving_size": row["serving_size"],
                    "quantity": float(row["quantity"] or 1.0),
                    "image_url": row["image_url"],
                    "logged_at": row["logged_at"].isoformat() if row["logged_at"] else None
                })
            
            return meals
    
    async def save_meal(self, meal_data: Dict[str, Any]) -> int:
        """Save a meal log entry"""
        if not self.pool:
            raise RuntimeError("Database not connected")
        
        from datetime import datetime
        
        async with self.pool.acquire() as conn:
            # Handle nutrition data which might come as a dict or individual fields
            nutrition = meal_data.get("nutrition_data", {}) or {}
            
            # Parse logged_at timestamp safely
            logged_at_str = meal_data.get("logged_at", "")
            try:
                if logged_at_str:
                    # Clean up ISO format string
                    clean_str = str(logged_at_str).replace('Z', '').replace('+00:00', '')
                    if '.' in clean_str:
                        clean_str = clean_str.split('.')[0]
                    logged_at = datetime.fromisoformat(clean_str)
                else:
                    logged_at = datetime.now()
            except:
                logged_at = datetime.now()
            
            # Safely get nutrition values with defaults
            def safe_int(val, default=0):
                try:
                    return int(val) if val is not None else default
                except:
                    return default
            
            def safe_float(val, default=0.0):
                try:
                    return float(val) if val is not None else default
                except:
                    return default
            
            # Extract specific micronutrients that are not in main columns
            micros = meal_data.get("micros", {}) or {}
            
            # If micros were passed as top-level keys in nutrition_data, capture them
            for k, v in nutrition.items():
                if k not in ['calories', 'protein', 'protein_g', 'carbs', 'carbs_g', 'fat', 'fat_g', 'fiber', 'fiber_g', 'sugar', 'sugar_g']:
                   # Convert camelCase to snake_case if needed, or just normalize
                   key = k.lower().replace(' ', '_')
                   if key not in micros:
                       micros[key] = safe_float(v)

            row = await conn.fetchrow("""
                INSERT INTO meals (
                    user_id, meal_type, food_name, 
                    calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g,
                    saturated_fat_g, sodium_mg,
                    serving_size, quantity, image_url, source, logged_at, micros
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                RETURNING id
            """,
                meal_data["user_id"],
                meal_data.get("meal_type", "snack"),
                meal_data.get("food_name", "Unknown"),
                safe_int(meal_data.get("calories") or nutrition.get("calories")),
                safe_float(meal_data.get("protein_g") or nutrition.get("protein")),
                safe_float(meal_data.get("carbs_g") or nutrition.get("carbs")),
                safe_float(meal_data.get("fat_g") or nutrition.get("fat")),
                safe_float(meal_data.get("fiber_g") or nutrition.get("fiber")),
                safe_float(meal_data.get("sugar_g") or nutrition.get("sugar")),
                safe_float(meal_data.get("saturated_fat_g") or nutrition.get("saturated_fat", 0)),
                safe_float(meal_data.get("sodium_mg") or nutrition.get("sodium", 0)),
                meal_data.get("serving_size", "1 serving"),
                safe_float(meal_data.get("quantity", 1.0)),
                meal_data.get("image_url"),
                meal_data.get("source", "manual"),
                logged_at,
                json.dumps(micros)
            )
            
            # Save meal items (ingredients) if provided
            items = meal_data.get("items", []) or meal_data.get("ingredients", [])
            if items:
                for item in items:
                    # Item can be a string (name) or dict
                    item_name = item if isinstance(item, str) else item.get("name")
                    # If it's a dict, it might have quantity/weight
                    qty = item.get("quantity", 1.0) if isinstance(item, dict) else 1.0
                    
                    await conn.execute("""
                        INSERT INTO meal_items (meal_id, user_id, item_name, quantity)
                        VALUES ($1, $2, $3, $4)
                    """, row["id"], meal_data["user_id"], item_name[:255] if item_name else "Unknown", float(qty))

            return row["id"]
    
    async def delete_meal(self, meal_id: str, user_id: int) -> bool:
        """Delete a meal log entry"""
        if not self.pool:
            return False
        
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM meals WHERE id = $1 AND user_id = $2
            """, int(meal_id), user_id)
            return "DELETE 1" in result
    
    async def get_meal_summary(self, user_id: int, period: str = "today") -> Dict[str, Any]:
        """Get meal summary for a period"""
        if not self.pool:
            return self._empty_meal_summary()
        
        meals = await self.get_user_meals(user_id, period)
        
        total_calories = 0
        total_protein = 0.0
        total_carbs = 0.0
        total_fat = 0.0
        total_fiber = 0.0
        total_sugar = 0.0
        last_meal_time = None
        
        for meal in meals:
            nutrition = meal.get("nutrition_data", {}) or {}
            total_calories += int(nutrition.get("calories") or 0)
            total_protein += float(nutrition.get("protein") or 0)
            total_carbs += float(nutrition.get("carbs") or 0)
            total_fat += float(nutrition.get("fat") or 0)
            total_fiber += float(nutrition.get("fiber") or 0)
            total_sugar += float(nutrition.get("sugar") or 0)
            
            if meal.get("logged_at") and (last_meal_time is None or meal["logged_at"] > last_meal_time):
                last_meal_time = meal["logged_at"]
        
        return {
            "total_calories": total_calories,
            "total_protein": total_protein,
            "total_carbs": total_carbs,
            "total_fat": total_fat,
            "total_fiber": total_fiber,
            "total_sugar": total_sugar,
            "meals_logged": len(meals),
            "last_meal_time": last_meal_time
        }
    
    def _empty_meal_summary(self) -> Dict[str, Any]:
        return {
            "total_calories": 0,
            "total_protein": 0.0,
            "total_carbs": 0.0,
            "total_fat": 0.0,
            "total_fiber": 0.0,
            "total_sugar": 0.0,
            "meals_logged": 0,
            "last_meal_time": None
        }
    
    async def get_daily_nutrition(self, user_id: int) -> Dict[str, Any]:
        """Get daily nutrition analysis"""
        summary = await self.get_meal_summary(user_id, "today")
        
        # Default daily goals
        daily_goal = {
            "calories": 2000,
            "protein": 60.0,
            "carbs": 300.0,
            "fat": 65.0
        }
        
        consumed = {
            "calories": summary["total_calories"],
            "protein": summary["total_protein"],
            "carbs": summary["total_carbs"],
            "fat": summary["total_fat"]
        }
        
        remaining = {
            "calories": max(0, daily_goal["calories"] - consumed["calories"]),
            "protein": max(0, daily_goal["protein"] - consumed["protein"]),
            "carbs": max(0, daily_goal["carbs"] - consumed["carbs"]),
            "fat": max(0, daily_goal["fat"] - consumed["fat"])
        }
        
        percentage = {
            "calories": min(100, (consumed["calories"] / daily_goal["calories"]) * 100) if daily_goal["calories"] > 0 else 0,
            "protein": min(100, (consumed["protein"] / daily_goal["protein"]) * 100) if daily_goal["protein"] > 0 else 0,
            "carbs": min(100, (consumed["carbs"] / daily_goal["carbs"]) * 100) if daily_goal["carbs"] > 0 else 0,
            "fat": min(100, (consumed["fat"] / daily_goal["fat"]) * 100) if daily_goal["fat"] > 0 else 0
        }
        
        return {
            "daily_goal": daily_goal,
            "consumed": consumed,
            "remaining": remaining,
            "percentage": percentage
        }
    
    # Dashboard operations
    async def get_user_dashboard(self, user_id: int) -> Dict[str, Any]:
        """Get user dashboard data"""
        if not self.pool:
            return self._empty_dashboard()
        
        try:
            async with self.pool.acquire() as conn:
                # Get recent scans count
                scan_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM scan_history WHERE user_id = $1
                """, user_id)
                
                # Get today's meals
                from datetime import datetime
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                meals_today = await conn.fetchval("""
                    SELECT COUNT(*) FROM meals WHERE user_id = $1 AND logged_at >= $2
                """, user_id, today)
                
                # Get recent scans with details (last 5)
                recent_scans_rows = await conn.fetch("""
                    SELECT session_id, food_name, category, freshness_score, image_url, analyzed_at
                    FROM scan_history
                    WHERE user_id = $1 
                    ORDER BY analyzed_at DESC 
                    LIMIT 5
                """, user_id)
                
                # Calculate average freshness and items at risk
                all_scans = await conn.fetch("""
                    SELECT freshness_score, analyzed_at
                    FROM scan_history
                    WHERE user_id = $1
                    ORDER BY analyzed_at DESC
                    LIMIT 50
                """, user_id)
                
                # Get saved items count
                saved_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM saved_items WHERE user_id = $1
                """, user_id)
            
            # Calculate average freshness
            average_freshness = None
            items_at_risk = 0
            if all_scans:
                total_freshness = sum(row["freshness_score"] or 0 for row in all_scans)
                average_freshness = total_freshness / len(all_scans) if len(all_scans) > 0 else 0
                
                # Items at risk = freshness < 50%
                items_at_risk = sum(1 for row in all_scans if (row["freshness_score"] or 0) < 50)
            
            # Format recent scans
            recent_scans = []
            for row in recent_scans_rows:
                score = row["freshness_score"] or 0
                if score >= 80:
                    level = "Fresh"
                    level_normalized = "fresh"
                elif score >= 50:
                    level = "Medium Fresh"
                    level_normalized = "mid_fresh"
                else:
                    level = "Not Fresh"
                    level_normalized = "not_fresh"
                
                recent_scans.append({
                    "session_id": row["session_id"],
                    "food_name": row["food_name"],
                    "category": row["category"],
                    "freshness": {
                        "percentage": score,
                        "level": level,
                        "level_normalized": level_normalized
                    },
                    "image_url": row["image_url"],
                    "timestamp": row["analyzed_at"].isoformat() if row["analyzed_at"] else None
                })
            
            meal_summary = await self.get_meal_summary(user_id, "today")
            
            return {
                "total_scans": scan_count or 0,
                "meals_today": meals_today or 0,
                "saved_items": saved_count or 0,
                "calories_today": meal_summary.get("total_calories", 0),
                "average_freshness": average_freshness,
                "items_at_risk": items_at_risk,
                "recent_scans": recent_scans,
                "recent_scan": recent_scans[0] if recent_scans else None
            }
        except Exception as e:
            print(f"Error in get_user_dashboard: {e}")
            import traceback
            traceback.print_exc()
            return self._empty_dashboard()
    
    def _empty_dashboard(self) -> Dict[str, Any]:
        return {
            "total_scans": 0,
            "meals_today": 0,
            "saved_items": 0,
            "calories_today": 0,
            "average_freshness": None,
            "items_at_risk": 0,
            "recent_scans": [],
            "recent_scan": None
        }
    
    async def get_nutrition_summary(self, user_id: int, period: str = "daily") -> Dict[str, Any]:
        """Get nutrition summary for a period combining meals and scans"""
        if not self.pool:
            return self._empty_nutrition_summary(period)
        
        # Map period to meal summary format
        period_map = {
            "daily": "today",
            "today": "today",
            "weekly": "week",
            "monthly": "month",
            "yearly": "year"
        }
        mapped_period = period_map.get(period, "today")
        
        # Get meal summary
        meal_summary = await self.get_meal_summary(user_id, mapped_period)
        
        # Get comprehensive nutrition data which includes both scans and meals
        comp_nutrition = await self.get_comprehensive_nutrition(user_id, period if period in ["today", "weekly", "monthly", "yearly"] else "today")
        
        # Use comprehensive data for more accurate totals
        macros = comp_nutrition.get("macros", {})
        daily_goals = comp_nutrition.get("daily_goals", {})
        period_goals = comp_nutrition.get("period_goals", daily_goals)  # Use period-specific goals
        period_multiplier = comp_nutrition.get("period_multiplier", 1)
        
        return {
            "total_calories": int(macros.get("calories", 0) or meal_summary["total_calories"]),
            "total_protein": float(macros.get("protein", 0) or meal_summary["total_protein"]),
            "total_carbs": float(macros.get("carbs", 0) or meal_summary["total_carbs"]),
            "total_fat": float(macros.get("fat", 0) or meal_summary["total_fat"]),
            "total_fiber": float(macros.get("fiber", 0) or meal_summary.get("total_fiber", 0)),
            "total_sodium": float(macros.get("sodium", 0) or 0),
            "total_sugar": float(macros.get("sugar", 0) or meal_summary.get("total_sugar", 0)),
            "daily_goals": {
                "calories": daily_goals.get("calories", 2000),
                "protein": daily_goals.get("protein", 60.0),
                "carbs": daily_goals.get("carbs", 300.0),
                "fat": daily_goals.get("fat", 65.0),
                "fiber": daily_goals.get("fiber", 30.0),
                "sodium": 2300.0,
                "sugar": daily_goals.get("sugar", 50.0)
            },
            "period_goals": {
                "calories": period_goals.get("calories", 2000 * period_multiplier),
                "protein": period_goals.get("protein", 60.0 * period_multiplier),
                "carbs": period_goals.get("carbs", 300.0 * period_multiplier),
                "fat": period_goals.get("fat", 65.0 * period_multiplier),
                "fiber": period_goals.get("fiber", 30.0 * period_multiplier),
                "sodium": 2300.0 * period_multiplier,
                "sugar": period_goals.get("sugar", 50.0 * period_multiplier)
            },
            "period_multiplier": period_multiplier,
            "foods_analyzed": comp_nutrition.get("foods_analyzed", 0),
            "meals_logged": meal_summary.get("meals_logged", 0),
            "period": period,
            "last_updated": datetime.now().isoformat()
        }
    
    def _empty_nutrition_summary(self, period: str = "daily") -> Dict[str, Any]:
        period_multiplier = self._get_period_multiplier(period)
        return {
            "total_calories": 0,
            "total_protein": 0.0,
            "total_carbs": 0.0,
            "total_fat": 0.0,
            "total_fiber": 0.0,
            "total_sodium": 0.0,
            "total_sugar": 0.0,
            "daily_goals": {
                "calories": 2000,
                "protein": 60.0,
                "carbs": 300.0,
                "fat": 65.0,
                "fiber": 30.0,
                "sodium": 2300.0,
                "sugar": 50.0
            },
            "period_goals": {
                "calories": 2000 * period_multiplier,
                "protein": 60.0 * period_multiplier,
                "carbs": 300.0 * period_multiplier,
                "fat": 65.0 * period_multiplier,
                "fiber": 30.0 * period_multiplier,
                "sodium": 2300.0 * period_multiplier,
                "sugar": 50.0 * period_multiplier
            },
            "period_multiplier": period_multiplier,
            "foods_analyzed": 0,
            "meals_logged": 0,
            "period": period,
            "last_updated": None
        }
    
    async def get_health_indicators(self, user_id: int) -> Dict[str, Any]:
        """Get health indicators based on scan history"""
        if not self.pool:
            return self._empty_health_indicators()
        
        history = await self.get_user_scan_history(user_id, limit=100)
        foods = history.get("foods", [])
        
        if not foods:
            return self._empty_health_indicators()
        
        # Calculate scores from actual data
        total_freshness = 0
        freshness_count = 0
        food_types = set()
        
        for food in foods:
            freshness = food.get("freshness", {})
            if isinstance(freshness, dict) and freshness.get("percentage"):
                total_freshness += freshness.get("percentage", 0)
                freshness_count += 1
            
            food_types.add(food.get("food_name", "").lower())
        
        freshness_score = int(total_freshness / freshness_count) if freshness_count > 0 else 0
        variety_score = min(100, len(food_types) * 10)
        nutrition_score = 50  # Base score, could be calculated from nutrition data
        overall_score = int((freshness_score + variety_score + nutrition_score) / 3)
        
        recommendations = []
        if freshness_score < 60:
            recommendations.append("Focus on consuming fresher produce for better nutrition")
        if variety_score < 30:
            recommendations.append("Try analyzing different types of fruits and vegetables for variety")
        if nutrition_score < 50:
            recommendations.append("Consider adding more nutrient-dense foods to your diet")
        if not recommendations:
            recommendations.append("Great job! Keep up the healthy eating habits")
        
        return {
            "overall_score": overall_score,
            "nutrition_score": nutrition_score,
            "freshness_score": freshness_score,
            "variety_score": variety_score,
            "recommendations": recommendations,
            "last_analyzed": foods[0].get("analyzed_at") if foods else None
        }
    
    def _empty_health_indicators(self) -> Dict[str, Any]:
        return {
            "overall_score": 0,
            "nutrition_score": 0,
            "freshness_score": 0,
            "variety_score": 0,
            "recommendations": [
                "Start analyzing food to get personalized health insights",
                "Complete your health profile for better recommendations"
            ],
            "last_analyzed": None
        }
    
    # Saved items operations
    async def get_saved_items(self, user_id: int) -> List[Dict[str, Any]]:
        """Get user's saved/favorite food items with consumed/risky status and FULL session data"""
        if not self.pool:
            return []
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT s.session_id, s.image_url, s.food_name, s.category, 
                           s.nutrition, s.freshness, s.timestamp, 
                           s.storage_recommendations, s.consumption_recommendations, s.health_risk_factors,
                           si.saved_at, si.is_consumed, si.consumed_at, si.is_risky, si.health_warning
                    FROM saved_items si
                    JOIN sessions s ON si.session_id = s.session_id
                    WHERE si.user_id = $1
                    ORDER BY si.is_consumed ASC, si.saved_at DESC
                """, user_id)
                
                items = []
                for row in rows:
                    freshness = row["freshness"] or {}
                    freshness_pct = freshness.get("percentage", 50) if isinstance(freshness, dict) else 50
                    
                    # Parse storage recommendations
                    storage_recs = row["storage_recommendations"]
                    if isinstance(storage_recs, str):
                        import json
                        try:
                            storage_recs = json.loads(storage_recs)
                        except:
                            storage_recs = []
                    
                    # Parse consumption recommendations
                    consumption_recs = row["consumption_recommendations"]
                    if isinstance(consumption_recs, str):
                        import json
                        try:
                            consumption_recs = json.loads(consumption_recs)
                        except:
                            consumption_recs = {}
                    
                    # Parse health risk factors
                    health_risks = row["health_risk_factors"]
                    if isinstance(health_risks, str):
                        import json
                        try:
                            health_risks = json.loads(health_risks)
                        except:
                            health_risks = []
                    
                    items.append({
                        "id": row["session_id"],
                        "session_id": row["session_id"],
                        "food_name": row["food_name"],
                        "category": row["category"] or "Produce",
                        "freshness": freshness,
                        "freshness_percentage": freshness_pct,
                        "nutrition": row["nutrition"] or [],
                        "storage_recommendations": storage_recs or [],
                        "consumption_recommendations": consumption_recs or {},
                        "health_risk_factors": health_risks or [],
                        "image_url": row["image_url"],
                        "saved_at": row["saved_at"].isoformat() if row["saved_at"] else None,
                        "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                        # Consumed/risky status fields
                        "is_consumed": row["is_consumed"] or False,
                        "consumed_at": row["consumed_at"].isoformat() if row["consumed_at"] else None,
                        "is_risky": row["is_risky"] or False,
                        "health_warning": row["health_warning"]
                    })
                
                return items
        except Exception as e:
            print(f"Error getting saved items: {e}")
            return []
    
    async def get_usable_saved_items(self, user_id: int, min_freshness: int = 30) -> List[Dict[str, Any]]:
        """Get saved items that are usable for meal suggestions (not consumed, not risky, fresh enough)"""
        all_items = await self.get_saved_items(user_id)
        
        usable = []
        for item in all_items:
            if item["is_consumed"]:
                continue
            if item["is_risky"]:
                continue
            if item["freshness_percentage"] < min_freshness:
                continue
            usable.append(item)
        
        return usable
    
    async def mark_item_consumed(self, user_id: int, session_id: str) -> bool:
        """Mark a saved item as consumed"""
        if not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute("""
                    UPDATE saved_items 
                    SET is_consumed = TRUE, consumed_at = NOW()
                    WHERE user_id = $1 AND session_id = $2
                """, user_id, session_id)
                return "UPDATE 1" in result
        except Exception as e:
            print(f"Error marking item consumed: {e}")
            return False
    
    async def save_item_to_favorites(self, user_id: int, session_id: str, is_risky: bool = False, health_warning: str = None) -> bool:
        """Save a session to favorites with optional health warning"""
        if not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO saved_items (user_id, session_id, is_risky, health_warning)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id, session_id) DO UPDATE SET
                        is_risky = $3,
                        health_warning = $4
                """, user_id, session_id, is_risky, health_warning)
            return True
        except Exception as e:
            print(f"Error saving to favorites: {e}")
            return False
    
    async def remove_from_favorites(self, user_id: int, session_id: str) -> bool:
        """Remove a session from favorites"""
        if not self.pool:
            return False
        
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM saved_items WHERE user_id = $1 AND session_id = $2
            """, user_id, session_id)
            return "DELETE 1" in result
    
    async def save_to_storage(self, saved_item: Dict[str, Any]) -> int:
        """Save a food item to storage/favorites with full data"""
        if not self.pool:
            return 0
        
        try:
            user_id = saved_item.get("user_id")
            session_id = saved_item.get("session_id")
            
            if not user_id or not session_id:
                print("Error: user_id and session_id are required for save_to_storage")
                return 0
            
            async with self.pool.acquire() as conn:
                # Insert or update saved_items entry
                row = await conn.fetchrow("""
                    INSERT INTO saved_items (user_id, session_id, is_risky, health_warning, saved_at)
                    VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, session_id) DO UPDATE SET
                        is_risky = EXCLUDED.is_risky,
                        health_warning = EXCLUDED.health_warning,
                        saved_at = CURRENT_TIMESTAMP
                    RETURNING id
                """, 
                    user_id, 
                    session_id, 
                    saved_item.get("is_risky", False),
                    saved_item.get("health_warning")
                )
                
                return row["id"] if row else 0
        except Exception as e:
            print(f"Error in save_to_storage: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    async def remove_from_storage(self, user_id: int, session_id: str, reason: str = "removed") -> bool:
        """Remove a food item from storage/favorites"""
        if not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                # If reason is "consumed", mark as consumed instead of deleting
                if reason == "consumed":
                    result = await conn.execute("""
                        UPDATE saved_items 
                        SET is_consumed = TRUE, consumed_at = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND session_id = $2
                    """, user_id, session_id)
                    return "UPDATE 1" in result
                else:
                    # Actually delete the item
                    result = await conn.execute("""
                        DELETE FROM saved_items WHERE user_id = $1 AND session_id = $2
                    """, user_id, session_id)
                    return "DELETE 1" in result
        except Exception as e:
            print(f"Error in remove_from_storage: {e}")
            return False

    # AI Insights Operations
    async def save_ai_insight(self, user_id: int, insight_data: Dict[str, Any]) -> int:
        """Save an AI generated insight"""
        if not self.pool:
            return 0
            
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO ai_health_insights (user_id, insight_type, title, content, generated_at)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                RETURNING id
            """,
                user_id,
                insight_data.get("insight_type", "daily_advice"),
                insight_data.get("title"),
                insight_data.get("content")
            )
            return row["id"]

    async def get_ai_insights(self, user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent AI insights for user"""
        if not self.pool:
            return []
            
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM ai_health_insights 
                WHERE user_id = $1 
                ORDER BY generated_at DESC 
                LIMIT $2
            """, user_id, limit)
            
            return [dict(row) for row in rows]
    
    async def mark_insight_as_read(self, insight_id: int, user_id: int) -> bool:
        """Mark an AI insight as read"""
        if not self.pool:
            return False
            
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute("""
                    UPDATE ai_health_insights 
                    SET is_read = TRUE 
                    WHERE id = $1 AND user_id = $2
                """, insight_id, user_id)
                return "UPDATE 1" in result
        except Exception as e:
            print(f"Error marking insight as read: {e}")
            return False

            
    async def get_advanced_dashboard_stats(self, user_id: int) -> Dict[str, Any]:
        """Get aggregated stats for advanced dashboard graphs"""
        if not self.pool:
            return {}
            
        # Get daily nutrition for last 7 days
        meals = await self.get_user_meals(user_id, period="week")
        
        # Aggregate by day
        daily_stats = {}
        for meal in meals:
            date_str = meal["logged_at"].split("T")[0]
            if date_str not in daily_stats:
                daily_stats[date_str] = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "sugar": 0}
            
            nut = meal["nutrition_data"]
            daily_stats[date_str]["calories"] += nut.get("calories", 0)
            daily_stats[date_str]["protein"] += nut.get("protein", 0)
            daily_stats[date_str]["carbs"] += nut.get("carbs", 0)
            daily_stats[date_str]["fat"] += nut.get("fat", 0)
            daily_stats[date_str]["fiber"] += nut.get("fiber", 0)
            daily_stats[date_str]["sugar"] += nut.get("sugar", 0)
            
        return {
            "daily_history": daily_stats,
            "today": await self.get_daily_nutrition(user_id)
        }


    async def get_user_guides_seen(self, user_id: int) -> List[str]:
        """Get list of guide IDs seen by user"""
        if not self.pool:
            return []
        
        async with self.pool.acquire() as conn:
            val = await conn.fetchval("SELECT guides_seen FROM users WHERE id = $1", user_id)
            if not val:
                return []
            # asyncpg auto-decodes jsonb if we set up codec, but let's be safe
            if isinstance(val, str):
                return json.loads(val)
            return val

    async def mark_guide_seen(self, user_id: int, guide_id: str) -> bool:
        """Mark a guide as seen"""
        if not self.pool:
            return False
            
        try:
            async with self.pool.acquire() as conn:
                # Use JSONB operator to append only if not exists
                # '["a", "b"]'::jsonb || '["c"]'::jsonb
                # to_jsonb converts string to json string, e.g. "guide1"
                # We want to append a value to the array.
                # Since guides_seen is a JSON ARRAY, we need to treat it as such.
                await conn.execute("""
                    UPDATE users 
                    SET guides_seen = (
                        COALESCE(guides_seen, '[]'::jsonb) || to_jsonb($2::text)
                    )
                    WHERE id = $1 
                    AND (guides_seen IS NULL OR NOT (guides_seen @> to_jsonb($2::text)))
                """, user_id, guide_id)
                return True
        except Exception as e:
            print(f"Error marking guide as seen: {e}")
            return False

    # ==================== Meal Items Operations ====================
    
    async def save_meal_item(self, item_data: Dict[str, Any]) -> int:
        """Save a meal item linking a scan to a meal with nutrient snapshot"""
        if not self.pool:
            raise RuntimeError("Database not connected")
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO meal_items (
                    meal_id, scan_id, user_id, quantity, weight_grams, nutrients_snapshot
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """,
                item_data["meal_id"],
                item_data.get("scan_id"),
                item_data["user_id"],
                float(item_data.get("quantity", 1.0)),
                float(item_data.get("weight_grams", 100.0)),
                item_data.get("nutrients_snapshot", {})
            )
            return row["id"]
    
    async def get_meal_items(self, meal_id: int) -> List[Dict[str, Any]]:
        """Get all items for a meal"""
        if not self.pool:
            return []
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT mi.*, s.food_name, s.image_url, s.freshness
                FROM meal_items mi
                LEFT JOIN sessions s ON mi.scan_id = s.session_id
                WHERE mi.meal_id = $1
                ORDER BY mi.created_at
            """, meal_id)
            
            return [dict(row) for row in rows]
    
    # ==================== Daily Aggregates Operations ====================
    
    async def update_daily_aggregate(self, user_id: int, day_date, nutrients: Dict[str, Any]) -> None:
        """Update or create daily nutrition aggregate for a user/date"""
        if not self.pool:
            return
        
        async with self.pool.acquire() as conn:
            # Upsert - insert or update aggregates
            await conn.execute("""
                INSERT INTO daily_nutrition_aggregates (user_id, day_date, totals, meals_count, updated_at)
                VALUES ($1, $2, $3, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, day_date) DO UPDATE SET
                    totals = jsonb_build_object(
                        'calories', COALESCE((daily_nutrition_aggregates.totals->>'calories')::numeric, 0) + COALESCE($4::numeric, 0),
                        'protein', COALESCE((daily_nutrition_aggregates.totals->>'protein')::numeric, 0) + COALESCE($5::numeric, 0),
                        'carbs', COALESCE((daily_nutrition_aggregates.totals->>'carbs')::numeric, 0) + COALESCE($6::numeric, 0),
                        'fat', COALESCE((daily_nutrition_aggregates.totals->>'fat')::numeric, 0) + COALESCE($7::numeric, 0),
                        'fiber', COALESCE((daily_nutrition_aggregates.totals->>'fiber')::numeric, 0) + COALESCE($8::numeric, 0),
                        'sugar', COALESCE((daily_nutrition_aggregates.totals->>'sugar')::numeric, 0) + COALESCE($9::numeric, 0)
                    ),
                    meals_count = daily_nutrition_aggregates.meals_count + 1,
                    updated_at = CURRENT_TIMESTAMP
            """,
                user_id,
                day_date,
                nutrients,
                nutrients.get("calories", 0),
                nutrients.get("protein", 0),
                nutrients.get("carbs", 0),
                nutrients.get("fat", 0),
                nutrients.get("fiber", 0),
                nutrients.get("sugar", 0)
            )
    
    async def get_daily_aggregate(self, user_id: int, day_date) -> Optional[Dict[str, Any]]:
        """Get daily aggregate for a specific date"""
        if not self.pool:
            return None
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM daily_nutrition_aggregates
                WHERE user_id = $1 AND day_date = $2
            """, user_id, day_date)
            
            if not row:
                return {
                    "day_date": str(day_date),
                    "totals": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "sugar": 0},
                    "meals_count": 0
                }
            
            return {
                "day_date": str(row["day_date"]),
                "totals": row["totals"] or {},
                "meals_count": row["meals_count"] or 0,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
            }
    
    async def get_daily_aggregates_range(self, user_id: int, from_date, to_date) -> List[Dict[str, Any]]:
        """Get daily aggregates for a date range. Accepts date objects or strings."""
        if not self.pool:
            return []
        
        # Convert strings to date objects if needed
        from datetime import date as date_type
        if isinstance(from_date, str):
            from_date = date_type.fromisoformat(from_date)
        if isinstance(to_date, str):
            to_date = date_type.fromisoformat(to_date)
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM daily_nutrition_aggregates
                WHERE user_id = $1 AND day_date >= $2 AND day_date <= $3
                ORDER BY day_date ASC
            """, user_id, from_date, to_date)
            
            return [{
                "day_date": str(row["day_date"]),
                "totals": row["totals"] or {},
                "meals_count": row["meals_count"] or 0,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
            } for row in rows]
    
    # ==================== Session Update Operations ====================
    
    async def update_session_add_to_meal(self, session_id: str, add_to_meal: bool) -> bool:
        """Update the add_to_meal flag on a session"""
        if not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                # First check if column exists (migration might not have run)
                try:
                    await conn.execute("""
                        UPDATE sessions SET add_to_meal = $2
                        WHERE session_id = $1
                    """, session_id, add_to_meal)
                    return True
                except Exception as col_error:
                    # Column might not exist yet, add it
                    if "add_to_meal" in str(col_error):
                        await conn.execute("""
                            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS add_to_meal BOOLEAN DEFAULT FALSE
                        """)
                        await conn.execute("""
                            UPDATE sessions SET add_to_meal = $2
                            WHERE session_id = $1
                        """, session_id, add_to_meal)
                        return True
                    raise
        except Exception as e:
            print(f"Error updating session add_to_meal: {e}")
            return False
    
    # ==================== Comprehensive Nutrition Analysis ====================
    
    async def get_comprehensive_nutrition(self, user_id: int, period: str = "today") -> Dict[str, Any]:
        """Get comprehensive macro/micro nutrition data for Summary Tab"""
        if not self.pool:
            return self._empty_comprehensive_nutrition()
        
        try:
            # Determine date range based on period
            now = datetime.now()
            if period == "today" or period == "daily":
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
            elif period == "weekly":
                start_date = now - timedelta(days=7)
                end_date = now
            elif period == "monthly":
                start_date = now - timedelta(days=30)
                end_date = now
            elif period == "yearly":
                start_date = now - timedelta(days=365)
                end_date = now
            elif period == "all":
                start_date = datetime(2000, 1, 1)  # Very old date to get all data
                end_date = now
            else:
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
            
            print(f"[DB] get_comprehensive_nutrition: period={period}, start={start_date}, end={end_date}")
        except Exception as e:
            print(f"[DB ERROR] Date calculation failed: {e}")
            return self._empty_comprehensive_nutrition()
        
        try:
            async with self.pool.acquire() as conn:
                # Get all sessions with nutrition data for this period
                session_rows = await conn.fetch("""
                    SELECT session_id, food_name, category, nutrition, timestamp
                    FROM sessions
                    WHERE user_id = $1 AND timestamp >= $2 AND timestamp <= $3 AND status = 'completed'
                    ORDER BY timestamp DESC
                """, user_id, start_date, end_date)
                
                # Get all meals for this period (including saturated_fat and sodium if available)
                meal_rows = await conn.fetch("""
                    SELECT id, food_name, meal_type, 
                           calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g,
                           COALESCE(saturated_fat_g, 0) as saturated_fat_g,
                           COALESCE(sodium_mg, 0) as sodium_mg,
                           logged_at
                    FROM meals
                    WHERE user_id = $1 AND logged_at >= $2 AND logged_at <= $3
                    ORDER BY logged_at DESC
                """, user_id, start_date, end_date)
                
                # Initialize nutrient aggregates
                macros = {
                    "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0,
                    "fiber": 0.0, "sugar": 0.0, "saturated_fat": 0.0
                }
                micros = {
                    "vitamin_a": 0.0, "vitamin_c": 0.0, "vitamin_d": 0.0,
                    "vitamin_b12": 0.0, "calcium": 0.0, "iron": 0.0,
                    "potassium": 0.0, "magnesium": 0.0, "sodium": 0.0,
                    "zinc": 0.0, "selenium": 0.0
                }
                foods_data = []

                # Process Scans (Sessions)
                for row in session_rows:
                    nutrition = row["nutrition"] or []
                    food_nutrients = {"name": row["food_name"], "category": row["category"], "nutrients": {}}
                    
                    for item in nutrition:
                        if not isinstance(item, dict):
                            continue
                        name = (item.get("name") or "").lower()
                        value_str = str(item.get("value", "0"))
                        # Extract numeric value
                        value = 0.0
                        for part in value_str.split():
                            try:
                                value = float(part.replace(",", ""))
                                break
                            except:
                                continue
                        
                        # Map to macro nutrients
                        if "calor" in name or "energy" in name:
                            macros["calories"] += value
                            food_nutrients["nutrients"]["calories"] = value
                        elif "protein" in name:
                            macros["protein"] += value
                            food_nutrients["nutrients"]["protein"] = value
                        elif "carb" in name:
                            macros["carbs"] += value
                            food_nutrients["nutrients"]["carbs"] = value
                        elif "fat" in name and "saturated" not in name:
                            macros["fat"] += value
                            food_nutrients["nutrients"]["fat"] = value
                        elif "saturated" in name:
                            macros["saturated_fat"] += value
                        elif "fiber" in name:
                            macros["fiber"] += value
                            food_nutrients["nutrients"]["fiber"] = value
                        elif "sugar" in name:
                            macros["sugar"] += value
                            food_nutrients["nutrients"]["sugar"] = value
                        # Map to micro nutrients
                        elif "vitamin a" in name:
                            micros["vitamin_a"] += value
                        elif "vitamin c" in name:
                            micros["vitamin_c"] += value
                        elif "vitamin d" in name:
                            micros["vitamin_d"] += value
                        elif "vitamin b12" in name or "b-12" in name:
                            micros["vitamin_b12"] += value
                        elif "calcium" in name:
                            micros["calcium"] += value
                        elif "iron" in name:
                            micros["iron"] += value
                        elif "potassium" in name:
                            micros["potassium"] += value
                        elif "magnesium" in name:
                            micros["magnesium"] += value
                        elif "sodium" in name:
                            micros["sodium"] += value
                        elif "zinc" in name:
                            micros["zinc"] += value
                        elif "selenium" in name:
                            micros["selenium"] += value
                    
                    # Note: Scans contribute to totals but don't appear in nutrient sources
                    # Only meals are added to foods_data for nutrient source display

                # Process Meals (Manual/Recommended)
                for row in meal_rows:
                    # Add to macros
                    calories = float(row["calories"] or 0)
                    protein = float(row["protein_g"] or 0)
                    carbs = float(row["carbs_g"] or 0)
                    fat = float(row["fat_g"] or 0)
                    fiber = float(row["fiber_g"] or 0)
                    sugar = float(row["sugar_g"] or 0)
                    saturated_fat = float(row["saturated_fat_g"] or 0)
                    sodium = float(row["sodium_mg"] or 0)
                    
                    macros["calories"] += calories
                    macros["protein"] += protein
                    macros["carbs"] += carbs
                    macros["fat"] += fat
                    macros["fiber"] += fiber
                    macros["sugar"] += sugar
                    macros["saturated_fat"] += saturated_fat
                    
                    # Add sodium from meals to micros
                    micros["sodium"] += sodium
                    
                    # Add to foods list - use meal_type as identifier
                    meal_type = str(row["meal_type"] or "Meal").capitalize()
                    food_nutrients = {
                        "name": meal_type,  # Show as "Breakfast", "Lunch", etc. instead of food name
                        "category": "Meal", 
                        "nutrients": {
                            "calories": calories,
                            "protein": protein,
                            "carbs": carbs,
                            "fat": fat,
                            "fiber": fiber,
                            "sugar": sugar,
                            "saturated_fat": saturated_fat,
                            "sodium": sodium
                        }
                    }
                    foods_data.append(food_nutrients)
                
                # Get health profile for personalized goals
                health_profile = await self.get_health_profile(user_id)
                daily_goals = await self._calculate_daily_goals_async(user_id, health_profile)
                micro_goals = self._get_micro_rda()
                
                # Calculate period-specific goals (multiply daily by period multiplier)
                period_multiplier = self._get_period_multiplier(period)
                period_goals = {k: v * period_multiplier for k, v in daily_goals.items()}
                period_micro_goals = {k: v * period_multiplier for k, v in micro_goals.items()}
                
                return {
                    "period": period,
                    "macros": macros,
                    "micros": micros,
                    "daily_goals": daily_goals,  # Keep daily for reference
                    "period_goals": period_goals,  # Period-specific goals (scaled)
                    "micro_goals": micro_goals,  # Keep daily micro goals for reference
                    "period_micro_goals": period_micro_goals,  # Period-specific micro goals
                    "period_multiplier": period_multiplier,  # Include multiplier for frontend
                    "foods_analyzed": len(session_rows) + len(meal_rows),
                    "foods_data": foods_data[:20],
                    "last_updated": now.isoformat()
                }
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[DB ERROR] get_comprehensive_nutrition failed: {e}")
            return self._empty_comprehensive_nutrition()
    
    def _get_period_multiplier(self, period: str) -> int:
        """Get the multiplier for a period to convert daily targets to period targets.
        
        Args:
            period: 'today', 'daily', 'weekly', 'monthly', 'yearly', 'all'
        Returns:
            int: multiplier (1 for daily, 7 for weekly, 30 for monthly, 365 for yearly)
        """
        multipliers = {
            "today": 1,
            "daily": 1,
            "weekly": 7,
            "monthly": 30,
            "yearly": 365,
            "all": 1  # 'all' shows daily goals
        }
        return multipliers.get(period.lower(), 1)
    
    def _empty_comprehensive_nutrition(self) -> Dict[str, Any]:
        default_goals = self._calculate_daily_goals(None)
        default_micro_goals = self._get_micro_rda()
        return {
            "period": "today",
            "macros": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0, "sugar": 0, "saturated_fat": 0},
            "micros": {"vitamin_a": 0, "vitamin_c": 0, "vitamin_d": 0, "vitamin_b12": 0, "calcium": 0, "iron": 0, "potassium": 0, "magnesium": 0, "sodium": 0, "zinc": 0, "selenium": 0},
            "daily_goals": default_goals,
            "period_goals": default_goals,  # Same as daily for empty/default
            "micro_goals": default_micro_goals,
            "period_micro_goals": default_micro_goals,  # Same as daily for empty/default
            "period_multiplier": 1,
            "foods_analyzed": 0,
            "foods_data": [],
            "last_updated": None
        }
    
    async def _calculate_daily_goals_async(self, user_id: int, health_profile: Optional[Dict], for_date=None) -> Dict[str, float]:
        """Get daily goals - uses stored goals first, falls back to GPT/calculation.
        
        This is the async version that properly checks stored goals.
        Args:
            user_id: User ID for stored goals lookup
            health_profile: Health profile dict for fallback calculation
            for_date: Date to get goals for (for versioning)
        """
        default_goals = {
            "calories": 2000, "protein": 50, "carbs": 275, "fat": 65, 
            "fiber": 28, "sugar": 50, "saturated_fat": 20
        }
        
        # Try stored goals first
        try:
            stored = await self.get_user_nutrition_goals(user_id, for_date=for_date, period="daily")
            if stored:
                # Remove non-nutrient fields
                result = {k: v for k, v in stored.items() if k not in ("period", "effective_from", "reasoning")}
                return result
        except Exception as e:
            print(f"[GOALS] Could not fetch stored goals: {e}")
        
        # Fallback to GPT/calculation
        if not health_profile:
            return default_goals
        
        try:
            from gpt_model.gptapi import generate_personalized_nutrition_goals
            goals = generate_personalized_nutrition_goals(health_profile)
            goals.pop("reasoning", None)
            return goals
        except Exception as e:
            print(f"[GOALS] Error generating personalized goals: {e}")
            
            # Fallback: use basic Harris-Benedict calculation
            weight = float(health_profile.get("weight_kg") or 70)
            height = float(health_profile.get("height_cm") or 170)
            age = int(health_profile.get("age") or 30)
            gender = (health_profile.get("gender") or "other").lower()
            activity = (health_profile.get("activity_level") or "moderate").lower()
            
            if gender == "male":
                bmr = 88.362 + (13.397 * weight) + (4.799 * height) - (5.677 * age)
            elif gender == "female":
                bmr = 447.593 + (9.247 * weight) + (3.098 * height) - (4.330 * age)
            else:
                bmr = 300 + (10 * weight) + (4 * height) - (5 * age)
            
            multipliers = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
            calories = float(bmr) * multipliers.get(activity, 1.55)
            
            return {
                "calories": round(calories),
                "protein": round(weight * 0.8),
                "carbs": round(calories * 0.5 / 4),
                "fat": round(calories * 0.3 / 9),
                "fiber": 28,
                "sugar": 50,
                "saturated_fat": 20
            }
    
    def _calculate_daily_goals(self, health_profile: Optional[Dict]) -> Dict[str, float]:
        """Legacy sync version - calculates goals without checking stored (for fallback).
        
        Note: Use _calculate_daily_goals_async when possible to get stored goals.
        """
        default_goals = {
            "calories": 2000, "protein": 50, "carbs": 275, "fat": 65, 
            "fiber": 28, "sugar": 50, "saturated_fat": 20
        }
        
        if not health_profile:
            return default_goals
        
        try:
            from gpt_model.gptapi import generate_personalized_nutrition_goals
            goals = generate_personalized_nutrition_goals(health_profile)
            goals.pop("reasoning", None)
            return goals
        except Exception as e:
            print(f"[GOALS] Error generating personalized goals: {e}")
            
            weight = float(health_profile.get("weight_kg") or 70)
            height = float(health_profile.get("height_cm") or 170)
            age = int(health_profile.get("age") or 30)
            gender = (health_profile.get("gender") or "other").lower()
            activity = (health_profile.get("activity_level") or "moderate").lower()
            
            if gender == "male":
                bmr = 88.362 + (13.397 * weight) + (4.799 * height) - (5.677 * age)
            elif gender == "female":
                bmr = 447.593 + (9.247 * weight) + (3.098 * height) - (4.330 * age)
            else:
                bmr = 300 + (10 * weight) + (4 * height) - (5 * age)
            
            multipliers = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
            calories = float(bmr) * multipliers.get(activity, 1.55)
            
            return {
                "calories": round(calories),
                "protein": round(weight * 0.8),
                "carbs": round(calories * 0.5 / 4),
                "fat": round(calories * 0.3 / 9),
                "fiber": 28,
                "sugar": 50,
                "saturated_fat": 20
            }
    
    def _get_micro_rda(self) -> Dict[str, float]:
        """Get recommended daily allowances for micronutrients"""
        return {
            "vitamin_a": 900,    # mcg RAE
            "vitamin_c": 90,     # mg
            "vitamin_d": 20,     # mcg
            "vitamin_b12": 2.4,  # mcg
            "calcium": 1000,     # mg
            "iron": 18,          # mg
            "potassium": 3500,   # mg
            "magnesium": 400,    # mg
            "sodium": 2300,      # mg (upper limit)
            "zinc": 11,          # mg
            "selenium": 55       # mcg
        }

    async def get_recent_meals(self, user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent meals for chatbot context"""
        if not self.pool:
            return []
            
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT food_name, calories, meal_type, logged_at
                FROM meals
                WHERE user_id = $1
                ORDER BY logged_at DESC
                LIMIT $2
            """, user_id, limit)
            
            return [{
                "food_name": row["food_name"],
                "calories": row["calories"],
                "meal_type": row["meal_type"],
                "logged_at": row["logged_at"].isoformat() if row["logged_at"] else "Unknown"
            } for row in rows]
    
    async def get_nutrient_sources(self, user_id: int, period: str = "today") -> Dict[str, List]:
        """Get top food sources for each nutrient (deduplicated by food name)"""
        nutrition_data = await self.get_comprehensive_nutrition(user_id, period)
        foods = nutrition_data.get("foods_data", [])
        
        # Group by nutrient, aggregate by food name
        sources_temp: Dict[str, Dict[str, Dict]] = {
            "calories": {}, "protein": {}, "carbs": {}, "fat": {},
            "fiber": {}, "sugar": {}
        }
        
        for food in foods:
            food_name = food.get("name", "Unknown")
            category = food.get("category", "")
            
            for nutrient, value in food.get("nutrients", {}).items():
                if nutrient in sources_temp and value > 0:
                    if food_name in sources_temp[nutrient]:
                        # Aggregate: add value to existing entry
                        sources_temp[nutrient][food_name]["value"] += value
                    else:
                        # New entry
                        sources_temp[nutrient][food_name] = {
                            "food": food_name,
                            "value": value,
                            "category": category
                        }
        
        # Convert to list, round values, sort and take top 3 unique foods
        sources: Dict[str, List] = {}
        for nutrient, food_dict in sources_temp.items():
            entries = list(food_dict.values())
            for entry in entries:
                entry["value"] = round(entry["value"], 1)
            sources[nutrient] = sorted(entries, key=lambda x: x["value"], reverse=True)[:3]
        
        return sources
    
    async def get_meal_timing_analysis(self, user_id: int) -> Dict[str, Any]:
        """Analyze meal timing patterns from BOTH sessions and meals tables"""
        if not self.pool:
            return {"breakfast": "unknown", "lunch": "unknown", "dinner": "unknown", "efficiency": 0}
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        async with self.pool.acquire() as conn:
            # Get timestamps from sessions (scans)
            session_rows = await conn.fetch("""
                SELECT timestamp as time_logged, NULL as meal_type FROM sessions
                WHERE user_id = $1 AND timestamp >= $2 AND status = 'completed'
            """, user_id, today_start)
            
            # Get timestamps and meal_type from meals table
            meal_rows = await conn.fetch("""
                SELECT logged_at as time_logged, meal_type FROM meals
                WHERE user_id = $1 AND logged_at >= $2
            """, user_id, today_start)
            
            # Define ideal meal windows
            breakfast_window = (5, 11)   # 5 AM - 11 AM
            lunch_window = (11, 15)      # 11 AM - 3 PM
            dinner_window = (17, 22)     # 5 PM - 10 PM
            
            meals_status = {"breakfast": None, "lunch": None, "dinner": None}
            
            # First, check explicit meal types from meals table
            for row in meal_rows:
                meal_type = (row["meal_type"] or "").lower()
                time_logged = row["time_logged"]
                if not time_logged:
                    continue
                hour = time_logged.hour
                
                if meal_type == "breakfast" and not meals_status["breakfast"]:
                    if breakfast_window[0] <= hour <= breakfast_window[1]:
                        meals_status["breakfast"] = "on_time"
                    else:
                        meals_status["breakfast"] = "late"
                elif meal_type == "lunch" and not meals_status["lunch"]:
                    if lunch_window[0] <= hour <= lunch_window[1]:
                        meals_status["lunch"] = "on_time"
                    else:
                        meals_status["lunch"] = "late"
                elif meal_type == "dinner" and not meals_status["dinner"]:
                    if dinner_window[0] <= hour <= dinner_window[1]:
                        meals_status["dinner"] = "on_time"
                    else:
                        meals_status["dinner"] = "late"
                elif meal_type == "snack":
                    # Snacks don't affect timing status
                    pass
            
            # Then, infer from sessions (scans) by time if not already set
            for row in session_rows:
                time_logged = row["time_logged"]
                if not time_logged:
                    continue
                hour = time_logged.hour
                
                if breakfast_window[0] <= hour <= breakfast_window[1] and not meals_status["breakfast"]:
                    meals_status["breakfast"] = "on_time"
                elif lunch_window[0] <= hour <= lunch_window[1] and not meals_status["lunch"]:
                    meals_status["lunch"] = "on_time"
                elif dinner_window[0] <= hour <= dinner_window[1] and not meals_status["dinner"]:
                    meals_status["dinner"] = "on_time"
            
            # Calculate efficiency score
            total_meals = len([v for v in meals_status.values() if v is not None])
            on_time = sum(1 for v in meals_status.values() if v == "on_time")
            
            # If no meals logged, efficiency is 0. Otherwise calculate based on on_time meals
            if total_meals == 0:
                efficiency = 0
            else:
                # Partial scoring: on_time=100%, late=50%, skipped=0%
                score = 0
                for status in meals_status.values():
                    if status == "on_time":
                        score += 100
                    elif status == "late":
                        score += 50
                efficiency = round(score / 3)
            
            return {
                "breakfast": meals_status["breakfast"] or "skipped",
                "lunch": meals_status["lunch"] or "skipped",
                "dinner": meals_status["dinner"] or "skipped",
                "efficiency": efficiency,
                "meals_logged": total_meals
            }
    
    async def get_food_classification(self, user_id: int, period: str = "today") -> Dict[str, List]:
        """Classify foods as healthy or risky based on nutrition profile"""
        nutrition_data = await self.get_comprehensive_nutrition(user_id, period)
        foods = nutrition_data.get("foods_data", [])
        health_profile = await self.get_health_profile(user_id)
        
        healthy = []
        risky = []
        
        # Get user health conditions
        has_diabetes = health_profile.get("has_diabetes", False) if health_profile else False
        has_bp = health_profile.get("has_blood_pressure_issues", False) if health_profile else False
        has_heart = health_profile.get("has_heart_issues", False) if health_profile else False
        
        for food in foods:
            nutrients = food.get("nutrients", {})
            reasons = []
            is_risky = False
            
            # Check for risky conditions
            sugar = nutrients.get("sugar", 0)
            sodium = nutrients.get("sodium", 0)
            sat_fat = nutrients.get("saturated_fat", 0)
            fiber = nutrients.get("fiber", 0)
            
            if sugar > 15 and has_diabetes:
                is_risky = True
                reasons.append("high sugar")
            if sodium > 400 and has_bp:
                is_risky = True
                reasons.append("high sodium")
            if sat_fat > 5 and has_heart:
                is_risky = True
                reasons.append("high saturated fat")
            
            # Check for healthy indicators
            if fiber > 3:
                reasons.append("high fiber")
            if nutrients.get("protein", 0) > 10:
                reasons.append("good protein")
            
            if is_risky:
                risky.append({"food": food["name"], "reasons": reasons})
            else:
                healthy.append({"food": food["name"], "reasons": reasons if reasons else ["balanced"]})
        
        return {
            "healthy": healthy[:5],
            "risky": risky[:5]
        }

