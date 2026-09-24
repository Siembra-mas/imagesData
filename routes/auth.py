import os
from datetime import datetime, timedelta
import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from database import users_col

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET no está definido. Añádelo al archivo .env.")
SECRET_KEY = JWT_SECRET
ALGORITHM = "HS256"
COOKIE_NAME = "session_token"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
ROLE_UPLOADER = "uploader"
ROLE_DATASET_MANAGER = "dataset_manager"

class AuthSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=6)

def get_current_user_or_none(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username or not users_col.find_one({"username": username, "is_active": True}):
            return None
        return username
    except jwt.PyJWTError:
        return None


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        user = users_col.find_one({"username": username, "is_active": True})
        if not user:
            raise HTTPException(status_code=401, detail="Sesión inválida o cuenta inactiva.")
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sesión inválida.")


def require_role(request: Request, *roles: str) -> dict:
    user = get_current_user(request)
    if user.get("role", ROLE_UPLOADER) not in roles:
        raise HTTPException(status_code=403, detail="No tienes permisos para esta operación.")
    return user

@auth_router.post("/register")
def register(data: AuthSchema):
    if users_col.find_one({"username": data.username}):
        raise HTTPException(status_code=400, detail="El usuario ya existe.")

    hashed = bcrypt.hashpw(data.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    users_col.insert_one({
        "username": data.username,
        "password_hash": hashed,
        "is_active": False,
        "role": ROLE_UPLOADER,
        "created_at": datetime.utcnow()
    })

    return {"message": "Cuenta creada. Espera a que el administrador la autorice."}

@auth_router.post("/login")
def login(data: AuthSchema, response: Response):
    user = users_col.find_one({"username": data.username})
    if not user:
        raise HTTPException(status_code=400, detail="usuario no registrado")

    if not bcrypt.checkpw(data.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise HTTPException(status_code=400, detail="Credenciales incorrectas.")

    if user.get("is_active") is not True:
        raise HTTPException(status_code=403, detail="Tu cuenta aún no ha sido autorizada.")

    expire = datetime.utcnow() + timedelta(hours=12)
    role = user.get("role", ROLE_UPLOADER)
    token = jwt.encode({"sub": user["username"], "role": role, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=12 * 60 * 60,
    )
    return {"message": "Sesión iniciada.", "role": role}

@auth_router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"message": "Sesión finalizada."}


@auth_router.get("/me")
def current_session(request: Request):
    user = get_current_user(request)
    return {"username": user["username"], "role": user.get("role", ROLE_UPLOADER)}