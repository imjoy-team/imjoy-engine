"""Test plugin engine api."""
import logging
import os
import sys
import uuid

import pytest

from imjoy.engine import Engine
from imjoy.env import bootstrap, prep_env
from imjoy.options import parse_cmd_line
from .fake_client import FakeClient

logging.basicConfig(stream=sys.stdout)
_LOGGER = logging.getLogger(__name__)

_LOGGER.setLevel(logging.INFO)

# pylint: disable=unused-argument
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio  # pylint: disable=invalid-name

HOST = "localhost"
PORT = 9527
TOKEN = "12345678"
WORKSPACE = "~/ImJoyWorkspace"
WORKSPACE_DIR = os.path.expanduser("~/ImJoyWorkspace")
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
    # "env": "conda create -n test-env python=3.6.7",
    # "requirements": "pip: numpy",
    "dependencies": [],
}


@pytest.fixture(name="engine")
async def setup_engine(event_loop):
    """Set up engine."""
    logger = _LOGGER
    opt = parse_cmd_line(["--debug", "--token", TOKEN])
    opt = prep_env(opt, logger)
    opt = bootstrap(opt, logger)
    engine = Engine(opt, logger)
    engine.setup()
    await engine.async_start()
    print(engine)
    yield engine
    await engine.async_stop()


@pytest.fixture(name="client")
async def mock_client(engine, event_loop):
    """Provide a mock client."""
    client_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    client = FakeClient(URL, client_id, session_id, TOKEN, event_loop)
    await client.connect()
    await client.register_client()
    yield client


async def test_debugging(engine):
    """Try to figure out what is going on."""
    print(engine)
    # print(client)
    assert True
    assert False


@pytest.fixture(name="init_plugin")
async def setup_init_plugin(client, event_loop):
    """Initialize the plugin."""
    pid = await client.init_plugin(TEST_PLUGIN_CONFIG)
    initialized = event_loop.create_future()
    client.on_plugin_message(pid, "initialized", initialized)
    print(client)
    await initialized
    return {"id": pid}


@pytest.mark.skip
async def test_plugin_execute(client, init_plugin, event_loop):
    """Test plugin execute."""
    pid = init_plugin["id"]
    executed = event_loop.create_future()
    await client.execute(pid, {"type": "script", "content": "print('hello')"}, executed)
    await executed
    assert executed.result() == {'type': 'executeSuccess'}
    assert False
