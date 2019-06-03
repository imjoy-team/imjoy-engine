"""Provide project scoped test fixtures."""
import signal
import subprocess
import time
import uuid

import pytest

from tests.common import ENGINE_MODULE, TOKEN, URL
from tests.mock_client import TestClient


@pytest.fixture(name="engine")
def setup_engine():
    """Set up engine."""
    engine_args = f"python {ENGINE_MODULE} --dev --debug --token {TOKEN}"
    process = subprocess.Popen(engine_args.split())
    time.sleep(2)  # This is needed to let the engine finish setup.
    yield
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("Waiting for engine exit timed out")


@pytest.fixture(name="client")
async def mock_client(engine, event_loop):  # pylint: disable=unused-argument
    """Provide a mock client."""
    client_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    client = TestClient(URL, client_id, session_id, TOKEN, event_loop)
    await client.connect()
    await client.register_client()
    yield client
    await client.sio.disconnect()
