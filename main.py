
# main.py
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
import os
from dotenv import load_dotenv

from database import get_db, engine
from models import Base, User, UserLog
from schemas import UserCreate, UserResponse, Token
from auth import AuthManager

load_dotenv()

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Koronka IoT Control System",
    description="Secure authentication system for Koronka meat cooling equipment",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:1234", 
        "http://192.168.100.30:1234",  # Frontend port
        "http://192.168.100.30:8001",  # Backend port
        "*"  # TEMPORARY untuk development - HAPUS di production!
        ],  # Frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
auth_manager = AuthManager()

@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# File: main.py (update login endpoint)

@app.post("/auth/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Secure login endpoint with comprehensive security logging
    """
    client_ip = request.client.host if request else "unknown"
    user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"
    
    print(f"🔐 Login attempt: {form_data.username} from {client_ip}")
    print(f"🌐 User Agent: {user_agent}")
    
    # Authenticate user with comprehensive security checks
    user = auth_manager.authenticate_user(
        db, form_data.username, form_data.password, client_ip, user_agent
    )
    
    if not user:
        # Failed attempts are now logged in authenticate_user method
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is in cooldown
    if user.cooldown_until and user.cooldown_until > datetime.utcnow():
        remaining_time = (user.cooldown_until - datetime.utcnow()).seconds
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Akun terkunci. Coba lagi dalam {remaining_time} detik",
        )
    
    # Reset login attempts on successful login
    auth_manager.reset_login_attempts(db, user)
    
    # Create access token
    access_token = auth_manager.create_access_token(data={"sub": user.username})
    
    # Log successful login with full details
    auth_manager.log_user_action(db, user.id, None, "LOGIN_SUCCESS", client_ip, user_agent)
    
    print(f"✅ Login successful: {user.username}")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "created_at": user.created_at
        }
    }

@app.get("/auth/security/failed-attempts")
async def get_failed_attempts_summary(
    hours: int = 24,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """
    Get summary of failed login attempts (admin only)
    """
    # Verify admin user
    user = auth_manager.get_current_user(db, token)
    
    # Get summary
    summary = auth_manager.get_failed_attempts_summary(db, hours)
    
    return {
        "timeframe_hours": hours,
        "summary": summary,
        "generated_at": datetime.utcnow()
    }

@app.get("/auth/security/events")
async def get_security_events(
    limit: int = 50,
    severity: Optional[str] = None,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """
    Get recent security events (admin only)
    """
    # Verify admin user
    user = auth_manager.get_current_user(db, token)
    
    query = db.query(SecurityEvent).order_by(SecurityEvent.timestamp.desc())
    
    if severity:
        query = query.filter(SecurityEvent.severity == severity.upper())
    
    events = query.limit(limit).all()
    
    return {
        "events": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "severity": event.severity,
                "ip_address": event.ip_address,
                "username": event.username,
                "details": event.details,
                "timestamp": event.timestamp,
                "resolved": event.resolved
            }
            for event in events
        ],
        "total_count": len(events)
    }

@app.post("/auth/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Register new user (admin only in production)
    """
    client_ip = request.client.host if request else "unknown"
    
    # Check if user already exists
    existing_user = auth_manager.get_user_by_username(db, user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username sudah terdaftar"
        )
    
    # Create new user
    new_user = auth_manager.create_user(db, user_data)
    
    # Log user creation
    auth_manager.log_user_action(db, new_user.id, None, "USER_CREATED", client_ip)
    
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        created_at=new_user.created_at
    )

@app.get("/auth/me", response_model=UserResponse)
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """
    Get current authenticated user information
    """
    user = auth_manager.get_current_user(db, token)
    return UserResponse(
        id=user.id,
        username=user.username,
        created_at=user.created_at
    )

@app.post("/auth/logout")
async def logout(
    token: str = Depends(oauth2_scheme),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Logout user and log the action
    """
    client_ip = request.client.host if request else "unknown"
    # 🔧 FIX: Extract user agent for logout too
    user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"
    
    user = auth_manager.get_current_user(db, token)
    
    # 🔧 FIX: Log logout action WITH user agent
    auth_manager.log_user_action(db, user.id, None, "LOGOUT", client_ip, user_agent)
    
    return {"message": "Logout berhasil"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
