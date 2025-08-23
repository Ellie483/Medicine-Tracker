from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import timedelta

from database import get_database
from auth import authenticate_user, create_access_token
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid username or password"
        })

    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )

    if user["role"] == "admin":
        response = RedirectResponse(url="/admin/dashboard", status_code=302)
    elif user["role"] == "seller":
        if user["is_profile_complete"]:
            response = RedirectResponse(url="/seller/home", status_code=302)
        else:
            response = RedirectResponse(url="/seller/profile", status_code=302)
    else:
        if user["is_profile_complete"]:
            response = RedirectResponse(url="/buyer/home", status_code=302)
        else:
            response = RedirectResponse(url="/buyer/profile", status_code=302)

    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

@router.get("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key="access_token")
    return response
