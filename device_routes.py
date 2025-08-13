# device_routes.py - Updated dengan InfluxDB validation
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from device_service import DeviceService
from device_schemas import (
    ProductListResponse, 
    DeviceRegistrationRequest, 
    DeviceRegistrationResponse,
    ProductResponse
)
from models import User
from typing import List
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Temporary auth dependency - ganti dengan yang sesuai
async def get_current_user_temp(db: Session = Depends(get_db)):
    """Temporary auth - replace with actual auth system"""
    from models import User
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=401, detail="No user found")
    return user

@router.get("/products", response_model=List[ProductListResponse])
async def get_all_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Endpoint untuk mendapatkan semua products untuk Things page
    """
    try:
        products = DeviceService.get_all_products(db)
        logger.info(f"User {current_user.username} retrieved {len(products)} products")
        return products
    
    except Exception as e:
        logger.error(f"Error retrieving products: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving products"
        )

# 🆕 UPDATED: Add async and InfluxDB validation support
@router.post("/register", response_model=DeviceRegistrationResponse)
async def register_device(
    request: DeviceRegistrationRequest,
    skip_influx: bool = False,  # 🆕 Added query parameter
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Endpoint untuk mendaftarkan device baru berdasarkan chip ID
    Logic: chipid = "F0101" + String(ESP.getEfuseMac())
    Jika prefix "F0101" -> Commercial Freezer
    
    Query Parameters:
    - skip_influx: Set true untuk bypass InfluxDB validation (development only)
    """
    try:
        chip_id = request.device_id.strip()
        
        # Validasi format chip ID
        if len(chip_id) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Device ID terlalu pendek. Format yang benar: F0101 + MAC Address"
            )
        
        logger.info(f"User {current_user.username} attempting to register device: {chip_id} (skip_influx: {skip_influx})")
        
        # 🆕 UPDATED: Changed to await for async call
        success, message, product = await DeviceService.create_product_from_chip_id(
            db, chip_id, str(current_user.id), skip_influx_validation=skip_influx
        )
        
        if success:
            logger.info(f"Device {chip_id} successfully registered by {current_user.username}")
            return DeviceRegistrationResponse(
                success=True,
                message=message,
                product=None
            )
        else:
            # Customize error messages untuk user experience yang lebih baik
            if "sudah terdaftar" in message.lower():
                logger.info(f"Device {chip_id} already registered - informing user")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,  # Conflict instead of Bad Request
                    detail={
                        "type": "DEVICE_ALREADY_REGISTERED",
                        "message": f"Device {chip_id} sudah terdaftar di sistem",
                        "suggestion": "Periksa daftar device di halaman Things, atau gunakan Device ID yang berbeda"
                    }
                )
            elif "tidak dikenal" in message.lower():
                logger.warning(f"Unknown device prefix for {chip_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "type": "UNKNOWN_DEVICE_PREFIX",
                        "message": f"Prefix '{chip_id[:5]}' tidak dikenal",
                        "suggestion": "Pastikan Device ID dimulai dengan F0101 untuk Commercial Freezer"
                    }
                )
            # 🆕 TAMBAHAN: InfluxDB validation error handling
            elif "influxdb validation failed" in message.lower():
                logger.warning(f"InfluxDB validation failed for {chip_id}")
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "type": "INFLUXDB_VALIDATION_FAILED",
                        "message": message.replace("InfluxDB Validation Failed: ", ""),
                        "suggestion": "Pastikan device sudah aktif dan mengirim data ke InfluxDB sebelum registrasi"
                    }
                )
            elif "tidak ditemukan" in message.lower():
                logger.error(f"Product type not found for {chip_id}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "type": "PRODUCT_TYPE_NOT_FOUND",
                        "message": "Tipe device tidak ditemukan di database",
                        "suggestion": "Hubungi administrator sistem"
                    }
                )
            else:
                logger.warning(f"Failed to register device {chip_id}: {message}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "type": "REGISTRATION_FAILED",
                        "message": message,
                        "suggestion": "Periksa format Device ID atau hubungi administrator"
                    }
                )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during device registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "INTERNAL_ERROR",
                "message": "Terjadi kesalahan sistem saat mendaftarkan device",
                "suggestion": "Coba lagi dalam beberapa saat atau hubungi administrator"
            }
        )

@router.put("/products/{product_id}/name")
async def update_product_name(
    product_id: str,
    new_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Update nama product
    """
    try:
        success, message = DeviceService.update_product_name(db, product_id, new_name)
        
        if success:
            logger.info(f"User {current_user.username} updated product {product_id} name to {new_name}")
            return {"success": True, "message": message}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating product name: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error updating product name"
        )

@router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Hapus product
    """
    try:
        logger.info(f"Attempting to delete product: {product_id}")
        
        # Validate UUID format
        try:
            import uuid as uuid_lib
            uuid_lib.UUID(product_id)
        except ValueError:
            logger.error(f"Invalid UUID format: {product_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid product ID format: {product_id}"
            )
        
        success, message = DeviceService.delete_product(db, product_id)
        
        if success:
            logger.info(f"User {current_user.username} deleted product {product_id}")
            return {"success": True, "message": message}
        else:
            logger.warning(f"Failed to delete product {product_id}: {message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error deleting product {product_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting product: {str(e)}"
        )

@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product_detail(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Get detail product untuk debugging/monitoring
    """
    try:
        from device_models import Product, ProductType, ProductState
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product tidak ditemukan"
            )
        
        return product
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving product detail: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving product detail"
        )

# 🆕 TAMBAHAN: Debug endpoints
@router.get("/debug/products")
async def debug_products(db: Session = Depends(get_db)):
    """Debug endpoint untuk check data"""
    try:
        from device_models import Product, ProductType, ProductState
        
        products = db.query(Product).all()
        product_states = db.query(ProductState).all()
        product_types = db.query(ProductType).all()
        
        return {
            "total_products": len(products),
            "total_states": len(product_states),
            "total_types": len(product_types),
            "products": [{"id": str(p.id), "serial": p.serial_number, "name": p.name} for p in products[:5]],
            "states": [{"id": str(s.id), "product_id": str(s.product_id), "mode": s.current_mode} for s in product_states[:5]]
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/debug/influx/{device_id}")
async def test_influx_device(device_id: str):
    """Test InfluxDB connectivity dan device validation"""
    try:
        from influxdb_service import InfluxDBService
        from datetime import datetime
        
        influx_service = InfluxDBService()
        
        # Test basic connectivity
        exists, metadata = await influx_service.check_device_exists(device_id, time_window_minutes=60)
        
        # Test validation
        is_valid, validation_message, validation_metadata = await influx_service.validate_device_for_registration(device_id)
        
        # Test last activity
        last_activity = await influx_service.get_device_last_activity(device_id)
        
        return {
            "device_id": device_id,
            "influx_connectivity": "OK",
            "exists_in_influx": exists,
            "metadata": metadata,
            "validation_result": {
                "is_valid": is_valid,
                "message": validation_message,
                "metadata": validation_metadata
            },
            "last_activity": last_activity.isoformat() if last_activity else None,
            "test_timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"InfluxDB test error: {str(e)}")
        return {
            "device_id": device_id,
            "error": str(e),
            "influx_connectivity": "FAILED",
            "test_timestamp": datetime.utcnow().isoformat()
        }