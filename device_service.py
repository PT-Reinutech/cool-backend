# device_service.py
from sqlalchemy.orm import Session
from sqlalchemy import and_
from device_models import Product, ProductType, ProductState
from device_schemas import ProductCreate, ProductListResponse
from typing import List, Optional, Tuple
import uuid
from datetime import datetime

class DeviceService:
    """
    Service layer untuk device management di Koronka
    """
    
    # Mapping prefix chip ID ke product type
    CHIP_PREFIX_TO_PRODUCT_TYPE = {
        "F0101": "1109005e-92f2-4eec-8b19-4afccf4f5052"  # Commercial Freezer
    }
    
    @staticmethod
    def get_all_products(db: Session) -> List[ProductListResponse]:
        """
        Mengambil semua products untuk ditampilkan di Things page
        """
        query = db.query(
            Product.id,
            Product.serial_number,
            Product.name,
            ProductType.name.label('product_type_name'),
            Product.installed_at,
            Product.location_lat,
            Product.location_long,
            ProductState.current_mode,
            ProductState.current_cycle_status
        ).join(
            ProductType, Product.product_type_id == ProductType.id
        ).outerjoin(
            ProductState, Product.id == ProductState.product_id
        ).order_by(Product.created_at.desc())
        
        results = query.all()
        
        products = []
        for result in results:
            # Determine status based on product_state
            status = "offline"
            if result.current_mode is not None:
                status = "online"
            
            products.append(ProductListResponse(
                id=result.id,
                serial_number=result.serial_number,
                name=result.name,
                product_type_name=result.product_type_name,
                status=status,
                installed_at=result.installed_at,
                location_lat=result.location_lat,
                location_long=result.location_long
            ))
        
        return products
    
    @staticmethod
    def get_product_by_serial(db: Session, serial_number: str) -> Optional[Product]:
        """
        Cari product berdasarkan serial number
        """
        return db.query(Product).filter(Product.serial_number == serial_number).first()
    
    @staticmethod
    def determine_product_type_from_chip_id(chip_id: str) -> Optional[str]:
        """
        Menentukan product_type_id berdasarkan prefix chip ID
        Logic: chipid = "F0101" + String(ESP.getEfuseMac())
        """
        for prefix, product_type_id in DeviceService.CHIP_PREFIX_TO_PRODUCT_TYPE.items():
            if chip_id.startswith(prefix):
                return product_type_id
        return None
    
    @staticmethod
    def validate_product_type_exists(db: Session, product_type_id: str) -> bool:
        """
        Validasi apakah product type ID ada di database
        """
        product_type = db.query(ProductType).filter(ProductType.id == product_type_id).first()
        return product_type is not None
    
    @staticmethod
    def create_product_from_chip_id(
        db: Session, 
        chip_id: str,
        user_id: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Product]]:
        """
        Membuat product baru berdasarkan chip ID
        
        Returns:
            (success: bool, message: str, product: Optional[Product])
        """
        try:
            # Cek apakah device sudah terdaftar
            existing_product = DeviceService.get_product_by_serial(db, chip_id)
            if existing_product:
                return False, f"Device dengan ID {chip_id} sudah terdaftar", existing_product
            
            # Tentukan product type berdasarkan prefix
            product_type_id = DeviceService.determine_product_type_from_chip_id(chip_id)
            if not product_type_id:
                return False, f"Prefix chip ID {chip_id[:5]} tidak dikenal", None
            
            # Validasi product type exists
            if not DeviceService.validate_product_type_exists(db, product_type_id):
                return False, f"Product type {product_type_id} tidak ditemukan di database", None
            
            # Buat product baru
            new_product = Product(
                serial_number=chip_id,
                product_type_id=uuid.UUID(product_type_id),
                name=f"Device {chip_id}",
                installed_at=datetime.utcnow(),
                created_at=datetime.utcnow()
            )
            
            db.add(new_product)
            db.flush()  # Flush untuk mendapatkan ID sebelum commit
            
            # Buat initial product state
            initial_state = ProductState(
                product_id=new_product.id,
                current_mode="offline",
                current_cycle_status="idle",
                updated_at=datetime.utcnow()
            )
            
            db.add(initial_state)
            db.commit()
            db.refresh(new_product)
            
            return True, f"Device {chip_id} berhasil didaftarkan", new_product
            
        except Exception as e:
            db.rollback()
            return False, f"Error saat mendaftarkan device: {str(e)}", None
    
    @staticmethod
    def update_product_name(db: Session, product_id: str, new_name: str) -> Tuple[bool, str]:
        """
        Update nama product
        """
        try:
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                return False, "Product tidak ditemukan"
            
            product.name = new_name
            db.commit()
            
            return True, "Nama product berhasil diupdate"
            
        except Exception as e:
            db.rollback()
            return False, f"Error saat update nama: {str(e)}"
    
    @staticmethod
    def delete_product(db: Session, product_id: str) -> Tuple[bool, str]:
        """
        Hapus product (soft delete atau hard delete)
        """
        try:
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                return False, "Product tidak ditemukan"
            
            # Hapus product state dulu
            db.query(ProductState).filter(ProductState.product_id == product_id).delete()
            
            # Hapus product
            db.delete(product)
            db.commit()
            
            return True, f"Product {product.name} berhasil dihapus"
            
        except Exception as e:
            db.rollback()
            return False, f"Error saat menghapus product: {str(e)}"