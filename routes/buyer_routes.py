from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from bson import ObjectId
from datetime import datetime
from fastapi.templating import Jinja2Templates

from database import get_database
from utils import format_currency, is_medicine_expired
from auth import require_role

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# @router.get("/buyer/profile", response_class=HTMLResponse)
# def buyer_profile_form(request: Request, current_user: dict = Depends(require_role("buyer"))):
#     if current_user.get("is_profile_complete"):
#         return RedirectResponse(url="/buyer/home", status_code=302)
#     return request.app.templates.TemplateResponse("buyer_profile.html", {
#         "request": request,
#         "current_user": current_user
#     })

# @router.post("/buyer/profile")
# def create_buyer_profile(
#     request: Request,
#     name: str = Form(...),
#     age: int = Form(...),
#     address: str = Form(...),
#     current_user: dict = Depends(require_role("buyer"))
# ):
#     db = get_database()
#     profile = {
#         "user_id": str(current_user["_id"]),
#         "name": name,
#         "age": age,
#         "address": address,
#         "favorite_pharmacies": [],
#         "created_at": datetime.utcnow()
#     }
#     db.buyer_profiles.insert_one(profile)
#     db.users.update_one({"_id": current_user["_id"]}, {"$set": {"is_profile_complete": True}})
#     return RedirectResponse(url="/buyer/home", status_code=302)

# @router.get("/buyer/home", response_class=HTMLResponse)
# def buyer_home(request: Request, current_user: dict = Depends(require_role("buyer"))):
#     if not current_user.get("is_profile_complete"):
#         return RedirectResponse(url="/buyer/profile", status_code=302)
#     db = get_database()
#     buyer_profile = db.buyer_profiles.find_one({"user_id": current_user["_id"]})
#     medicines_count = db.medicines.count_documents({"stock": {"$gt": 0}})
#     orders = db.orders.find({"buyer_id": current_user["_id"]}).to_list(None)
#     recent_pharmacies = []
#     pharmacy_ids = list(set([order["seller_id"] for order in orders[-5:]]))
#     for pid in pharmacy_ids:
#         pharmacy = db.pharmacy_profiles.find_one({"user_id": pid})
#         if pharmacy:
#             recent_pharmacies.append(pharmacy)
#     return request.app.templates.TemplateResponse("buyer/home.html", {
#         "request": request,
#         "current_user": current_user,
#         "buyer": buyer_profile,
#         "medicines_count": medicines_count,
#         "orders_count": len(orders),
#         "recent_pharmacies": recent_pharmacies[:3]
#     })

@router.get("/buyer/home", response_class=HTMLResponse)
def buyer_home(request: Request, current_user: dict = Depends(require_role("buyer"))):
    print(f"📦 Arrived at buyer home for: {current_user['username']}")

    # 👉 Just render the template, no DB interaction
    return templates.TemplateResponse(
        "buyer/home.html",
        {
        "request": request,
        "current_user": current_user,
        "medicines_count": 0,
        "orders_count": 0
    },
    )

@router.get("/buyer/medicines", response_class=HTMLResponse)
def buyer_medicines(request: Request, current_user: dict = Depends(require_role("buyer"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/buyer/profile", status_code=302)
    db = get_database()
    medicines = db.medicines.find({"stock": {"$gt": 0}}).to_list(None)
    for med in medicines:
        pharmacy = db.pharmacy_profiles.find_one({"_id": ObjectId(med["pharmacy_id"])})
        med["pharmacy_name"] = pharmacy["pharmacy_name"] if pharmacy else "Unknown Pharmacy"
        med["formatted_price"] = format_currency(med["price"])
        med["is_expired"] = is_medicine_expired(med)
    pharmacies = db.pharmacy_profiles.find({}).to_list(None)
    return request.app.templates.TemplateResponse("buyer/medicines.html", {
        "request": request,
        "current_user": current_user,
        "medicines": medicines,
        "pharmacies": pharmacies
    })

@router.get("/buyer/pharmacies", response_class=HTMLResponse)
def buyer_pharmacies(request: Request, current_user: dict = Depends(require_role("buyer"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/buyer/profile", status_code=302)
    db = get_database()
    pharmacies = db.pharmacy_profiles.find({}).to_list(None)
    for pharmacy in pharmacies:
        count = db.medicines.count_documents({"seller_id": pharmacy["user_id"], "stock": {"$gt": 0}})
        pharmacy["medicine_count"] = count
    return request.app.templates.TemplateResponse("buyer/pharmacies.html", {
        "request": request,
        "current_user": current_user,
        "pharmacies": pharmacies
    })

@router.get("/buyer/profile-edit", response_class=HTMLResponse)
def buyer_profile_edit(request: Request, current_user: dict = Depends(require_role("buyer"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/buyer/profile", status_code=302)
    db = get_database()
    profile = db.buyer_profiles.find_one({"user_id": current_user["_id"]})
    return request.app.templates.TemplateResponse("buyer/profile_edit.html", {
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
    db.buyer_profiles.update_one({"user_id": current_user["_id"]}, {"$set": update_data})
    return RedirectResponse(url="/buyer/home", status_code=302)
