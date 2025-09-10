from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from database import get_database
from auth import require_role
from bson import ObjectId
from utils import format_currency, equirectangular_distance
from fastapi.templating import Jinja2Templates
import requests

router = APIRouter()

# Initialize templates
templates = Jinja2Templates(directory="templates")

# -----------------------------
# Utility: Geocoding
# -----------------------------
def geocode_address(address: str):
    """
    Use OpenStreetMap Nominatim API to convert address -> (lat, lon).
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "medicine-tracker-app"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"⚠️ Geocoding failed for {address}: {e}")
    return None, None


def get_buyer_coordinates(db, buyer_profile, force_update=False):
    """
    Return buyer coordinates.
    - If already present and force_update=False → return them
    - If missing or force_update=True → geocode from address → save → return
    """
    coords = buyer_profile.get("coordinates")
    if coords and coords.get("latitude") is not None and coords.get("longitude") is not None and not force_update:
        return coords["latitude"], coords["longitude"]

    address = buyer_profile.get("address")
    if address:
        lat, lon = geocode_address(address)
        if lat is not None and lon is not None:
            db.buyer_profiles.update_one(
                {"_id": buyer_profile["_id"]},
                {"$set": {"coordinates": {"latitude": lat, "longitude": lon}}}
            )
            return lat, lon
    return None, None


# -----------------------------
# Buyer Home
# -----------------------------
@router.get("/buyer/home", response_class=HTMLResponse)
def buyer_home(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()

    # Fetch buyer profile
    buyer_profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})

    if not buyer_profile:
        print(f"❌ No profile found for user {current_user['username']}. Redirecting to profile creation.")
        return RedirectResponse(url="/buyer/profile-edit", status_code=302)

    return templates.TemplateResponse("buyer/home.html", {
        "request": request,
        "current_user": current_user,
        "buyer_profile": buyer_profile
    })


# -----------------------------
# Medicines
# -----------------------------
@router.get("/buyer/medicines", response_class=HTMLResponse)
async def buyer_medicines(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()

    # availability: stock - reserved > 0
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
            "image_url": (f"/static/images/medicines/{med.get('image_filename')}" if med.get("image_filename") else None),
        })

    available_count = sum(1 for m in medicines_data if (m["available"] or 0) > 0)

    return templates.TemplateResponse(
        "buyer/medicines.html",
        {
            "request": request,
            "current_user": current_user,
            "medicines": medicines_data,
            "available_count": available_count,
        },
    )


# -----------------------------
# Pharmacies (Sorted by Distance)
# -----------------------------
@router.get("/buyer/pharmacies", response_class=HTMLResponse)
def buyer_pharmacies(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    buyer_profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})
    if not buyer_profile:
        return RedirectResponse(url="/buyer/profile-edit", status_code=302)

    # Ensure buyer has coordinates
    user_lat, user_lon = get_buyer_coordinates(db, buyer_profile)

    pharmacies = list(db.pharmacy_profiles.find({}))

    for p in pharmacies:
        # Ensure required fields exist
        p["user_id"] = p.get("user_id", "")
        # Dynamically count medicines for this pharmacy
        p["medicine_count"] = db.Medicine.count_documents({"seller_id": p["user_id"]})

        coords = p.get("coordinates", {})
        plat = coords.get("latitude")
        plon = coords.get("longitude")

        # Calculate distance safely
        if user_lat is not None and user_lon is not None and plat is not None and plon is not None:
            try:
                p["distance"] = equirectangular_distance(user_lat, user_lon, float(plat), float(plon))
            except Exception:
                p["distance"] = None
        else:
            p["distance"] = None  # None indicates distance not available

    # Sort by distance if coordinates exist
    pharmacies.sort(key=lambda x: (x["distance"] is None, x["distance"] or 0))

    # Optional search query
    q = request.query_params.get("q", "").lower()
    if q:
        pharmacies = [p for p in pharmacies if q in p.get("pharmacy_name", "").lower() or q in p.get("address", "").lower()]

    return templates.TemplateResponse("buyer/pharmacies.html", {
        "request": request,
        "current_user": current_user,
        "pharmacies": pharmacies
    })


# -----------------------------
# API: Medicines per Pharmacy
# -----------------------------
@router.get("/api/pharmacy/{pharmacy_id}/medicines")
def get_pharmacy_medicines(pharmacy_id: str):
    db = get_database()
    meds = list(db.Medicine.find({"seller_id": pharmacy_id}))
    result = []
    for med in meds:
        result.append({
            "name": med.get("name"),
            "price": med.get("selling_price", 0),
            "stock": med.get("stock", 0)
        })
    return result


# -----------------------------
# Profile Edit + Update
# -----------------------------
@router.get("/buyer/profile-edit", response_class=HTMLResponse)
def buyer_profile_edit(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})
    return templates.TemplateResponse("buyer/profile_edit.html", {
        "request": request,
        "current_user": current_user,
        "profile": profile
    })


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
    
    update_data = {
        "name": name,
        "age": age,
        "address": address,
        "updated_at": datetime.utcnow()
    }
    if phone:
        update_data["phone"] = phone
    if email:
        update_data["email"] = email

    db.buyer_profiles.update_one({"user_id": current_user["id"]}, {"$set": update_data})

    # Fetch the updated profile
    buyer_profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})
    
    # ⚡ Force update coordinates if address changed
    get_buyer_coordinates(db, buyer_profile, force_update=True)

    return RedirectResponse(url="/buyer/home", status_code=302)
