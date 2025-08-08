
# models.py
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

# schemas.py
from pydantic import BaseModel, validator
from datetime import datetime
from typing import Optional
import uuid
import re

class UserCreate(BaseModel):
    username: str
    password: str
    
    @validator('username')
    def validate_username(cls, v):
        if len(v) < 3:
            raise ValueError('Username minimal 3 karakter')
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username hanya boleh mengandung huruf, angka, dan underscore')
        return v.lower()
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password minimal 8 karakter')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password harus mengandung minimal 1 huruf besar')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password harus mengandung minimal 1 huruf kecil')
        if not re.search(r'\d', v):
            raise ValueError('Password harus mengandung minimal 1 angka')
        return v

class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse
