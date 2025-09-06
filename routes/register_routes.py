from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request, Form, HTTPException, status
from fastapi import Depends
from typing import Optional
from datetime import datetime
from database import get_database
from auth import get_password_hash
from passlib.context import CryptContext
from bson import ObjectId
from auth import create_access_token  # Add this import

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/register", response_class=RedirectResponse)
def register_role_selection(request: Request):
    return templates.TemplateResponse("register_role_selection.html", {"request": request})

@router.get("/register/buyer")
def register_buyer_form(request: Request):
    return templates.TemplateResponse("register_buyer.html", {"request": request})

@router.get("/register/seller")
def register_seller_form(request: Request):
    return templates.TemplateResponse("register_seller.html", {"request": request})

@router.post("/register/buyer")
def register_buyer(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    age: int = Form(...),
    address: str = Form(...)
):
    db = get_database()
    existing_user = db.users.find_one({"username": username})
    if existing_user:
        return templates.TemplateResponse("register_buyer.html", {
            "request": request,
            "error": "Username already exists. Please choose a different username."
        })

    user_data = {
        "username": username,
        "password": get_password_hash(password),
        "role": "buyer",
        "is_profile_complete": True,
        "created_at": datetime.utcnow()
    }
    user_result = db.users.insert_one(user_data)

    buyer_profile_data = {
        "user_id": str(user_result.inserted_id),
        "name": name,
        "age": age,
        "address": address,
        "coordinates": None,
        "favorite_pharmacies": [],
        "created_at": datetime.utcnow()
    }
    db.buyer_profiles.insert_one(buyer_profile_data)
    return RedirectResponse(url="/?registered=buyer", status_code=302)


@router.post("/register/seller")
def register_seller(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    pharmacy_name: str = Form(...),
    license_number: str = Form(...),
    contact_info: str = Form(...),
    address: str = Form(...),
    operating_hours: str = Form(...)
): 
    db = get_database()
    if db.users.find_one({"username": username}):
        return templates.TemplateResponse("register_seller.html", {
            "request": request,
            "error": "Username already exists. Please choose a different username."
        })

    if db.pharmacy_profiles.find_one({"license_number": license_number}):
        return templates.TemplateResponse("register_seller.html", {
            "request": request,
            "error": "License number already exists. Please check your license number."
        })

    user_data = {
        "username": username,
        "password": get_password_hash(password),
        "role": "seller",
        "is_profile_complete": True,
        "created_at": datetime.utcnow()
    }
    user_result = db.users.insert_one(user_data)

    pharmacy_profile_data = {
        "user_id": str(user_result.inserted_id),
        "pharmacy_name": pharmacy_name,
        "license_number": license_number,
        "contact_info": contact_info,
        "address": address,
        "coordinates": None,
        "operating_hours": operating_hours,
        "created_at": datetime.utcnow()
    }
    db.pharmacy_profiles.insert_one(pharmacy_profile_data)
    return RedirectResponse(url="/?registered=seller", status_code=302)


# Password context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    db = get_database()
    print("🔍 Checking credentials for:", username)

    user = db.users.find_one({"username": username})
    
    if not user or not verify_password(password, user["password"]):
        print("❌ Login failed for:", username)
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid credentials"
        })

    # ✅ Save user info into session
    request.session["user"] = {
        "username": user["username"],
        "role": user["role"],
        "id": str(user["_id"]),
        "is_profile_complete": bool(user["is_profile_complete"])
    }
    
    print(f"✅ User session created for {username} with role {user['role']}")

    # ✅ Redirect based on role
    if user["role"] == "buyer":
        print("➡️ Redirecting buyer to /buyer/home")
        return RedirectResponse(url="/buyer/home", status_code=302)
    elif user["role"] == "seller":
        print("➡️ Redirecting seller to /seller/home")
        return RedirectResponse(url="/seller/home", status_code=302)
    elif user["role"] == "admin":
        return RedirectResponse(url="/admin_dashboard", status_code=302)
    else:
        print("⚠️ Unknown role for:", username)
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Unknown user role"
        })
    

@router.get("/logout")
async def logout(request: Request):
    print("🚪 Logging out user:", request.session.get("user", {}).get("username"))
    request.session.clear()
    print("✅ Session cleared")
    return RedirectResponse(url="/")

