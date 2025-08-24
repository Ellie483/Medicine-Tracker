from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_database
import os
from dotenv import load_dotenv
from passlib.hash import bcrypt
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "medicine123")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def hash_password(password: str) -> str:
    return bcrypt.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_user_by_username(username: str):
    db = get_database()
    user = await db.users.find_one({"username": username})
    return user

async def authenticate_user(username: str, password: str):
    user = await get_user_by_username(username)
    if not user:
        return False
    if not verify_password(password, user["password"]):
        return False
    return user

# ✅ Get the current user from session
async def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        print("❌ No active session found → User not authenticated")
        raise HTTPException(status_code=401, detail="Not authenticated")

    print(f"✅ User session found → {user['username']} ({user['role']})")
    return user


# ✅ Role checker dependency
def require_role(required_role: str):
    def role_checker(current_user: dict = Depends(get_current_user)):
        print(f"🔍 Checking role → required: {required_role}, current: {current_user['role']}")
        
        if current_user["role"] != required_role:
            print(f"❌ Permission denied for {current_user['username']} → Needs {required_role}")
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        print(f"✅ Permission granted → {current_user['username']} has role {required_role}")
        return current_user

    return role_checker

