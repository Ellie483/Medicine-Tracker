from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from bson import ObjectId

from database import get_database
from auth import require_role
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
router = APIRouter()


@router.get("/admin/customers", response_class=HTMLResponse)
def customers_dashboard(request: Request, current_user: dict = Depends(require_role("admin"))):
    db = get_database()

    buyers = list(db.buyer_profiles.find({}))

    # Top 3 most active customers
    top_customers = list(db.Orders.aggregate([
        {"$match": {"status": "delivered"}},
        {"$group": {"_id": "$buyer_id", "totalOrders": {"$sum": 1}}},
        {"$sort": {"totalOrders": -1}},
        {"$limit": 3},
        {
            "$lookup": {
                "from": "buyer_profiles",
                "localField": "_id",
                "foreignField": "user_id",
                "as": "buyer"
            }
        },
        {"$unwind": "$buyer"},
        {"$project": {"_id": 0, "buyerName": "$buyer.name", "totalOrders": 1}}
    ]))

    return templates.TemplateResponse("customer_dashboard_admin.html", {
        "request": request,
        "buyers": buyers,
        "top_customers": top_customers,
        "current_user": current_user
    })


@router.get("/admin/pharmacies", response_class=HTMLResponse)
def pharmacies_dashboard(request: Request, current_user: dict = Depends(require_role("admin"))):
    db = get_database()
    
    pharmacies = list(db.pharmacy_profiles.find({}))

    # Top 3 best-selling pharmacies (same structure as top_customers)
    top_pharmacies = list(db.Orders.aggregate([
        {"$match": {"status": "delivered"}},
        {"$group": {"_id": "$pharmacy_id", "totalSales": {"$sum": 1}}},
        {"$sort": {"totalSales": -1}},
        {"$limit": 3},
        {
            "$lookup": {
                "from": "pharmacy_profiles",
                "localField": "_id",
                "foreignField": "_id",
                "as": "pharmacy"
            }
        },
        {"$unwind": "$pharmacy"},
        {"$project": {"_id": 0, "pharmacyName": "$pharmacy.pharmacy_name", "totalSales": 1}}
    ]))

    return templates.TemplateResponse("pharmacies_dashboard_admin.html", {
        "request": request,
        "pharmacies": pharmacies,
        "top_pharmacies": top_pharmacies,
        "current_user": current_user
    })


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, current_user: dict = Depends(require_role("admin"))):
    db = get_database()

    buyers = list(db.buyer_profiles.find({}))
    pharmacies = list(db.pharmacy_profiles.find({}))

    total_users = len(buyers) + len(pharmacies)

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "buyers": buyers,
        "pharmacies": pharmacies,
        "total_users": total_users,
        "current_user": current_user
    })


@router.post("/admin/remove_user/{user_id}")
async def remove_user(user_id: str, request: Request):
    db = get_database()
    # Convert string back to ObjectId
    result = db.buyers.delete_one({"_id": ObjectId(user_id)})
    if result.deleted_count == 1:
        print("Deleted successfully")
    else:
        print("No document found to delete")
    
    # Redirect back to customers page
    return RedirectResponse("/admin/customers", status_code=303)


@router.post("/admin/remove_pharmacy/{pharmacy_id}")
def remove_pharmacy(
    pharmacy_id: str,
    next: str = Form(...),
    current_user: dict = Depends(require_role("admin"))
):
    db = get_database()
    oid = ObjectId(pharmacy_id)

    db.pharmacy_profiles.delete_one({"_id": oid})

    db.buyer_profiles.update_many(
        {"favorite_pharmacies": oid},
        {"$pull": {"favorite_pharmacies": oid}}
    )

    redirect_map = {
        "admin_dashboard": "/admin/dashboard",
        "pharmacies_dashboard_admin": "/admin/pharmacies"
    }
    redirect_url = redirect_map.get(next, "/admin/dashboard")

    return RedirectResponse(url=redirect_url, status_code=302)