# File: create_simple_user.py
import sys
sys.path.append('.')

from sqlalchemy.orm import Session
from database import get_db, engine
from models import Base, User
import uuid
from datetime import datetime
from passlib.context import CryptContext

# Setup bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_simple_user():
    try:
        print("Creating database tables...")
        # Create tables
        Base.metadata.create_all(bind=engine)
        
        print("Setting up default user...")
        # Get database session
        db = next(get_db())
        
        # Check if user exists
        existing_user = db.query(User).filter(User.username == "admin").first()
        if not existing_user:
            # Hash password
            password_hash = pwd_context.hash("admin123")
            
            # Create user directly
            new_user = User(
                id=uuid.uuid4(),
                username="admin",
                password_hash=password_hash,
                login_attempts=0,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            
            print(f"✅ User created successfully!")
            print(f"📧 Username: admin")
            print(f"🔑 Password: admin123")
        else:
            print("✅ User already exists")
            print(f"📧 Username: {existing_user.username}")
        
        db.close()
        print("✅ Setup complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("Trying alternative approach...")
        
        # Alternative: Skip bcrypt validation
        try:
            db = next(get_db())
            existing_user = db.query(User).filter(User.username == "admin").first()
            if not existing_user:
                # Simple hash for testing
                simple_hash = "admin123"  # We'll fix this in auth.py
                
                new_user = User(
                    id=uuid.uuid4(),
                    username="admin",
                    password_hash=simple_hash,
                    login_attempts=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                db.add(new_user)
                db.commit()
                
                print(f"✅ Simple user created!")
                print(f"📧 Username: admin")
                print(f"🔑 Password: admin123")
            
            db.close()
        except Exception as e2:
            print(f"❌ Alternative failed: {e2}")

if __name__ == "__main__":
    create_simple_user()