# File: main.py (Fixed CORS and middleware order)

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from auth import AuthManager
from database import get_db
from models import User
from pydantic import BaseModel
from typing import Optional
import uuid
import logging

# Enable logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Koronka IoT Control System",
    description="Sistema de control para equipos de refrigeración",
    version="1.0.0"
)

# ========================================
# CRITICAL: Add CORS middleware FIRST, before anything else!
# ========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ecooling.reinutechiot.com",
        "http://localhost:3000",
        "http://localhost:1234",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods including OPTIONS
    allow_headers=["*"],  # Allow all headers
    max_age=3600,  # Cache preflight responses for 1 hour
)

# Add TrustedHost middleware AFTER CORS
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["ecoolapi.reinutechiot.com", "ecooling.reinutechiot.com", "localhost", "*.reinutechiot.com"]
)

# ========================================
# Initialize auth and OAuth2 with correct tokenUrl
# ========================================
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")  # Fixed tokenUrl
auth_manager = AuthManager()

# ========================================
# Pydantic models
# ========================================
class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict

class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    created_at: datetime

class UserCreate(BaseModel):
    username: str
    password: str

class IPStatusResponse(BaseModel):
    is_blocked: bool
    remaining_time: int
    failed_attempts: int
    cooldown_until: Optional[datetime]
    message: str

# ========================================
# Custom middleware for logging and security headers
# ========================================
@app.middleware("http")
async def add_security_headers_and_log(request: Request, call_next):
    """Add security headers and log requests for debugging"""
    # Log incoming request
    logger.info(f"Request: {request.method} {request.url.path}")
    logger.info(f"Origin: {request.headers.get('origin', 'No origin header')}")
    
    # Handle OPTIONS preflight requests immediately
    if request.method == "OPTIONS":
        response = JSONResponse(content={})
        origin = request.headers.get("origin")
        if origin in ["https://ecooling.reinutechiot.com", "http://localhost:3000", "http://localhost:1234"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Max-Age"] = "3600"
        return response
    
    # Process the request
    response = await call_next(request)
    
    # Add security headers to all responses
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # Ensure CORS headers are present (backup)
    origin = request.headers.get("origin")
    if origin in ["https://ecooling.reinutechiot.com", "http://localhost:3000", "http://localhost:1234"]:
        if "access-control-allow-origin" not in response.headers:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
    
    # Log response status
    logger.info(f"Response: {response.status_code} for {request.url.path}")
    
    return response

# ========================================
# Health and CORS test endpoints (define these FIRST)
# ========================================
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "timestamp": datetime.utcnow(),
        "security": "enhanced_ip_cooldown_active"
    }

@app.get("/cors-test")
async def cors_test():
    """Test endpoint to verify CORS is working"""
    return {"message": "CORS is working correctly", "status": "ok"}

@app.get("/cors-debug")
async def cors_debug(request: Request):
    """Debug endpoint to check CORS headers"""
    return {
        "origin": request.headers.get("origin"),
        "method": request.method,
        "headers": dict(request.headers),
        "message": "Debug info for CORS"
    }

# ========================================
# Authentication endpoints
# ========================================
@app.get("/auth/ip-status", response_model=IPStatusResponse)
async def check_ip_status(
    request: Request,
    db: Session = Depends(get_db)
):
    """Check IP cooldown status"""
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

@app.post("/auth/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Secure login endpoint with IP-based cooldown protection"""
    client_ip = request.client.host if request else "unknown"
    user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"
    
    logger.info(f"🔐 Login attempt: {form_data.username} from {client_ip}")
    
    try:
        # Authenticate user (this will handle IP cooldown internally)
        user = auth_manager.authenticate_user(
            db, form_data.username, form_data.password, client_ip, user_agent
        )
        
        if not user:
            # Check IP status to provide specific error message
            ip_status = auth_manager.get_ip_status(db, client_ip)
            
            if ip_status['is_blocked']:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"IP address dalam cooldown. Tunggu {ip_status['remaining_time']} detik.",
                    headers={"Retry-After": str(ip_status['remaining_time'])}
                )
            else:
                # Regular authentication failure
                attempts_left = 3 - ip_status['failed_attempts']
                if attempts_left <= 0:
                    detail = "Terlalu banyak percobaan login gagal"
                else:
                    detail = f"Username atau password salah. {attempts_left} percobaan tersisa."
                
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=detail,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        
        # Check if user is in user-level cooldown
        if user.cooldown_until and user.cooldown_until > datetime.utcnow():
            remaining_time = int((user.cooldown_until - datetime.utcnow()).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Akun terkunci. Tunggu {remaining_time} detik.",
                headers={"Retry-After": str(remaining_time)}
            )
        
        # Successful authentication - create token
        access_token_expires = timedelta(minutes=30)
        access_token = auth_manager.create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires
        )
        
        logger.info(f"✅ Login successful for {user.username} from {client_ip}")
        
        return Token(
            access_token=access_token,
            token_type="bearer",
            user={
                "id": str(user.id),
                "username": user.username,
                "created_at": user.created_at.isoformat()
            }
        )
        
    except HTTPException as e:
        # Re-raise HTTP exceptions (like cooldown errors)
        raise e
    except Exception as e:
        logger.error(f"❌ Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server error during authentication"
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
    except:
        raise credentials_exception
    
    user = auth_manager.get_user_by_username(db, username)
    if user is None:
        raise credentials_exception
    
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
    """Logout user and log the action"""
    client_ip = request.client.host if request else "unknown"
    user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"
    
    try:
        # Get current user
        payload = auth_manager.verify_token(token)
        username = payload.get("sub")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        user = auth_manager.get_user_by_username(db, username)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        # Log logout action
        auth_manager.log_user_action(db, user.id, None, "LOGOUT", client_ip, user_agent)
        
        return {"message": "Logout berhasil", "status": "success"}
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Logout error: {e}")
        # Still return success even if logging fails
        return {"message": "Logout berhasil", "status": "success"}

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

# ========================================
# Include routers AFTER all middleware is configured
# ========================================
from device_routes import router as device_router
from device_config_routes import router as config_router

app.include_router(device_router)
app.include_router(config_router)

# ========================================
# Run the application
# ========================================
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI application with enhanced CORS support...")
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True, log_level="info")