import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json

class SessionManager:
    """
    Session management untuk Koronka dengan Redis backend
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.session_timeout = 28800  # 8 hours in seconds
        self.max_sessions_per_user = 3  # Max concurrent sessions

    async def create_session(self, user_id: str, client_ip: str, 
                           user_agent: str) -> str:
        """Create new session"""
        session_id = str(uuid.uuid4())
        
        session_data = {
            "user_id": user_id,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            "is_active": True
        }
        
        # Store session
        session_key = f"session:{session_id}"
        self.redis_client.setex(
            session_key, 
            self.session_timeout, 
            json.dumps(session_data)
        )
        
        # Add to user sessions list
        user_sessions_key = f"user_sessions:{user_id}"
        self.redis_client.sadd(user_sessions_key, session_id)
        self.redis_client.expire(user_sessions_key, self.session_timeout)
        
        # Enforce max sessions limit
        await self.enforce_max_sessions(user_id)
        
        return session_id

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data"""
        session_key = f"session:{session_id}"
        session_data = self.redis_client.get(session_key)
        
        if session_data:
            data = json.loads(session_data)
            
            # Update last activity
            data["last_activity"] = datetime.utcnow().isoformat()
            self.redis_client.setex(
                session_key, 
                self.session_timeout, 
                json.dumps(data)
            )
            
            return data
        
        return None

    async def invalidate_session(self, session_id: str):
        """Invalidate a session"""
        session_data = await self.get_session(session_id)
        if session_data:
            user_id = session_data["user_id"]
            
            # Remove from Redis
            session_key = f"session:{session_id}"
            self.redis_client.delete(session_key)
            
            # Remove from user sessions list
            user_sessions_key = f"user_sessions:{user_id}"
            self.redis_client.srem(user_sessions_key, session_id)

    async def invalidate_all_user_sessions(self, user_id: str):
        """Invalidate all sessions for a user"""
        user_sessions_key = f"user_sessions:{user_id}"
        session_ids = self.redis_client.smembers(user_sessions_key)
        
        for session_id in session_ids:
            session_key = f"session:{session_id.decode()}"
            self.redis_client.delete(session_key)
        
        self.redis_client.delete(user_sessions_key)

    async def enforce_max_sessions(self, user_id: str):
        """Enforce maximum sessions per user"""
        user_sessions_key = f"user_sessions:{user_id}"
        session_ids = list(self.redis_client.smembers(user_sessions_key))
        
        if len(session_ids) > self.max_sessions_per_user:
            # Sort by creation time and remove oldest
            sessions_with_time = []
            for session_id in session_ids:
                session_data = await self.get_session(session_id.decode())
                if session_data:
                    sessions_with_time.append((
                        session_id.decode(),
                        session_data["created_at"]
                    ))
            
            # Sort by creation time (oldest first)
            sessions_with_time.sort(key=lambda x: x[1])
            
            # Remove oldest sessions
            sessions_to_remove = len(sessions_with_time) - self.max_sessions_per_user
            for i in range(sessions_to_remove):
                session_id = sessions_with_time[i][0]
                await self.invalidate_session(session_id)

    async def get_active_sessions(self, user_id: str) -> list:
        """Get all active sessions for a user"""
        user_sessions_key = f"user_sessions:{user_id}"
        session_ids = self.redis_client.smembers(user_sessions_key)
        
        active_sessions = []
        for session_id in session_ids:
            session_data = await self.get_session(session_id.decode())
            if session_data and session_data["is_active"]:
                active_sessions.append({
                    "session_id": session_id.decode(),
                    "client_ip": session_data["client_ip"],
                    "created_at": session_data["created_at"],
                    "last_activity": session_data["last_activity"]
                })
        
        return active_sessions