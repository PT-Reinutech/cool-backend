# auth.py
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
import os
import uuid

from models import User, UserLog
from schemas import UserCreate

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours
MAX_LOGIN_ATTEMPTS = 5
COOLDOWN_MINUTES = 15

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthManager:
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash"""
        return pwd_context.verify(plain_password, hashed_password)
    
    def get_password_hash(self, password: str) -> str:
        """Hash password"""
        return pwd_context.hash(password)
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Create JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
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
            return None
        
        # Check if user is in cooldown
        if user.cooldown_until and user.cooldown_until > datetime.utcnow():
            return None
        
        if not self.verify_password(password, user.password_hash):
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
        """Get current user from JWT token"""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            if username is None:
                raise credentials_exception
        except JWTError:
            raise credentials_exception
        
        user = self.get_user_by_username(db, username)
        if user is None:
            raise credentials_exception
        
        return user
    
    def log_user_action(self, db: Session, user_id: uuid.UUID, product_id: Optional[uuid.UUID], 
                       action: str, client_ip: str = None):
        """Log user action"""
        log_entry = UserLog(
            user_id=user_id,
            product_id=product_id,
            action=action,
            ip_address=client_ip
        )
        
        db.add(log_entry)
        db.commit()
    
    def log_failed_attempt(self, db: Session, username: str, client_ip: str = None):
        """Log failed login attempt"""
        # Create a generic log entry for failed attempts
        # In production, you might want to store this separately
        pass