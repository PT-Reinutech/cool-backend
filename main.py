# File: main.py - Complete Fixed Version with Custom CORS

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from auth import AuthManager
from database import get_db
from models import User
from pydantic import BaseModel
from typing import Optional
import uuid
import logging
import json

# ========================================
# Setup logging
# ========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========================================
# Initialize FastAPI app
# ========================================
app = FastAPI(
    title="Koronka IoT Control System",
    description="Sistema de control para equipos de refrigeración",
    version="1.0.0"
)

# ========================================
# ALLOWED ORIGINS - Define once
# ========================================
ALLOWED_ORIGINS = [
    "https://ecooling.reinutechiot.com",
    "http://localhost:3000",
    "http://localhost:1234",
]

# ========================================
# CRITICAL: Custom CORS Middleware - MUST BE FIRST!
# This replaces FastAPI's built-in CORSMiddleware
# ========================================
@app.middleware("http")
async def custom_cors_middleware(request: Request, call_next):
    """
    Custom CORS middleware that reliably adds headers to ALL responses
    """
    origin = request.headers.get("origin")
    method = request.method
    
    # Debug logging
    logger.info(f"📨 {method} {request.url.path}")
    logger.info(f"📍 Origin: {origin}")
    logger.info(f"🔑 Headers: Authorization={request.headers.get('authorization', 'None')}")
    
    # Handle preflight OPTIONS requests
    if method == "OPTIONS":
        response = Response(
            content="",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": origin if origin in ALLOWED_ORIGINS else "",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
                "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, Origin, User-Agent, X-Client-App, X-Client-Version",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "86400",
                "Content-Type": "text/plain",
            }
        )
        logger.info(f"✅ OPTIONS response with CORS headers")
        return response
    
    # Process the actual request
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"❌ Error processing request: {e}")
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
    
    # Add CORS headers to ALL responses (GET, POST, PUT, DELETE, etc.)
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Type"
        
        # Log that we added CORS headers
        logger.info(f"✅ Added CORS headers for origin: {origin}")
    else:
        logger.warning(f"⚠️ Origin not allowed: {origin}")
    
    # Log response status
    logger.info(f"📤 Response: {response.status_code} for {request.url.path}")
    logger.info(f"📋 Response headers: {dict(response.headers)}")
    
    return response

# ========================================
# Security headers middleware (AFTER CORS!)
# ========================================
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    
    # Only add security headers if not already present
    if "X-Frame-Options" not in response.headers:
        response.headers["X-Frame-Options"] = "DENY"
    if "X-Content-Type-Options" not in response.headers:
        response.headers["X-Content-Type-Options"] = "nosniff"
    if "X-XSS-Protection" not in response.headers:
        response.headers["X-XSS-Protection"] = "1; mode=block"
    if "Strict-Transport-Security" not in response.headers:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    return response

# ========================================
# TrustedHost middleware (optional, after security headers)
# ========================================
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "ecoolapi.reinutechiot.com",
        "ecooling.reinutechiot.com",
        "localhost",
        "127.0.0.1",
        "*.reinutechiot.com"
    ]
)

# ========================================
# Initialize Auth
# ========================================
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
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
# Test endpoints - Define these FIRST
# ========================================
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Koronka IoT Control System API",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "security": "enhanced_ip_cooldown_active",
        "cors": "custom_middleware_active"
    }

@app.get("/cors-test")
async def cors_test(request: Request):
    """Test endpoint to verify CORS is working"""
    return {
        "message": "CORS is working correctly",
        "origin": request.headers.get("origin"),
        "method": request.method,
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/cors-debug")
async def cors_debug(request: Request):
    """Debug endpoint to check request headers"""
    return {
        "origin": request.headers.get("origin"),
        "method": request.method,
        "headers": dict(request.headers),
        "url": str(request.url),
        "message": "Debug information for CORS troubleshooting"
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
    logger.info(f"🔍 Checking IP status for {request.client.host}")
    
    client_ip = request.client.host
    
    try:
        # Get IP status from auth manager
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
    except Exception as e:
        logger.error(f"Error checking IP status: {e}")
        # Return default status if error
        return IPStatusResponse(
            is_blocked=False,
            remaining_time=0,
            failed_attempts=0,
            cooldown_until=None,
            message="IP status normal"
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
        # Authenticate user
        user = auth_manager.authenticate_user(
            db, form_data.username, form_data.password, client_ip, user_agent
        )
        
        if not user:
            # Check IP status for specific error message
            ip_status = auth_manager.get_ip_status(db, client_ip)
            
            if ip_status['is_blocked']:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"IP address dalam cooldown. Tunggu {ip_status['remaining_time']} detik.",
                    headers={"Retry-After": str(ip_status['remaining_time'])}
                )
            else:
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
        
        # Check user-level cooldown
        if user.cooldown_until and user.cooldown_until > datetime.utcnow():
            remaining_time = int((user.cooldown_until - datetime.utcnow()).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Akun terkunci. Tunggu {remaining_time} detik.",
                headers={"Retry-After": str(remaining_time)}
            )
        
        # Create access token
        access_token_expires = timedelta(minutes=30)
        access_token = auth_manager.create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires
        )
        
        logger.info(f"✅ Login successful for {user.username}")
        
        return Token(
            access_token=access_token,
            token_type="bearer",
            user={
                "id": str(user.id),
                "username": user.username,
                "created_at": user.created_at.isoformat()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server error during authentication"
        )

@app.get("/auth/me", response_model=UserResponse)
async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get current authenticated user"""
    # Get token from Authorization header
    auth_header = request.headers.get("authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("No valid authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = auth_header.split(" ")[1]
    
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
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
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
    request: Request,
    db: Session = Depends(get_db)
):
    """Logout user and log the action"""
    client_ip = request.client.host if request else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Get token from header
    auth_header = request.headers.get("authorization")
    
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = auth_manager.verify_token(token)
            username = payload.get("sub")
            if username:
                user = auth_manager.get_user_by_username(db, username)
                if user:
                    auth_manager.log_user_action(
                        db, user.id, None, "LOGOUT", client_ip, user_agent
                    )
                    logger.info(f"✅ User {username} logged out")
        except Exception as e:
            logger.error(f"Logout error: {e}")
    
    # Always return success for logout
    return {"message": "Logout berhasil", "status": "success"}

@app.post("/auth/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Register new user"""
    client_ip = request.client.host if request else "unknown"
    
    # Check if user exists
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
    
    logger.info(f"✅ New user registered: {new_user.username}")
    
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        created_at=new_user.created_at
    )

@app.get("/auth/security-status")
async def get_security_status(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get security status summary"""
    # Get token from header
    auth_header = request.headers.get("authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    token = auth_header.split(" ")[1]
    
    try:
        # Verify token
        payload = auth_manager.verify_token(token)
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get security summary
        summary = auth_manager.get_failed_attempts_summary(db, hours=24)
        
        return {
            "status": "active",
            "ip_cooldown_minutes": 30,
            "max_ip_attempts": 3,
            "failed_attempts_24h": summary
        }
    except Exception as e:
        logger.error(f"Security status error: {e}")
        raise HTTPException(status_code=500, detail="Error getting security status")

# ========================================
# Include routers LAST (after all middleware and core endpoints)
# ========================================
try:
    from device_routes import router as device_router
    from device_config_routes import router as config_router
    
    app.include_router(device_router)
    app.include_router(config_router)
    logger.info("✅ Device routers loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️ Could not import device routers: {e}")
    # Continue without device routers for testing

# ========================================
# Run the application
# ========================================
if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 Starting Koronka IoT Control System API with Custom CORS...")
    logger.info(f"📍 Allowed origins: {ALLOWED_ORIGINS}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
        access_log=True
    )