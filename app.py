from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from routes.auth import auth_router, get_current_user, get_current_user_or_none, ROLE_DATASET_MANAGER
from routes.uploader import uploader_router
from routes.download import download_router

app = FastAPI()
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.include_router(auth_router)
app.include_router(uploader_router)
app.include_router(download_router)

@app.get("/login")
def login_page(request: Request):
    if get_current_user_or_none(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"user": None})

@app.get("/", response_class=HTMLResponse)
def index_page(request: Request):
    username = get_current_user_or_none(request)
    if not username:
        return RedirectResponse(url="/login", status_code=303)
    current_user = get_current_user(request)
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"user": username, "role": current_user.get("role")},
    )


@app.get("/downloads", response_class=HTMLResponse)
def downloads_page(request: Request):
    user = get_current_user(request)
    if user.get("role") != ROLE_DATASET_MANAGER:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="downloads.html",
        context={"user": user["username"], "role": user.get("role")},
    )