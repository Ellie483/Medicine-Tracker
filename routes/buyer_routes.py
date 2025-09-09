from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from database import get_database
from auth import require_role
from fastapi.templating import Jinja2Templates
from utils import equirectangular_distance, format_currency
import requests

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --- Replace with your actual Geoapify API key ---
GEOAPIFY_API_KEY = "https://api.geoapify.com/v1/geocode/search?text=38%20Upper%20Montagu%20Street%2C%20Westminster%20W1H%201LJ%2C%20United%20Kingdom&apiKey=YOUR_API_KEY"

def geocode_address(address: str):
    """Geocode an address into latitude and longitude using Geoapify API"""
    url = "https://api.geoapify.com/v1/geocode/search"
    params = {"text": address, "apiKey": GEOAPIFY_API_KEY}
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if data.get("features"):
            lat = data["features"][0]["geometry"]["coordinates"][1]
            lon = data["features"][0]["geometry"]["coordinates"][0]
            return lat, lon
    except Exception as e:
        print("Geocoding error:", e)
    return None, None

# --- Home ---
@router.get("/buyer/home", response_class=HTMLResponse)
def buyer_home(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    buyer_profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})
    if not buyer_profile:
        return RedirectResponse(url="/buyer/profile-edit", status_code=302)
    return templates.TemplateResponse("buyer/home.html", {
        "request": request,
        "current_user": current_user,
        "buyer_profile": buyer_profile
    })

# --- Medicines ---
@router.get("/buyer/medicines", response_class=HTMLResponse)
async def buyer_medicines(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    cur = db.Medicine.find({
        "$expr": {"$gt": [
            {"$subtract": ["$stock", {"$ifNull": ["$reserved", 0]}]},
            0
        ]},
        "$or": [
            {"expiration_date": {"$exists": False}},
            {"expiration_date": {"$gte": datetime.utcnow()}}
        ]
    })

    meds = list(cur)
    medicines_data = []
    for med in meds:
        stock = int(med.get("stock", 0) or 0)
        reserved = int(med.get("reserved", 0) or 0)
        available = max(0, stock - reserved)
        pharmacy = db.pharmacy_profiles.find_one({"user_id": med.get("seller_id")})
        medicines_data.append({
            "_id": str(med["_id"]),
            "name": med.get("name"),
            "buying_price": med.get("buying_price"),
            "selling_price": med.get("selling_price"),
            "stock": stock,
            "reserved": reserved,
            "available": available,
            "description": med.get("description"),
            "formatted_price": format_currency(med.get("selling_price", 0)),
            "is_expired": bool(med.get("expiration_date") and med["expiration_date"] < datetime.utcnow()),
            "expiration_date": (med.get("expiration_date").strftime("%Y-%m-%d") if med.get("expiration_date") else None),
            "pharmacy_name": (pharmacy.get("pharmacy_name") if pharmacy else "Unknown Pharmacy"),
            "image_url": (f"/static/uploads/{med.get('image_filename')}" if med.get("image_filename") else None),
        })

    available_count = sum(1 for m in medicines_data if (m["available"] or 0) > 0)

    return templates.TemplateResponse("buyer/medicines.html", {
        "request": request,
        "current_user": current_user,
        "medicines": medicines_data,
        "available_count": available_count,
    })

# --- Pharmacies ---
@router.get("/buyer/pharmacies", response_class=HTMLResponse)
def buyer_pharmacies(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    pharmacies = list(db.pharmacy_profiles.find({}))

    # Get buyer profile for location
    buyer_profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})
    user_lat = buyer_profile.get("latitude") if buyer_profile else None
    user_lon = buyer_profile.get("longitude") if buyer_profile else None

    # Calculate distance for each pharmacy if location is available
    for p in pharmacies:
        plat = p.get('latitude')
        plon = p.get('longitude')
        if user_lat is not None and user_lon is not None and plat is not None and plon is not None:
            try:
                p['distance'] = equirectangular_distance(float(user_lat), float(user_lon), float(plat), float(plon))
            except Exception:
                p['distance'] = float('inf')
        else:
            p['distance'] = None

    # Sort by distance initially (closest first)
    pharmacies.sort(key=lambda x: x['distance'] if x['distance'] is not None else float('inf'))

    return templates.TemplateResponse("buyer/pharmacies.html", {
        "request": request,
        "current_user": current_user,
        "pharmacies": pharmacies
    })

# --- Profile Edit ---
@router.get("/buyer/profile-edit", response_class=HTMLResponse)
def buyer_profile_edit(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})
    return templates.TemplateResponse("buyer/profile_edit.html", {
        "request": request,
        "current_user": current_user,
        "profile": profile
    })

# --- Profile Update ---
@router.post("/buyer/profile/update")
def update_buyer_profile(
    request: Request,
    name: str = Form(...),
    age: int = Form(...),
    address: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    current_user: dict = Depends(require_role("buyer"))
):
    db = get_database()

    # Geocode the new address
    lat, lon = geocode_address(address)
    if lat is None or lon is None:
        # If geocoding fails, fallback to just updating the address
        lat = None
        lon = None

    update_data = {
        "name": name,
        "age": age,
        "address": address,
        "updated_at": datetime.utcnow()
    }
    if lat is not None and lon is not None:
        update_data["latitude"] = lat
        update_data["longitude"] = lon
    if phone:
        update_data["phone"] = phone
    if email:
        update_data["email"] = email

    db.buyer_profiles.update_one({"user_id": current_user["id"]}, {"$set": update_data})
    return RedirectResponse(url="/buyer/home", status_code=302)
