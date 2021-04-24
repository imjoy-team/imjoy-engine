import os
import pytest
import subprocess
import sys
import requests
import time

from imjoy_rpc import connect_to_server

PORT = 38283


@pytest.fixture
async def socketio_server():
    """Start server as test fixture and tear down after test"""

    proc = subprocess.Popen([sys.executable, "-m", "imjoy.server", f"--port={PORT}"])

    timeout = 5
    while timeout > 0:
        try:
            r = requests.get(f"http://127.0.0.1:{PORT}/")
            if r.ok:
                break
        except:
            pass
        timeout -= 0.1
        time.sleep(0.1)
    yield
    proc.terminate()
    proc.wait()


async def test_connect_to_server(socketio_server):
    """test connecting to the server """

    class ImJoyPlugin:
        def __init__(self, ws):
            self._ws = ws

        async def setup(self):
            await self._ws.log("initialized.")

        async def run(self, ctx):
            await self._ws.log("hello world.")

    server_url = f"http://127.0.0.1:{PORT}"
    ws = await connect_to_server({"name": "my plugin", "server_url": server_url})
    ws.export(ImJoyPlugin(ws))


async def test_plugin_runner(socketio_server):
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
