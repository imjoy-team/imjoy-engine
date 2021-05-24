"""Test the imjoy engine server."""
import os
import subprocess
import sys
import time

import pytest
import requests
from requests import RequestException
from imjoy_rpc import connect_to_server

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

PORT = 38283
PORT2 = 38223
SERVER_URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture(name="socketio_server")
def socketio_server_fixture():
    """Start server as test fixture and tear down after test."""
    with subprocess.Popen(
        [sys.executable, "-m", "imjoy.server", f"--port={PORT}"]
    ) as proc:

        timeout = 10
        while timeout > 0:
            try:
                response = requests.get(f"http://127.0.0.1:{PORT}/liveness")
                if response.ok:
                    break
            except RequestException:
                pass
            timeout -= 0.1
            time.sleep(0.1)
        yield

        proc.terminate()


@pytest.fixture(name="socketio_subpath_server")
def socketio_subpath_server_fixture():
    """Start server (under /my/engine) as test fixture and tear down after test."""
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.server",
            f"--port={PORT2}",
            "--base-path=/my/engine",
        ]
    ) as proc:

        timeout = 10
        while timeout > 0:
            try:
                response = requests.get(f"http://127.0.0.1:{PORT2}/my/engine/liveness")
                if response.ok:
                    break
            except RequestException:
                pass
            timeout -= 0.1
            time.sleep(0.1)
        yield

        proc.terminate()


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

    with pytest.raises(Exception, match=r".*Workspace test does not exist.*"):
        ws = await connect_to_server(
            {"name": "my plugin", "workspace": "test", "server_url": SERVER_URL}
        )
    ws = await connect_to_server({"name": "my plugin", "server_url": SERVER_URL})
    await ws.export(ImJoyPlugin(ws))

    ws = await connect_to_server({"server_url": SERVER_URL})
    assert len(ws.config.name) == 36


def test_plugin_runner(socketio_server):
    """Test the plugin runner."""
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.runner",
            f"--server-url=http://127.0.0.1:{PORT}",
            "--quit-on-ready",
            os.path.join(os.path.dirname(__file__), "example_plugin.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        out, err = proc.communicate()
        assert err.decode("utf8") == ""
        output = out.decode("utf8")
        assert "Generated token: imjoy@" in output
        assert "echo: a message" in output


def test_plugin_runner_subpath(socketio_subpath_server):
    """Test the plugin runner with subpath server."""
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.runner",
            f"--server-url=http://127.0.0.1:{PORT2}/my/engine",
            "--quit-on-ready",
            os.path.join(os.path.dirname(__file__), "example_plugin.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        out, err = proc.communicate()
        assert err.decode("utf8") == ""
        output = out.decode("utf8")
        assert "Generated token: imjoy@" in output
        assert "echo: a message" in output


async def test_plugin_runner_workspace(socketio_server):
    """Test the plugin runner with workspace."""
    api = await connect_to_server(
        {"name": "my second plugin", "server_url": SERVER_URL}
    )
    ret = await api.generate_token()
    assert "id" in ret and "token" in ret
    assert ret["token"].startswith("imjoy@")

    # The following code without passing the token should fail
    # Here we assert the output message contains "permission denied"
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.runner",
            f"--server-url=http://127.0.0.1:{PORT}",
            f"--workspace={api.config['workspace']}",
            # f"--token={ret['token']}",
            "--quit-on-ready",
            os.path.join(os.path.dirname(__file__), "example_plugin.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        out, err = proc.communicate()
        assert proc.returncode == 1
        assert err.decode("utf8") == ""
        output = out.decode("utf8")
        assert "Permission denied for workspace:" in output

    # now with the token, it should pass
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.runner",
            f"--server-url=http://127.0.0.1:{PORT}",
            f"--workspace={api.config['workspace']}",
            f"--token={ret['token']}",
            "--quit-on-ready",
            os.path.join(os.path.dirname(__file__), "example_plugin.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        out, err = proc.communicate()
        assert proc.returncode == 0
        assert err.decode("utf8") == ""
        output = out.decode("utf8")
        assert "Generated token: imjoy@" in output
        assert "echo: a message" in output


async def test_workspace(socketio_server):
    """Test the plugin runner."""
    api = await connect_to_server({"name": "my plugin", "server_url": SERVER_URL})
    with pytest.raises(
        Exception, match=r".*Scopes must be empty or contains only the workspace name*"
    ):
        await api.generate_token({"scopes": ["test-workspace"]})
    ret = await api.generate_token()
    assert "id" in ret and "token" in ret
    assert ret["token"].startswith("imjoy@")

    ws = await api.create_workspace(
        {
            "name": "test-workspace",
            "owners": ["user1@imjoy.io", "user2@imjoy.io"],
            "allow_list": [],
            "deny_list": [],
            "visibility": "protected",  # or public
        }
    )
    await ws.log("hello")
    await ws.register_service(
        {
            "name": "test_service",
            "type": "#test",
        }
    )
    service = await ws.get_services({"type": "#test"})
    assert len(service) == 1

    # we should not get it because api is in another workspace
    ss2 = await api.get_services({"type": "#test"})
    assert len(ss2) == 0

    # let's generate a token for the test-workspace
    ret = await ws.generate_token()
    token = ret["token"]

    # now if we connect directly to the workspace
    # we should be able to get the test-workspace services
    api2 = await connect_to_server(
        {
            "name": "my plugin 2",
            "workspace": "test-workspace",
            "server_url": SERVER_URL,
            "token": token,
        }
    )
    assert api2.config["workspace"] == "test-workspace"
    await api2.export({"foo": "bar"})
    ss3 = await api2.get_services({"type": "#test"})
    assert len(ss3) == 1

    plugin = await api2.get_plugin("my plugin 2")
    assert plugin.foo == "bar"

    await api2.export({"foo2": "bar2"})
    plugin = await api2.get_plugin("my plugin 2")
    assert plugin.foo is None
    assert plugin.foo2 == "bar2"

    with pytest.raises(Exception, match=r".*Plugin my plugin 2 not found.*"):
        await api.get_plugin("my plugin 2")

    with pytest.raises(
        Exception, match=r".*Workspace authorizer is not supported yet.*"
    ):
        await api.create_workspace(
            {
                "name": "my-workspace",
                "owners": ["user1@imjoy.io", "user2@imjoy.io"],
                "allow_list": [],
                "deny_list": [],
                "visibility": "protected",  # or public
                "authorizer": "my-plugin::my_authorizer",
            }
        )

    ws2 = await api.get_workspace("test-workspace")
    assert ws.config == ws2.config

    await ws2.set({"docs": "https://imjoy.io"})
    with pytest.raises(Exception, match=r".*Changing workspace name is not allowed.*"):
        await ws2.set({"name": "new-name"})

    with pytest.raises(Exception):
        await ws2.set({"covers": [], "non-exist-key": 999})
