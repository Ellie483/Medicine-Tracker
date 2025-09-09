import qrcode
import os
from datetime import datetime
import uuid
from typing import Optional

def generate_qr_code(data: str, filename: Optional[str] = None) -> str:
    """Generate QR code and save it to static/qr_codes directory"""
    if not filename:
        filename = f"qr_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    
    # Ensure directory exists
    qr_dir = "static/qr_codes"
    os.makedirs(qr_dir, exist_ok=True)
    
    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    # Create image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save image
    file_path = os.path.join(qr_dir, filename)
    img.save(file_path)
    
    return file_path

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two coordinates in kilometers"""
    from math import radians, cos, sin, asin, sqrt
    
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of earth in kilometers
    return c * r

def format_currency(amount: float) -> str:
    """Format currency amount"""
    return f"{amount:.2f}Ks"

def is_medicine_expired(expiration_date: datetime) -> bool:
    """Check if medicine is expired"""
    return expiration_date < datetime.utcnow()

def is_low_stock(stock: int, threshold: int = 10) -> bool:
    """Check if medicine stock is low"""
    return stock <= threshold

    # Equirectangular approximation: fast and accurate for short distances (local search)
# Equirectangular approximation: fast and accurate for short distances (local search)
def equirectangular_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance between two coordinates in kilometers (for local search)"""
    from math import radians, cos, sqrt
    R = 6371  # Earth radius in kilometers
    x = radians(lon2 - lon1) * cos(radians((lat1 + lat2) / 2))
    y = radians(lat2 - lat1)
    return sqrt(x*x + y*y) * R