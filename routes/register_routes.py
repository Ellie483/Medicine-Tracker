from fastapi import APIRouter, Request, Form
import requests
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from database import get_database
from auth import get_password_hash
from passlib.context import CryptContext
from math import sqrt, cos
import re

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# -----------------------------
# Password context
# -----------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# -----------------------------
# Myanmar township list
# -----------------------------
MYANMAR_TOWNSHIPS = [
    "Ahlone","Bahan","Botataung","Dagon Seikkan","Dagon","Dawbon","Hlaing","Hlaing Tharyar",
    "Hmawbi","Insein","Kamayut","Kawhmu","Kyauktada","Kyimyindaing","Latha","Mayangone",
    "Mingaladon","Mingalartaungnyunt","North Okkalapa","Pabedan","Pazundaung",
    "Sanchaung","Shwepyitha","South Okkalapa","Tamwe","Thingangyun","Thaketa","Thuwunna",
    "Yangon","Yangon East","Yangon West","Yangon North","Yangon South"
]

MYANMAR_TOWNSHIPS_LOWER = {t.lower() for t in MYANMAR_TOWNSHIPS}

# -----------------------------
# Normalize township names
# -----------------------------
def normalize_township(name: str):
    """
    Normalize township names:
    - Remove extra spaces
    - Capitalize each word
    - Return if exists in MYANMAR_TOWNSHIPS ignoring case
    """
    if not name:
        return None
    name_clean = " ".join(name.strip().split())
    normalized = " ".join([w.capitalize() for w in name_clean.split()])

    # Match against full list
    for tw in MYANMAR_TOWNSHIPS:
        if tw.lower() in normalized.lower():
            return tw
    return None

# -----------------------------
# Geocoding function
# -----------------------------
def geocode_address(address: str):
    """
    Return township, latitude, longitude.
    Township is normalized robustly.
    """
    # Extract township from address text first
    township_from_text = normalize_township(address)

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1, "addressdetails": 1}
    headers = {"User-Agent": "MedicineTracker/1.0"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        data = response.json()
        if data and len(data) > 0:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])

            # Try to get township from geocoding result
            addr_details = data[0].get("address", {})
            township_raw = (
                addr_details.get("suburb")
                or addr_details.get("city_district")
                or addr_details.get("town")
                or addr_details.get("village")
                or addr_details.get("municipality")
                or addr_details.get("county")
                or addr_details.get("city")
            )
            township_from_geo = normalize_township(township_raw)

            # Prefer text-extracted township
            township = township_from_text or township_from_geo

            if township:
                return township, lat, lon
    except Exception as e:
        print("Geocoding error:", e)

    # Fallback: return None if township cannot be determined
    return None, None, None

# -----------------------------
# Distance calculation
# -----------------------------
def simple_distance_km(lat1, lon1, lat2, lon2):
    lat_km = (lat2 - lat1) * 111
    lon_km = (lon2 - lon1) * 111 * cos(lat1 * 3.14159265 / 180)
    return sqrt(lat_km**2 + lon_km**2)

# -----------------------------
# Nearest pharmacies
# -----------------------------
def get_nearest_pharmacies(user_township, user_lat, user_lon, db, limit=5):
    pharmacies = list(db.pharmacy_profiles.find({}))
    results = []

    for pharmacy in pharmacies:
        pharmacy_township = pharmacy.get("township")
        ph_lat = pharmacy["coordinates"]["latitude"]
        ph_lon = pharmacy["coordinates"]["longitude"]

        # If township matches, distance = 0
        if pharmacy_township and user_township and pharmacy_township.lower() == user_township.lower():
            distance = 0
        else:
            distance = simple_distance_km(user_lat, user_lon, ph_lat, ph_lon)

        results.append({
            "pharmacy_name": pharmacy["pharmacy_name"],
            "address": pharmacy["address"],
            "township": pharmacy_township,
            "distance_km": round(distance, 2)
        })

    results.sort(key=lambda x: x["distance_km"])
    return results[:limit]

# -----------------------------
# Registration routes
# -----------------------------
@router.get("/register", response_class=RedirectResponse)
def register_role_selection(request: Request):
    return templates.TemplateResponse("register_role_selection.html", {"request": request})

@router.get("/register/buyer")
def register_buyer_form(request: Request):
    return templates.TemplateResponse("register_buyer.html", {"request": request})

@router.get("/register/seller")
def register_seller_form(request: Request):
    return templates.TemplateResponse("register_seller.html", {"request": request})

# -----------------------------
# Buyer registration
# -----------------------------
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
    if db.users.find_one({"username": username}):
        return templates.TemplateResponse("register_buyer.html", {"request": request, "error": "Username already exists."})

    township, lat, lon = geocode_address(address)
    if not township:
        return templates.TemplateResponse("register_buyer.html", {"request": request, "error": "Address must include a valid Myanmar township."})

    user_data = {"username": username, "password": get_password_hash(password), "role": "buyer", "is_profile_complete": True, "created_at": datetime.utcnow()}
    user_result = db.users.insert_one(user_data)

    buyer_profile_data = {
        "user_id": str(user_result.inserted_id),
        "name": name,
        "age": age,
        "address": address,
        "township": township,
        "coordinates": {"latitude": lat, "longitude": lon} if lat and lon else {},
        "favorite_pharmacies": [],
        "created_at": datetime.utcnow()
    }
    db.buyer_profiles.insert_one(buyer_profile_data)

    return RedirectResponse(url="/?registered=buyer", status_code=302)

# -----------------------------
# Seller registration
# -----------------------------
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
        return templates.TemplateResponse("register_seller.html", {"request": request, "error": "Username already exists."})
    if db.pharmacy_profiles.find_one({"license_number": license_number}):
        return templates.TemplateResponse("register_seller.html", {"request": request, "error": "License number already exists."})

    township, lat, lon = geocode_address(address)
    if not township:
        return templates.TemplateResponse("register_seller.html", {"request": request, "error": "Address must include a valid Myanmar township."})

    user_data = {"username": username, "password": get_password_hash(password), "role": "seller", "is_profile_complete": True, "created_at": datetime.utcnow()}
    user_result = db.users.insert_one(user_data)

    pharmacy_profile_data = {
        "user_id": str(user_result.inserted_id),
        "pharmacy_name": pharmacy_name,
        "license_number": license_number,
        "contact_info": contact_info,
        "address": address,
        "township": township,
        "coordinates": {"latitude": lat, "longitude": lon} if lat and lon else {},
        "operating_hours": operating_hours,
        "created_at": datetime.utcnow()
    }
    db.pharmacy_profiles.insert_one(pharmacy_profile_data)

    return RedirectResponse(url="/?registered=seller", status_code=302)

# -----------------------------
# Login route
# -----------------------------
@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    db = get_database()
    user = db.users.find_one({"username": username})
    if not user or not verify_password(password, user["password"]):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

    request.session["user"] = {"username": user["username"], "role": user["role"], "id": str(user["_id"]), "is_profile_complete": user.get("is_profile_complete", False)}
    if user["role"] == "buyer":
        return RedirectResponse(url="/buyer/home", status_code=302)
    elif user["role"] == "seller":
        return RedirectResponse(url="/seller/home", status_code=302)
    elif user["role"] == "admin":
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    else:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unknown user role"})

# -----------------------------
# Logout route
# -----------------------------
@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")
