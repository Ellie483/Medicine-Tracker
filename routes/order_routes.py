# routes/order_routes.py
from __future__ import annotations

import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Any, Tuple, List, Dict
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import (
    APIRouter,
    Request,
    Depends,
    Form,
    HTTPException,
    UploadFile,
    File,
)
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from auth import require_role
from database import get_database
from utils import format_currency

# -------------------- logging --------------------
logger = logging.getLogger("orders")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# -------------------- fastapi --------------------
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# jinja filter
def _fmt_dt_local(dt: Optional[datetime], tz: ZoneInfo | str = "Asia/Yangon") -> str:
    if not dt:
        return "—"
    if isinstance(tz, str):
        tz = ZoneInfo(tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")

templates.env.filters["fmt_local"] = lambda dt, tz="Asia/Yangon": _fmt_dt_local(dt, tz)

# ======================== MODELS ========================

class AddToCartRequest(BaseModel):
    medicine_id: str
    quantity: int

# ======================== HELPERS ========================

def _now() -> datetime:
    return datetime.now(timezone.utc)  # tz-aware UTC

def _to_oid(maybe_id):
    if isinstance(maybe_id, ObjectId):
        return maybe_id
    return ObjectId(str(maybe_id))

def _user_tz(request: Request, db=None, current_user: dict | None = None) -> ZoneInfo:
    # user -> profile -> session -> default
    if current_user and current_user.get("tz"):
        try:
            return ZoneInfo(current_user["tz"])
        except Exception:
            pass
    if db is not None and current_user and current_user.get("id"):
        prof = db.user_profiles.find_one({"user_id": current_user["id"]}) or {}
        tzname = prof.get("timezone")
        if tzname:
            try:
                return ZoneInfo(tzname)
            except Exception:
                pass
    try:
        tzname = request.session.get("tz")
        if tzname:
            return ZoneInfo(tzname)
    except Exception:
        pass
    return ZoneInfo("Asia/Yangon")

def _save_receipt(order_id: str, upload: UploadFile) -> str:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".pdf"]:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, PDF allowed")
    folder = os.path.join("static", "receipts", str(order_id))
    os.makedirs(folder, exist_ok=True)
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(folder, fname)
    with open(path, "wb") as f:
        f.write(upload.file.read())
    return f"/static/receipts/{order_id}/{fname}"

def _audit(db, oid: ObjectId, actor: str, action: str, meta: Optional[dict] = None):
    db.Orders.update_one(
        {"_id": oid},
        {
            "$push": {
                "timeline": {"ts": _now(), "actor": actor, "action": action, "meta": meta or {}}
            },
            "$set": {"updated_at": _now()},
        },
    )

def _short_id(s: Optional[str], n: int = 6) -> str:
    if not s:
        return "—"
    s = str(s)
    return f"{s[:n]}…{s[-n:]}" if len(s) > 2 * n else s

def _lookup_buyer_display(db, buyer_id: Optional[str]) -> Tuple[str, Optional[str], Optional[str]]:
    if not buyer_id:
        return "—", None, None
    try:
        boid = _to_oid(buyer_id)
    except Exception:
        boid = None

    prof = (
        db.user_profiles.find_one({"user_id": buyer_id})
        or (boid and db.user_profiles.find_one({"user_id": str(boid)}))
        or (boid and db.user_profiles.find_one({"_id": boid}))
        or {}
    )
    name = prof.get("full_name") or prof.get("name")
    phone = prof.get("phone")
    email = prof.get("email")
    if not name and boid:
        u = db.users.find_one({"_id": boid}) or {}
        name = u.get("full_name") or u.get("name") or u.get("username")
    return (name or _short_id(buyer_id), phone, email)

# ---- pharmacy name resolver (original intent, but corrected) ----
def _lookup_pharmacy_name(db, seller_id: str | None) -> str:
    """
    Resolve pharmacy name from pharmacy_profiles.user_id (seller_id).
    Tries string and ObjectId. Logs steps.
    """
    if not seller_id:
        logger.info("[pharmacy_name] No seller_id → Unknown Pharmacy")
        return "Unknown Pharmacy"

    sid_str = str(seller_id)
    logger.info(f"[pharmacy_name] Looking for seller_id={sid_str!r}")

    # user_id stored as string
    doc = db.pharmacy_profiles.find_one({"user_id": sid_str})
    if doc and (doc.get("pharmacy_name") or doc.get("name")):
        name = doc.get("pharmacy_name") or doc.get("name")
        logger.info(f"[pharmacy_name] ✓ by user_id(str) → {name!r}")
        return name

    # user_id stored as ObjectId
    try:
        oid = ObjectId(sid_str)
    except Exception:
        oid = None
    if oid:
        doc = db.pharmacy_profiles.find_one({"user_id": oid})
        if doc and (doc.get("pharmacy_name") or doc.get("name")):
            name = doc.get("pharmacy_name") or doc.get("name")
            logger.info(f"[pharmacy_name] ✓ by user_id(ObjectId) → {name!r}")
            return name

    logger.info(f"[pharmacy_name] ✗ not found for seller_id={sid_str!r}")
    return "Unknown Pharmacy"

def _extract_shipping(o: dict) -> Dict[str, Optional[str]]:
    ship = o.get("shipping") or o.get("shipping_address") or o.get("delivery_address") or {}
    if isinstance(ship, str):
        return {"address": ship, "city": None}
    return {
        "address": ship.get("address") or ship.get("address_line") or ship.get("line1"),
        "city": ship.get("city"),
    }

# ======================== BUYER FLOWS ========================

@router.post("/buyer/add_to_cart")
async def add_to_cart(
    medicine_id: str = Form(...),
    quantity: int = Form(...),
    current_user: dict = Depends(require_role("buyer")),
):
    buyer_id = current_user["id"]

    # 1) validate
    try:
        payload = AddToCartRequest(medicine_id=medicine_id, quantity=quantity)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if payload.quantity < 1:
        raise HTTPException(status_code=422, detail="Quantity must be >= 1")

    db = get_database()

    # 2) load medicine and pharmacy
    try:
        med_oid = _to_oid(payload.medicine_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid medicine ID")

    med = db.Medicine.find_one({"_id": med_oid})
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")

    price_sell = float(med.get("selling_price", 0) or 0)
    price_buy = float(med.get("buying_price", 0) or 0)

    seller_id = med.get("seller_id")  # e.g. "68aafb40bcb5ca2ab1d25187"
    pharmacy_id_str = str(seller_id) if seller_id else None
    pharmacy_name = _lookup_pharmacy_name(db, pharmacy_id_str)
    logger.info(f"[cart] med={med.get('name')} seller_id={pharmacy_id_str} resolved_name={pharmacy_name}")

    # 3) find existing open order for this buyer+pharmacy
    existing = db.Orders.find_one({
        "buyer_id": buyer_id,
        "pharmacy_id": pharmacy_id_str,
        "order_status": {"$in": ["cart", "pending"]},
        "payment_status": {"$in": ["unpaid", "rejected"]},
    })

    line_delta_total = int(payload.quantity) * price_sell

    if existing:
        items = existing.get("items", []) or []
        idx = None
        for i, it in enumerate(items):
            if str(it.get("medicine_id")) == str(med["_id"]):
                idx = i
                break
        if idx is not None:
            new_qty = int(items[idx].get("quantity", 0)) + int(payload.quantity)
            items[idx]["quantity"] = new_qty
            items[idx]["price"] = price_sell
            items[idx]["buying_price"] = price_buy
            items[idx]["total"] = new_qty * price_sell
        else:
            items.append({
                "medicine_id": med["_id"],
                "medicine_name": med.get("name", "Unknown"),
                "quantity": int(payload.quantity),
                "price": price_sell,
                "buying_price": price_buy,
                "total": line_delta_total,
            })

        total_amount = sum(int(it.get("quantity", 0)) * float(it.get("price", 0)) for it in items)
        formatted_total = format_currency(total_amount)

        db.Orders.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "items": items,
                    "total_amount": total_amount,
                    "formatted_total": formatted_total,
                    "pharmacy_name": pharmacy_name,
                    "updated_at": _now(),
                },
                "$push": {
                    "timeline": {
                        "ts": _now(),
                        "actor": "buyer",
                        "action": "add_to_cart",
                        "meta": {
                            "medicine_id": str(med["_id"]),
                            "quantity_added": int(payload.quantity),
                            "line_total_added": line_delta_total,
                        },
                    }
                },
            },
        )
        return JSONResponse(status_code=200, content={"message": "Updated existing order.", "order_id": str(existing["_id"]), "merged": True})

    # create new order
    order_doc = {
        "buyer_id": buyer_id,
        "pharmacy_id": pharmacy_id_str,
        "pharmacy_name": pharmacy_name,
        "items": [{
            "medicine_id": med["_id"],
            "medicine_name": med.get("name", "Unknown"),
            "quantity": int(payload.quantity),
            "price": price_sell,
            "buying_price": price_buy,
            "total": line_delta_total,
        }],
        "total_amount": line_delta_total,
        "formatted_total": format_currency(line_delta_total),
        "order_status": "cart",
        "status": "cart",
        "payment_status": "unpaid",
        "payment": {
            "payment_id": None,
            "receipt_path": None,
            "rejected_reason": None,
            "uploaded_at": None,
        },
        "created_at": _now(),
        "updated_at": _now(),
        "timeline": [{
            "ts": _now(),
            "actor": "buyer",
            "action": "create_cart",
            "meta": {"medicine_id": str(med["_id"]), "quantity": int(payload.quantity), "line_total": line_delta_total},
        }],
    }
    try:
        res = db.Orders.insert_one(order_doc)
        logger.info(f"[cart] Created order={res.inserted_id} for seller_id={pharmacy_id_str} name={pharmacy_name}")
    except Exception:
        logger.exception("Failed to create order")
        raise HTTPException(status_code=500, detail="Failed to create order")

    return JSONResponse(status_code=200, content={"message": "Created a new order.", "order_id": str(res.inserted_id), "merged": False})

@router.get("/buyer/orders", response_class=HTMLResponse)
def buyer_orders(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    tz = _user_tz(request, db, current_user)
    buyer_id = current_user["id"]

    q = (request.query_params.get("q") or "").strip()
    status = request.query_params.get("status")
    sort_key = request.query_params.get("sort", "created_desc")

    query: Dict[str, Any] = {"buyer_id": buyer_id}
    if status in ["cart", "pending", "confirmed", "delivered"]:
        query["order_status"] = status
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"pharmacy_name": rx}, {"items.medicine_name": rx}]

    sort_map = {
        "created_desc": [("created_at", -1)],
        "created_asc":  [("created_at", 1)],
        "total_desc":   [("total_amount", -1), ("created_at", -1)],
        "total_asc":    [("total_amount", 1),  ("created_at", -1)],
    }
    sort_spec = sort_map.get(sort_key, [("created_at", -1)])

    orders = list(db.Orders.find(query).sort(sort_spec))

    formatted_orders = []
    for o in orders:
        items = [{
            "medicine_name": it.get("medicine_name", "Unknown"),
            "quantity": int(it.get("quantity", 0) or 0),
            "price": float(it.get("price", 0) or 0.0),
        } for it in (o.get("items") or [])]

        computed_total = sum(i["price"] * i["quantity"] for i in items)
        created_at = o.get("created_at")

        # resolve & backfill name if missing
        resolved = o.get("pharmacy_name") or _lookup_pharmacy_name(db, o.get("pharmacy_id") or o.get("seller_id"))
        if resolved and resolved != o.get("pharmacy_name"):
            db.Orders.update_one({"_id": o["_id"]}, {"$set": {"pharmacy_name": resolved, "updated_at": _now()}})
        logger.info(f"[buyer_list] order={o.get('_id')} pid={o.get('pharmacy_id')} name={resolved}")

        formatted_orders.append({
            "_id": str(o.get("_id")),
            "created_at": created_at,
            "created_at_str": _fmt_dt_local(created_at, tz),
            "order_status": (o.get("order_status") or o.get("status") or "cart").lower(),
            "payment_status": (o.get("payment_status") or "unpaid").lower(),
            "items": items,
            "pharmacy_name": resolved or "Unknown Pharmacy",
            "formatted_total": o.get("formatted_total") or format_currency(computed_total),
            "payment": {
                "payment_id": (o.get("payment") or {}).get("payment_id"),
                "receipt_path": (o.get("payment") or {}).get("receipt_path"),
                "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            },
        })

    return templates.TemplateResponse(
        "buyer/orders_list.html",
        {"request": request, "orders": formatted_orders, "current_user": current_user, "sort": sort_key, "status": status or "", "q": q},
    )

@router.get("/buyer/orders/{order_id}", response_class=HTMLResponse)
def buyer_order_detail(
    request: Request,
    order_id: str,
    current_user: dict = Depends(require_role("buyer")),
):
    db = get_database()
    tz = _user_tz(request, db, current_user)

    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "buyer_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    ship = _extract_shipping(o)
    items = []
    for it in (o.get("items") or []):
        q = int(it.get("quantity", 0) or 0)
        p_sell = float(it.get("price", 0) or 0.0)
        items.append({"medicine_name": it.get("medicine_name", "Unknown"), "quantity": q, "price": p_sell, "line_total": q * p_sell})

    total_amount = o.get("total_amount")
    if total_amount is None:
        total_amount = sum(x["line_total"] for x in items)

    resolved_name = o.get("pharmacy_name") or _lookup_pharmacy_name(db, o.get("pharmacy_id") or o.get("seller_id"))
    if resolved_name and resolved_name != o.get("pharmacy_name"):
        db.Orders.update_one({"_id": o["_id"]}, {"$set": {"pharmacy_name": resolved_name, "updated_at": _now()}})
    logger.info(f"[buyer_detail] order={o.get('_id')} pid={o.get('pharmacy_id') or o.get('seller_id')} name={resolved_name}")

    order = {
        "_id": str(o["_id"]),
        "created_at": o.get("created_at"),
        "created_at_str": _fmt_dt_local(o.get("created_at"), tz),
        "order_status": (o.get("order_status") or o.get("status") or "cart").lower(),
        "status": (o.get("order_status") or o.get("status") or "cart").lower(),
        "payment_status": (o.get("payment_status") or "unpaid").lower(),
        "payment": {
            "payment_id": (o.get("payment") or {}).get("payment_id"),
            "receipt_path": (o.get("payment") or {}).get("receipt_path"),
            "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            "uploaded_at": (o.get("payment") or {}).get("uploaded_at"),
        },
        "items": items,
        "pharmacy_name": resolved_name or "Unknown Pharmacy",
        "pharmacy_address": o.get("pharmacy_address"),
        "ship_to": {"address": ship["address"], "city": ship["city"]},
        "formatted_total": o.get("formatted_total") or format_currency(total_amount),
        "timeline": o.get("timeline", []),
    }

    return templates.TemplateResponse("buyer/order_detail.html", {"request": request, "order": order, "current_user": current_user})

@router.post("/buyer/orders/{order_id}/submit_and_upload")
async def buyer_submit_and_upload(
    request: Request,
    order_id: str,
    payment_id: str = Form(...),
    address_line: str = Form(...),
    city: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role("buyer")),
):
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "buyer_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    if (o.get("order_status") not in ["cart", "pending"]) or (o.get("payment_status") not in ["unpaid", "rejected"]):
        raise HTTPException(400, "Order not in a state that can be submitted")

    receipt_path = _save_receipt(order_id, file)

    db.Orders.update_one(
        {"_id": oid},
        {
            "$set": {
                "order_status": "pending",
                "status": "pending",
                "payment_status": "proof_uploaded",
                "payment.payment_id": payment_id,
                "payment.receipt_path": receipt_path,
                "payment.rejected_reason": None,
                "payment.uploaded_at": _now(),
                "shipping": {"address_line": address_line, "city": city},
                "updated_at": _now(),
            },
            "$push": {"timeline": {"ts": _now(), "actor": "buyer", "action": "submit_order", "meta": {"payment_id": payment_id, "city": city}}},
        },
    )
    return RedirectResponse(f"/buyer/orders/{order_id}", status_code=303)

@router.post("/buyer/orders/{order_id}/payment")
def buyer_upload_payment(
    order_id: str,
    payment_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role("buyer")),
):
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "buyer_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    if (o.get("order_status") or "").lower() not in ["pending", "confirmed"]:
        raise HTTPException(400, "Cannot upload payment in current status")

    receipt_path = _save_receipt(order_id, file)
    db.Orders.update_one(
        {"_id": oid},
        {"$set": {
            "payment_status": "proof_uploaded",
            "payment.payment_id": payment_id,
            "payment.receipt_path": receipt_path,
            "payment.rejected_reason": None,
            "payment.uploaded_at": _now(),
            "updated_at": _now(),
        }}
    )
    _audit(db, oid, "buyer", "upload_payment", {"payment_id": payment_id})
    return RedirectResponse(f"/buyer/orders/{order_id}", status_code=303)

# ======================== SELLER FLOWS ========================

@router.get("/seller/orders", response_class=HTMLResponse)
def seller_orders_list(
    request: Request,
    status: Optional[str] = None,
    payment: Optional[str] = None,
    sort: Optional[str] = "created_desc",
    q: Optional[str] = None,
    current_user: dict = Depends(require_role("seller")),
):
    db = get_database()
    tz = _user_tz(request, db, current_user)

    filt: Dict[str, Any] = {"pharmacy_id": current_user["id"]}
    filt["$nor"] = [{"order_status": "cart", "payment_status": "unpaid"}]

    if status:
        if status == "pending":
            filt["order_status"] = {"$in": ["pending", "placed"]}
        else:
            filt["order_status"] = status

    if payment:
        filt["payment_status"] = payment

    or_terms: List[dict] = []
    q_val = (q or request.query_params.get("q") or "").strip()
    if q_val:
        rx = {"$regex": re.escape(q_val), "$options": "i"}
        or_terms.extend([
            {"payment.payment_id": rx},
            {"items.medicine_name": rx},
        ])
        prof_ids_str: List[str] = []
        user_ids_str: List[str] = []
        for p in db.user_profiles.find({"$or": [{"full_name": rx}, {"name": rx}]}, {"user_id": 1}):
            if p.get("user_id"):
                prof_ids_str.append(str(p["user_id"]))
        for u in db.users.find({"$or": [{"full_name": rx}, {"name": rx}, {"username": rx}]}, {"_id": 1}):
            user_ids_str.append(str(u["_id"]))
        buyer_ids_str = list({*prof_ids_str, *user_ids_str})
        if buyer_ids_str:
            or_terms.append({"buyer_id": {"$in": buyer_ids_str}})
    if or_terms:
        filt["$or"] = or_terms

    sort_map = {
        "created_desc": [("created_at", -1)],
        "created_asc":  [("created_at", 1)],
        "total_desc":   [("total_amount", -1), ("created_at", -1)],
        "total_asc":    [("total_amount", 1),  ("created_at", -1)],
    }
    sort_spec = sort_map.get(sort or "created_desc", [("created_at", -1)])

    orders = list(db.Orders.find(filt).sort(sort_spec))
    logger.info(f"[seller_list] found {len(orders)} orders for pharmacy_id={current_user['id']}")

    buyer_ids_in = list({o.get("buyer_id") for o in orders if o.get("buyer_id")})
    profiles = {}
    if buyer_ids_in:
        for p in db.user_profiles.find({"user_id": {"$in": buyer_ids_in}}):
            profiles[p.get("user_id")] = p

    shaped = []
    for o in orders:
        prof = profiles.get(o.get("buyer_id")) or {}
        display_name = prof.get("full_name") or prof.get("name") or _short_id(o.get("buyer_id"))

        items_out = []
        for it in (o.get("items") or []):
            items_out.append({
                "medicine_name": it.get("medicine_name", "Unknown"),
                "quantity": int(it.get("quantity", 0) or 0),
                "price": float(it.get("price", 0) or 0.0),
            })

        ship = _extract_shipping(o)
        created_at = o.get("created_at")
        shaped.append({
            "_id": str(o["_id"]),
            "created_at": created_at,
            "created_at_str": _fmt_dt_local(created_at, tz),
            "order_status": (o.get("order_status") or o.get("status") or "pending").lower(),
            "payment_status": (o.get("payment_status") or "unpaid").lower(),
            "formatted_total": o.get("formatted_total") or format_currency(o.get("total_amount") or 0),
            "buyer_display": display_name,
            "items": items_out,
            "address": ship["address"],
            "city": ship["city"],
        })

    return templates.TemplateResponse(
        "seller/orders_list.html",
        {"request": request, "orders": shaped, "current_user": current_user,
         "status": status or request.query_params.get("status", "") or "",
         "payment": payment or request.query_params.get("payment", "") or "",
         "sort": sort or request.query_params.get("sort", "created_desc")},
    )

@router.get("/seller/orders/review", response_class=HTMLResponse)
def seller_review_queue(request: Request, current_user: dict = Depends(require_role("seller"))):
    db = get_database()
    tz = _user_tz(request, db, current_user)

    cur = db.Orders.find(
        {
            "pharmacy_id": current_user["id"],
            "payment_status": {"$in": ["proof_uploaded", "rejected"]},
            "order_status": {"$in": ["pending", "confirmed"]},
        }
    ).sort("updated_at", -1)

    orders = list(cur)
    shaped = []
    for o in orders:
        shaped.append({
            "_id": str(o["_id"]),
            "buyer_id": o.get("buyer_id"),
            "created_at_str": _fmt_dt_local(o.get("created_at"), tz),
            "order_status": (o.get("order_status") or "pending").lower(),
            "payment_status": (o.get("payment_status") or "unpaid").lower(),
            "formatted_total": o.get("formatted_total") or format_currency(o.get("total_amount", 0)),
            "payment_id": (o.get("payment") or {}).get("payment_id"),
            "receipt_path": (o.get("payment") or {}).get("receipt_path"),
            "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
        })

    return templates.TemplateResponse("seller/review_list.html", {"request": request, "orders": shaped, "current_user": current_user})

@router.get("/seller/orders/{order_id}", response_class=HTMLResponse)
def seller_order_detail(
    request: Request,
    order_id: str,
    current_user: dict = Depends(require_role("seller"))
):
    db = get_database()
    tz = _user_tz(request, db, current_user)

    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")
    
    # Exclude cart+unpaid from seller detail too
    if (o.get("order_status") or "").lower() == "cart" and (o.get("payment_status") or "").lower() == "unpaid":
        raise HTTPException(404, "Order not found")

    buyer_name, buyer_phone, buyer_email = _lookup_buyer_display(db, o.get("buyer_id"))

    ship = _extract_shipping(o)

    # items + revenue
    items = []
    revenue_total = 0.0
    for it in (o.get("items") or []):
        q = int(it.get("quantity", 0) or 0)
        p_sell = float(it.get("price", 0) or 0.0)
        p_buy = float(it.get("buying_price", 0) or 0.0)
        line_total = q * p_sell
        line_rev = (p_sell - p_buy) * q
        revenue_total += line_rev
        items.append({
            "medicine_name": it.get("medicine_name", "Unknown"),
            "quantity": q,
            "price": p_sell,
            "buying_price": p_buy,
            "line_total": line_total,
            "line_revenue": line_rev,
        })

    total_amount = o.get("total_amount")
    if total_amount is None:
        total_amount = sum(x["line_total"] for x in items)

    order_status = (o.get("order_status") or o.get("status") or "pending").lower()
    payment_status = (o.get("payment_status") or "unpaid").lower()

    actions = {
        "verify": {"can": (payment_status == "proof_uploaded"), "done": (payment_status == "paid")},
        "reject": {"can": (payment_status == "proof_uploaded"), "done": (payment_status == "rejected")},
        "delivered": {"can": (order_status in ["confirmed", "dispatched"]) and (payment_status == "paid"),
                      "done": (order_status == "delivered")},
    }

    resolved_name = o.get("pharmacy_name") or _lookup_pharmacy_name(db, o.get("pharmacy_id") or o.get("seller_id"))
    if resolved_name and resolved_name != o.get("pharmacy_name"):
        db.Orders.update_one({"_id": o["_id"]}, {"$set": {"pharmacy_name": resolved_name, "updated_at": _now()}})
    logger.info(f"[seller_detail] order={o.get('_id')} pid={o.get('pharmacy_id') or o.get('seller_id')} name={resolved_name}")

    order = {
        "_id": str(o["_id"]),
        "created_at": o.get("created_at"),
        "created_at_str": _fmt_dt_local(o.get("created_at"), tz),
        "updated_at_str": _fmt_dt_local(o.get("updated_at"), tz),
        "order_status": order_status,
        "payment_status": payment_status,
        "payment": {
            "payment_id": (o.get("payment") or {}).get("payment_id"),
            "receipt_path": (o.get("payment") or {}).get("receipt_path"),
            "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            "uploaded_at": _fmt_dt_local((o.get("payment") or {}).get("uploaded_at"), tz) if (o.get("payment") or {}).get("uploaded_at") else None,
        },
        "items": items,
        "formatted_total": o.get("formatted_total") or format_currency(total_amount),
        "revenue_total": revenue_total,
        "formatted_revenue_total": format_currency(revenue_total),
        "buyer": {"display": buyer_name, "phone": buyer_phone, "email": buyer_email},
        "ship_to": {"address": ship["address"], "city": ship["city"]},
        "timeline": o.get("timeline", []),
        "actions": actions,
        "pharmacy_name": resolved_name or "Unknown Pharmacy",
    }

    return templates.TemplateResponse("seller/order_detail.html", {"request": request, "order": order, "current_user": current_user})

@router.post("/seller/orders/{order_id}/verify")
def seller_verify_payment(order_id: str, current_user: dict = Depends(require_role("seller"))):
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    if (o.get("payment_status") or "").lower() != "proof_uploaded":
        raise HTTPException(400, "No proof to verify")

    db.Orders.update_one(
        {"_id": oid},
        {"$set": {"payment_status": "paid", "order_status": "confirmed", "status": "confirmed", "updated_at": _now()},
         "$push": {"timeline": {"ts": _now(), "actor": "seller", "action": "payment_verified"}}}
    )
    return RedirectResponse(f"/seller/orders/{order_id}", status_code=303)

@router.post("/seller/orders/{order_id}/reject")
def seller_reject_payment(order_id: str, reason: str = Form(...), current_user: dict = Depends(require_role("seller"))):
    if not reason.strip():
        raise HTTPException(400, "Reason is required")

    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    db.Orders.update_one(
        {"_id": oid},
        {"$set": {"payment_status": "rejected", "payment.rejected_reason": reason, "updated_at": _now()},
         "$push": {"timeline": {"ts": _now(), "actor": "seller", "action": "payment_rejected", "meta": {"reason": reason}}}}
    )
    return RedirectResponse(f"/seller/orders/{order_id}", status_code=303)

@router.post("/seller/orders/{order_id}/delivered")
def seller_mark_delivered(order_id: str, current_user: dict = Depends(require_role("seller"))):
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    order_status = (o.get("order_status") or "").lower()
    payment_status = (o.get("payment_status") or "").lower()

    if payment_status != "paid":
        raise HTTPException(400, "Payment must be verified before delivery")
    if order_status not in ["confirmed", "dispatched"]:
        raise HTTPException(400, "Order must be confirmed or dispatched to mark delivered")

    db.Orders.update_one(
        {"_id": oid},
        {"$set": {"order_status": "delivered", "status": "delivered", "delivered": {"ts": _now()}, "updated_at": _now()},
         "$push": {"timeline": {"ts": _now(), "actor": "seller", "action": "delivered"}}}
    )
    return RedirectResponse(f"/seller/orders/{order_id}", status_code=303)
