import io
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError

from routes.auth import get_current_user_or_none, require_role, ROLE_DATASET_MANAGER, ROLE_UPLOADER
from database import dataset_catalog_col, uploads_col
from sync_worker import process_uploaded_image

uploader_router = APIRouter(prefix="/api/upload", tags=["uploader"])

BASE_DIR = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
MIME_TO_FORMAT = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def safe_path_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("._") or "usuario"


def validate_image(data: bytes, content_type: str, extension: str) -> None:
    if content_type not in ALLOWED_MIME_TYPES or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato de archivo no permitido. Solo imágenes PNG, JPG o WEBP.")

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != MIME_TO_FORMAT[content_type]:
                raise HTTPException(status_code=400, detail="El MIME no coincide con el contenido de la imagen.")
            image.verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="El archivo no contiene una imagen válida.")


def get_dataset_config(dataset_type: str) -> dict:
    config = dataset_catalog_col.find_one({"dataset_type": dataset_type, "is_active": True})
    if not config:
        raise HTTPException(status_code=400, detail="Tipo de dataset no permitido.")
    return config


@uploader_router.get("/catalog")
def get_catalog(request: Request):
    if not get_current_user_or_none(request):
        raise HTTPException(status_code=401, detail="No autenticado o cuenta inactiva.")
    catalog = dataset_catalog_col.find({"is_active": True}, {"_id": 0, "dataset_type": 1, "name": 1, "subtypes": 1})
    return {"datasets": list(catalog)}


@uploader_router.post("/images", status_code=202)
async def upload_image(
    request: Request,
    background_tasks: BackgroundTasks,
    dataset_type: str = Form(...),
    subtype: str = Form(...),
    file: UploadFile = File(...),
):
    user = require_role(request, ROLE_UPLOADER, ROLE_DATASET_MANAGER)
    username = user["username"]
    dataset_config = get_dataset_config(dataset_type)
    if subtype not in dataset_config.get("subtypes", []):
        raise HTTPException(status_code=400, detail="Subtipo no permitido para este dataset.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="El archivo no tiene nombre.")

    extension = Path(file.filename).suffix.lower()
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="La imagen supera el tamaño máximo permitido.")
    validate_image(data, file.content_type or "", extension)

    upload_id = uuid.uuid4().hex
    uploads_col.insert_one({
        "upload_id": upload_id,
        "original_filename": file.filename,
        "username": username,
        "dataset_type": dataset_type,
        "subtype": subtype,
        "status": "pending",
        "created_at": datetime.utcnow(),
    })
    background_tasks.add_task(
        process_uploaded_image,
        safe_path_segment(username),
        dataset_type,
        safe_path_segment(subtype),
        extension,
        upload_id,
        data,
        file.content_type or "application/octet-stream",
    )

    return {"message": "Imagen aceptada para procesamiento.", "upload_id": upload_id}
