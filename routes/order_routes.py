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

import re
from bson import ObjectId
from fastapi.responses import JSONResponse

def _normalize_mid(mid: str) -> str:
    """Return the 24-char hex id from many possible shapes."""
    if mid is None:
        return ""
    s = str(mid)
    # ObjectId('...') or ObjectId("...")
    m = re.match(r"ObjectId\(['\"]?([0-9a-fA-F]{24})['\"]?\)", s)
    if m:
        return m.group(1)
    # {"$oid":"..."} or {"_id":"..."} or {"id":"..."}
    m = re.search(r'([0-9a-fA-F]{24})', s)
    return m.group(1) if m else s

def _extract_item_mid(it: dict) -> str:
    """Try multiple keys/shapes for item medicine id."""
    for k in ("medicine_id", "_id", "id"):
        if k in it and it[k] is not None:
            v = it[k]
            if isinstance(v, dict):
                v = v.get("$oid") or v.get("_id") or v.get("id") or v
            return _normalize_mid(v)
    return ""
# --- Seller receipt generation ---------------------------------------------
# --- RECEIPT (VOUCHER) GENERATION & NOTIFY HELPERS ---

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics

def _generate_seller_receipt(db, order: dict, out_dir: str = "static/seller_receipts") -> str:
    """
    Create a nicer PDF voucher (seller-issued receipt) for the order.
    Returns a web path like: /static/seller_receipts/<order_id>/receipt.pdf
    """
    import os
    os.makedirs(out_dir, exist_ok=True)
    subdir = os.path.join(out_dir, str(order["_id"]))
    os.makedirs(subdir, exist_ok=True)

    pdf_path = os.path.join(subdir, "receipt.pdf")
    url_path = f"/{subdir.replace(os.sep, '/')}/receipt.pdf"

    # ---- data ----
    buyer_name, _, _ = _lookup_buyer_display(db, order.get("buyer_id"))
    ship = _extract_shipping(order) or {}
    addr = ship.get("address") or ship.get("address_line") or ship.get("line1") or "-"
    city = ship.get("city") or "-"

    created_str = _fmt_dt_local(order.get("created_at"), "Asia/Yangon")
    pharmacy_name = order.get("pharmacy_name") or "Unknown Pharmacy"
    items = list(order.get("items") or [])

    total_amount = order.get("total_amount")
    if total_amount is None:
        total_amount = sum(
            int(i.get("quantity", 0) or 0) * float(i.get("price", 0) or 0.0)
            for i in items
        )

    # ---- pdf canvas ----
    c = canvas.Canvas(pdf_path, pagesize=A4)
    W, H = A4
    margin_x = 18 * mm
    margin_top = 20 * mm
    y = H - margin_top

    # table geometry
    table_left = margin_x
    table_right = W - margin_x
    table_width = table_right - table_left

    # columns: Name (68%), Qty (10%), Price (22%)
    name_w  = table_width * 0.68
    qty_w   = table_width * 0.10
    price_w = table_width * 0.22

    # x positions (left edges); for right-align we will use right edge
    x_name  = table_left
    x_qty_r = table_left + name_w + qty_w  # right edge of qty col
    x_price_r = table_right                # right edge of price col

    def hr(y_pos, lw=0.6, col=colors.black):
        c.setLineWidth(lw)
        c.setStrokeColor(col)
        c.line(table_left, y_pos, table_right, y_pos)

    def clip_text_to_width(text, max_w, font="Helvetica", size=10):
        """Return text that fits into max_w (in points), trimming with … if needed."""
        w = pdfmetrics.stringWidth(text, font, size)
        if w <= max_w:
            return text
        ell = "…"
        ell_w = pdfmetrics.stringWidth(ell, font, size)
        # binary-ish shrink
        s = text
        while s and pdfmetrics.stringWidth(s, font, size) + ell_w > max_w:
            s = s[:-1]
        return (s + ell) if s else text[:1] + ell

    def draw_header():
        nonlocal y
        c.setFont("Helvetica-Bold", 18)
        c.drawString(margin_x, y, f"{pharmacy_name} — Voucher")
        y -= 8 * mm

        c.setFont("Helvetica", 10.5)
        c.drawString(margin_x, y, f"Order ID: {order['_id']}")
        y -= 5 * mm
        c.drawString(margin_x, y, f"Date: {created_str}")
        y -= 5 * mm
        c.drawString(margin_x, y, f"Buyer: {buyer_name}")
        y -= 5 * mm
        c.drawString(margin_x, y, f"Ship To: {addr}{', ' + city if city else ''}")
        y -= 6 * mm

        c.setStrokeColor(colors.HexColor("#D9D9D9"))
        hr(y)
        c.setStrokeColor(colors.black)
        y -= 8 * mm

    def draw_table_header():
        nonlocal y
        c.setFillColor(colors.HexColor("#F4F6F8"))
        c.rect(table_left, y - 14, table_width, 16, stroke=0, fill=1)
        c.setFillColor(colors.black)

        c.setFont("Helvetica-Bold", 10)
        c.drawString(x_name + 3, y - 11, "Medicine")
        c.drawRightString(x_qty_r - 3, y - 11, "Qty")
        c.drawRightString(x_price_r - 3, y - 11, "Price")
        y -= 18

        c.setStrokeColor(colors.HexColor("#E5E7EB"))
        hr(y)
        c.setStrokeColor(colors.black)
        y -= 6

    def ensure_room(min_h=24*mm):
        """Start a new page if we don't have vertical space; redraw headers."""
        nonlocal y
        if y < min_h:
            c.showPage()
            # reset margins & geometry for new page
            nonlocal W, H, table_left, table_right, table_width
            W, H = A4
            y = H - margin_top
            draw_header()
            draw_table_header()

    # ---- draw ----
    draw_header()
    draw_table_header()

    c.setFont("Helvetica", 10)
    row_h = 14  # row height

    for it in items:
        ensure_room()

        name  = str(it.get("medicine_name", "Unknown"))
        qty   = int(it.get("quantity", 0) or 0)
        price = float(it.get("price", 0) or 0.0)

        # trim long names to fit name column
        name_txt = clip_text_to_width(name, name_w - 6, "Helvetica", 10)

        # Name (left), Qty (right), Price (right)
        c.drawString(x_name + 3, y - 10, name_txt)
        c.drawRightString(x_qty_r - 3, y - 10, f"{qty:d}")
        c.drawRightString(x_price_r - 3, y - 10, f"{price:,.2f}Ks")

        y -= row_h
        # light row divider
        c.setStrokeColor(colors.HexColor("#F1F3F5"))
        hr(y)
        c.setStrokeColor(colors.black)
        y -= 2

    # total row
    y -= 8
    c.setFont("Helvetica-Bold", 11.5)
    c.drawRightString(x_price_r - 3, y, f"Total: {total_amount:,.2f}Ks")
    y -= 16

    # footer
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.gray)
    c.drawString(margin_x, y, "Thank you for your purchase.")
    y -= 12
    c.drawString(margin_x, y, "This voucher was generated by the pharmacy system.")
    c.setFillColor(colors.black)

    c.save()
    return url_path


def notify_buyer_with_receipt(db, order: dict, receipt_url: str) -> None:
    """
    Minimal 'notification': log + add timeline + stamp sent_at.
    Replace this with email/SMS/FCM/etc. when ready.
    """
    logger.info("[receipt_notify] order=%s -> %s", order.get("_id"), receipt_url)
    db.Orders.update_one(
        {"_id": order["_id"]},
        {
            "$set": {"payment.seller_receipt_sent_at": _now(), "updated_at": _now()},
            "$push": {"timeline": {"ts": _now(), "actor": "system", "action": "seller_receipt_sent", "meta": {"url": receipt_url}}},
        },
    )

def _to_hex(val) -> str:
    """
    Coerce val (ObjectId/str/dict with _id/$oid) to a consistent hex string
    so the comparison between DB-stored ObjectId and UI-sent string always matches.
    """
    if val is None:
        return ""
    if isinstance(val, dict):
        if "_id" in val:
            return _to_hex(val["_id"])
        if "$oid" in val:
            return _to_hex(val["$oid"])
    try:
        return str(ObjectId(str(val)))
    except Exception:
        return str(val).strip()

# ============== STOCK HELPERS (Medicine collection) ==============

def _reserve_item(db, mid: ObjectId, qty: int) -> bool:
    # available = stock - reserved  >= qty
    q = {
        "_id": mid,
        "$expr": {"$gte": [{"$subtract": ["$stock", {"$ifNull": ["$reserved", 0]}]}, qty]}
    }
    upd = {"$inc": {"reserved": qty}}
    return db.Medicine.update_one(q, upd).modified_count == 1

def _release_item(db, mid: ObjectId, qty: int) -> bool:
    q = {"_id": mid, "$expr": {"$gte": [{"$ifNull": ["$reserved", 0]}, qty]}}
    upd = {"$inc": {"reserved": -qty}}
    return db.Medicine.update_one(q, upd).modified_count == 1

def _commit_item(db, mid: ObjectId, qty: int) -> bool:
    # move from reserved → stock (decrement both)
    q = {"_id": mid, "$expr": {"$gte": [{"$ifNull": ["$reserved", 0]}, qty]}}
    upd = {"$inc": {"stock": -qty, "reserved": -qty}}
    return db.Medicine.update_one(q, upd).modified_count == 1


def create_notification(db, *, user_id: str, role: str, type_: str,
                        title: str, message: str, order_id=None, meta: dict | None = None):
    doc = {
        "user_id": str(user_id),
        "role": role,
        "type": type_,
        "title": title,
        "message": message,
        "order_id": str(order_id) if order_id else None,
        "meta": meta or {},
        "is_read": False,
        "created_at": _now(),
        "read_at": None,
    }
    db.Notifications.insert_one(doc)
    return doc
# ======================== BUYER FLOWS ========================
class AddToCartRequest(BaseModel):
    medicine_id: str
    quantity: int
@router.post("/buyer/add_to_cart")
async def add_to_cart(
    medicine_id: str = Form(...),
    quantity: int = Form(1),
    current_user: dict = Depends(require_role("buyer")),
):
    buyer_id = current_user["id"]
    if quantity < 1:
        quantity = 1

    try:
        payload = AddToCartRequest(medicine_id=medicine_id, quantity=quantity)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db = get_database()

    # Load medicine
    try:
        med_oid = _to_oid(payload.medicine_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid medicine ID")

    med = db.Medicine.find_one({"_id": med_oid})
    if not med:
        raise HTTPException(status_code=404, detail="Medicine not found")

    price_sell = float(med.get("selling_price", 0) or 0)
    price_buy  = float(med.get("buying_price", 0) or 0)
    available  = int(med.get("stock", 0)) - int(med.get("reserved", 0) or 0)

    if available <= 0:
        raise HTTPException(status_code=409, detail="Out of stock")

    seller_id        = med.get("seller_id")
    pharmacy_id_str  = str(seller_id) if seller_id else None
    pharmacy_name    = _lookup_pharmacy_name(db, pharmacy_id_str)
    logger.info(f"[cart] med={med.get('name')} seller_id={pharmacy_id_str} resolved_name={pharmacy_name}")

    # Find open order (cart or pending, unpaid/rejected)
    existing = db.Orders.find_one({
        "buyer_id": buyer_id,
        "pharmacy_id": pharmacy_id_str,
        "order_status": {"$in": ["cart", "pending"]},
        "payment_status": {"$in": ["unpaid", "rejected"]},
    })

    add_qty = int(payload.quantity)
    line_delta_total = add_qty * price_sell

    if existing:
        items = existing.get("items") or []
        idx = next((i for i, it in enumerate(items)
                    if str(it.get("medicine_id")) == str(med["_id"])), None)

        is_pending = (existing.get("order_status") == "pending")

        if idx is not None:
            # If pending, reserve the additional quantity first
            if is_pending:
                if not _reserve_item(db, med_oid, add_qty):
                    raise HTTPException(status_code=409, detail="out_of_stock")
                # grow reserved on that line
                items[idx]["reserved_qty"] = int(items[idx].get("reserved_qty", items[idx].get("quantity", 0))) + add_qty
            else:
                # in cart: basic guard to avoid obvious oversell
                if available < add_qty:
                    raise HTTPException(status_code=409, detail="Out of stock")

            new_qty = int(items[idx].get("quantity", 0)) + add_qty
            items[idx]["quantity"]      = new_qty
            items[idx]["price"]         = price_sell
            items[idx]["buying_price"]  = price_buy
            items[idx]["total"]         = new_qty * price_sell

            if is_pending:
                # keep reserved == quantity for pending
                items[idx]["reserved_qty"] = new_qty
        else:
            # New line
            if is_pending:
                if not _reserve_item(db, med_oid, add_qty):
                    raise HTTPException(status_code=409, detail="out_of_stock")
                items.append({
                    "medicine_id": med["_id"],
                    "medicine_name": med.get("name", "Unknown"),
                    "quantity": add_qty,
                    "reserved_qty": add_qty,
                    "price": price_sell,
                    "buying_price": price_buy,
                    "total": line_delta_total,
                })
            else:
                if available < add_qty:
                    raise HTTPException(status_code=409, detail="Out of stock")
                items.append({
                    "medicine_id": med["_id"],
                    "medicine_name": med.get("name", "Unknown"),
                    "quantity": add_qty,
                    "price": price_sell,
                    "buying_price": price_buy,
                    "total": line_delta_total,
                })

        total_amount   = sum(int(it.get("quantity", 0)) * float(it.get("price", 0) or 0.0) for it in items)
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
                        "meta": {"medicine_id": str(med["_id"]), "quantity_added": add_qty, "line_total_added": line_delta_total},
                    }
                },
            },
        )
        return JSONResponse(status_code=200, content={
            "message": "Updated existing order.", "order_id": str(existing["_id"]), "merged": True
        })

    # New order (cart state, no reservation yet)
    order_doc = {
        "buyer_id": buyer_id,
        "pharmacy_id": pharmacy_id_str,
        "pharmacy_name": pharmacy_name,
        "items": [{
            "medicine_id": med["_id"],
            "medicine_name": med.get("name", "Unknown"),
            "quantity": add_qty,
            "price": price_sell,
            "buying_price": price_buy,
            "total": line_delta_total,
        }],
        "total_amount": line_delta_total,
        "formatted_total": format_currency(line_delta_total),
        "order_status": "cart",
        "status": "cart",
        "payment_status": "unpaid",
        "payment": {"payment_id": None, "receipt_path": None, "rejected_reason": None, "uploaded_at": None},
        "created_at": _now(),
        "updated_at": _now(),
        "timeline": [{
            "ts": _now(), "actor": "buyer", "action": "create_cart",
            "meta": {"medicine_id": str(med["_id"]), "quantity": add_qty, "line_total": line_delta_total},
        }],
    }
    try:
        res = db.Orders.insert_one(order_doc)
        logger.info(f"[cart] Created order={res.inserted_id} for seller_id={pharmacy_id_str} name={pharmacy_name}")
    except Exception:
        logger.exception("Failed to create order")
        raise HTTPException(status_code=500, detail="Failed to create order")

    return JSONResponse(status_code=200, content={
        "message": "Created a new order.", "order_id": str(res.inserted_id), "merged": False
    })

from pydantic import BaseModel, Field
class UpdateItemReq(BaseModel):
    medicine_id: str = Field(..., description="The medicine ID")
    delta: int = Field(..., description="Use +1 to increase or -1 to decrease")
    
@router.post("/buyer/orders/{order_id}/update_item")
def update_item(
    order_id: str,
    payload: UpdateItemReq,
    current_user: dict = Depends(require_role("buyer")),
):
    db = get_database()
    oid = _to_oid(order_id)

    o = db.Orders.find_one({
        "_id": oid,
        "buyer_id": current_user["id"],
        "order_status": {"$in": ["cart", "pending"]},
        "payment_status": {"$in": ["unpaid", "rejected"]},
    })
    if not o:
        return JSONResponse(status_code=400, content={"detail": "not_editable"})

    want  = _normalize_mid(payload.medicine_id)
    items = list(o.get("items") or [])

    idx = next((i for i, it in enumerate(items) if _extract_item_mid(it) == want), None)
    if idx is None:
        idx = next((i for i, it in enumerate(items) if str(it.get("medicine_name")) == str(payload.medicine_id)), None)
    if idx is None:
        return JSONResponse(status_code=404, content={"detail": "item_not_found"})

    it         = items[idx]
    delta      = int(payload.delta)
    new_qty    = int(it.get("quantity", 0)) + delta
    is_pending = (o.get("order_status") == "pending")

    # try to reserve/release first (when pending)
    if is_pending and delta != 0:
        try:
            mid = _to_oid(_extract_item_mid(it))
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "bad_medicine_id"})

        if delta > 0:
            if not _reserve_item(db, mid, delta):
                return JSONResponse(status_code=409, content={"detail": "out_of_stock"})
            it["reserved_qty"] = int(it.get("reserved_qty", it.get("quantity", 0))) + delta
        else:
            rel = abs(delta)
            _release_item(db, mid, rel)
            it["reserved_qty"] = max(0, int(it.get("reserved_qty", it.get("quantity", 0))) - rel)

    removed = False
    if new_qty <= 0:
        # if removing the row while pending, release any remaining reserved
        if is_pending:
            try:
                mid = _to_oid(_extract_item_mid(it))
                rq  = int(it.get("reserved_qty", it.get("quantity", 0)) or 0)
                if rq > 0: _release_item(db, mid, rq)
            except Exception:
                pass
        items.pop(idx)
        removed = True
        line_total = 0.0
    else:
        it["quantity"] = new_qty
        price          = float(it.get("price", 0) or 0.0)
        it["total"]    = new_qty * price
        if is_pending:
            # keep reserved == quantity to stay in sync
            it["reserved_qty"] = new_qty
        items[idx] = it
        line_total = it["total"]

    if len(items) == 0:
        db.Orders.delete_one({"_id": o["_id"]})
        return {
            "deleted": True,
            "removed": True,
            "quantity": 0,
            "line_total": 0.0,
            "order_total": 0.0,
            "formatted_order_total": format_currency(0.0),
        }

    total_amount    = sum(int(x.get("quantity", 0)) * float(x.get("price", 0) or 0.0) for x in items)
    formatted_total = format_currency(total_amount)

    db.Orders.update_one(
        {"_id": o["_id"]},
        {"$set": {
            "items": items,
            "total_amount": total_amount,
            "formatted_total": formatted_total,
            "updated_at": _now(),
        }}
    )

    return {
        "deleted": False,
        "removed": removed,
        "quantity": 0 if removed else new_qty,
        "line_total": line_total,
        "order_total": total_amount,
        "formatted_order_total": formatted_total,
    }

@router.post("/buyer/orders/{order_id}/cancel")
def buyer_cancel_order(
    order_id: str,
    current_user: dict = Depends(require_role("buyer")),
):
    db = get_database()
    oid = _to_oid(order_id)

    o = db.Orders.find_one({
        "_id": oid,
        "buyer_id": current_user["id"],
        "order_status": {"$in": ["cart", "pending"]},
        "payment_status": {"$in": ["unpaid", "rejected"]},
    })
    if not o:
        raise HTTPException(400, "Order cannot be cancelled at this stage")

    # If pending, release reservations
    if (o.get("order_status") == "pending"):
        for it in (o.get("items") or []):
            rq = int(it.get("reserved_qty", it.get("quantity", 0)) or 0)
            if rq > 0:
                try:
                    _release_item(db, _to_oid(_extract_item_mid(it)), rq)
                except Exception:
                    pass

    db.Orders.delete_one({"_id": o["_id"]})
    _audit(db, oid, "buyer", "cancelled_order", {})

    return RedirectResponse("/buyer/orders", status_code=303)


@router.get("/buyer/orders", response_class=HTMLResponse)
def buyer_orders(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()
    tz = _user_tz(request, db, current_user)
    buyer_id = current_user["id"]
    filt = {
        "buyer_id": current_user["id"],
        # hide empty carts
        "$expr": {"$gt": [{"$size": "$items"}, 0]},
        # and hide zero-amount orders (safety)
        "total_amount": {"$gt": 0},
    }

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

    # --- Load order ---
    try:
        oid = _to_oid(order_id)
    except Exception:
        raise HTTPException(404, "Order not found")

    o = db.Orders.find_one({"_id": oid, "buyer_id": current_user["id"]})
    if not o:
        raise HTTPException(404, "Order not found")

    # --- Items & totals ---
    ship = _extract_shipping(o)
    items = []
    for it in (o.get("items") or []):
        q = int(it.get("quantity", 0) or 0)
        p_sell = float(it.get("price", 0) or 0.0)
        items.append({
            "medicine_name": it.get("medicine_name", "Unknown"),
            "quantity": q,
            "price": p_sell,
            "line_total": q * p_sell
        })

    total_amount = o.get("total_amount")
    if total_amount is None:
        total_amount = sum(x["line_total"] for x in items)

    # --- Resolve pharmacy display name on the order (once) ---
    resolved_name = o.get("pharmacy_name") or _lookup_pharmacy_name(
        db, o.get("pharmacy_id") or o.get("seller_id")
    )
    if resolved_name and resolved_name != o.get("pharmacy_name"):
        db.Orders.update_one(
            {"_id": o["_id"]},
            {"$set": {"pharmacy_name": resolved_name, "updated_at": _now()}}
        )

    pid = o.get("pharmacy_id") or o.get("seller_id")
    logger.info(
        "[buyer_detail] order=%s pid=%s name=%s",
        o.get("_id"), pid, resolved_name
    )

    # --- Fetch pharmacy profile robustly (for QR) ---
    pharmacy_profile = None
    if pid:
        # Try as profile _id
        try:
            pharmacy_profile = db.pharmacy_profiles.find_one({"_id": _to_oid(pid)})
        except Exception:
            pharmacy_profile = None

        # If not found, try matching the user_id field as a string
        if not pharmacy_profile:
            # pid could be ObjectId or str; normalize to str for user_id
            pid_str = str(pid)
            pharmacy_profile = db.pharmacy_profiles.find_one({"user_id": pid_str})

    # Pull QR/instructions if present
    pharmacy_qr_url = (pharmacy_profile or {}).get("payment_qr_url")
    payment_instructions = (pharmacy_profile or {}).get("payment_instructions")

    logger.info(
        "[buyer_detail] qr_found=%s instr_found=%s profile_id=%s",
        bool(pharmacy_qr_url), bool(payment_instructions),
        (str(pharmacy_profile.get('_id')) if pharmacy_profile else None)
    )

    # --- Build template model (put QR fields INSIDE order) ---
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
            "seller_receipt_path": (o.get("payment") or {}).get("seller_receipt_path"),
            "seller_receipt_sent_at": (o.get("payment") or {}).get("seller_receipt_sent_at"),
            "rejected_reason": (o.get("payment") or {}).get("rejected_reason"),
            "uploaded_at": (o.get("payment") or {}).get("uploaded_at"),
        },
        "items": items,
        "pharmacy_name": resolved_name or "Unknown Pharmacy",
        "pharmacy_address": o.get("pharmacy_address"),
        "ship_to": {"address": ship["address"], "city": ship["city"]},
        "formatted_total": o.get("formatted_total") or format_currency(total_amount),
        "timeline": o.get("timeline", []),

        # >>> These two are what your template reads <<<
        "pharmacy_qr_url": pharmacy_qr_url,
        "pharmacy_instructions": payment_instructions,
    }

    return templates.TemplateResponse(
        "buyer/order_detail.html",
        {"request": request, "order": order, "current_user": current_user}
    )


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

    # Upload receipt first
    receipt_path = _save_receipt(order_id, file)

    # If coming from CART, reserve per line so we avoid oversell while pending
    if (o.get("order_status") == "cart"):
        reserved_mids: list[tuple[ObjectId, int]] = []
        try:
            for it in (o.get("items") or []):
                q = int(it.get("quantity", 0) or 0)
                if q <= 0: 
                    continue
                mid = _to_oid(_extract_item_mid(it))
                if not _reserve_item(db, mid, q):
                    # rollback any prior reservations in this loop
                    for mid0, q0 in reserved_mids:
                        try: _release_item(db, mid0, q0)
                        except Exception: pass
                    raise HTTPException(409, f"Out of stock for {it.get('medicine_name','item')}")
                reserved_mids.append((mid, q))

            # Stamp reserved_qty == quantity on each item
            fresh = db.Orders.find_one({"_id": oid}, {"items": 1}) or {}
            new_items = []
            for it in (fresh.get("items") or []):
                it["reserved_qty"] = int(it.get("quantity", 0) or 0)
                new_items.append(it)
            db.Orders.update_one({"_id": oid}, {"$set": {"items": new_items}})
        except HTTPException:
            raise
        except Exception:
            # best-effort rollback
            for mid0, q0 in reserved_mids:
                try: _release_item(db, mid0, q0)
                except Exception: pass
            raise HTTPException(500, "Failed to reserve stock")

    # Move to pending + proof_uploaded
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
            "$push": {"timeline": {"ts": _now(), "actor": "buyer", "action": "submit_order",
                                   "meta": {"payment_id": payment_id, "city": city}}},
        },
    )
    create_notification(
    db,
    user_id=o.get("pharmacy_id"),
    role="seller",
    type_="payment_proof_uploaded",
    title="Payment proof uploaded",
    message=f"An order has a new payment proof from {current_user.get('username')}.",
    order_id=order_id,
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
        buyer_id = o.get("buyer_id")
        buyer_name, _, _ = _lookup_buyer_display(db, buyer_id) 
        display_name = buyer_name or _short_id(buyer_id)
        prof = profiles.get(o.get("buyer_id")) or {}
        
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
            "buyer_display": display_name,            # <- now a real name when available
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
    pmt = (o.get("payment") or {})
    voucher_generated = bool(((o.get("payment") or {}).get("seller_receipt_path")))
    voucher_sent = bool(((o.get("payment") or {}).get("seller_receipt_sent_at")))

    actions = {
    "verify": {"can": (payment_status == "proof_uploaded"), "done": (payment_status == "paid")},
    "reject": {"can": (payment_status == "proof_uploaded"), "done": (payment_status == "rejected")},
    "voucher": {"generated": voucher_generated, "sent": voucher_sent},
    # delivered can only be marked when paid AND voucher sent
    "delivered": {
        "can": (payment_status == "paid") and voucher_sent and (order_status not in ["delivered"]),
        "done": (order_status == "delivered"),
    },
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
            "payment_id": pmt.get("payment_id"),
            "receipt_path": pmt.get("receipt_path"),                     # buyer's proof
            "seller_receipt_path": pmt.get("seller_receipt_path"),       # seller voucher file
            "seller_receipt_sent_at": pmt.get("seller_receipt_sent_at"), # ts when sent to buyer
            "rejected_reason": pmt.get("rejected_reason"),
            "uploaded_at": _fmt_dt_local(pmt.get("uploaded_at"), tz) if pmt.get("uploaded_at") else None,
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

@router.post("/seller/orders/{order_id}/generate_receipt")
def seller_generate_receipt(order_id: str, current_user: dict = Depends(require_role("seller"))):
    db = get_database()
    oid = _to_oid(order_id)
    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o or (o.get("payment_status") or "").lower() != "paid":
        raise HTTPException(400, "Voucher can be generated only after payment is verified")

    # generate using the full DB order
    generated_url = _generate_seller_receipt(db, o)

    db.Orders.update_one(
        {"_id": oid},
        {"$set": {"payment.seller_receipt_path": generated_url, "updated_at": _now()}}
    )
    _audit(db, oid, "seller", "receipt_generated", {"path": generated_url})
    return RedirectResponse(f"/seller/orders/{order_id}", status_code=303)


@router.post("/seller/orders/{order_id}/send_receipt")
def seller_send_receipt(order_id: str, current_user: dict = Depends(require_role("seller"))):
    db = get_database()
    oid = _to_oid(order_id)
    o = db.Orders.find_one({"_id": oid, "pharmacy_id": current_user["id"]})
    if not o or (o.get("payment_status") or "").lower() != "paid":
        raise HTTPException(400, "Send only after payment is verified")

    path = ((o or {}).get("payment") or {}).get("seller_receipt_path")
    if not path:
        raise HTTPException(400, "Generate the voucher first")

    # notify + mark as sent
    notify_buyer_with_receipt(db, o, path)
    _audit(db, oid, "seller", "receipt_sent", {"path": path})
    return RedirectResponse(f"/seller/orders/{order_id}", status_code=303)


@router.post("/seller/orders/{order_id}/verify")
def seller_verify_payment(order_id: str, current_user: dict = Depends(require_role("seller"))):
    """proof_uploaded → (commit stock) → paid + confirmed; then prepare seller receipt."""
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

    # Commit all reserved quantities to real stock BEFORE flipping to paid
    for it in (o.get("items") or []):
        q = int(it.get("reserved_qty", it.get("quantity", 0)) or 0)
        if q <= 0: 
            continue
        ok = _commit_item(db, _to_oid(_extract_item_mid(it)), q)
        if not ok:
            logger.error("Stock commit failed mid=%s qty=%s", it.get("medicine_id"), q)
            raise HTTPException(409, "Stock commit failed")

    # Mark as paid + confirmed
    db.Orders.update_one(
        {"_id": oid},
        {
            "$set": {
                "payment_status": "paid",
                "order_status": "confirmed",
                "status": "confirmed",
                "updated_at": _now(),
            },
            "$push": {"timeline": {"ts": _now(), "actor": "seller", "action": "payment_verified"}},
        },
    )
    create_notification(
    db,
    user_id=o.get("buyer_id"),
    role="buyer",
    type_="payment_verified",
    title="Payment verified",
    message=f"Your order {order_id} payment was verified. We are preparing your items.",
    order_id=order_id,
)

    # Re-fetch minimal fields for receipt
    o2 = db.Orders.find_one({"_id": oid})
    shaped_for_pdf = {
        "_id": o2["_id"],
        "created_at": o2.get("created_at"),
        "pharmacy_name": o2.get("pharmacy_name"),
        "items": o2.get("items", []),
        "total_amount": o2.get("total_amount"),
        "formatted_total": o2.get("formatted_total") or format_currency(o2.get("total_amount") or 0),
        "buyer": {"display": (_lookup_buyer_display(db, o2.get("buyer_id"))[0])},
        "ship_to": (lambda s: {
            "address": (s or {}).get("address") or (s or {}).get("address_line") or (s or {}).get("line1"),
            "city": (s or {}).get("city"),
        })(o2.get("shipping") or o2.get("shipping_address") or o2.get("delivery_address")),
    }

    # Generate seller receipt (best-effort)
    try:
        seller_receipt_path = _generate_seller_receipt(db, o2)
    except Exception:
        logger.exception("Failed generating seller receipt")
        seller_receipt_path = None

    db.Orders.update_one(
        {"_id": oid},
        {
            "$set": {
                "payment.seller_receipt_path": seller_receipt_path,
                "payment.seller_receipt_uploaded_at": _now(),
            },
            "$push": {"timeline": {"ts": _now(), "actor": "system", "action": "seller_receipt_ready",
                                   "meta": {"path": seller_receipt_path}}},
        },
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
    create_notification(
    db,
    user_id=o.get("buyer_id"),
    role="buyer",
    type_="payment_rejected",
    title="Payment rejected",
    message=f"Your order {order_id} payment was rejected.",
    order_id=order_id,
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
    create_notification(
    db,
    user_id=o.get("buyer_id"),
    role="buyer",
    type_="delivered",
    title="Order delivered",
    message=f"Order {order_id} has been delivered. Thank you!",
    order_id=order_id,
)
    return RedirectResponse(f"/seller/orders/{order_id}", status_code=303)
