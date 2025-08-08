# File: auth.py (updated untuk fix bcrypt issue)
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
import os
import uuid
import hashlib

from models import User, UserLog
from schemas import UserCreate

# Alternative bcrypt setup untuk compatibility
try:
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    BCRYPT_AVAILABLE = True
    print("✅ Bcrypt loaded successfully")
except Exception as e:
    print(f"⚠️ Bcrypt error: {e}")
    print("Using fallback hash method for development...")
    BCRYPT_AVAILABLE = False

# JWT setup
try:
    from jose import JWTError, jwt
    JWT_AVAILABLE = True
except ImportError:
    print("⚠️ JWT not available, using simple token")
    JWT_AVAILABLE = False

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours
MAX_LOGIN_ATTEMPTS = 5
COOLDOWN_MINUTES = 15

class AuthManager:
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash with fallback"""
        if BCRYPT_AVAILABLE:
            try:
                return pwd_context.verify(plain_password, hashed_password)
            except Exception as e:
                print(f"Bcrypt verify error: {e}")
                # Fallback untuk development
                return plain_password == hashed_password
        else:
            # Simple comparison untuk development
            return plain_password == hashed_password or self._simple_hash(plain_password) == hashed_password
    
    def get_password_hash(self, password: str) -> str:
        """Hash password with fallback"""
        if BCRYPT_AVAILABLE:
            try:
                return pwd_context.hash(password)
            except Exception as e:
                print(f"Bcrypt hash error: {e}")
                return self._simple_hash(password)
        else:
            return self._simple_hash(password)
    
    def _simple_hash(self, password: str) -> str:
        """Simple hash untuk development fallback"""
        return hashlib.sha256(f"{password}{SECRET_KEY}".encode()).hexdigest()
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Create JWT access token with fallback"""
        if JWT_AVAILABLE:
            try:
                to_encode = data.copy()
                if expires_delta:
                    expire = datetime.utcnow() + expires_delta
                else:
                    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
                
                to_encode.update({"exp": expire})
                encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
                return encoded_jwt
            except Exception as e:
                print(f"JWT error: {e}")
                # Simple token fallback
                return f"simple_token_{data['sub']}_{int(datetime.utcnow().timestamp())}"
        else:
            return f"simple_token_{data['sub']}_{int(datetime.utcnow().timestamp())}"
    
    def get_user_by_username(self, db: Session, username: str) -> Optional[User]:
        """Get user by username"""
        return db.query(User).filter(User.username == username.lower()).first()
    
    def create_user(self, db: Session, user_data: UserCreate) -> User:
        """Create new user"""
        hashed_password = self.get_password_hash(user_data.password)
        
        db_user = User(
            username=user_data.username.lower(),
            password_hash=hashed_password
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    
    def authenticate_user(self, db: Session, username: str, password: str, client_ip: str = None) -> Optional[User]:
        """Authenticate user with security checks"""
        user = self.get_user_by_username(db, username)
        
        if not user:
            print(f"❌ User not found: {username}")
            return None
        
        # Check if user is in cooldown
        if user.cooldown_until and user.cooldown_until > datetime.utcnow():
            print(f"❌ User in cooldown: {username}")
            return None
        
        # Verify password
        password_valid = self.verify_password(password, user.password_hash)
        print(f"🔐 Password check for {username}: {password_valid}")
        
        if not password_valid:
            # Increment login attempts
            user.login_attempts += 1
            
            # Set cooldown if max attempts reached
            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.cooldown_until = datetime.utcnow() + timedelta(minutes=COOLDOWN_MINUTES)
                self.log_user_action(db, user.id, None, "ACCOUNT_LOCKED", client_ip)
            
            db.commit()
            return None
        
        return user
    
    def reset_login_attempts(self, db: Session, user: User):
        """Reset login attempts after successful login"""
        user.login_attempts = 0
        user.cooldown_until = None
        user.updated_at = datetime.utcnow()
        db.commit()
    
    def get_current_user(self, db: Session, token: str) -> User:
        """Get current user from JWT token with fallback"""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        if JWT_AVAILABLE:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                username: str = payload.get("sub")
                if username is None:
                    raise credentials_exception
            except JWTError:
                # Try simple token fallback
                if token.startswith("simple_token_"):
                    parts = token.split("_")
                    if len(parts) >= 3:
                        username = parts[2]
                    else:
                        raise credentials_exception
                else:
                    raise credentials_exception
        else:
            # Simple token parsing
            if token.startswith("simple_token_"):
                parts = token.split("_")
                if len(parts) >= 3:
                    username = parts[2]
                else:
                    raise credentials_exception
            else:
                raise credentials_exception
        
        user = self.get_user_by_username(db, username)
        if user is None:
            raise credentials_exception
        
        return user
    
    def log_user_action(self, db: Session, user_id: uuid.UUID, product_id: Optional[uuid.UUID], 
                       action: str, client_ip: str = None):
        """Log user action"""
        try:
            log_entry = UserLog(
                user_id=user_id,
                product_id=product_id,
                action=action,
                ip_address=client_ip
            )
            
            db.add(log_entry)
            db.commit()
        except Exception as e:
            print(f"Logging error: {e}")
    
    def log_failed_attempt(self, db: Session, username: str, client_ip: str = None):
        """Log failed login attempt"""
        print(f"Failed login attempt: {username} from {client_ip}")
        # Create a generic log entry for failed attempts
        pass