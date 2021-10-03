"""Test the ImJoy engine."""
import uuid

SIO_PORT = 38283
SIO_PORT2 = 38223
SIO_SERVER_URL = f"http://127.0.0.1:{SIO_PORT}"

MINIO_PORT = 38483
MINIO_SERVER_URL = f"http://127.0.0.1:{MINIO_PORT}"
MINIO_ROOT_USER = "minio"
MINIO_ROOT_PASSWORD = str(uuid.uuid4())
