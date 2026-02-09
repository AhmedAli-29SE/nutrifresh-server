"""
Session service for managing user sessions and food analysis data
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import json

class SessionService:
    """Service for managing user sessions and food analysis data"""
    
    def __init__(self):
        # In-memory storage (in production, use Redis or database)
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
    
    async def store_session(self, session_id: str, data: Dict[str, Any]) -> None:
        """Store session data"""
        # Add metadata
        data["session_id"] = session_id
        if "timestamp" not in data:
            data["timestamp"] = datetime.now().isoformat()
        
        self.active_sessions[session_id] = data
        print(f"Session {session_id} stored with data: {data.get('food_name', 'Unknown')}")
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data by ID"""
        return self.active_sessions.get(session_id)
    
    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update existing session data"""
        if session_id in self.active_sessions:
            self.active_sessions[session_id].update(updates)
            return True
        return False
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
            return True
        return False
    
    async def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """Get all active sessions"""
        return self.active_sessions.copy()
    
    async def get_food_history(self, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
        """Get food analysis history"""
        # Sort sessions by timestamp (newest first)
        sessions_list = list(self.active_sessions.values())
        sessions_list.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # Apply pagination
        paginated_sessions = sessions_list[offset:offset + limit]
        
        # Convert to history format
        foods = []
        for session in paginated_sessions:
            food_item = {
                "food_name": session.get("food_name", "Unknown"),
                "category": session.get("category", "Unknown"),
                "freshness": session.get("freshness", {"level": "Unknown", "percentage": 0}),
                "analyzed_at": session.get("timestamp", datetime.now().isoformat()),
                "thumbnail_url": session.get("image_url", "/uploads/default-food.jpg"),
                "session_id": session.get("session_id", ""),
                "status": session.get("status", "completed")
            }
            foods.append(food_item)
        
        return {
            "foods": foods,
            "total": len(self.active_sessions)
        }
    
    async def get_pending_sessions(self) -> List[Dict[str, Any]]:
        """Get sessions with pending status"""
        pending = []
        for session in self.active_sessions.values():
            if session.get("status") == "pending":
                pending.append(session)
        
        # Sort by timestamp (newest first)
        pending.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return pending
    
    async def clear_all_sessions(self) -> None:
        """Clear all sessions (for testing)"""
        self.active_sessions.clear()
        print("All sessions cleared")
    
    async def get_sessions_count(self) -> int:
        """Get total number of sessions"""
        return len(self.active_sessions)
    
    async def get_pending_count(self) -> int:
        """Get number of pending sessions"""
        pending_count = 0
        for session in self.active_sessions.values():
            if session.get("status") == "pending":
                pending_count += 1
        return pending_count 