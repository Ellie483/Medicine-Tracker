from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from database import get_database
from auth import get_password_hash

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
