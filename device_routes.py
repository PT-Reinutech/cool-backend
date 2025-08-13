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
from auth import get_current_user  # Assuming auth system exists
from models import User
from typing import List
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])

@router.get("/products", response_model=List[ProductListResponse])
async def get_all_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
    current_user: User = Depends(get_current_user)
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
                detail="Device ID terlalu pendek"
            )
        
        logger.info(f"User {current_user.username} attempting to register device: {chip_id}")
        
        # Proses registrasi device
        success, message, product = DeviceService.create_product_from_chip_id(
            db, chip_id, str(current_user.id)
        )
        
        if success:
            logger.info(f"Device {chip_id} successfully registered by {current_user.username}")
            
            # Log user action (assuming user_logs table exists)
            # You can implement logging here if needed
            
            return DeviceRegistrationResponse(
                success=True,
                message=message,
                product=None  # We don't need to return full product details
            )
        else:
            logger.warning(f"Failed to register device {chip_id}: {message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during device registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during device registration"
        )

@router.put("/products/{product_id}/name")
async def update_product_name(
    product_id: str,
    new_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
    current_user: User = Depends(get_current_user)
):
    """
    Hapus product
    """
    try:
        success, message = DeviceService.delete_product(db, product_id)
        
        if success:
            logger.info(f"User {current_user.username} deleted product {product_id}")
            return {"success": True, "message": message}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting product: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error deleting product"
        )

@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product_detail(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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