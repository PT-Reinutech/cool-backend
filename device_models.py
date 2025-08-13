# device_models.py
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

Base = declarative_base()

class ProductType(Base):
    __tablename__ = "product_types"
    __table_args__ = {"schema": "device"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    description = Column(Text)
    maintenance_interval_day = Column(Integer)
    has_auto_mode = Column(Boolean, default=False)
    has_manual_mode = Column(Boolean, default=False)
    supports_fan_control = Column(Boolean, default=False)
    supports_compressor = Column(Boolean, default=False)
    supports_defrost = Column(Boolean, default=False)
    supports_alarm_config = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    products = relationship("Product", back_populates="product_type")

class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "device"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    serial_number = Column(Text, unique=True, nullable=False, index=True)
    product_type_id = Column(UUID(as_uuid=True), ForeignKey("device.product_types.id"), nullable=False)
    name = Column(Text, nullable=False)
    location_lat = Column(Float, nullable=True)
    location_long = Column(Float, nullable=True)
    installed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    product_type = relationship("ProductType", back_populates="products")
    product_state = relationship("ProductState", back_populates="product", uselist=False)
    alarms = relationship("Alarm", back_populates="product")

class ProductState(Base):
    __tablename__ = "product_state"
    __table_args__ = {"schema": "device"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("device.products.id"), nullable=False)
    current_mode = Column(Text, nullable=True)
    current_cycle_status = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    product = relationship("Product", back_populates="product_state")

class Alarm(Base):
    __tablename__ = "alarms"
    __table_args__ = {"schema": "device"}
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("device.products.id"), nullable=False)
    alarm_type = Column(Text, nullable=False)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)
    
    # Relationship
    product = relationship("Product", back_populates="alarms")