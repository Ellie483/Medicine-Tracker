# routes/notification_routes.py

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime, timezone
from bson import ObjectId
from database import get_database

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def _now():
    return datetime.now(timezone.utc)

# accept any logged-in user (reads session directly)
def require_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@router.get("/notifications/unread_count")
def notif_unread_count(current_user: dict = Depends(require_user)):
    db = get_database()
    n = db.Notifications.count_documents({"user_id": current_user["id"], "is_read": False})
    return {"unread": int(n)}


@router.get("/notifications/list")
def notif_list(limit: int = Query(20, ge=1, le=100), current_user: dict = Depends(require_user)):
    db = get_database()
    cur = db.Notifications.find({"user_id": current_user["id"]}).sort("created_at", -1).limit(limit)
    items = []
    for d in cur:
        ts = d.get("created_at")
        items.append({
            "id": str(d["_id"]),
            "type": d.get("type"),
            "title": d.get("title"),
            "message": d.get("message"),
            "order_id": d.get("order_id"),
            "is_read": bool(d.get("is_read")),
            # keep iso if you like, but add ms epoch:
            "created_at_ms": int(ts.replace(tzinfo=timezone.utc).timestamp() * 1000) if ts else None,
        })
    return {"items": items}

class MarkReq(BaseModel):
    ids: list[str] | None = None  # if None, mark all

@router.post("/notifications/mark_read")
def notif_mark_read(payload: MarkReq, current_user: dict = Depends(require_user)):
    db = get_database()
    q = {"user_id": current_user["id"], "is_read": False}
    if payload.ids:
        q["_id"] = {"$in": [ObjectId(i) for i in payload.ids if i]}
    db.Notifications.update_many(q, {"$set": {"is_read": True, "read_at": _now()}})
    return {"ok": True}
