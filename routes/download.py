import io
import os
import re
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from minio import Minio
from pydantic import BaseModel
from starlette.background import BackgroundTask

from config import MINIO_ACCESS_KEY, MINIO_BUCKET, MINIO_ENDPOINT, MINIO_SECRET_KEY
from database import dataset_catalog_col, uploads_col
from routes.auth import ROLE_DATASET_MANAGER, require_role

download_router = APIRouter(prefix="/api/download", tags=["download"])
TEMP_DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "dataset-uploader-downloads"
TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("._") or "dataset"


class DownloadSelection(BaseModel):
    upload_ids: list[str]


def remove_archive(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def cleanup_expired_archives() -> None:
    expiration_time = time.time() - 24 * 60 * 60
    for path in TEMP_DOWNLOAD_DIR.glob("*.zip"):
        try:
            if path.stat().st_mtime < expiration_time:
                path.unlink(missing_ok=True)
        except OSError:
            continue


@download_router.get("/files")
def list_download_files(
    request: Request,
    dataset_type: str | None = Query(default=None),
    subtype: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
):
    require_role(request, ROLE_DATASET_MANAGER)

    if file_type and file_type not in {"image", "document"}:
        raise HTTPException(status_code=400, detail="Tipo de archivo inválido.")
    if dataset_type and not dataset_catalog_col.find_one({"dataset_type": dataset_type, "is_active": True}):
        raise HTTPException(status_code=404, detail="Dataset no encontrado.")

    query = {"status": "completed", "storage_key": {"$exists": True}}
    if dataset_type:
        query["dataset_type"] = dataset_type
    if subtype:
        query["subtype"] = subtype
    if file_type == "document":
        query["file_type"] = file_type
    elif file_type == "image":
        query["$or"] = [{"file_type": "image"}, {"file_type": {"$exists": False}}]

    records = uploads_col.find(
        query,
        {
            "_id": 0,
            "upload_id": 1,
            "original_filename": 1,
            "dataset_type": 1,
            "subtype": 1,
            "file_type": 1,
            "content_type": 1,
            "file_size": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).limit(5000)

    files = []
    for record in records:
        filename = record.get("original_filename", "archivo")
        extension = Path(filename).suffix.lower()
        files.append({
            "upload_id": record["upload_id"],
            "filename": filename,
            "dataset_type": record.get("dataset_type", ""),
            "subtype": record.get("subtype", ""),
            "file_type": record.get("file_type", "image" if extension in {".png", ".jpg", ".jpeg", ".webp"} else "document"),
            "content_type": record.get("content_type", ""),
            "file_size": record.get("file_size"),
            "created_at": record.get("created_at").isoformat() if record.get("created_at") else None,
        })

    return {"files": files, "truncated": len(files) == 5000}


@download_router.post("/selection")
def prepare_selection_download(selection: DownloadSelection, request: Request):
    require_role(request, ROLE_DATASET_MANAGER)
    cleanup_expired_archives()
    upload_ids = list(dict.fromkeys(selection.upload_ids))
    if not upload_ids or len(upload_ids) > 250:
        raise HTTPException(status_code=400, detail="Selecciona entre 1 y 250 archivos.")

    records = list(uploads_col.find({
        "upload_id": {"$in": upload_ids},
        "status": "completed",
        "storage_key": {"$exists": True},
    }))
    records_by_id = {record["upload_id"]: record for record in records}
    if len(records_by_id) != len(upload_ids):
        raise HTTPException(status_code=404, detail="Uno o más archivos no están disponibles para descargar.")

    archive_id = uuid.uuid4().hex
    archive_path = TEMP_DOWNLOAD_DIR / f"{archive_id}.zip"
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for upload_id in upload_ids:
                record = records_by_id[upload_id]
                response = minio_client.get_object(MINIO_BUCKET, record["storage_key"])
                original_filename = record.get("original_filename", "archivo").replace("\\", "/")
                archive_name = (
                    f"{safe_name(record.get('dataset_type', 'dataset'))}/"
                    f"{safe_name(record.get('subtype', 'sin_subtipo'))}/"
                    f"{upload_id}_{Path(original_filename).name}"
                )
                try:
                    with archive.open(archive_name, "w") as archive_file:
                        while chunk := response.read(1024 * 1024):
                            archive_file.write(chunk)
                finally:
                    response.close()
                    response.release_conn()
    except Exception as error:
        remove_archive(str(archive_path))
        print(f"[-] Error creando ZIP seleccionado: {error}")
        raise HTTPException(status_code=503, detail="No se pudo preparar la descarga. Verifica que MinIO esté disponible.")

    return {"download_url": f"/api/download/selection/{archive_id}"}


@download_router.get("/selection/{archive_id}")
def download_selection(archive_id: str, request: Request):
    require_role(request, ROLE_DATASET_MANAGER)
    try:
        archive_id = uuid.UUID(hex=archive_id).hex
    except ValueError:
        raise HTTPException(status_code=404, detail="Descarga no encontrada.")

    archive_path = TEMP_DOWNLOAD_DIR / f"{archive_id}.zip"
    if not archive_path.is_file():
        raise HTTPException(status_code=404, detail="La descarga expiró o no existe.")

    filename = f"seleccion-{datetime.utcnow():%Y%m%d-%H%M%S}.zip"
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(remove_archive, str(archive_path)),
    )


@download_router.get("/datasets/{dataset_type}")
def download_dataset(dataset_type: str, request: Request):
    require_role(request, ROLE_DATASET_MANAGER)
    config = dataset_catalog_col.find_one({"dataset_type": dataset_type, "is_active": True})
    if not config:
        raise HTTPException(status_code=404, detail="Dataset no encontrado.")

    archive = io.BytesIO()
    object_count = 0
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for item in minio_client.list_objects(MINIO_BUCKET, recursive=True):
                path_parts = item.object_name.split("/")
                if len(path_parts) < 4 or path_parts[1] != dataset_type:
                    continue
                response = minio_client.get_object(MINIO_BUCKET, item.object_name)
                try:
                    zip_file.writestr(item.object_name, response.read())
                    object_count += 1
                finally:
                    response.close()
                    response.release_conn()
    except Exception as error:
        print(f"[-] Error leyendo MinIO ({MINIO_ENDPOINT}/{MINIO_BUCKET}): {error}")
        raise HTTPException(
            status_code=503,
            detail="MinIO no está disponible. Ejecuta la API dentro de Docker Compose.",
        )

    if object_count == 0:
        raise HTTPException(status_code=404, detail="El dataset no contiene archivos.")

    archive.seek(0)
    filename = f"{safe_name(dataset_type)}-completo.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )