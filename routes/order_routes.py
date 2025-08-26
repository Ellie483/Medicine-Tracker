from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from database import get_database
from bson import ObjectId
from auth import require_role
from datetime import datetime

router = APIRouter()

# Define the Pydantic model for request data
class AddToCartRequest(BaseModel):
    medicine_id: str
    quantity: int

@router.post("/buyer/add_to_cart")
async def add_to_cart(
    request: Request,
    cart_data: AddToCartRequest,  # Use Pydantic model to validate and parse request body
    current_user: dict = Depends(require_role("buyer"))
):
    # Log the received data
    print(f"Received add_to_cart request: Medicine ID = {cart_data.medicine_id}, Quantity = {cart_data.quantity}, Buyer ID = {current_user['_id']}")

    db = get_database()

    # Convert medicine_id to ObjectId
    try:
        medicine_id_obj = ObjectId(cart_data.medicine_id)
    except Exception as e:
        print(f"Error converting medicine_id to ObjectId: {e}")
        return JSONResponse(status_code=400, content={"message": "Invalid medicine ID format"})
    
    # Fetch the medicine to check if it exists
    medicine = db.medicines.find_one({"_id": medicine_id_obj})

    if not medicine:
        print(f"Medicine with ID {medicine_id_obj} not found.")
        return JSONResponse(status_code=404, content={"message": "Medicine not found"})

    if medicine["stock"] < cart_data.quantity:
        print(f"Not enough stock for Medicine ID {medicine_id_obj}. Available: {medicine['stock']}, Requested: {cart_data.quantity}")
        return JSONResponse(status_code=400, content={"message": "Not enough stock available"})

    # Check if the buyer already has an order with this medicine
    order = db.orders.find_one({
        "buyer_id": current_user["_id"],
        "medicine_id": medicine["_id"]
    })

    if order:
        # Update the existing order with the new quantity
        print(f"Updating order for Medicine ID {medicine_id_obj}. New Quantity: {order['quantity'] + cart_data.quantity}")
        db.orders.update_one(
            {"_id": order["_id"]},
            {"$set": {"quantity": order["quantity"] + cart_data.quantity}}
        )
    else:
        # Create a new order entry for the medicine in the cart
        print(f"Creating new order for Medicine ID {medicine_id_obj} with Quantity: {cart_data.quantity}")
        db.orders.insert_one({
            "buyer_id": current_user["_id"],
            "medicine_id": medicine["_id"],
            "quantity": cart_data.quantity,
            "created_at": datetime.utcnow()
        })

    return JSONResponse(status_code=200, content={"success": True, "message": "Added to cart successfully"})
