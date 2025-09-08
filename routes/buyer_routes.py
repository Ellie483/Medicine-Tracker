from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from database import get_database
from auth import require_role
from bson import ObjectId
from utils import format_currency, is_medicine_expired
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from pydantic import BaseModel
router = APIRouter()

# Initialize templates
templates = Jinja2Templates(directory="templates")

@router.get("/buyer/home", response_class=HTMLResponse)
def buyer_home(request: Request, current_user: dict = Depends(require_role("buyer"))):
    print(f"📦 Current User Data: {current_user}")  # Log current user data

    db = get_database()

    # Fetch buyer profile from the buyer_profiles collection
    buyer_profile = db.buyer_profiles.find_one({"user_id": current_user["id"]})

    # Check if profile exists
    if not buyer_profile:
        print(f"❌ No profile found for user {current_user['username']}. Redirecting to profile creation.")
        return RedirectResponse(url="/buyer/profile-edit", status_code=302)

    print(f"✅ Profile found for user {current_user['username']}")

    # Only pass available data to template
    return templates.TemplateResponse("buyer/home.html", {
        "request": request,
        "current_user": current_user,
        "buyer_profile": buyer_profile  # Pass profile data directly
    })


from datetime import datetime

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
        stock    = int(med.get("stock", 0) or 0)
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

    # Count only items with availability > 0, in case you reuse the badge
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



@router.get("/buyer/pharmacies", response_class=HTMLResponse)
def buyer_pharmacies(request: Request, current_user: dict = Depends(require_role("buyer"))):
    # Fetch the list of pharmacies available in the system
    db = get_database()
    pharmacies = list(db.pharmacy_profiles.find({}))  # Use list() to convert the cursor
    return templates.TemplateResponse("buyer/pharmacies.html", {
        "request": request,
        "current_user": current_user,
        "pharmacies": pharmacies
    })

@router.get("/buyer/profile-edit", response_class=HTMLResponse)
def buyer_profile_edit(request: Request, current_user: dict = Depends(require_role("buyer"))):
    # Fetch the user's profile to allow editing
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
    return RedirectResponse(url="/buyer/home", status_code=302)


