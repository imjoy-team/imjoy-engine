import os
import pytest
import asyncio
import uuid
from .fake_client import FakeClient

WORKSPACE_DIR = os.path.expanduser("~/ImJoyWorkspace")
URL = "http://localhost:9527"

test_plugin_config = {
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
    "env": "conda create -n test-env python=3.6.7",
    "requirements": "pip: numpy",
    "dependencies": [],
}


@pytest.yield_fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def client(event_loop):
    with open(os.path.join(WORKSPACE_DIR, ".token"), "r") as f:
        token = f.read()
    client_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    return FakeClient(URL, client_id, session_id, token, event_loop)


@pytest.mark.asyncio
async def test_plugin_init(client):
    await client.connect()
    await client.register_client()
    await client.init_plugin(test_plugin_config)
