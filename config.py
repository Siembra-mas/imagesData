import os

# Los valores no sensibles pueden tener respaldo
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "vision-datasets")

# Las credenciales sin respaldo forzarán un fallo si el .env no se carga
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
    raise ValueError("Las credenciales de MinIO no están configuradas en el entorno.")