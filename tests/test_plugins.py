"""Test plugin engine api."""
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from .fake_client import FakeClient

# pylint: disable=unused-argument
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio  # pylint: disable=invalid-name

HERE = Path(__file__).parent
ENGINE_MODULE = HERE.parent / "imjoy/engine.py"
HOST = "localhost"
PORT = 9527
TOKEN = "12345678"
URL = f"http://{HOST}:{PORT}"

TEST_PLUGIN_CONFIG = {
    "name": "test-plugin",
    "type": "native-python",
    "version": "0.1.12",
    "api_version": "0.1.2",
    "description": "This is a test plugin.",
    "tags": ["CPU", "GPU", "macOS CPU"],
    "ui": "",
    "inputs": None,
    "outputs": None,
    "flags": [],
    "icon": None,
    "env": "",
    "requirements": "",
    "dependencies": [],
}


@pytest.fixture(name="engine")
def setup_engine():
    """Set up engine."""
    engine_args = f"python {ENGINE_MODULE} --debug --token {TOKEN}"
    process = subprocess.Popen(engine_args.split())
    time.sleep(2)  # This is needed to let the engine finish setup.
    yield
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("Waiting for engine exit timed out")


@pytest.fixture(name="client")
async def mock_client(engine, event_loop):
    """Provide a mock client."""
    client_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    client = FakeClient(URL, client_id, session_id, TOKEN, event_loop)
    await client.connect()
    await client.register_client()
    yield client


@pytest.fixture(name="init_plugin")
async def setup_init_plugin(client, event_loop):
    """Initialize the plugin."""
    pid = await client.init_plugin(TEST_PLUGIN_CONFIG)
    initialized = event_loop.create_future()
    client.on_plugin_message(pid, "initialized", initialized)
    await initialized
    return {"id": pid}


async def test_plugin_execute(client, init_plugin, event_loop):
    """Test plugin execute."""
    pid = init_plugin["id"]
    executed = event_loop.create_future()
    await client.execute(pid, {"type": "script", "content": "print('hello')"}, executed)
    await executed
    assert executed.result() == {'type': 'executeSuccess'}
    assert False
