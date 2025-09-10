from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from database import get_database
from passlib.context import CryptContext
import requests
import os
import shutil

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def geocode_address(address: str):
    """Geocode an address using OpenStreetMap Nominatim API."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    try:
        response = requests.get(url, params=params, headers={"User-Agent": "MedicineTracker/1.0"}, timeout=5)
        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None

@router.get("/register")
def register_role_selection(request: Request):
    return templates.TemplateResponse("register_role_selection.html", {"request": request})

@router.get("/register/seller")
def register_seller_form(request: Request):
    townships = [
        "Ahlone", "Bahan", "Dagon", "Dawbon", "Hlaing", "Insein", "Kamayut", "Kawhmu",
        "Kyeemyindaing", "Kyauktada", "Lanmadaw", "Latha", "Mayangone", "Mingaladon",
        "Mingalartaungnyunt", "North Okkalapa", "North Dagon", "Pabedan", "Pazundaung",
        "Sanchaung", "Shwepyitha", "South Okkalapa", "South Dagon", "Seikkyi Kanaungto",
        "Tamwe", "Thaketa", "Thingangyun", "Thuwanna", "Twante", "Dala", "Hmawbi",
        "Hlegu", "Htantabin", "Htantha", "Kyaukse", "Kyaukpyu", "Kyaunggone", "Mawlamyine",
        "Myingyan", "Yankin"
    ]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return templates.TemplateResponse("register_seller.html", {"request": request, "townships": townships, "days": days})

@router.post("/register/seller")
async def register_seller(
    request: Request,
    pharmacy_name: str = Form(...),
    license_number: str = Form(...),
    phone: str = Form(...),
    township: str = Form(...),
    address: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    payment_phone: str = Form(None),
    qrCode: UploadFile = File(None),
    latitude: str = Form(None),
    longitude: str = Form(None),
    mon_start: str = Form(None),
    mon_end: str = Form(None),
    tue_start: str = Form(None),
    tue_end: str = Form(None),
    wed_start: str = Form(None),
    wed_end: str = Form(None),
    thu_start: str = Form(None),
    thu_end: str = Form(None),
    fri_start: str = Form(None),
    fri_end: str = Form(None),
    sat_start: str = Form(None),
    sat_end: str = Form(None),
    sun_start: str = Form(None),
    sun_end: str = Form(None),
):
    db = get_database()

    # Basic validations
    if password != confirm_password:
        return templates.TemplateResponse("register_seller.html", {
            "request": request,
            "error": "Passwords do not match.",
        })

    if db.users.find_one({"username": {"$regex": f"^{pharmacy_name.lower().replace(' ', '_')}"}}) is not None:
        pass  # This is a light check; later username generation will ensure uniqueness

    if db.pharmacy_profiles.find_one({"license_number": license_number}):
        return templates.TemplateResponse("register_seller.html", {
            "request": request,
            "error": "License number already exists. Please check your license number."
        })

    # Generate username
    base_username = pharmacy_name.lower().replace(" ", "_").replace(",", "").replace(".", "")
    username = base_username
    counter = 1
    while db.users.find_one({"username": username}):
        username = f"{base_username}_{counter}"
        counter += 1

    # Create user
    hashed = get_password_hash(password)
    user_data = {
        "username": username,
        "password": hashed,
        "role": "seller",
        "is_profile_complete": True,
        "created_at": datetime.utcnow()
    }
    user_result = db.users.insert_one(user_data)

    # Assemble operating hours dict
    operating_hours = {}
    mapping = {
        "mon": (mon_start, mon_end),
        "tue": (tue_start, tue_end),
        "wed": (wed_start, wed_end),
        "thu": (thu_start, thu_end),
        "fri": (fri_start, fri_end),
        "sat": (sat_start, sat_end),
        "sun": (sun_start, sun_end),
    }
    for day_key, (s, e) in mapping.items():
        if s and e:
            operating_hours[day_key] = {"open": s, "close": e}

    # Handle coordinates
    if latitude and longitude:
        try:
            lat, lon = float(latitude), float(longitude)
        except Exception:
            lat, lon = None, None
    else:
        lat, lon = geocode_address(address)

    # Save QR code file if uploaded
    qr_filename = None
    if qrCode:
        upload_dir = os.path.join(os.getcwd(), "static", "qr_codes")
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = f"{int(datetime.utcnow().timestamp())}_{qrCode.filename}"
        dest_path = os.path.join(upload_dir, safe_name)
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(qrCode.file, buffer)
        qr_filename = f"/static/qr_codes/{safe_name}"

    pharmacy_profile_data = {
        "user_id": str(user_result.inserted_id),
        "pharmacy_name": pharmacy_name,
        "license_number": license_number,
        "contact_info": phone,
        "payment_phone": payment_phone,
        "payment_qr_url": "/static/qr_codes/qr2.jpg",
        "payment_instructions": "Scan with KBZPay. Include your Order ID in the note.",
        "township": township,
        "address": address,
        "latitude": lat,
        "longitude": lon,
        "operating_hours": operating_hours,
        "created_at": datetime.utcnow()
    }
    db.pharmacy_profiles.insert_one(pharmacy_profile_data)

    return RedirectResponse(url="/?registered=seller", status_code=302)

# Buyer registration endpoints
@router.get("/register/buyer")
def register_buyer_form(request: Request):
    return templates.TemplateResponse("register_buyer.html", {"request": request})

@router.post("/register/buyer")
def register_buyer(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    age: int = Form(...),
    address: str = Form(...),
):
    db = get_database()
    if db.users.find_one({"username": username}):
        return templates.TemplateResponse("register_buyer.html", {
            "request": request,
            "error": "Username already exists."
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
        "created_at": datetime.utcnow()
    }
    db.buyer_profiles.insert_one(buyer_profile_data)

    return RedirectResponse(url="/?registered=buyer", status_code=302)
