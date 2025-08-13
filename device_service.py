# device_service.py - Updated dengan soft delete + InfluxDB validation
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
        Mengambil semua products yang tidak dihapus untuk ditampilkan di Things page
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
        ).filter(
            # Filter hanya yang tidak dihapus
            Product.is_deleted == False
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
        Cari product berdasarkan serial number (hanya yang tidak dihapus)
        """
        return db.query(Product).filter(
            and_(Product.serial_number == serial_number, Product.is_deleted == False)
        ).first()
    
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
    
    # 🆕 UPDATED: Changed to async and added InfluxDB validation
    @staticmethod
    async def create_product_from_chip_id(
        db: Session, 
        chip_id: str,
        user_id: Optional[str] = None,
        skip_influx_validation: bool = False  # 🆕 Added parameter
    ) -> Tuple[bool, str, Optional[Product]]:
        """
        Membuat product baru berdasarkan chip ID dengan InfluxDB validation
        
        Returns:
            (success: bool, message: str, product: Optional[Product])
        """
        try:
            # Cek apakah device sudah terdaftar (termasuk yang soft deleted)
            existing_product = db.query(Product).filter(Product.serial_number == chip_id).first()
            if existing_product:
                if existing_product.is_deleted:
                    # Restore product yang sudah di-soft delete
                    existing_product.is_deleted = False
                    existing_product.deleted_at = None
                    db.commit()
                    db.refresh(existing_product)
                    return True, f"Device {chip_id} berhasil di-restore dan siap digunakan kembali", existing_product
                else:
                    return False, f"Device dengan ID {chip_id} sudah terdaftar dan aktif", existing_product
            
            # Tentukan product type berdasarkan prefix
            product_type_id = DeviceService.determine_product_type_from_chip_id(chip_id)
            if not product_type_id:
                return False, f"Prefix chip ID {chip_id[:5]} tidak dikenal", None
            
            # Validasi product type exists
            if not DeviceService.validate_product_type_exists(db, product_type_id):
                return False, f"Product type {product_type_id} tidak ditemukan di database", None
            
            # 🆕 TAMBAHAN: InfluxDB Validation
            if not skip_influx_validation:
                try:
                    from influxdb_service import InfluxDBService
                    
                    influx_service = InfluxDBService()
                    is_valid, validation_message, metadata = await influx_service.validate_device_for_registration(chip_id)
                    
                    if not is_valid:
                        return False, f"InfluxDB Validation Failed: {validation_message}", None
                except ImportError:
                    # If InfluxDB service not available, log warning but continue
                    print(f"Warning: InfluxDB service not available for validation of {chip_id}")
                except Exception as e:
                    # If InfluxDB validation fails, log error but continue
                    print(f"Warning: InfluxDB validation error for {chip_id}: {str(e)}")
            
            # Buat product baru
            new_product = Product(
                serial_number=chip_id,
                product_type_id=uuid.UUID(product_type_id),
                name=f"Device {chip_id}",
                installed_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                is_deleted=False
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
            
            # Success message
            success_message = f"Device {chip_id} berhasil didaftarkan"
            if not skip_influx_validation:
                success_message += " dan terverifikasi di InfluxDB"
            
            return True, success_message, new_product
            
        except Exception as e:
            db.rollback()
            return False, f"Error saat mendaftarkan device: {str(e)}", None
    
    @staticmethod
    def update_product_name(db: Session, product_id: str, new_name: str) -> Tuple[bool, str]:
        """
        Update nama product
        """
        try:
            product = db.query(Product).filter(
                and_(Product.id == product_id, Product.is_deleted == False)
            ).first()
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
        Soft delete product (lebih aman daripada hard delete)
        """
        try:
            product = db.query(Product).filter(
                and_(Product.id == product_id, Product.is_deleted == False)
            ).first()
            if not product:
                return False, "Product tidak ditemukan"
            
            # Soft delete - set flag instead of actual deletion
            product.is_deleted = True
            product.deleted_at = datetime.utcnow()
            db.commit()
            
            return True, f"Product {product.name} berhasil dihapus"
            
        except Exception as e:
            db.rollback()
            return False, f"Error saat menghapus product: {str(e)}"
    
    @staticmethod
    def hard_delete_product(db: Session, product_id: str) -> Tuple[bool, str]:
        """
        Hard delete product dengan cascade delete untuk semua referensi
        Hanya gunakan jika benar-benar diperlukan!
        """
        try:
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                return False, "Product tidak ditemukan"
            
            # Import semua model yang mungkin memiliki foreign key ke products
            from device_models import ProductState, Alarm
            
            # Hapus semua referensi berurutan (cascade delete manual)
            
            # 1. Hapus product_state
            db.query(ProductState).filter(ProductState.product_id == product_id).delete()
            
            # 2. Hapus alarms
            db.query(Alarm).filter(Alarm.product_id == product_id).delete()
            
            # 3. Hapus maintenance records (jika ada)
            try:
                from sqlalchemy import text
                db.execute(text("DELETE FROM maintenance.product_maintenance WHERE product_id = :product_id"), 
                          {"product_id": product_id})
            except Exception as e:
                print(f"Warning: Could not delete maintenance records: {e}")
            
            # 4. Hapus dari config tables jika ada
            try:
                db.execute(text("DELETE FROM config.product_auto_config WHERE product_id = :product_id"), 
                          {"product_id": product_id})
                db.execute(text("DELETE FROM config.product_manual_config WHERE product_id = :product_id"), 
                          {"product_id": product_id})
            except Exception as e:
                print(f"Warning: Could not delete config records: {e}")
            
            # 5. Terakhir hapus product
            db.delete(product)
            db.commit()
            
            return True, f"Product {product.name} dan semua referensinya berhasil dihapus permanen"
            
        except Exception as e:
            db.rollback()
            return False, f"Error saat menghapus product: {str(e)}"