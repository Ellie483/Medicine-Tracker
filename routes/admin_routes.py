from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from bson import ObjectId

from database import get_database
from auth import require_role

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

router = APIRouter()

@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, current_user: dict = Depends(require_role("admin"))):
    db = get_database()

    users = db.users.find({})
    pharmacies = db.pharmacy_profiles.find({})
    buyers = db.buyer_profiles.find({})

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "users": list(users),
        "pharmacies": list(pharmacies),
        "buyers": list(buyers),
        "current_user": current_user
    })

@router.post("/admin/remove_user/{user_id}")
def remove_user(user_id: str, current_user: dict = Depends(require_role("admin"))):
    db = get_database()
    db.users.delete_one({"_id": ObjectId(user_id)})
    return RedirectResponse(url="/admin/dashboard", status_code=302)
