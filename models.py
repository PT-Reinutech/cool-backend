#models.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(Text, unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    login_attempts = Column(Integer, default=0)
    cooldown_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user_logs = relationship("UserLog", back_populates="user")

class UserLog(Base):
    __tablename__ = "user_logs"
    __table_args__ = {"schema": "auth"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=True)  # Can be null for non-device actions
    action = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Additional fields for security logging
    ip_address = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    
    # Relationship
    user = relationship("User", back_populates="user_logs")

class FailedLoginAttempt(Base):
    __tablename__ = "failed_login_attempts"
    __table_args__ = {"schema": "auth"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(Text, nullable=False, index=True)  # Store username even if user doesn't exist
    ip_address = Column(Text, nullable=True, index=True)
    user_agent = Column(Text, nullable=True)
    attempt_time = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    failure_reason = Column(Text, nullable=True)  # "INVALID_USERNAME", "INVALID_PASSWORD", "ACCOUNT_LOCKED"
    
    # Optional: Link to user if exists
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=True)
    
    # Geographical/security info
    country = Column(Text, nullable=True)
    is_suspicious = Column(Boolean, default=False)
    
    # Relationship (optional)
    user = relationship("User", backref="failed_attempts")

class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = {"schema": "auth"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(Text, nullable=False, index=True)  # "BRUTE_FORCE", "SUSPICIOUS_IP", "RATE_LIMIT"
    severity = Column(Text, default="MEDIUM")  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    ip_address = Column(Text, nullable=True, index=True)
    user_agent = Column(Text, nullable=True)
    username = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON string with additional info
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Text, nullable=True)
    
    # Optional user link
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=True)
    user = relationship("User", backref="security_events")