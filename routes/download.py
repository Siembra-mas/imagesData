import io
import re
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from minio import Minio

from config import MINIO_ACCESS_KEY, MINIO_BUCKET, MINIO_ENDPOINT, MINIO_SECRET_KEY
from database import dataset_catalog_col
from routes.auth import ROLE_DATASET_MANAGER, require_role

download_router = APIRouter(prefix="/api/download", tags=["download"])

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("._") or "dataset"


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
        raise HTTPException(status_code=404, detail="El dataset no contiene imágenes.")

    archive.seek(0)
    filename = f"{safe_name(dataset_type)}-completo.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )