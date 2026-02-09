"""
Auth Router - Authentication endpoints
Handles signup, login, token refresh, password reset, logout
"""

from typing import Dict, Optional, Any
from pydantic import BaseModel, Field, EmailStr

from fastapi import APIRouter, HTTPException, Header

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

_auth_service = None
_db_service = None


def init_services(auth_service, db_service):
    global _auth_service, _db_service
    _auth_service = auth_service
    _db_service = db_service


async def _get_current_user(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    if not authorization or not _auth_service:
        return None
    try:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        user = await _auth_service.verify_token(parts[1])
        if user:
            user["token"] = parts[1]
        return user
    except:
        return None


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str
    last_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


def create_auth_routes(auth_service, db_service, get_current_user_fn):
    init_services(auth_service, db_service)
    
    @router.post("/signup")
    async def signup(req: SignupRequest):
        try:
            existing = await _auth_service.get_user_by_email(req.email)
            if existing:
                raise HTTPException(status_code=400, detail="Email already registered")
            
            result = await _auth_service.create_user(
                email=req.email, password=req.password,
                first_name=req.first_name, last_name=req.last_name
            )
            
            if result:
                return {
                    "success": True, "message": "Account created successfully",
                    "data": {
                        "user_id": result.get("user_id"),
                        "email": req.email,
                        "first_name": req.first_name,
                        "last_name": req.last_name,
                        "access_token": result.get("access_token"),
                        "refresh_token": result.get("access_token"),
                        "token_type": "bearer"
                    }
                }
            
            raise HTTPException(status_code=500, detail="Failed to create account")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")
    
    @router.post("/login")
    async def login(req: LoginRequest):
        try:
            result = await _auth_service.authenticate(req.email, req.password)
            
            if result:
                user = result.get("user", {})
                return {
                    "success": True, "message": "Login successful",
                    "data": {
                        "user_id": user.get("id") or user.get("user_id"),
                        "email": user.get("email"),
                        "first_name": user.get("first_name"),
                        "last_name": user.get("last_name"),
                        "access_token": result.get("access_token"),
                        "refresh_token": result.get("refresh_token"),
                        "token_type": "bearer",
                        "has_profile": bool(user.get("has_profile", False))
                    }
                }
            
            raise HTTPException(status_code=401, detail="Invalid email or password")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")
    
    @router.post("/refresh-token")
    async def refresh_token(req: RefreshTokenRequest):
        try:
            result = await _auth_service.refresh_tokens(req.refresh_token)
            
            if result:
                return {
                    "success": True, "message": "Token refreshed",
                    "data": {
                        "access_token": result.get("access_token"),
                        "refresh_token": result.get("refresh_token"),
                        "token_type": "bearer"
                    }
                }
            
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Token refresh failed: {str(e)}")
    
    @router.post("/logout")
    async def logout(authorization: Optional[str] = Header(None)):
        try:
            current_user = await _get_current_user(authorization)
            if current_user:
                await _auth_service.invalidate_token(current_user.get("token"))
                return {"success": True, "message": "Logged out successfully"}
            return {"success": True, "message": "No active session"}
        except:
            return {"success": True, "message": "Logged out"}
    
    @router.post("/password-reset/request")
    async def request_password_reset(req: PasswordResetRequest):
        try:
            user = await _auth_service.get_user_by_email(req.email)
            if user:
                await _auth_service.send_password_reset(req.email)
            return {"success": True, "message": "If an account with that email exists, a reset link has been sent"}
        except:
            return {"success": True, "message": "If an account with that email exists, a reset link has been sent"}
    
    @router.post("/password-reset/confirm")
    async def confirm_password_reset(req: PasswordResetConfirm):
        try:
            success = await _auth_service.reset_password(req.token, req.new_password)
            if success:
                return {"success": True, "message": "Password reset successfully"}
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Password reset failed: {str(e)}")
    
    @router.post("/change-password")
    async def change_password(req: ChangePasswordRequest, authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            user = await _auth_service.verify_password(current_user["user_id"], req.current_password)
            if not user:
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            
            success = await _auth_service.update_password(current_user["user_id"], req.new_password)
            if success:
                return {"success": True, "message": "Password changed successfully"}
            raise HTTPException(status_code=500, detail="Failed to change password")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Password change failed: {str(e)}")
    
    @router.get("/me")
    async def get_current_user_info(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        return {
            "success": True,
            "data": {
                "user_id": current_user.get("user_id") or current_user.get("id"),
                "email": current_user.get("email"),
                "first_name": current_user.get("first_name"),
                "last_name": current_user.get("last_name"),
            }
        }
    
    @router.delete("/account")
    async def delete_account(authorization: Optional[str] = Header(None)):
        current_user = await _get_current_user(authorization)
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        try:
            success = await _auth_service.delete_user(current_user["user_id"])
            if success:
                return {"success": True, "message": "Account deleted successfully"}
            raise HTTPException(status_code=500, detail="Failed to delete account")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Account deletion failed: {str(e)}")
    
    return router
