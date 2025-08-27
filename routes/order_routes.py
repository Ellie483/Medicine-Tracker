from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from database import get_database
from bson import ObjectId
from auth import require_role
from datetime import datetime
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from utils import format_currency, is_medicine_expired
router = APIRouter()
# Initialize templates
templates = Jinja2Templates(directory="templates")
# ---------------- Pydantic model ----------------
class AddToCartRequest(BaseModel):
    medicine_id: str
    quantity: int

# ---------------- Add to cart route ----------------
@router.post("/buyer/add_to_cart")
async def add_to_cart(
    medicine_id: str = Form(...),
    quantity: int = Form(...),
    current_user: dict = Depends(require_role("buyer"))
):
    buyer_id = current_user['id']
    print(f"Received: medicine_id={medicine_id}, quantity={quantity}, buyer_id={buyer_id}")

    # Validate using Pydantic
    try:
        cart_data = AddToCartRequest(medicine_id=medicine_id, quantity=quantity)
        print(f"Validated cart_data -> medicine_id: {cart_data.medicine_id}, quantity: {cart_data.quantity}")
    except Exception as e:
        return JSONResponse(status_code=400, content={"message": f"Validation error: {str(e)}"})

    db = get_database()

    # Convert medicine_id to ObjectId
    try:
        medicine_id_obj = ObjectId(cart_data.medicine_id)
    except Exception as e:
        print(f"Error converting medicine_id to ObjectId: {e}")
        return JSONResponse(status_code=400, content={"message": "Invalid medicine ID format"})

    # Fetch medicine details
    medicine = db.Medicine.find_one({"_id": medicine_id_obj})
    if not medicine:
        return JSONResponse(status_code=404, content={"message": "Medicine not found"})

    # Fetch pharmacy name from pharmacy_profiles collection
    pharmacy_name = "Unknown Pharmacy"
    pharmacy_id = medicine.get("seller_id")
    if pharmacy_id:
        pharmacy = db.pharmacy_profiles.find_one({"_id": ObjectId(pharmacy_id)})
        if pharmacy:
            pharmacy_name = pharmacy.get("pharmacy_name", pharmacy_name)
            print(pharmacy_name)

    # Calculate total for this item
    item_total = cart_data.quantity * medicine["price"]

    # Prepare order document
    order_doc = {
        "buyer_id": buyer_id,
        "pharmacy_name": pharmacy_name,
        "items": [
            {
                "medicine_id": medicine["_id"],
                "medicine_name": medicine["name"],
                "quantity": cart_data.quantity,
                "price": medicine["price"],
                "total": item_total
            }
        ],
        "total_amount": item_total,
        "formatted_total": f"₹{item_total:.2f}",
        "status": "pending",
        "payment_status": "pending",
        "created_at": datetime.utcnow(),
        "qr_code_path": None,
        "receipt_path": None
    }

    # Insert into Orders collection
    try:
        result = db.Orders.insert_one(order_doc)
        print(f"Order inserted with _id: {result.inserted_id}")
    except Exception as e:
        print(f"Error inserting order: {e}")
        return JSONResponse(status_code=500, content={"message": "Failed to create order"})

    # Success response
    return JSONResponse(
        status_code=200,
        content={
            "message": "Added to cart and order created successfully",
            "order_id": str(result.inserted_id)
        }
    )

@router.get("/buyer/orders", response_class=HTMLResponse)
def buyer_orders(request: Request, current_user: dict = Depends(require_role("buyer"))):
    db = get_database()

    buyer_id = current_user['id']  # make sure we use the correct key
    print(buyer_id)
    # Fetch all orders for this buyer
    orders_cursor = db.Orders.find({"buyer_id": buyer_id}).sort("created_at", -1)
    orders = list(orders_cursor)  # <-- convert cursor to list

    # Prepare orders for template
    formatted_orders = []
    for order in orders:
        items = []
        for item in order.get("items", []):
            med_name = item.get("medicine_name", "Unknown")
            price = float(item.get("price", 0))
            qty = int(item.get("quantity", 1))
            items.append({
                "medicine_name": med_name,
                "quantity": qty,
                "price": price
            })

        formatted_orders.append({
            "_id": str(order.get("_id")),
            "created_at": order.get("created_at"),
            "status": order.get("status", "pending"),
            "payment_status": order.get("payment_status", "pending"),
            "items": items,
            "pharmacy_name": order.get("pharmacy_name", "Unknown Pharmacy"),
            "formatted_total": format_currency(sum(i['price']*i['quantity'] for i in items)),
            "qr_code_path": order.get("qr_code_path"),
            "receipt_path": order.get("receipt_path")
        })

    return templates.TemplateResponse(
        "buyer/orders.html",
        {
            "request": request,
            "orders": formatted_orders
        }
    )
