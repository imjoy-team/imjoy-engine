"""Test the imjoy engine server."""
import os
import subprocess
import sys
import time

import pytest
import requests
from imjoy_rpc import connect_to_server

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

PORT = 38283


@pytest.fixture(name="socketio_server")
def socketio_server_fixture():
    """Start server as test fixture and tear down after test."""
    proc = subprocess.Popen([sys.executable, "-m", "imjoy.server", f"--port={PORT}"])

    timeout = 5
    while timeout > 0:
        try:
            response = requests.get(f"http://127.0.0.1:{PORT}/")
            if response.ok:
                break
        except Exception:
            pass
        timeout -= 0.1
        time.sleep(0.1)
    yield
    proc.terminate()
    proc.wait()


async def test_connect_to_server(socketio_server):
    """Test connecting to the server."""

    class ImJoyPlugin:
        """Represent a test plugin."""

        def __init__(self, ws):
            self._ws = ws

        async def setup(self):
            """Set up the plugin."""
            await self._ws.log("initialized")

        async def run(self, ctx):
            """Run the plugin."""
            await self._ws.log("hello world")

    server_url = f"http://127.0.0.1:{PORT}"
    ws = await connect_to_server({"name": "my plugin", "server_url": server_url})
    ws.export(ImJoyPlugin(ws))


def test_plugin_runner(socketio_server):
    """Test the plugin runner."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.runner",
            f"--server-url=http://127.0.0.1:{PORT}",
            "--quit-on-ready",
            os.path.join(os.path.dirname(__file__), "example_plugin.py"),
        ]
    )
    proc.wait()
