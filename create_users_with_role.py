# File: create_users_with_roles.py
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

def create_users_with_roles():
    """Create test users for all three roles"""
    try:
        print("Creating database tables...")
        # Create tables
        Base.metadata.create_all(bind=engine)
        
        print("Setting up users with different roles...")
        # Get database session
        db = next(get_db())
        
        # Users to create
        users_to_create = [
            {
                'username': 'admin',
                'password': 'admin123',
                'account_type': 'admin'
            },
            {
                'username': 'teknisi1',
                'password': 'teknisi123',
                'account_type': 'teknisi'
            },
            {
                'username': 'client1',
                'password': 'client123',
                'account_type': 'client'
            }
        ]
        
        for user_data in users_to_create:
            # Check if user exists
            existing_user = db.query(User).filter(User.username == user_data['username']).first()
            
            if not existing_user:
                try:
                    # Hash password
                    password_hash = pwd_context.hash(user_data['password'])
                    
                    # Create user
                    new_user = User(
                        id=uuid.uuid4(),
                        username=user_data['username'],
                        password_hash=password_hash,
                        account_type=user_data['account_type'],
                        login_attempts=0,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    
                    db.add(new_user)
                    db.commit()
                    db.refresh(new_user)
                    
                    print(f"✅ User '{user_data['username']}' ({user_data['account_type']}) created successfully!")
                    print(f"   📧 Username: {user_data['username']}")
                    print(f"   🔑 Password: {user_data['password']}")
                    print(f"   👤 Role: {user_data['account_type']}")
                    print()
                    
                except Exception as e:
                    print(f"❌ Error creating user {user_data['username']}: {e}")
                    db.rollback()
            else:
                # Update existing user's account_type if needed
                if existing_user.account_type != user_data['account_type']:
                    existing_user.account_type = user_data['account_type']
                    existing_user.updated_at = datetime.utcnow()
                    db.commit()
                    print(f"✅ Updated '{user_data['username']}' role to '{user_data['account_type']}'")
                else:
                    print(f"✅ User '{user_data['username']}' ({user_data['account_type']}) already exists")
        
        db.close()
        
        print("\n🎉 Setup complete!")
        print("\n📋 Test Credentials:")
        print("=" * 50)
        print("Admin Access:")
        print("  Username: admin")
        print("  Password: admin123")
        print("  Access: Dashboard, Things, Full System")
        print()
        print("Teknisi Access:")
        print("  Username: teknisi1") 
        print("  Password: teknisi123")
        print("  Access: Maintenance & Repair Forms")
        print()
        print("Client Access:")
        print("  Username: client1")
        print("  Password: client123")
        print("  Access: Equipment Status & Service Requests")
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        
        # Try alternative approach without bcrypt
        try:
            print("Trying alternative approach...")
            db = next(get_db())
            
            for user_data in users_to_create:
                existing_user = db.query(User).filter(User.username == user_data['username']).first()
                if not existing_user:
                    # Simple hash for testing (fix this in production)
                    simple_hash = user_data['password']  # We'll fix this in auth.py
                    
                    new_user = User(
                        id=uuid.uuid4(),
                        username=user_data['username'],
                        password_hash=simple_hash,
                        account_type=user_data['account_type'],
                        login_attempts=0,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    
                    db.add(new_user)
                    db.commit()
                    
                    print(f"✅ Simple user '{user_data['username']}' ({user_data['account_type']}) created!")
            
            db.close()
        except Exception as e2:
            print(f"❌ Alternative approach failed: {e2}")

if __name__ == "__main__":
    create_users_with_roles()