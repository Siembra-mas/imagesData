import logging
import re
from datetime import datetime
from pathlib import Path
from collections.abc import Iterable, Iterator

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from minio import Minio
from zipstream import ZIP_DEFLATED, ZipStream

from config import MINIO_ACCESS_KEY, MINIO_BUCKET, MINIO_ENDPOINT, MINIO_SECRET_KEY
from database import dataset_catalog_col, uploads_col
from routes.auth import ROLE_DATASET_MANAGER, require_role

logger = logging.getLogger(__name__)

download_router = APIRouter(prefix="/api/download", tags=["download"])
CHUNK_SIZE = 1024 * 1024

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("._") or "dataset"


def minio_object_chunks(object_name: str) -> Iterator[bytes]:
    response = None
    try:
        response = minio_client.get_object(MINIO_BUCKET, object_name)
        while chunk := response.read(CHUNK_SIZE):
            yield chunk
    except Exception:
        logger.exception("Error transmitiendo objeto MinIO %s", object_name)
        raise
    finally:
        if response is not None:
            try:
                response.close()
            finally:
                response.release_conn()


def stream_zip(entries: Iterable[tuple[str, str]], filename: str) -> StreamingResponse:
    archive = ZipStream(compress_type=ZIP_DEFLATED)
    for object_name, archive_name in entries:
        archive.add(minio_object_chunks(object_name), archive_name)

    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
def download_selection(request: Request, upload_ids: list[str] = Form(...)):
    require_role(request, ROLE_DATASET_MANAGER)
    upload_ids = list(dict.fromkeys(upload_ids))
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

    entries = []
    for upload_id in upload_ids:
        record = records_by_id[upload_id]
        original_filename = record.get("original_filename", "archivo").replace("\\", "/")
        archive_name = (
            f"{safe_name(record.get('dataset_type', 'dataset'))}/"
            f"{safe_name(record.get('subtype', 'sin_subtipo'))}/"
            f"{upload_id}_{Path(original_filename).name}"
        )
        entries.append((record["storage_key"], archive_name))

    filename = f"seleccion-{datetime.utcnow():%Y%m%d-%H%M%S}.zip"
    return stream_zip(entries, filename)


@download_router.get("/datasets/{dataset_type}")
def download_dataset(dataset_type: str, request: Request):
    require_role(request, ROLE_DATASET_MANAGER)
    config = dataset_catalog_col.find_one({"dataset_type": dataset_type, "is_active": True})
    if not config:
        raise HTTPException(status_code=404, detail="Dataset no encontrado.")

    try:
        objects = [
            item.object_name
            for item in minio_client.list_objects(MINIO_BUCKET, recursive=True)
            if len(item.object_name.split("/")) >= 4 and item.object_name.split("/")[1] == dataset_type
        ]
    except Exception as error:
        logger.exception("Error listando objetos de MinIO para dataset %s", dataset_type)
        raise HTTPException(
            status_code=503,
            detail="MinIO no está disponible. Ejecuta la API dentro de Docker Compose.",
        ) from error

    if not objects:
        raise HTTPException(status_code=404, detail="El dataset no contiene archivos.")

    entries = ((object_name, object_name) for object_name in objects)
    filename = f"{safe_name(dataset_type)}-completo.zip"
    return stream_zip(entries, filename)
