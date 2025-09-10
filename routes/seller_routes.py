from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi import HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi import Form, Request, File, UploadFile
from datetime import datetime
from bson import ObjectId
from pathlib import Path
from database import get_database
from auth import require_role

import os
import uuid

from fastapi import HTTPException, status, UploadFile, File, Form
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import json

class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Create images directory if it doesn't exist
MEDICINE_IMAGES_DIR = "static/images/medicines"
Path(MEDICINE_IMAGES_DIR).mkdir(parents=True, exist_ok=True)

####################################################################################
# redirect to seller profile

@router.get("/seller/profile", response_class=HTMLResponse)
def seller_profile_form(request: Request, current_user: dict = Depends(require_role("seller"))):
    if current_user.get("is_profile_complete"):
        return RedirectResponse(url="/seller/home", status_code=302)
    return templates.TemplateResponse("seller_profile.html", {"request": request, "current_user": current_user})

####################################################################################
# redirect to seller home

@router.get("/seller/home")
async def seller_home(request: Request, current_user: dict = Depends(require_role("seller"))):
    try:
        db = get_database()
        
        # 1. Get pharmacy profile for this seller using user_id
        pharmacy_profile = db.pharmacy_profiles.find_one({
            "user_id": ObjectId(current_user["id"])  # Convert string to ObjectId
        })
        
        if not pharmacy_profile:
            return templates.TemplateResponse("seller/home.html", {
                "request": request,
                "current_user": current_user,
                "error": "Pharmacy profile not found. Please complete your profile."
            })
        
        pharmacy_name = pharmacy_profile.get("pharmacy_name", "")
        print(pharmacy_name)
        
        # 2. Get only CONFIRMED or DELIVERED orders with PAID payment status for this pharmacy
        # Use seller's ID (from session) to match pharmacy_id in orders
        orders = list(db.Orders.find({
            "pharmacy_id": current_user["id"],  # Match seller's ID with pharmacy_id in orders
            "order_status": {"$in": ["confirmed", "delivered"]},
            "payment_status": "paid"
        }))
        
        print(f"✅ Found {len(orders)} orders for pharmacy_id: {current_user['id']}")
        
        # 3. Get all medicines for this seller
        medicines = list(db.Medicine.find({"seller_id": current_user["id"]}))
        
        # 4. Calculate statistics
        total_medicines = len(medicines)
        low_stock_count = sum(1 for med in medicines if 0 < med.get("stock", 0) <= 10)
        out_of_stock_count = sum(1 for med in medicines if med.get("stock", 0) == 0)
        expired_count = sum(1 for med in medicines if med.get("is_expired", False))
        
        # 5. Calculate total revenue and profit from orders
        total_revenue = 0
        total_profit = 0
        orders_received = len(orders)
        
        for order in orders:
            order_total = order.get("total_amount", 0)
            total_revenue += order_total
            
            # Calculate profit: total_amount (selling) - total_buying_price
            total_buying_price = 0
            for item in order.get("items", []):
                buying_price = item.get("buying_price", 0)
                quantity = item.get("quantity", 0)
                total_buying_price += buying_price * quantity
            
            order_profit = order_total - total_buying_price
            total_profit += order_profit
            
            print(f"📦 Order {order.get('_id')}: Revenue={order_total}, Cost={total_buying_price}, Profit={order_profit}")
        
        print(f"📊 Total: Revenue={total_revenue}, Profit={total_profit}, Orders={orders_received}")
        
        # 6. Prepare dashboard data for charts - Convert all ObjectId to strings
        dashboard_data = {
            "orders": [],
            "medicines": [],
            "total_revenue": total_revenue,
            "total_profit": total_profit,
            "stats": {
                "total_orders": orders_received,
                "total_revenue": total_revenue,
                "total_profit": total_profit
            }
        }
        
        # 7. Process orders data for frontend - Ensure all ObjectId are converted to strings
        for order in orders:
            # Calculate buying price and profit for this order
            total_buying_price = 0
            for item in order.get("items", []):
                buying_price = item.get("buying_price", 0)
                quantity = item.get("quantity", 0)
                total_buying_price += buying_price * quantity
            
            order_profit = order.get("total_amount", 0) - total_buying_price
            
            # Convert all ObjectId to strings in items
            processed_items = []
            for item in order.get("items", []):
                processed_item = {
                    "medicine_id": str(item.get("medicine_id", "")),
                    "medicine_name": item.get("medicine_name", ""),
                    "quantity": item.get("quantity", 0),
                    "price": item.get("price", 0),
                    "buying_price": item.get("buying_price", 0),
                    "total": item.get("total", 0)
                }
                processed_items.append(processed_item)
            
            order_data = {
                "order_id": str(order.get("_id", "")),
                "total_amount": order.get("total_amount", 0),
                "total_buying_price": total_buying_price,
                "profit": order_profit,
                "order_status": order.get("order_status", ""),
                "payment_status": order.get("payment_status", ""),
                "created_at": order["created_at"].isoformat() if isinstance(order.get("created_at"), datetime) else str(order.get("created_at", "")),
                "items": processed_items  # Use processed items with string IDs
            }
            dashboard_data["orders"].append(order_data)
        
        # 8. Process medicines data for frontend - Ensure all ObjectId are converted to strings
        for medicine in medicines:
            medicine_data = {
                "medicine_id": str(medicine.get("_id", "")),
                "name": medicine.get("name", "Unknown Medicine"),
                "price": medicine.get("price", 0),
                "buying_price": medicine.get("buying_price", 0),
                "stock": medicine.get("stock", 0),
                "profit_margin": medicine.get("price", 0) - medicine.get("buying_price", 0)
            }
            dashboard_data["medicines"].append(medicine_data)
        
        # 9. Convert to JSON string using custom encoder
        dashboard_data_json = json.dumps(dashboard_data, cls=JSONEncoder)
        
        # 10. Return HTML template with all data
        return templates.TemplateResponse("seller/home.html", {
            "request": request,
            "current_user": current_user,
            "pharmacy_name": pharmacy_name,
            "total_medicines": total_medicines,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "expired_count": expired_count,
            "orders_received": orders_received,
            "total_revenue": total_revenue,
            "total_profit": total_profit,
            "dashboard_data": dashboard_data_json
        })
        
    except Exception as e:
        print(f"❌ Error in seller home: {e}")
        import traceback
        traceback.print_exc()
        
        return templates.TemplateResponse("seller/home.html", {
            "request": request,
            "current_user": current_user,
            "error": "Failed to load dashboard data"
        })

####################################################################################
# redirect to inventory page

@router.get("/seller/inventory", response_class=HTMLResponse)
def seller_inventory(request: Request, current_user: dict = Depends(require_role("seller"))):
    print("🔹 Starting seller inventory process...")
    
    try:
        # 1. Check if seller profile is complete
        print(f"🔹 Checking profile completion for user: {current_user.get('username')}")
        if not current_user.get("is_profile_complete"):
            print("❌ Profile not complete - redirecting to profile page")
            return RedirectResponse(url="/seller/profile", status_code=302)
        print("✅ Profile is complete")
        
        # 2. Get database connection
        print("🔹 Connecting to database...")
        db = get_database()
        
        # 3. Fetch medicines for the current seller
        print(f"🔹 Fetching medicines for seller ID: {current_user['id']}")
        medicines_cursor = db.Medicine.find({"seller_id": current_user["id"]})
        medicines_list = list(medicines_cursor)
        print(f"✅ Found {len(medicines_list)} medicines")
        
        # 4. Process medicines data for template
        processed_medicines = []
        current_date = datetime.utcnow().date()
        
        for medicine in medicines_list:
            # Convert ObjectId to string for template
            medicine_dict = dict(medicine)
            medicine_dict["_id"] = str(medicine["_id"])
            
            # Convert expiration_date to date object if it's datetime
            if isinstance(medicine.get("expiration_date"), datetime):
                expiration_date = medicine["expiration_date"].date()
                medicine_dict["expiration_date"] = expiration_date.strftime("%Y-%m-%d")
            else:
                expiration_date = datetime.strptime(medicine["expiration_date"], "%Y-%m-%d").date()
            
            # Calculate status flags
            stock = medicine.get("stock", 0)
            is_expired = expiration_date < current_date
            is_low_stock = 0 < stock <= 10  # Low stock if between 1-10
            is_out_of_stock = stock == 0     # Out of stock if 0
            
            # Add calculated fields
            medicine_dict["is_expired"] = is_expired
            medicine_dict["is_low_stock"] = is_low_stock
            medicine_dict["is_out_of_stock"] = is_out_of_stock
            medicine_dict["formatted_buying_price"] = f"{medicine.get('buying_price', 0):.2f}"
            medicine_dict["formatted_selling_price"] = f"{medicine.get('selling_price', 0):.2f}"
            
            # Add image URL if image exists
            if medicine.get("image_filename"):
                medicine_dict["image_url"] = f"/static/images/medicines/{medicine['image_filename']}"
            else:
                medicine_dict["image_url"] = "/static/images/placeholder-medicine.png"  # Default placeholder
            
            processed_medicines.append(medicine_dict)
            print(f"📦 Processed medicine: {medicine['name']} - Stock: {stock}, "
                  f"Expired: {is_expired}, Out of Stock: {is_out_of_stock}")
        
        # 5. Calculate summary statistics
        total_medicines = len(processed_medicines)
        in_stock_count = sum(1 for med in processed_medicines if med.get("stock", 0) > 10)
        low_stock_count = sum(1 for med in processed_medicines if med.get("is_low_stock", False))
        out_of_stock_count = sum(1 for med in processed_medicines if med.get("stock", 0) == 0)
        expired_count = sum(1 for med in processed_medicines if med.get("is_expired", False))
        
        print(f"📊 Summary - Total: {total_medicines}, In Stock: {in_stock_count}, "
              f"Low Stock: {low_stock_count}, Out of Stock: {out_of_stock_count}, "
              f"Expired: {expired_count}")
        
        # 6. Render template with processed data
        print("🔹 Rendering inventory template...")
        return templates.TemplateResponse("seller/inventory.html", {
            "request": request,
            "current_user": current_user,
            "medicines": processed_medicines,
            "total_medicines": total_medicines,
            "in_stock_count": in_stock_count,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "expired_count": expired_count
        })
        
    except Exception as e:
        print(f"❌ ERROR in seller_inventory: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        
        # Return empty data on error
        return templates.TemplateResponse("seller/inventory.html", {
            "request": request,
            "current_user": current_user,
            "medicines": [],
            "total_medicines": 0,
            "in_stock_count": 0,
            "low_stock_count": 0,
            "out_of_stock_count": 0,
            "expired_count": 0,
            "error": "Failed to load inventory data. Please try again."
        })
    
    finally:
        print("🔹 Seller inventory process completed")

####################################################################################
# redirect to add medicine form

@router.get("/seller/add-medicine", response_class=HTMLResponse)
def seller_add_medicine(request: Request, current_user: dict = Depends(require_role("seller"))):
    if not current_user.get("is_profile_complete"):
        return RedirectResponse(url="/seller/profile", status_code=302)
    
    return templates.TemplateResponse("seller/add_medicine.html",{"request": request})

####################################################################################
# add a medicine to database

@router.post("/seller/add-medicine", response_class=HTMLResponse)
async def seller_add_medicine(
    request: Request,
    current_user: dict = Depends(require_role("seller")),
    name: str = Form(...),
    stock: int = Form(...),
    buying_price: float = Form(...),
    selling_price: float = Form(...),
    expiration_date: str = Form(...),
    description: str = Form(""),
    medicine_image: UploadFile = File(None)
):
    print("🔹 Starting medicine addition process...")
    
    # 1. Check if seller profile is complete
    if not current_user.get("is_profile_complete"):
        print("❌ Profile not complete - redirecting to profile page")
        return RedirectResponse(url="/seller/profile", status_code=302)
    
    print("✅ Profile is complete")
    
    # 2. Store form data for potential re-rendering
    form_data = {
        "name": name,
        "stock": stock,
        "buying_price": buying_price,
        "selling_price": selling_price,
        "expiration_date": expiration_date,
        "description": description
    }
    print(f"📋 Form data received: {form_data}")
    
    # 3. Validation checks
    print("🔹 Validating form data...")
    if stock < 0:
        print("❌ Validation failed: Stock cannot be negative")
        return templates.TemplateResponse("seller/add_medicine.html", {
            "request": request,
            "current_user": current_user,
            "error": "Stock quantity cannot be negative.",
            "form_data": form_data
        })
    
    if buying_price <= 0:
        print("❌ Validation failed: Price must be positive")
        return templates.TemplateResponse("seller/add_medicine.html", {
            "request": request,
            "current_user": current_user,
            "error": "Price must be greater than 0.",
            "form_data": form_data
        })
    
    if selling_price <= 0:
        print("❌ Validation failed: Price must be positive")
        return templates.TemplateResponse("seller/add_medicine.html", {
            "request": request,
            "current_user": current_user,
            "error": "Price must be greater than 0.",
            "form_data": form_data
        })
    
    if selling_price < buying_price:
        print("❌ Validation failed: Selling price must be greater than buying price.")
        return templates.TemplateResponse("seller/add_medicine.html", {
            "request": request,
            "current_user": current_user,
            "error": "Selling price must be greater than buying price.",
            "form_data": form_data
        })
    
    image_filename = None
    try:
        # 4. Handle image upload if provided
        if medicine_image and medicine_image.filename:
            print(f"🔹 Processing image upload: {medicine_image.filename}")
            
            # Validate file type
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            file_extension = Path(medicine_image.filename).suffix.lower()
            
            if file_extension not in allowed_extensions:
                print("❌ Invalid file type")
                return templates.TemplateResponse("seller/add_medicine.html", {
                    "request": request,
                    "current_user": current_user,
                    "error": "Invalid file type. Please upload JPG, PNG, or GIF images.",
                    "form_data": form_data
                })
            
            # Generate unique filename: sellerid_randomuuid.extension
            unique_id = uuid.uuid4().hex[:8]  # First 8 chars of UUID
            image_filename = f"{current_user['id']}_{unique_id}{file_extension}"
            image_path = os.path.join(MEDICINE_IMAGES_DIR, image_filename)
            
            # Save the image file
            with open(image_path, "wb") as buffer:
                content = await medicine_image.read()
                buffer.write(content)
            
            print(f"✅ Image saved: {image_filename}")
        
        # 5. Get database connection
        print("🔹 Connecting to database...")
        db = get_database()
        
        # 6. Convert expiration_date string to datetime
        print(f"🔹 Converting expiration date: {expiration_date}")
        expiration_dt = datetime.strptime(expiration_date, "%Y-%m-%d")
        
        # 7. Check if expiration date is in the past
        current_time = datetime.utcnow()
        if expiration_dt < current_time:
            print("❌ Validation failed: Expiration date in past")
            return templates.TemplateResponse("seller/add_medicine.html", {
                "request": request,
                "current_user": current_user,
                "error": "Expiration date cannot be in the past.",
                "form_data": form_data
            })
        
        # 8. Create medicine document
        print("🔹 Creating medicine document...")
        medicine_data = {
            "seller_id": current_user["id"],
            "name": name,
            "stock": stock,
            "buying_price": buying_price,
            "selling_price": selling_price,
            "expiration_date": expiration_dt,
            "description": description.strip(),
            "image_filename": image_filename,
            "created_at": current_time,
            "updated_at": current_time
        }
        print(f"📦 Medicine data: {medicine_data}")
        
        # 9. Insert into database
        print("🔹 Inserting into Medicine collection...")
        result = db.Medicine.insert_one(medicine_data)
        print(f"✅ Medicine added successfully! Inserted ID: {result.inserted_id}")

        flash_message = "✅ Medicine added successfully!"

        return templates.TemplateResponse(
            "seller/add_medicine.html",
            {
                "request": request,
                "flash_message": flash_message
            }
        )
    
    except ValueError as e:
        print(f"❌ Date conversion error: {e}")
        return templates.TemplateResponse("seller/add_medicine.html", {
            "request": request,
            "current_user": current_user,
            "error": "Invalid date format. Please use YYYY-MM-DD format.",
            "form_data": form_data
        })
        
    except Exception as e:
        print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        
        return templates.TemplateResponse("seller/add_medicine.html", {
            "request": request,
            "current_user": current_user,
            "error": "An unexpected error occurred. Please try again.",
            "form_data": form_data
        })
    
    finally:
        print("🔹 Medicine addition process completed")

####################################################################################
# delete a medicine

@router.get("/seller/medicine/delete/{medicine_id}")
async def delete_medicine(
    request: Request,
    medicine_id: str,
    current_user: dict = Depends(require_role("seller"))
):
    print(f"🔹 Starting medicine deletion for ID: {medicine_id}")
    
    try:
        db = get_database()
        
        # Verify medicine exists and belongs to current seller
        medicine = db.Medicine.find_one({
            "_id": ObjectId(medicine_id),
            "seller_id": current_user["id"]
        })
        
        if not medicine:
            print(f"❌ Medicine not found or access denied: {medicine_id}")
            request.session["flash_error"] = "Medicine not found or access denied"
            return RedirectResponse(url="/seller/inventory", status_code=303)
        
        # Delete associated image
        if medicine.get("image_filename"):
            image_path = os.path.join("static/images/medicines", medicine["image_filename"])
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
                    print(f"✅ Deleted image file: {medicine['image_filename']}")
            except Exception as e:
                print(f"⚠️ Could not delete image file: {e}")
        
        # Delete from database
        result = db.Medicine.delete_one({"_id": ObjectId(medicine_id)})
        
        if result.deleted_count == 1:
            print(f"✅ Medicine deleted successfully: {medicine_id}")
            request.session["flash_success"] = f"Medicine '{medicine['name']}' deleted successfully"
        else:
            request.session["flash_error"] = "Failed to delete medicine"
            
    except Exception as e:
        print(f"❌ Error deleting medicine: {e}")
        request.session["flash_error"] = "Error deleting medicine"
    
    return RedirectResponse(url="/seller/inventory", status_code=303)

####################################################################################
# update a medicine

@router.post("/seller/medicine/update/{medicine_id}")
async def update_medicine(
    request: Request,
    medicine_id: str,
    name: str = Form(...),
    description: str = Form(""),
    stock: int = Form(...),
    buying_price: float = Form(...),
    selling_price: float = Form(...),
    expiration_date: str = Form(...),
    medicine_image: UploadFile = File(None),
    current_user: dict = Depends(require_role("seller"))
):
    try:
        db = get_database()
        
        # Verify medicine exists and belongs to current seller
        medicine = db.Medicine.find_one({
            "_id": ObjectId(medicine_id),
            "seller_id": current_user["id"]
        })
        
        if not medicine:
            request.session["flash_error"] = "Medicine not found or access denied"
            return RedirectResponse(url="/seller/inventory", status_code=303)
        
        update_data = {
            "name": name,
            "description": description,
            "stock": stock,
            "buying_price": buying_price,
            "selling_price": selling_price,
            "expiration_date": datetime.strptime(expiration_date, "%Y-%m-%d"),
            "updated_at": datetime.utcnow()
        }
        
        # Handle image upload
        if medicine_image and medicine_image.filename:
            # Delete old image if exists
            if medicine.get("image_filename"):
                old_image_path = os.path.join("static/images/medicines", medicine["image_filename"])
                if os.path.exists(old_image_path):
                    os.remove(old_image_path)
            
            # Save new image
            file_extension = os.path.splitext(medicine_image.filename)[1].lower()
            unique_id = uuid.uuid4().hex[:8]
            sanitized_name = "".join(c if c.isalnum() else "_" for c in name)
            image_filename = f"{current_user['id']}_{unique_id}_{sanitized_name}{file_extension}"
            image_path = os.path.join("static/images/medicines", image_filename)
            
            with open(image_path, "wb") as buffer:
                content = await medicine_image.read()
                buffer.write(content)
            
            update_data["image_filename"] = image_filename
        
        # Update database
        result = db.Medicine.update_one(
            {"_id": ObjectId(medicine_id)},
            {"$set": update_data}
        )
        
        if result.modified_count == 1:
            request.session["flash_success"] = f"Medicine '{name}' updated successfully"
        else:
            request.session["flash_error"] = "Failed to update medicine"
            
    except Exception as e:
        print(f"❌ Error updating medicine: {e}")
        request.session["flash_error"] = "Error updating medicine"
    
    return RedirectResponse(url="/seller/inventory", status_code=303)
    
####################################################################################
def update_pharmacy_coordinates(db, pharmacy_profile, force_update=False):
    """
    Ensure pharmacy coordinates exist.
    - If coordinates exist and force_update=False → return them
    - If missing or force_update=True → geocode from address → save → return
    """
    coords = pharmacy_profile.get("coordinates")
    if coords and coords.get("latitude") is not None and coords.get("longitude") is not None and not force_update:
        return coords["latitude"], coords["longitude"]

    address = pharmacy_profile.get("address")
    if address:
        lat, lon = geocode_address(address)
        if lat is not None and lon is not None:
            db.pharmacy_profiles.update_one(
                {"_id": pharmacy_profile["_id"]},
                {"$set": {"coordinates": {"latitude": lat, "longitude": lon}}}
            )
            return lat, lon
    return None, None

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

    # Update profile
    db.pharmacy_profiles.update_one({"user_id": current_user["_id"]}, {"$set": update_data})

    # ✅ Force update coordinates if address changed
    pharmacy_profile = db.pharmacy_profiles.find_one({"user_id": current_user["_id"]})
    update_pharmacy_coordinates(db, pharmacy_profile, force_update=True)

    return RedirectResponse(url="/seller/home", status_code=302)
