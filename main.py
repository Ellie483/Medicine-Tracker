from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
import os

# ---- route modules ----
from routes import (
    auth_routes,
    register_routes,
    admin_routes,
    seller_routes,
    buyer_routes,
    medicine_routes,
    order_routes,
    page_routes,
    notification_routes,  # must export `router`
)

from routes.init_routes import init_default_users

# ---- db ----
from database import get_database

app = FastAPI(title="Medicine Availability Tracker", version="1.0.0")

# ---- static & templates ----
BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ---- session middleware ----
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")

# ---- startup ----
@app.on_event("startup")
def startup_event():
    # seed default users/roles
    init_default_users()

    # indexes (best-effort)
    try:
        db = get_database()
        # Notifications: user unread recents
        db.Notifications.create_index([("user_id", 1), ("is_read", 1), ("created_at", -1)])
        # Orders commonly queried by buyer/seller + recency
        db.Orders.create_index([("buyer_id", 1), ("created_at", -1)])
        db.Orders.create_index([("pharmacy_id", 1), ("created_at", -1)])
        # Medicines availability (optional)
        db.Medicine.create_index([("stock", -1), ("reserved", -1)])
        db.Medicine.create_index("expiration_date")
    except Exception:
        # avoid crashing app on index creation issues
        pass

# ---- include routers ----
app.include_router(auth_routes.router)
app.include_router(register_routes.router)
app.include_router(admin_routes.router)
app.include_router(seller_routes.router)
app.include_router(buyer_routes.router)
app.include_router(medicine_routes.router)
app.include_router(order_routes.router)
app.include_router(page_routes.router)
app.include_router(notification_routes.router)

# ---- error handling ----
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)

# ---- dev run ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
