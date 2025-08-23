from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from bson import ObjectId

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")
        return field_schema

class User(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    username: str
    password: str
    role: str  # admin, seller, buyer
    is_profile_complete: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class PharmacyProfile(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: str
    pharmacy_name: str
    license_number: str
    contact_info: str
    address: str
    coordinates: Optional[dict] = None  # {"lat": float, "lng": float}
    operating_hours: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class BuyerProfile(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: str
    name: str
    age: int
    address: str
    coordinates: Optional[dict] = None
    favorite_pharmacies: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Medicine(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    pharmacy_id: str
    name: str
    stock: int
    price: float
    expiration_date: datetime
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Order(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    buyer_id: str
    pharmacy_id: str
    medicines: List[dict]  # [{"medicine_id": str, "quantity": int, "price": float}]
    total_amount: float
    status: str = "pending"  # pending, confirmed, completed, cancelled
    payment_status: str = "pending"  # pending, paid, failed
    qr_code_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class Receipt(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    order_id: str
    user_id: str
    file_path: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

# Registration request models
class BuyerRegistrationRequest(BaseModel):
    username: str
    password: str
    name: str
    age: int
    address: str

class SellerRegistrationRequest(BaseModel):
    username: str
    password: str
    pharmacy_name: str
    license_number: str
    contact_info: str
    address: str
    operating_hours: str
