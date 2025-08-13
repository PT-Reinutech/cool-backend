# device_routes.py
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
# Import auth functions (sesuaikan dengan struktur auth yang ada)
# from auth import get_current_user  # Jika ada
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
    # Return dummy user for now - replace this with actual auth
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

@router.post("/register", response_model=DeviceRegistrationResponse)
async def register_device(
    request: DeviceRegistrationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Endpoint untuk mendaftarkan device baru berdasarkan chip ID
    Logic: chipid = "F0101" + String(ESP.getEfuseMac())
    Jika prefix "F0101" -> Commercial Freezer
    """
    try:
        chip_id = request.device_id.strip()
        
        # Validasi format chip ID
        if len(chip_id) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Device ID terlalu pendek. Format yang benar: F0101 + MAC Address"
            )
        
        logger.info(f"User {current_user.username} attempting to register device: {chip_id}")
        
        # Proses registrasi device
        success, message, product = DeviceService.create_product_from_chip_id(
            db, chip_id, str(current_user.id)
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