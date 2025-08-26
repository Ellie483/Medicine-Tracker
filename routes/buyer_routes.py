from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from database import get_database
from auth import require_role
from bson import ObjectId
from utils import format_currency, is_medicine_expired
from fastapi.templating import Jinja2Templates

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

@router.get("/buyer/medicines", response_class=HTMLResponse)
async def buyer_medicines(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    
    # Fetch medicines with stock > 0 and not expired
    medicines_cursor = db.Medicine.find({
        "stock": {"$gt": 0},
        "expiration_date": {"$gte": datetime.utcnow()}  # Ensure the medicine is not expired
    })

    # Convert the cursor to a list
    medicines = list(medicines_cursor)

    # Print medicines data to the terminal to check the output
    print(f"📦 Medicines data: {medicines}")

    # Prepare medicines data with pharmacy info
    medicines_data = []
    for med in medicines:
        # Fetch the pharmacy info from the pharmacy_profiles collection
        pharmacy = db.pharmacy_profiles.find_one({"_id": ObjectId(med["seller_id"])})
        
        med_data = {
            "name": med["name"],
            "price": med["price"],
            "stock": med["stock"],
            "description": med["description"],
            "formatted_price": f"${med['price']:.2f}",
            "is_expired": med["expiration_date"] < datetime.utcnow(),  # Check if expired
            "expiration_date": med["expiration_date"],
            "pharmacy_name": pharmacy["pharmacy_name"] if pharmacy else "Unknown Pharmacy",  # Get pharmacy name
        }
        medicines_data.append(med_data)

    # Return template with medicines data
    return templates.TemplateResponse("buyer/medicines.html", {
        "request": request,
        "current_user": current_user,
        "medicines": medicines_data
    })

@router.get("/buyer/orders", response_class=HTMLResponse)
def buyer_orders(request: Request, current_user: dict = Depends(require_role("buyer"))):
    print(f"📦 Current User Data: {current_user}")  # Log current user data

    # Check if the profile is complete
    if not current_user.get("is_profile_complete"):
        print(f"❌ Profile is incomplete for user {current_user['username']}")
        return RedirectResponse(url="/buyer/profile", status_code=302)

    print(f"✅ Profile complete for user {current_user['username']}")

    db = get_database()

    # Fetch orders for the current user
    orders = list(db.orders.find({"buyer_id": current_user["id"]}))  # Use list() to convert the cursor
    print(f"📦 Orders: {orders}")

    return templates.TemplateResponse("buyer/orders.html", {
        "request": request,
        "current_user": current_user,
        "orders": orders
    })

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