from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
import os
from routes import (
    auth_routes,
    register_routes,
    admin_routes,
    seller_routes,
    buyer_routes,
    medicine_routes,
    order_routes,
    page_routes
)

from routes.init_routes import init_default_users

app = FastAPI(title="Medicine Availability Tracker", version="1.0.0")

# Static and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# ---------- Session middleware --------------
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")

# ---------- Startup Events ----------
@app.on_event("startup")
def startup_event():
    init_default_users()

# ---------- Include Routes ----------
app.include_router(auth_routes.router)
app.include_router(register_routes.router)
app.include_router(admin_routes.router)
app.include_router(seller_routes.router)
app.include_router(buyer_routes.router)
app.include_router(medicine_routes.router)
app.include_router(order_routes.router)
app.include_router(page_routes.router)

# ---------- Error Handling ----------
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)

# ---------- Run the app ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
