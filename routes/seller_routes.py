from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi import HTTPException, status
from bson import ObjectId
from datetime import datetime
from fastapi.templating import Jinja2Templates

from database import get_database
from auth import require_role

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/seller/profile", response_class=HTMLResponse)
def seller_profile_form(request: Request, current_user: dict = Depends(require_role("seller"))):
    if current_user.get("is_profile_complete"):
        return RedirectResponse(url="/seller/home", status_code=302)
    return request.app.state.templates.TemplateResponse("seller_profile.html", {"request": request, "current_user": current_user})

############################################################################

@router.get("/seller/home", response_class=HTMLResponse)
def seller_home(request: Request, current_user: dict = Depends(require_role("seller"))):
    print(f"📦 Arrived at seller home for: {current_user['username']}")

    # 👉 Just render the template, no DB interaction
    return templates.TemplateResponse(
        "seller/home.html",
        {
            "request": request,
            "current_user": current_user,
            "total_medicines": 0,
            "low_stock_count": 0,
        },
    )

####################################################################################

@router.get("/seller/inventory", response_class=HTMLResponse)
def seller_inventory(request: Request, current_user: dict = Depends(require_role("seller"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/seller/profile", status_code=302)

    db = get_database()
    medicines = db.medicines.find({"seller_id": current_user["_id"]})

    for medicine in medicines:
        medicine["formatted_price"] = f"${medicine['price']:.2f}"

    return request.app.state.templates.TemplateResponse("seller/inventory.html", {
        "request": request,
        "current_user": current_user,
        "medicines": list(medicines)
    })

@router.get("/seller/profile-edit", response_class=HTMLResponse)
def seller_profile_edit(request: Request, current_user: dict = Depends(require_role("seller"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/seller/profile", status_code=302)

    db = get_database()
    profile = db.pharmacy_profiles.find_one({"user_id": current_user["_id"]})

    return request.app.state.templates.TemplateResponse("seller/profile_edit.html", {
        "request": request,
        "current_user": current_user,
        "profile": profile
    })

@router.post("/seller/profile/update")
def update_seller_profile(
    request: Request,
    pharmacy_name: str = Form(...),
    license_number: str = Form(...),
    contact_info: str = Form(...),
    address: str = Form(...),
    operating_hours: str = Form(...),
    email: str = Form(""),
    website: str = Form(""),
    description: str = Form(""),
    current_user: dict = Depends(require_role("seller"))
):
    db = get_database()

    update_data = {
        "pharmacy_name": pharmacy_name,
        "license_number": license_number,
        "contact_info": contact_info,
        "address": address,
        "operating_hours": operating_hours,
        "updated_at": datetime.utcnow()
    }

    if email:
        update_data["email"] = email
    if website:
        update_data["website"] = website
    if description:
        update_data["description"] = description

    db.pharmacy_profiles.update_one({"user_id": current_user["_id"]}, {"$set": update_data})

    return RedirectResponse(url="/seller/home", status_code=302)

