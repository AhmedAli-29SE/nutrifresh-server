"""
Authentication service for user management and JWT token handling
"""

import bcrypt
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv

load_dotenv()

# JWT secret key (should be in environment variable)
JWT_SECRET = os.getenv("JWT_SECRET", "nutrifresh-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days

from fastapi import Header, HTTPException, status

class AuthService:
    """Service for handling user authentication and JWT tokens"""
    
    def __init__(self, db_service=None):
        """
        Initialize auth service with optional database service.
        If db_service is None, uses in-memory storage (for development).
        """
        self.db_service = db_service
        if not self.db_service:
            raise RuntimeError("Database service is required for AuthService")
    
    async def get_current_user(self, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
        """FastAPI Dependency for getting current user from token"""
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        try:
            scheme, token = authorization.split()
            if scheme.lower() != 'bearer':
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication scheme",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            user = await self.verify_token(token)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return user
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def _verify_password(self, password: str, hashed: str) -> bool:
        """Verify a password against a hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False
    
    def _create_token(self, user_id: int, email: str) -> str:
        """Create a JWT token for a user"""
        payload = {
            "user_id": user_id,
            "email": email,
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    def _verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode a JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    async def signup(self, email: str, password: str, first_name: str, last_name: str) -> Dict[str, Any]:
        """Register a new user"""
        # Check if user exists (check database first if connected, otherwise in-memory)
        existing = None
        if self.db_service and self.db_service.pool:
            existing = await self.db_service.get_user_by_email(email)
        else:
            raise RuntimeError("Database connection not available")
        
        if existing:
            raise ValueError("User with this email already exists")
        
        # Hash password
        hashed_password = self._hash_password(password)
        
        # Create user
        user_data = {
            "email": email.lower(),
            "password_hash": hashed_password,
            "first_name": first_name,
            "last_name": last_name,
            "created_at": datetime.utcnow().isoformat(),
            "profile": {}
        }
        
        # Try database first, fallback to in-memory
        # Try database
        if self.db_service and self.db_service.pool:
            try:
                user_id = await self.db_service.create_user(user_data)
            except Exception as e:
                raise RuntimeError(f"Database create_user failed: {e}")
        else:
            raise RuntimeError("Database connection not available")
        
        # Create token
        token = self._create_token(user_id, email)
        
        return {
            "user_id": user_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "access_token": token,
            "token_type": "bearer"
        }
    
    async def login(self, email: str, password: str) -> Dict[str, Any]:
        """Authenticate a user and return token"""
        # Get user (check database first if connected, otherwise in-memory)
        user = None
        if self.db_service and self.db_service.pool:
            user = await self.db_service.get_user_by_email(email)
        else:
            raise RuntimeError("Database connection not available")
        
        if not user:
            raise ValueError("Invalid email or password")
        
        # Verify password
        if not self._verify_password(password, user["password_hash"]):
            raise ValueError("Invalid email or password")
        
        # Create token
        user_id = user.get("user_id") or user.get("id")
        token = self._create_token(user_id, email)
        
        return {
            "user_id": user_id,
            "email": email,
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "access_token": token,
            "token_type": "bearer"
        }
    
    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify a JWT token and return user info"""
        payload = self._verify_token(token)
        if not payload:
            return None
        
        user_id = payload.get("user_id")
        email = payload.get("email")
        
        if not user_id or not email:
            return None
        
        # Get user from database
        if self.db_service and self.db_service.pool:
            user = await self.db_service.get_user_by_id(user_id)
        else:
            return None
        
        if not user:
            return None
        
        return {
            "user_id": user_id,
            "email": email,
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", "")
        }
    
    async def get_user_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user profile data including health profile"""
        if self.db_service and self.db_service.pool:
            user = await self.db_service.get_user_by_id(user_id)
            if not user:
                return None
            
            # Get health profile from new table
            health_profile = await self.db_service.get_health_profile(user_id)
            
            return {
                "user_id": user.get("user_id") or user.get("id"),
                "email": user.get("email"),
                "first_name": user.get("first_name", ""),
                "last_name": user.get("last_name", ""),
                "profile": health_profile or {} # Return empty dict if no profile yet
            }
        else:
            raise RuntimeError("Database connection not available")
    
    async def update_user_profile(self, user_id: int, profile_data: Dict[str, Any]) -> bool:
        """Update user health profile"""
        if self.db_service and self.db_service.pool:
            # Use new method for health profile table
            return await self.db_service.create_health_profile(user_id, profile_data)
        
        raise RuntimeError("Database connection not available")
    
    async def update_user_basic_info(self, user_id: int, first_name: str = None, last_name: str = None) -> bool:
        """Update user's basic info (first_name, last_name)"""
        if self.db_service and self.db_service.pool:
            return await self.db_service.update_user_basic_info(user_id, first_name, last_name)
        
        raise RuntimeError("Database connection not available")
    
    # =============================================
    # ALIAS METHODS (for router compatibility)
    # =============================================
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email - alias for db_service.get_user_by_email"""
        if self.db_service and self.db_service.pool:
            return await self.db_service.get_user_by_email(email)
        return None
    
    async def create_user(self, email: str, password: str, first_name: str, last_name: str) -> Dict[str, Any]:
        """Create a new user - alias for signup"""
        return await self.signup(email, password, first_name, last_name)
    
    async def authenticate(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user and return user data with tokens"""
        try:
            result = await self.login(email, password)
            # Format for router compatibility
            return {
                "user": {
                    "id": result.get("user_id"),
                    "user_id": result.get("user_id"),
                    "email": result.get("email"),
                    "first_name": result.get("first_name"),
                    "last_name": result.get("last_name"),
                    "has_profile": False  # Will be checked separately
                },
                "access_token": result.get("access_token"),
                "refresh_token": result.get("access_token"),  # Use same token for refresh
                "token_type": "bearer"
            }
        except ValueError:
            return None
    
    async def refresh_tokens(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refresh access and refresh tokens"""
        payload = self._verify_token(refresh_token)
        if not payload:
            return None
        
        user_id = payload.get("user_id")
        email = payload.get("email")
        
        if not user_id or not email:
            return None
        
        new_token = self._create_token(user_id, email)
        return {
            "access_token": new_token,
            "refresh_token": new_token,
            "token_type": "bearer"
        }
    
    async def invalidate_token(self, token: str) -> bool:
        """Invalidate a token (for logout)"""
        # For stateless JWT, we don't actually invalidate
        # In production, you'd add to a blacklist in Redis/DB
        return True
    
    async def verify_password(self, user_id: int, password: str) -> Optional[Dict[str, Any]]:
        """Verify user's current password"""
        if not self.db_service or not self.db_service.pool:
            return None
        
        user = await self.db_service.get_user_by_id(user_id)
        if not user:
            return None
        
        if self._verify_password(password, user.get("password_hash", "")):
            return user
        return None
    
    async def update_password(self, user_id: int, new_password: str) -> bool:
        """Update user's password"""
        if not self.db_service or not self.db_service.pool:
            return False
        
        hashed = self._hash_password(new_password)
        return await self.db_service.update_user_password(user_id, hashed)
    
    async def send_password_reset(self, email: str) -> bool:
        """Send password reset email (stub - implement with email service)"""
        # TODO: Implement email sending
        return True
    
    async def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password using reset token (stub)"""
        # TODO: Implement with proper token verification
        return False
    
    async def delete_user(self, user_id: int) -> bool:
        """Delete user and all associated data"""
        if not self.db_service or not self.db_service.pool:
            return False
        
        return await self.db_service.delete_user(user_id)

