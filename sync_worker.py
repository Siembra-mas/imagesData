import io
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image
from minio import Minio

from config import MINIO_ACCESS_KEY, MINIO_BUCKET, MINIO_ENDPOINT, MINIO_SECRET_KEY
from database import uploads_col

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)


def process_uploaded_document(
    username: str,
    dataset_type: str,
    subtype: str,
    extension: str,
    upload_id: str,
    document_path: str,
    content_type: str,
) -> None:
    """Store the original PDF or Word document in MinIO without modification."""
    path = Path(document_path)
    try:
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)

        object_name = f"{username}/{dataset_type}/{subtype}/{uuid.uuid4().hex}{extension}"
        with path.open("rb") as document:
            minio_client.put_object(
                MINIO_BUCKET,
                object_name,
                document,
                length=path.stat().st_size,
                content_type=content_type,
            )

        uploads_col.update_one(
            {"upload_id": upload_id},
            {"$set": {
                "status": "completed",
                "bucket": MINIO_BUCKET,
                "storage_key": object_name,
                "processed_at": datetime.utcnow(),
            }},
        )
    except Exception as error:
        uploads_col.update_one(
            {"upload_id": upload_id},
            {"$set": {"status": "failed", "error": str(error), "processed_at": datetime.utcnow()}},
        )
        print(f"[-] Error subiendo documento {upload_id} a MinIO: {error}")
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


def process_uploaded_image(
    username: str,
    dataset_type: str,
    subtype: str,
    extension: str,
    upload_id: str,
    image_path: str,
    content_type: str,
) -> None:
    """Normaliza la imagen ensamblada y la almacena directamente en MinIO."""
    try:
        with Image.open(image_path) as image:
            image.load()
            image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            object_name = f"{username}/{dataset_type}/{subtype}/{uuid.uuid4().hex}{extension}"
            image_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[extension]
            if image_format == "JPEG" and image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format=image_format, optimize=True)
            output.seek(0)

        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
        minio_client.put_object(
            MINIO_BUCKET,
            object_name,
            output,
            length=output.getbuffer().nbytes,
            content_type=content_type,
        )
        uploads_col.update_one(
            {"upload_id": upload_id},
            {"$set": {
                "status": "completed",
                "bucket": MINIO_BUCKET,
                "storage_key": object_name,
                "processed_at": datetime.utcnow(),
            }},
        )
    except Exception as error:
        uploads_col.update_one(
            {"upload_id": upload_id},
            {"$set": {"status": "failed", "error": str(error), "processed_at": datetime.utcnow()}},
        )
        print(f"[-] Error subiendo imagen {upload_id} a MinIO: {error}")
    finally:
        shutil.rmtree(Path(image_path).parent, ignore_errors=True)
