# device_schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid

class ProductTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    maintenance_interval_day: Optional[int] = None
    has_auto_mode: bool = False
    has_manual_mode: bool = False
    supports_fan_control: bool = False
    supports_compressor: bool = False
    supports_defrost: bool = False
    supports_alarm_config: bool = False

class ProductTypeResponse(ProductTypeBase):
    id: uuid.UUID
    created_at: datetime
    
    class Config:
        from_attributes = True

class ProductStateResponse(BaseModel):
    id: uuid.UUID
    current_mode: Optional[str] = None
    current_cycle_status: Optional[str] = None
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ProductBase(BaseModel):
    serial_number: str = Field(..., description="Serial number perangkat (chip ID)")
    name: str
    location_lat: Optional[float] = None
    location_long: Optional[float] = None

class ProductCreate(ProductBase):
    pass

class ProductResponse(ProductBase):
    id: uuid.UUID
    product_type_id: uuid.UUID
    installed_at: datetime
    created_at: datetime
    
    # Relationships
    product_type: ProductTypeResponse
    product_state: Optional[ProductStateResponse] = None
    
    class Config:
        from_attributes = True

class ProductListResponse(BaseModel):
    id: uuid.UUID
    serial_number: str
    name: str
    product_type_name: str
    status: str  # online/offline berdasarkan product_state
    installed_at: datetime
    location_lat: Optional[float] = None
    location_long: Optional[float] = None
    
    class Config:
        from_attributes = True

class DeviceRegistrationRequest(BaseModel):
    device_id: str = Field(..., description="Device ID dari ESP32 (chip ID)")
    
class DeviceRegistrationResponse(BaseModel):
    success: bool
    message: str
    product: Optional[ProductResponse] = None