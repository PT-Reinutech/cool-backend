
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
        "*"
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

@app.post("/auth/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Secure login endpoint with rate limiting and security measures
    """
    client_ip = request.client.host if request else "unknown"
    
    # Authenticate user with security checks
    user = auth_manager.authenticate_user(db, form_data.username, form_data.password, client_ip)
    
    if not user:
        # Log failed attempt
        auth_manager.log_failed_attempt(db, form_data.username, client_ip)
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
    
    # Log successful login
    auth_manager.log_user_action(db, user.id, None, "LOGIN_SUCCESS", client_ip)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "created_at": user.created_at
        }
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
    user = auth_manager.get_current_user(db, token)
    
    # Log logout action
    auth_manager.log_user_action(db, user.id, None, "LOGOUT", client_ip)
    
    return {"message": "Logout berhasil"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
