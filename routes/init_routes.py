# routes/init_routes.py

from database import get_database
from auth import hash_password

# This function will run at startup to ensure at least one admin exists
def init_default_users():
    db = get_database()

    existing_admin = db.users.find_one({"role": "admin"})
    if not existing_admin:
        db.users.insert_one({
            "username": "admin",
            "password": hash_password("admin123"),  # Default password
            "role": "admin"
        })
