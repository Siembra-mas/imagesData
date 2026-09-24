import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from routes.auth import auth_router, get_current_user_or_none
from routes.uploader import uploader_router

app = FastAPI()

# Obtener directorio base del script actual
BASE_DIR = Path(__file__).resolve().parent

# Montar con rutas absolutas verificadas
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(auth_router)
app.include_router(uploader_router)

@app.get("/login")
def login_view(request: Request):
    user = get_current_user_or_none(request)
    if user:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"user": None}
    )

@app.get("/")
def home_view(request: Request):
    user = get_current_user_or_none(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"user": user}
    )