from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from bson import ObjectId
from database import get_database
from utils import format_currency
from auth import require_role

router = APIRouter()

# -------------------- BUYER ORDERS --------------------
@router.get("/buyer/orders", response_class=HTMLResponse)
def buyer_orders(request: Request, current_user: dict = Depends(require_role("buyer"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/buyer/profile", status_code=302)

    db = get_database()
    orders = db.orders.find({"buyer_id": current_user["_id"]}).to_list(None)

    for order in orders:
        pharmacy = db.pharmacy_profiles.find_one({"user_id": order["seller_id"]})
        order["pharmacy_name"] = pharmacy["pharmacy_name"] if pharmacy else "Unknown Pharmacy"
        order["formatted_total"] = format_currency(order["total_amount"])

    return request.app.templates.TemplateResponse("buyer/orders.html", {
        "request": request,
        "current_user": current_user,
        "orders": orders
    })


# -------------------- SELLER ORDERS --------------------
@router.get("/seller/orders", response_class=HTMLResponse)
def seller_orders(request: Request, current_user: dict = Depends(require_role("seller"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/seller/profile", status_code=302)

    db = get_database()
    orders = db.orders.find({"seller_id": current_user["_id"]}).to_list(None)

    for order in orders:
        buyer = db.users.find_one({"_id": ObjectId(order["buyer_id"])})
        if buyer:
            buyer_profile = db.buyer_profiles.find_one({"user_id": order["buyer_id"]})
            order["buyer_name"] = buyer_profile.get("name", buyer["username"]) if buyer_profile else buyer["username"]
        order["formatted_total"] = format_currency(order["total_amount"])

    return request.app.templates.TemplateResponse("seller/orders.html", {
        "request": request,
        "current_user": current_user,
        "orders": orders
    })
