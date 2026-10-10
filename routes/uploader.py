import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
import aiofiles

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError

from routes.auth import get_current_user_or_none, require_role, ROLE_DATASET_MANAGER, ROLE_UPLOADER
from database import dataset_catalog_col, uploads_col
from sync_worker import process_uploaded_document, process_uploaded_image

uploader_router = APIRouter(prefix="/api/upload", tags=["uploader"])

BASE_DIR = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_CHUNK_BYTES = 10 * 1024 * 1024
if MAX_UPLOAD_BYTES <= 0:
    raise RuntimeError("MAX_UPLOAD_BYTES debe ser mayor que cero.")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DOCUMENT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".zip": "application/zip",
    ".rar": "application/vnd.rar",
}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | set(DOCUMENT_MIME_TYPES)
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", *DOCUMENT_MIME_TYPES.values()}
MIME_TO_FORMAT = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}

# Directorio temporal para ensamblar los fragmentos (chunked uploads)
TEMP_UPLOAD_DIR = Path("/tmp/temp_uploads")
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def safe_path_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("._") or "usuario"

def validate_uploaded_file(file_path: Path, content_type: str, extension: str) -> None:
    if content_type not in ALLOWED_MIME_TYPES or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato no permitido. Usa PNG/JPG/WEBP, PDF/DOC/DOCX o ZIP/RAR.")

    if extension in IMAGE_EXTENSIONS:
        try:
            with Image.open(file_path) as image:
                if image.format != MIME_TO_FORMAT[content_type]:
                    raise HTTPException(status_code=400, detail="El MIME no coincide con el contenido de la imagen.")
                image.verify()
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=400, detail="El archivo no contiene una imagen válida.")
        return

    try:
        with file_path.open("rb") as uploaded_file:
            header = uploaded_file.read(1024)

        if extension == ".pdf" and b"%PDF-" not in header:
            raise HTTPException(status_code=400, detail="El archivo no contiene un PDF válido.")
        if extension == ".doc" and not header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise HTTPException(status_code=400, detail="El archivo no contiene un documento DOC válido.")
        if extension == ".docx":
            with zipfile.ZipFile(file_path) as document:
                names = set(document.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise HTTPException(status_code=400, detail="El archivo no contiene un documento DOCX válido.")
        if extension == ".zip" and not zipfile.is_zipfile(file_path):
            raise HTTPException(status_code=400, detail="El archivo no contiene un ZIP válido.")
        if extension == ".rar" and not header.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
            raise HTTPException(status_code=400, detail="El archivo no contiene un RAR válido.")
    except (OSError, zipfile.BadZipFile):
        raise HTTPException(status_code=400, detail="El archivo de documento está dañado o no es válido.")

def get_dataset_config(dataset_type: str) -> dict:
    config = dataset_catalog_col.find_one({"dataset_type": dataset_type, "is_active": True})
    if not config:
        raise HTTPException(status_code=400, detail="Tipo de dataset no permitido.")
    return config

async def write_manifest(manifest_path: Path, manifest: dict) -> None:
    temporary_path = manifest_path.with_suffix(".json.tmp")
    async with aiofiles.open(temporary_path, "w", encoding="utf-8") as manifest_file:
        await manifest_file.write(json.dumps(manifest))
    os.replace(temporary_path, manifest_path)

@uploader_router.get("/catalog")
def get_catalog(request: Request):
    if not get_current_user_or_none(request):
        raise HTTPException(status_code=401, detail="No autenticado o cuenta inactiva.")
    catalog = dataset_catalog_col.find({"is_active": True}, {"_id": 0, "dataset_type": 1, "name": 1, "subtypes": 1})
    return {"datasets": list(catalog), "max_upload_bytes": MAX_UPLOAD_BYTES}


@uploader_router.get("/status/{upload_id}")
def get_upload_status(upload_id: str, request: Request):
    user = require_role(request, ROLE_UPLOADER, ROLE_DATASET_MANAGER)
    upload = uploads_col.find_one({"upload_id": upload_id})
    if not upload:
        raise HTTPException(status_code=404, detail="Carga no encontrada.")

    is_manager = user.get("role") == ROLE_DATASET_MANAGER
    if upload.get("username") != user["username"] and not is_manager:
        raise HTTPException(status_code=404, detail="Carga no encontrada.")

    status_message = {
        "pending": "El archivo se está guardando.",
        "completed": "Archivo guardado correctamente.",
        "failed": "No se pudo guardar el archivo. Inténtalo de nuevo o contacta al administrador.",
    }.get(upload.get("status"), "Estado de carga desconocido.")
    return {"status": upload.get("status", "unknown"), "message": status_message}


@uploader_router.post("/files", status_code=202)
@uploader_router.post("/images", status_code=202, include_in_schema=False)
async def upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
    dataset_type: str = Form(...),
    subtype: str = Form(...),
    filename: str = Form(...),
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk_sha256: str | None = Form(default=None),
    file: UploadFile = File(...),
):
    user = require_role(request, ROLE_UPLOADER, ROLE_DATASET_MANAGER)
    username = user["username"]
    dataset_config = get_dataset_config(dataset_type)

    if subtype not in dataset_config.get("subtypes", []):
        raise HTTPException(status_code=400, detail="Subtipo no permitido para este dataset.")

    extension = Path(filename).suffix.lower()
    if extension in DOCUMENT_MIME_TYPES:
        content_type_guess = DOCUMENT_MIME_TYPES[extension]
    else:
        content_type_guess = "image/jpeg" if extension in {".jpg", ".jpeg"} else f"image/{extension.lstrip('.')}"
    if extension not in ALLOWED_EXTENSIONS or content_type_guess not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Formato no permitido. Usa PNG/JPG/WEBP, PDF/DOC/DOCX o ZIP/RAR.")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="El nombre del archivo es demasiado largo.")

    try:
        normalized_upload_id = str(uuid.UUID(upload_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identificador de carga inválido.")

    if total_chunks < 1:
        raise HTTPException(
            status_code=400,
            detail=f"Se recibieron {total_chunks} fragmentos; el archivo debe producir al menos uno.",
        )
    max_chunks = (MAX_UPLOAD_BYTES + MAX_CHUNK_BYTES - 1) // MAX_CHUNK_BYTES
    if total_chunks > max_chunks:
        max_size_gib = MAX_UPLOAD_BYTES / (1024 ** 3)
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite máximo de {max_size_gib:g} GiB.",
        )
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(status_code=400, detail="Índice de fragmento inválido.")
    if chunk_sha256 is not None and not re.fullmatch(r"[a-fA-F0-9]{64}", chunk_sha256):
        raise HTTPException(status_code=400, detail="Hash del fragmento inválido.")

    existing_upload = uploads_col.find_one({"client_upload_id": normalized_upload_id, "username": username})
    if existing_upload:
        return {"message": "Archivo aceptado para procesamiento.", "upload_id": existing_upload["upload_id"]}

    chunk_data = await file.read(MAX_CHUNK_BYTES + 1)
    if not chunk_data:
        raise HTTPException(status_code=400, detail="El fragmento está vacío.")
    if len(chunk_data) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="El fragmento supera el máximo de 10 MB.")
    actual_chunk_hash = hashlib.sha256(chunk_data).hexdigest()
    if chunk_sha256 is not None and actual_chunk_hash.lower() != chunk_sha256.lower():
        raise HTTPException(status_code=400, detail="El hash del fragmento no coincide.")

    upload_dir = TEMP_UPLOAD_DIR / normalized_upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = upload_dir / "manifest.json"
    metadata = {
        "username": username,
        "dataset_type": dataset_type,
        "subtype": subtype,
        "filename": filename,
        "extension": extension,
        "content_type": content_type_guess,
        "total_chunks": total_chunks,
    }

    if manifest_path.exists():
        async with aiofiles.open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.loads(await manifest_file.read())
        if manifest.get("metadata") != metadata:
            raise HTTPException(status_code=409, detail="Los datos de la carga no coinciden con sus fragmentos anteriores.")
            if manifest.get("state") == "accepted":
                return {"message": "Archivo aceptado para procesamiento.", "upload_id": manifest["db_upload_id"]}
    else:
        manifest = {"metadata": metadata, "chunks": {}, "state": "uploading"}

    chunk_path = upload_dir / f"chunk-{chunk_index:08d}.part"
    temporary_chunk_path = chunk_path.with_suffix(".part.tmp")
    async with aiofiles.open(temporary_chunk_path, "wb") as chunk_file:
        await chunk_file.write(chunk_data)
    os.replace(temporary_chunk_path, chunk_path)

    manifest.setdefault("chunks", {})[str(chunk_index)] = {
        "sha256": actual_chunk_hash,
        "size": len(chunk_data),
    }
    await write_manifest(manifest_path, manifest)

    received_size = sum(chunk_info["size"] for chunk_info in manifest["chunks"].values())
    if received_size > MAX_UPLOAD_BYTES:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail="La imagen supera el tamaño máximo permitido.")

    if len(manifest["chunks"]) < total_chunks:
        return {
            "message": f"Fragmento {chunk_index + 1}/{total_chunks} recibido.",
            "received_chunks": len(manifest["chunks"]),
            "total_chunks": total_chunks,
        }

    assembled_path = upload_dir / "assembled.image"
    total_size = 0
    try:
        async with aiofiles.open(assembled_path, "wb") as assembled_file:
            for index in range(total_chunks):
                chunk_info = manifest["chunks"].get(str(index))
                if not chunk_info:
                    return {"message": f"Falta el fragmento {index + 1}/{total_chunks}.", "received_chunks": len(manifest["chunks"]), "total_chunks": total_chunks}

                chunk_path = upload_dir / f"chunk-{index:08d}.part"
                chunk_hash = hashlib.sha256()
                chunk_size = 0
                async with aiofiles.open(chunk_path, "rb") as chunk_file:
                    while chunk_data := await chunk_file.read(1024 * 1024):
                        chunk_hash.update(chunk_data)
                        chunk_size += len(chunk_data)
                        total_size += len(chunk_data)
                        if total_size > MAX_UPLOAD_BYTES:
                            raise HTTPException(status_code=413, detail="La imagen supera el tamaño máximo permitido.")
                        await assembled_file.write(chunk_data)

                if chunk_size != chunk_info["size"] or chunk_hash.hexdigest() != chunk_info["sha256"]:
                    raise HTTPException(status_code=400, detail=f"El fragmento {index + 1} está dañado; vuelve a enviarlo.")
    except Exception:
        assembled_path.unlink(missing_ok=True)
        raise

    try:
        validate_uploaded_file(assembled_path, content_type_guess, extension)
    except HTTPException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    db_upload_id = uuid.uuid4().hex
    file_type = "image" if extension in IMAGE_EXTENSIONS else "document"
    uploads_col.insert_one({
        "upload_id": db_upload_id,
        "client_upload_id": normalized_upload_id,
        "original_filename": filename,
        "username": username,
        "dataset_type": dataset_type,
        "subtype": subtype,
        "file_type": file_type,
        "content_type": content_type_guess,
        "file_size": total_size,
        "status": "pending",
        "created_at": datetime.utcnow(),
    })

    processor = process_uploaded_image if file_type == "image" else process_uploaded_document
    background_tasks.add_task(
        processor,
        safe_path_segment(username),
        dataset_type,
        safe_path_segment(subtype),
        extension,
        db_upload_id,
        str(assembled_path),
        content_type_guess,
    )

    manifest["state"] = "accepted"
    manifest["db_upload_id"] = db_upload_id
    await write_manifest(manifest_path, manifest)

    return {"message": "Archivo ensamblado y aceptado para procesamiento.", "upload_id": db_upload_id}