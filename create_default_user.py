from sqlalchemy.orm import Session
from database import get_db, engine
from models import Base, User
from auth import AuthManager
from schemas import UserCreate

# Create tables
Base.metadata.create_all(bind=engine)

# Create default user
def create_default_user():
    db = next(get_db())
    auth_manager = AuthManager()
    
    # Check if user exists
    existing_user = auth_manager.get_user_by_username(db, "admin")
    if not existing_user:
        user_data = UserCreate(username="admin", password="admin123")
        new_user = auth_manager.create_user(db, user_data)
        print(f"Default user created: {new_user.username}")
    else:
        print("Default user already exists")

if __name__ == "__main__":
    create_default_user()