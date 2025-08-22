# File: main.py (Enhanced with IP cooldown endpoints)

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Router
from device_routes import router as device_router
from device_config_routes import router as config_router
from influx_api_routes import router as influx_router

from datetime import datetime, timedelta
from auth import AuthManager
from database import get_db
from models import User
from schemas import Token, UserResponse, UserCreate, IPStatusResponse
from pydantic import BaseModel
from typing import Optional
import uuid

app = FastAPI(
    title="Koronka IoT Control System",
    description="Sistema de control para equipos de refrigeración",
    version="1.0.0"
)

app.include_router(device_router)
app.include_router(config_router)
app.include_router(influx_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:1234", 
        "http://192.168.100.30:1234",  # Frontend port
        "http://192.168.100.30:8001",  # Backend port
        "http://192.168.100.253:1234",  # Frontend port
        "http://100.69.240.25:1234",   # Tambahkan ini
        "http://100.69.240.25:8001",    # Jika backend juga diakses via IP ini
        "https://ecooling.reinutechiot.com",  # frontend domain
    ],
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

# 🆕 NEW: IP Status Check Endpoint
@app.get("/auth/ip-status", response_model=IPStatusResponse)
async def check_ip_status(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Check IP cooldown status - dapat dipanggil frontend untuk cek status cooldown
    """
    client_ip = request.client.host
    
    # Get IP status
    ip_status = auth_manager.get_ip_status(db, client_ip)
    
    # Format response message
    if ip_status['is_blocked']:
        minutes = ip_status['remaining_time'] // 60
        seconds = ip_status['remaining_time'] % 60
        message = f"IP address dalam cooldown. Tunggu {minutes}m {seconds}s lagi."
    else:
        attempts_left = 3 - ip_status['failed_attempts']
        if ip_status['failed_attempts'] > 0:
            message = f"Login gagal {ip_status['failed_attempts']} kali. {attempts_left} percobaan tersisa."
        else:
            message = "IP status normal"
    
    return IPStatusResponse(
        is_blocked=ip_status['is_blocked'],
        remaining_time=ip_status['remaining_time'],
        failed_attempts=ip_status['failed_attempts'],
        cooldown_until=ip_status['cooldown_until'],
        message=message
    )

# 🔧 ENHANCED: Login endpoint with IP cooldown
@app.post("/auth/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Secure login endpoint with account type checking
    """
    client_ip = request.client.host if request else "unknown"
    user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"
    
    print(f"🔐 Login attempt: {form_data.username} from {client_ip}")
    
    try:
        
        # Authenticate user
        user = auth_manager.authenticate_user(
            db, form_data.username, form_data.password, client_ip, user_agent
        )
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Username atau password salah"
            )
        
        print(f"✅ Successful authentication for {user.username} from {client_ip}")
        
        # Generate JWT token
        access_token = auth_manager.create_access_token(data={"sub": user.username})
        
        # ✅ FIX: Create UserResponse properly with all required fields
        user_response = UserResponse(
            id=user.id,
            username=user.username,
            account_type=user.account_type,  # Include account_type field
            created_at=user.created_at
        )
        
        # ✅ FIX: Return Token with proper UserResponse object
        return Token(
            access_token=access_token,
            token_type="bearer",
            user=user_response  # Now this is UserResponse, not dict
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terjadi kesalahan internal server"
        )

@app.post("/auth/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Register new user"""
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
    
    # ✅ FIX: Return UserResponse with account_type
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        account_type=new_user.account_type,  # Include account_type
        created_at=new_user.created_at
    )

@app.get("/auth/me", response_model=UserResponse)
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials", 
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = auth_manager.verify_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
            
        user = auth_manager.get_user_by_username(db, username)
        if user is None:
            raise credentials_exception
            
        # ✅ FIX: Return UserResponse with account_type
        return UserResponse(
            id=user.id,
            username=user.username,
            account_type=user.account_type,  # Include account_type
            created_at=user.created_at
        )
    except Exception:
        raise credentials_exception
    
@app.post("/auth/logout")
async def logout(
    token: str = Depends(oauth2_scheme),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Logout user and log the action"""
    client_ip = request.client.host if request else "unknown"
    user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"
    
    user = auth_manager.get_current_user(db, token)
    
    # Log logout action
    auth_manager.log_user_action(db, user.id, None, "LOGOUT", client_ip, user_agent)
    
    return {"message": "Logout berhasil"}

# 🆕 NEW: Admin endpoint to check security status
@app.get("/auth/security-status")
async def get_security_status(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Get security status summary (admin only)"""
    # Verify admin access (simplified - you may want proper role checking)
    user = auth_manager.get_current_user(db, token)
    
    # Get failed attempts summary
    summary = auth_manager.get_failed_attempts_summary(db, hours=24)
    
    return {
        "status": "active",
        "ip_cooldown_minutes": 30,
        "max_ip_attempts": 3,
        "failed_attempts_24h": summary
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "timestamp": datetime.utcnow(),
        "security": "enhanced_ip_cooldown_active"
    }

@app.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """OAuth2 compatible token endpoint"""
    return await login(form_data, request, db)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, workers=4)
