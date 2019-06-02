"""Provide common utils for tests."""
from pathlib import Path

HERE = Path(__file__).parent
ENGINE_MODULE = HERE.parent / "imjoy/engine.py"
TOKEN = "12345678"
HOST = "localhost"
PORT = 9527
URL = f"http://{HOST}:{PORT}"
