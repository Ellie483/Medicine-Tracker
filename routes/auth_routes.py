from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import timedelta
from jose import jwt, JWTError

from auth import verify_password, create_access_token
from database import db  # your MongoDB connection

router = APIRouter()
templates = Jinja2Templates(directory="templates")

SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"

@router.get("/route_redirector")
def route_redirector(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        scheme, _, param = token.partition(" ")
        payload = jwt.decode(param, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        user = db["users"].find_one({"username": username})
        if not user:
            raise ValueError("User not found")

        role = user["role"]
        if role == "buyer":
            return RedirectResponse(url="/buyer/home", status_code=302)
        elif role == "seller":
            return RedirectResponse(url="/seller/home", status_code=302)
        elif role == "admin":
            return RedirectResponse(url="/admin_dashboard", status_code=302)
        else:
            return RedirectResponse(url="/login", status_code=302)

    except (JWTError, ValueError):
        return RedirectResponse(url="/login", status_code=302)
