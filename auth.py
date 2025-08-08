# File: auth.py (Enhanced with IP-based cooldown)

import jwt
import bcrypt
import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from fastapi import HTTPException, status
from models import User, UserLog, FailedLoginAttempt, SecurityEvent

# Enhanced Configuration
SECRET_KEY = "koronka_iot_secret_key_2024"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# User-based limits
MAX_LOGIN_ATTEMPTS = 5
COOLDOWN_MINUTES = 15

# IP-based limits (NEW)
MAX_IP_ATTEMPTS = 10        # Max failed attempts from same IP
IP_COOLDOWN_MINUTES = 30   # IP cooldown duration 
MAX_FAILED_ATTEMPTS_PER_IP = 15  # Total failed attempts per IP per hour

class AuthManager:
    def __init__(self):
        self.pwd_context = bcrypt
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash"""
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    
    def get_password_hash(self, password: str) -> str:
        """Hash password"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
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
    
    # 🆕 NEW: IP-based cooldown checking
    def check_ip_cooldown(self, db: Session, client_ip: str) -> dict:
        """
        Check if IP is in cooldown period
        Returns: {
            'is_blocked': bool,
            'remaining_time': int (seconds),
            'failed_attempts': int,
            'cooldown_until': datetime
        }
        """
        if not client_ip or client_ip == "unknown":
            return {'is_blocked': False, 'remaining_time': 0, 'failed_attempts': 0, 'cooldown_until': None}
        
        # Check for recent failed attempts from this IP
        last_hour = datetime.utcnow() - timedelta(hours=1)
        last_cooldown_period = datetime.utcnow() - timedelta(minutes=IP_COOLDOWN_MINUTES)
        
        # Count failed attempts from this IP in the last cooldown period
        recent_failures = db.query(FailedLoginAttempt).filter(
            and_(
                FailedLoginAttempt.ip_address == client_ip,
                FailedLoginAttempt.attempt_time >= last_cooldown_period
            )
        ).order_by(FailedLoginAttempt.attempt_time.desc()).all()
        
        if len(recent_failures) >= MAX_IP_ATTEMPTS:
            # IP is in cooldown
            latest_attempt = recent_failures[0].attempt_time
            cooldown_until = latest_attempt + timedelta(minutes=IP_COOLDOWN_MINUTES)
            
            if cooldown_until > datetime.utcnow():
                remaining_seconds = int((cooldown_until - datetime.utcnow()).total_seconds())
                
                print(f"🚫 IP {client_ip} is in cooldown. {len(recent_failures)} attempts. {remaining_seconds}s remaining")
                
                return {
                    'is_blocked': True,
                    'remaining_time': remaining_seconds,
                    'failed_attempts': len(recent_failures),
                    'cooldown_until': cooldown_until
                }
        
        return {
            'is_blocked': False,
            'remaining_time': 0,
            'failed_attempts': len(recent_failures),
            'cooldown_until': None
        }
    
    # 🆕 NEW: IP-based attempt tracking
    def increment_ip_failed_attempts(self, db: Session, client_ip: str, username: str, 
                                   failure_reason: str, user_agent: str = None):
        """
        Track failed attempts by IP address
        """
        if not client_ip or client_ip == "unknown":
            return
        
        # Log the failed attempt
        self.log_failed_attempt(db, username, client_ip, user_agent, failure_reason)
        
        # Check if this IP should be flagged
        ip_status = self.check_ip_cooldown(db, client_ip)
        
        if ip_status['failed_attempts'] >= MAX_IP_ATTEMPTS:
            # Log security event
            self._log_security_event(
                db, "IP_COOLDOWN_TRIGGERED", "HIGH", client_ip, user_agent, username,
                f"IP {client_ip} triggered cooldown after {ip_status['failed_attempts']} failed attempts"
            )
            
            print(f"🚨 IP {client_ip} has been put into {IP_COOLDOWN_MINUTES}-minute cooldown")
    
    def get_user_by_username(self, db: Session, username: str) -> Optional[User]:
        """Get user by username"""
        return db.query(User).filter(User.username == username.lower()).first()
    
    def create_user(self, db: Session, user_data) -> User:
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
    
    # 🔧 ENHANCED: Authentication with IP cooldown
    def authenticate_user(self, db: Session, username: str, password: str, 
                         client_ip: str = None, user_agent: str = None) -> Optional[User]:
        """Authenticate user with IP-based cooldown protection"""
        
        # 🆕 STEP 1: Check IP cooldown FIRST
        ip_status = self.check_ip_cooldown(db, client_ip)
        if ip_status['is_blocked']:
            print(f"🚫 Authentication blocked - IP {client_ip} in cooldown for {ip_status['remaining_time']}s")
            
            # Log the blocked attempt
            self.log_failed_attempt(db, username, client_ip, user_agent, "IP_COOLDOWN_BLOCKED")
            
            # Return None to indicate authentication failure
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"IP address dalam cooldown. Tunggu {ip_status['remaining_time']} detik.",
                headers={"Retry-After": str(ip_status['remaining_time'])}
            )
        
        # STEP 2: Check for suspicious activity
        if self._is_suspicious_activity(db, client_ip, user_agent):
            self._log_security_event(db, "SUSPICIOUS_ACTIVITY", "HIGH", client_ip, 
                                   user_agent, username, "Suspicious login pattern detected")
        
        # STEP 3: Check if user exists
        user = self.get_user_by_username(db, username)
        if not user:
            # Increment IP failed attempts for invalid username
            self.increment_ip_failed_attempts(db, client_ip, username, "INVALID_USERNAME", user_agent)
            return None
        
        # STEP 4: Check user-level cooldown
        if user.cooldown_until and user.cooldown_until > datetime.utcnow():
            # Increment IP failed attempts for account locked
            self.increment_ip_failed_attempts(db, client_ip, username, "ACCOUNT_LOCKED", user_agent)
            return None
        
        # STEP 5: Verify password
        if not self.verify_password(password, user.password_hash):
            # Increment user login attempts
            user.login_attempts += 1
            
            # Increment IP failed attempts for wrong password
            self.increment_ip_failed_attempts(db, client_ip, username, "INVALID_PASSWORD", user_agent)
            
            # Set user cooldown if max attempts reached
            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.cooldown_until = datetime.utcnow() + timedelta(minutes=COOLDOWN_MINUTES)
                self.log_user_action(db, user.id, None, "ACCOUNT_LOCKED", client_ip, user_agent)
                
                # Log security event for user brute force
                self._log_security_event(db, "BRUTE_FORCE_ATTEMPT", "HIGH", client_ip,
                                       user_agent, username, f"Account locked after {MAX_LOGIN_ATTEMPTS} failed attempts")
            
            db.commit()
            return None
        
        # STEP 6: Successful authentication
        print(f"✅ Successful authentication for {username} from {client_ip}")
        
        # Reset user login attempts on successful login
        self.reset_login_attempts(db, user)
        
        # Log successful login
        self.log_user_action(db, user.id, None, "LOGIN_SUCCESS", client_ip, user_agent)
        
        return user
    
    def log_failed_attempt(self, db: Session, username: str, client_ip: str = None, 
                          user_agent: str = None, failure_reason: str = "UNKNOWN", 
                          user_id: uuid.UUID = None):
        """Log failed login attempt to database"""
        try:
            # Analyze if this is suspicious
            is_suspicious = self._analyze_suspicious_attempt(user_agent, client_ip, failure_reason)
            
            # Create failed login record
            failed_attempt = FailedLoginAttempt(
                username=username.lower(),
                ip_address=client_ip,
                user_agent=user_agent,
                attempt_time=datetime.utcnow(),
                failure_reason=failure_reason,
                user_id=user_id,
                is_suspicious=is_suspicious
            )
            
            db.add(failed_attempt)
            
            # Log to user_logs as well for centralized logging
            if user_id:
                user_log = UserLog(
                    user_id=user_id,
                    product_id=None,
                    action=f"LOGIN_FAILED_{failure_reason}",
                    ip_address=client_ip,
                    user_agent=user_agent
                )
                db.add(user_log)
            
            db.commit()
            
            print(f"❌ Failed login logged: {username} from {client_ip} - Reason: {failure_reason}")
            
        except Exception as e:
            print(f"❌ Error logging failed attempt: {e}")
            db.rollback()
    
    def log_user_action(self, db: Session, user_id: uuid.UUID, product_id: Optional[uuid.UUID], 
                       action: str, client_ip: str = None, user_agent: str = None):
        """Log user action"""
        try:
            user_log = UserLog(
                user_id=user_id,
                product_id=product_id,
                action=action,
                ip_address=client_ip,
                user_agent=user_agent
            )
            
            db.add(user_log)
            db.commit()
            
        except Exception as e:
            print(f"❌ Error logging user action: {e}")
            db.rollback()
    
    def _is_suspicious_activity(self, db: Session, client_ip: str, user_agent: str) -> bool:
        """Detect suspicious login patterns"""
        if not client_ip:
            return False
        
        last_hour = datetime.utcnow() - timedelta(hours=1)
        
        # Check for high frequency attempts from same IP
        ip_attempts = db.query(FailedLoginAttempt).filter(
            FailedLoginAttempt.ip_address == client_ip,
            FailedLoginAttempt.attempt_time >= last_hour
        ).count()
        
        if ip_attempts >= MAX_FAILED_ATTEMPTS_PER_IP:
            return True
        
        # Check for user agent anomalies
        if user_agent and len(user_agent) < 10:
            return True
        
        return False
    
    def _analyze_suspicious_attempt(self, user_agent: str, client_ip: str, failure_reason: str) -> bool:
        """Analyze if a login attempt is suspicious"""
        suspicious_indicators = []
        
        # Check user agent
        if not user_agent or len(user_agent) < 10:
            suspicious_indicators.append("Short/missing user agent")
        
        # Check for common bot patterns
        if user_agent and any(bot in user_agent.lower() for bot in ['bot', 'crawler', 'spider', 'scraper']):
            suspicious_indicators.append("Bot user agent")
        
        # Check failure reason patterns
        if failure_reason in ["INVALID_USERNAME", "IP_COOLDOWN_BLOCKED"]:
            suspicious_indicators.append(f"Suspicious failure: {failure_reason}")
        
        return len(suspicious_indicators) > 0
    
    def _log_security_event(self, db: Session, event_type: str, severity: str, 
                           ip_address: str, user_agent: str, username: str, details: str):
        """Log security events"""
        try:
            security_event = SecurityEvent(
                event_type=event_type,
                severity=severity,
                ip_address=ip_address,
                user_agent=user_agent,
                username=username,
                details=details,
                timestamp=datetime.utcnow()
            )
            
            db.add(security_event)
            db.commit()
            
            print(f"🚨 SECURITY EVENT: {event_type} - {severity}")
            print(f"Details: {details}")
            
        except Exception as e:
            print(f"Error logging security event: {e}")
            db.rollback()
    
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
        except jwt.JWTError:
            raise credentials_exception
        
        user = self.get_user_by_username(db, username)
        if user is None:
            raise credentials_exception
        
        return user
    
    # 🆕 NEW: Get IP cooldown status for frontend
    def get_ip_status(self, db: Session, client_ip: str) -> dict:
        """Get IP status for frontend to display cooldown info"""
        return self.check_ip_cooldown(db, client_ip)