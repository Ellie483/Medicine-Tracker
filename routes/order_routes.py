# routes/order_routes.py

from typing import Optional
import os
import uuid
from datetime import datetime

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

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# ======================== MODELS ========================

class AddToCartRequest(BaseModel):
    medicine_id: str
    quantity: int


# ======================== HELPERS ========================

def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")

def _to_oid(maybe_id):
    if isinstance(maybe_id, ObjectId):
        return maybe_id
    return ObjectId(str(maybe_id))

def _now():
    return datetime.utcnow()

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
                "timeline": {
                    "ts": _now(),
                    "actor": actor,
                    "action": action,
                    "meta": meta or {},
                }
            },
            "$set": {"updated_at": _now()},
        },
    )


# ======================== BUYER FLOWS ========================

@router.post("/buyer/add_to_cart")
async def add_to_cart(
    medicine_id: str = Form(...),
    quantity: int = Form(...),
    current_user: dict = Depends(require_role("buyer")),
):
    buyer_id = current_user["id"]

    # 1) Validate incoming fields
    try:
        payload = AddToCartRequest(medicine_id=medicine_id, quantity=quantity)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if payload.quantity < 1:
        raise HTTPException(status_code=422, detail="Quantity must be >= 1")

    db = get_database()

    # 2) Load medicine and pharmacy
    try:
        med_oid = _to_oid(payload.medicine_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid medicine ID")

    med = db.Medicine.find_one({"_id": med_oid})
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")

    price = float(med.get("price", 0))
    pharmacy_id = med.get("seller_id")
    pharmacy_id_str = str(pharmacy_id) if pharmacy_id else None

    pharmacy_name = "Unknown Pharmacy"
    if pharmacy_id:
        pharm = db.pharmacy_profiles.find_one({"_id": _to_oid(pharmacy_id)})
        if pharm:
            pharmacy_name = pharm.get("pharmacy_name", pharmacy_name)

    # 3) Find an existing OPEN order for this buyer + pharmacy
    #    We only merge into orders that are still editable: order_status in ['cart','pending'] AND payment_status == 'unpaid'
    existing = db.Orders.find_one({
        "buyer_id": buyer_id,
        "pharmacy_id": pharmacy_id_str,
        "order_status": {"$in": ["cart", "pending"]},
        "payment_status": "unpaid",
    })

    line_delta_total = payload.quantity * price

    if existing:
        # 4) Merge into existing order
        items = existing.get("items", []) or []

        # Find existing line for this medicine
        idx = None
        for i, it in enumerate(items):
            # compare by ObjectId (string-safety)
            if str(it.get("medicine_id")) == str(med["_id"]):
                idx = i
                break

        if idx is not None:
            # Increase quantity on the existing line
            new_qty = int(items[idx].get("quantity", 0)) + int(payload.quantity)
            items[idx]["quantity"] = new_qty
            items[idx]["price"] = price  # keep price current (optional)
            items[idx]["total"] = new_qty * price
        else:
            # Append a new line
            items.append({
                "medicine_id": med["_id"],
                "medicine_name": med.get("name", "Unknown"),
                "quantity": int(payload.quantity),
                "price": price,
                "total": line_delta_total,
            })

        # Recompute totals
        total_amount = sum((int(it.get("quantity", 0)) * float(it.get("price", 0))) for it in items)
        formatted_total = format_currency(total_amount)

        db.Orders.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "items": items,
                    "total_amount": total_amount,
                    "formatted_total": formatted_total,
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

        return JSONResponse(
            status_code=200,
            content={
                "message": "Updated your existing order for this pharmacy.",
                "order_id": str(existing["_id"]),
                "merged": True,
            },
        )

    # 5) No open order found → create a new one
    order_doc = {
        "buyer_id": buyer_id,
        "pharmacy_id": pharmacy_id_str,
        "pharmacy_name": pharmacy_name,
        "items": [
            {
                "medicine_id": med["_id"],
                "medicine_name": med.get("name", "Unknown"),
                "quantity": int(payload.quantity),
                "price": price,
                "total": line_delta_total,
            }
        ],
        "total_amount": line_delta_total,
        "formatted_total": format_currency(line_delta_total),

        # state
        "order_status": "cart",     # editable cart; you can also choose 'pending' if you've defined that as "open"
        "payment_status": "unpaid",
        "payment": {
            "payment_id": None,
            "receipt_path": None,
            "rejected_reason": None,
            "uploaded_at": None,
        },

        "created_at": _now(),
        "updated_at": _now(),
        "status": "cart",           # legacy mirror
        "timeline": [
            {
                "ts": _now(),
                "actor": "buyer",
                "action": "create_cart",
                "meta": {
                    "medicine_id": str(med["_id"]),
                    "quantity": int(payload.quantity),
                    "line_total": line_delta_total,
                },
            }
        ],
    }

    try:
        res = db.Orders.insert_one(order_doc)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create order")

    return JSONResponse(
        status_code=200,
        content={
            "message": "Created a new order for this pharmacy.",
            "order_id": str(res.inserted_id),
            "merged": False,
        },
    )


@router.get("/buyer/orders", response_class=HTMLResponse)
def buyer_orders(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    buyer_id = current_user["id"]

    q = (request.query_params.get("q") or "").strip()
    status = request.query_params.get("status")  # 'cart' | 'pending' | 'confirmed' | 'delivered' (optional)
    sort_key = request.query_params.get("sort", "created_desc")

    # Build query
    query = {"buyer_id": buyer_id}
    if status in ["cart", "pending", "confirmed", "delivered"]:
        query["order_status"] = status

    if q:
        query["$or"] = [
            {"pharmacy_name": {"$regex": q, "$options": "i"}},
            {"items.medicine_name": {"$regex": q, "$options": "i"}},
        ]

    # Map sort
    sort_map = {
        "created_desc": [("created_at", -1)],
        "created_asc":  [("created_at", 1)],
        "total_desc":   [("total_amount", -1), ("created_at", -1)],
        "total_asc":    [("total_amount", 1),  ("created_at", -1)],
    }
    sort_spec = sort_map.get(sort_key, [("created_at", -1)])

    # Fetch
    orders = list(db.Orders.find(query).sort(sort_spec))

    # (rest of your formatting code…)
    formatted_orders = []
    for o in orders:
        items = [{
            "medicine_name": it.get("medicine_name", "Unknown"),
            "quantity": int(it.get("quantity", 0) or 0),
            "price": float(it.get("price", 0) or 0.0),
        } for it in o.get("items", [])]

        computed_total = sum(i["price"] * i["quantity"] for i in items)
        formatted_orders.append({
            "_id": str(o.get("_id")),
            "created_at": o.get("created_at"),
            "created_at_str": _fmt_dt(o.get("created_at")),
            "order_status": o.get("order_status") or o.get("status", "cart"),
            "payment_status": o.get("payment_status", "unpaid"),
            "items": items,
            "pharmacy_name": o.get("pharmacy_name", "Unknown Pharmacy"),
            "formatted_total": o.get("formatted_total") or format_currency(computed_total),
            "payment": {
                "payment_id": (o.get("payment") or {}).get("payment_id"),
                "receipt_path": (o.get("payment") or {}).get("receipt_path"),
                "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            },
        })

    return templates.TemplateResponse(
        "buyer/orders_list.html",
        {
            "request": request,
            "orders": formatted_orders,
            "current_user": current_user,
            # (optional) pass sort/status so chips can highlight
            "sort": sort_key,
            "status": status or "",
            "q": q,
        },
    )



@router.get("/buyer/orders/{order_id}", response_class=HTMLResponse)
def buyer_order_detail(
    request: Request,
    order_id: str,
    current_user: dict = Depends(require_role("buyer"))
):
    """Order detail page (full view)."""
    db = get_database()
    buyer_id = current_user["id"]

    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")

    o = db.Orders.find_one({"_id": oid, "buyer_id": buyer_id})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")

    items = []
    for it in o.get("items", []):
        q = int(it.get("quantity", 0) or 0)
        p = float(it.get("price", 0) or 0.0)
        items.append({
            "medicine_name": it.get("medicine_name", "Unknown"),
            "quantity": q,
            "price": p,
            "line_total": q * p,
        })

    total_amount = o.get("total_amount")
    if total_amount is None:
        total_amount = sum(x["line_total"] for x in items)

    order = {
        "_id": str(o["_id"]),
        "created_at": o.get("created_at"),
        "created_at_str": _fmt_dt(o.get("created_at")),
        "order_status": o.get("order_status") or o.get("status", "cart"),
        "status": o.get("order_status") or o.get("status", "cart"),  # mirror
        "payment_status": o.get("payment_status", "unpaid"),
        "payment": {
            "payment_id": (o.get("payment") or {}).get("payment_id"),
            "receipt_path": (o.get("payment") or {}).get("receipt_path"),
            "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            "uploaded_at": (o.get("payment") or {}).get("uploaded_at"),
        },
        "items": items,
        "pharmacy_name": o.get("pharmacy_name", "Unknown Pharmacy"),
        "pharmacy_address": o.get("pharmacy_address"),
        "formatted_total": o.get("formatted_total") or format_currency(total_amount),
    }

    return templates.TemplateResponse(
    "buyer/order_detail.html",
    {"request": request, "order": order, "current_user": current_user},
)


@router.post("/buyer/orders/{order_id}/submit_and_upload")
async def submit_and_upload(
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

    # Only allow if this is the buyer and still open
    o = db.Orders.find_one({"_id": oid, "buyer_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    if (o.get("order_status") not in ["cart", "pending"]) or (o.get("payment_status") not in ["unpaid", "rejected"]):
        raise HTTPException(400, "Order not in a state that can be submitted")

    # Save proof
    receipt_path = _save_receipt(order_id, file)

    # Move to pending + under review
    db.Orders.update_one(
        {"_id": oid},
        {
            "$set": {
                "order_status": "pending",
                "status": "pending",  # mirror if old templates read 'status'
                "payment_status": "proof_uploaded",
                "payment.payment_id": payment_id,
                "payment.receipt_path": receipt_path,
                "payment.rejected_reason": None,
                "payment.uploaded_at": _now(),
                "shipping": {
                    "address_line": address_line,
                    "city": city,
                },
                "updated_at": _now(),
            },
            "$push": {
                "timeline": {
                    "ts": _now(),
                    "actor": "buyer",
                    "action": "submit_order",
                    "meta": {"payment_id": payment_id, "city": city}
                }
            },
        },
    )

    return RedirectResponse(f"/buyer/orders/{order_id}", status_code=303)


@router.post("/buyer/orders/{order_id}/payment")
def upload_payment(
    order_id: str,
    payment_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role("buyer")),
):
    """Upload/replace payment proof; set payment_status to proof_uploaded."""
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "buyer_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    # allow upload while pending or confirmed
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


# ======================== PHARMACY FLOWS ========================

@router.get("/pharmacy/orders/review", response_class=HTMLResponse)
def pharm_review_page(request: Request, current_user: dict = Depends(require_role("pharmacy"))):
    """Payment proofs awaiting verification (and recently rejected)."""
    db = get_database()
    cur = db.Orders.find(
        {
            "pharmacy_id": current_user["id"],
            "payment_status": {"$in": ["proof_uploaded", "rejected"]},
            "order_status": {"$in": ["placed", "confirmed"]},
        }
    ).sort("updated_at", -1)
    orders = list(cur)

    shaped = []
    for o in orders:
        shaped.append(
            {
                "_id": str(o["_id"]),
                "buyer_id": o.get("buyer_id"),
                "created_at_str": _fmt_dt(o.get("created_at")),
                "order_status": o.get("order_status"),
                "payment_status": o.get("payment_status"),
                "formatted_total": o.get("formatted_total"),
                "payment_id": (o.get("payment") or {}).get("payment_id"),
                "receipt_path": (o.get("payment") or {}).get("receipt_path"),
                "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            }
        )

        return templates.TemplateResponse(
            "pharmacy/review_list.html",
            {"request": request, "orders": shaped, "current_user": current_user},
        )

@router.get("/pharmacy/orders", response_class=HTMLResponse)
def pharm_orders_list(
    request: Request,
    status: Optional[str] = None,
    payment: Optional[str] = None,
    current_user: dict = Depends(require_role("pharmacy")),
):
    """All pharmacy orders with simple filters."""
    db = get_database()
    q = {"pharmacy_id": current_user["id"]}
    if status:
        q["order_status"] = status
    if payment:
        q["payment_status"] = payment

    cur = db.Orders.find(q).sort("created_at", -1)
    orders = list(cur)

    shaped = []
    for o in orders:
        shaped.append(
            {
                "_id": str(o["_id"]),
                "buyer_id": o.get("buyer_id"),
                "created_at_str": _fmt_dt(o.get("created_at")),
                "order_status": o.get("order_status"),
                "payment_status": o.get("payment_status"),
                "formatted_total": o.get("formatted_total"),
                "pharmacy_name": o.get("pharmacy_name"),
            }
        )

    return templates.TemplateResponse(
    "pharmacy/orders_list.html",
    {"request": request, "orders": shaped, "status": status or "", "payment": payment or "", "current_user": current_user},
)


@router.get("/pharmacy/orders/{order_id}", response_class=HTMLResponse)
def pharm_order_detail(
    request: Request, order_id: str, current_user: dict = Depends(require_role("pharmacy"))
):
    """Pharmacy-side order detail."""
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    items = []
    for it in o.get("items", []):
        q = int(it.get("quantity", 0) or 0)
        p = float(it.get("price", 0) or 0.0)
        items.append(
            {
                "medicine_name": it.get("medicine_name", "Unknown"),
                "quantity": q,
                "price": p,
                "line_total": q * p,
            }
        )

    total_amount = o.get("total_amount")
    if total_amount is None:
        total_amount = sum(x["line_total"] for x in items)

    order = {
        "_id": str(o["_id"]),
        "created_at_str": _fmt_dt(o.get("created_at")),
        "order_status": o.get("order_status"),
        "payment_status": o.get("payment_status"),
        "payment": {
            "payment_id": (o.get("payment") or {}).get("payment_id"),
            "receipt_path": (o.get("payment") or {}).get("receipt_path"),
            "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            "uploaded_at": (o.get("payment") or {}).get("uploaded_at"),
        },
        "items": items,
        "formatted_total": o.get("formatted_total") or format_currency(total_amount),
        "buyer_id": o.get("buyer_id"),
        "pharmacy_name": o.get("pharmacy_name"),
        "pharmacy_address": o.get("pharmacy_address"),
        "timeline": o.get("timeline", []),
    }

    return templates.TemplateResponse(
    "pharmacy/order_detail.html",
    {"request": request, "order": order, "current_user": current_user},
)

@router.post("/pharmacy/orders/{order_id}/verify")
def pharm_verify(order_id: str, current_user: dict = Depends(require_role("pharmacy"))):
    """Confirm payment (proof_uploaded -> paid) and promote order to confirmed."""
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    if o.get("payment_status") != "proof_uploaded":
        raise HTTPException(400, "No proof to verify")

    db.Orders.update_one(
        {"_id": oid},
        {
            "$set": {
                "payment_status": "paid",
                "order_status": "confirmed",
                "status": "confirmed",  # mirror
                "updated_at": _now(),
            }
        },
    )
    _audit(db, oid, "pharmacy", "payment_verified")
    return RedirectResponse(f"/pharmacy/orders/{order_id}", status_code=303)


@router.post("/pharmacy/orders/{order_id}/reject")
def pharm_reject(
    order_id: str,
    reason: str = Form(...),
    current_user: dict = Depends(require_role("pharmacy")),
):
    """Reject a payment proof with a reason (proof_uploaded -> rejected)."""
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
        {
            "$set": {
                "payment_status": "rejected",
                "payment.rejected_reason": reason,
                "updated_at": _now(),
            }
        },
    )
    _audit(db, oid, "pharmacy", "payment_rejected", {"reason": reason})
    return RedirectResponse(f"/pharmacy/orders/{order_id}", status_code=303)


@router.post("/pharmacy/orders/{order_id}/dispatch")
def pharm_dispatch(
    order_id: str,
    tracking_no: Optional[str] = Form(None),
    current_user: dict = Depends(require_role("pharmacy")),
):
    """Dispatch an order (requires payment_status=paid)."""
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    if o.get("payment_status") != "paid":
        raise HTTPException(400, "Payment not verified")

    db.Orders.update_one(
        {"_id": oid},
        {
            "$set": {
                "order_status": "dispatched",
                "status": "dispatched",  # mirror
                "dispatch": {"tracking_no": tracking_no, "ts": _now()},
                "updated_at": _now(),
            }
        },
    )
    _audit(db, oid, "pharmacy", "dispatched", {"tracking_no": tracking_no})
    return RedirectResponse(f"/pharmacy/orders/{order_id}", status_code=303)


@router.post("/pharmacy/orders/{order_id}/delivered")
def pharm_delivered(order_id: str, current_user: dict = Depends(require_role("pharmacy"))):
    """Mark an order delivered (allowed from confirmed or dispatched)."""
    db = get_database()
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    if o.get("order_status") not in ["dispatched", "confirmed"]:
        raise HTTPException(400, "Order must be confirmed or dispatched to mark delivered")

    db.Orders.update_one(
        {"_id": oid},
        {
            "$set": {
                "order_status": "delivered",
                "status": "delivered",  # mirror
                "delivered": {"ts": _now()},
                "updated_at": _now(),
            }
        },
    )
    _audit(db, oid, "pharmacy", "delivered")
    return RedirectResponse(f"/pharmacy/orders/{order_id}", status_code=303)
