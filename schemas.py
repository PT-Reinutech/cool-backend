# schemas.py - Updated with account_type
from pydantic import BaseModel, validator
from datetime import datetime
from typing import Optional, Literal
import uuid
import re

class UserCreate(BaseModel):
    username: str
    password: str
    account_type: Literal['admin', 'teknisi', 'client'] = 'admin'  # NEW FIELD
    
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
    account_type: str  # NEW FIELD
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse  # Updated to include account_type