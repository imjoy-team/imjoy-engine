"""Test plugin engine api."""
import asyncio
import os
import uuid

import pytest

from .fake_client import FakeClient

WORKSPACE_DIR = os.path.expanduser("~/ImJoyWorkspace")
URL = "http://localhost:9527"

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
@pytest.mark.asyncio
async def client(event_loop):
    """Provide a mock client."""
    with open(os.path.join(WORKSPACE_DIR, ".token"), "r") as fil:
        token = fil.read()
    client_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    client = FakeClient(URL, client_id, session_id, token, event_loop)
    await client.connect()
    await client.register_client()
    return client


@pytest.mark.asyncio
@pytest.fixture(scope="module")
async def init_plugin(client, event_loop):
    """Initialize the plugin."""
    pid = await client.init_plugin(TEST_PLUGIN_CONFIG)
    initialized = event_loop.create_future()
    client.on_plugin_message(pid, "initialized", initialized)
    await initialized
    return {"id": pid}


@pytest.mark.asyncio
async def test_plugin_execute(client, init_plugin, event_loop):
    """Test plugin execute."""
    pid = init_plugin["id"]
    executed = event_loop.create_future()
    await client.execute(pid, {"type": "script", "content": "print('hello')"}, executed)
    await executed
