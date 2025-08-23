from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

router = APIRouter()

# ---------- Home Page ----------
@router.get("/", response_class=HTMLResponse)
def role_selector(request: Request):
    return request.app.templates.TemplateResponse("login.html", {"request": request})


