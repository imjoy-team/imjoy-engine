"""Test the imjoy engine server."""
import os
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import shutil

import pytest
import requests
from imjoy_rpc import connect_to_server
from requests import RequestException

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

    # test workspace is an exception, so it can pass directly
    ws = await connect_to_server(
        {"name": "my plugin", "workspace": "public", "server_url": SERVER_URL}
    )
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
        assert "Generated token: " in output and "@imjoy@" in output
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
        assert "Generated token: " in output and "@imjoy@" in output
        assert "echo: a message" in output


async def test_plugin_runner_workspace(socketio_server):
    """Test the plugin runner with workspace."""
    api = await connect_to_server(
        {"name": "my second plugin", "server_url": SERVER_URL}
    )
    token = await api.generate_token()
    assert "@imjoy@" in token

    # The following code without passing the token should fail
    # Here we assert the output message contains "permission denied"
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.runner",
            f"--server-url=http://127.0.0.1:{PORT}",
            f"--workspace={api.config['workspace']}",
            # f"--token={token}",
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
            f"--token={token}",
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
        assert "Generated token: " in output and "@imjoy@" in output
        assert "echo: a message" in output


async def test_workspace(socketio_server):
    """Test the plugin runner."""
    api = await connect_to_server({"name": "my plugin", "server_url": SERVER_URL})
    with pytest.raises(
        Exception, match=r".*Scopes must be empty or contains only the workspace name*"
    ):
        await api.generate_token({"scopes": ["test-workspace"]})
    token = await api.generate_token()
    assert "@imjoy@" in token

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
    token = await ws.generate_token()

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


TEST_APP_CODE = """
api.log('awesome!connected!');

api.export({
    async setup(){
        await api.log("initialized")
    },
    async check_webgpu(){
        if ("gpu" in navigator) {
            // WebGPU is supported! 🎉
            return true
        }
        else return false
    },
    async execute(a, b){
        return a + b
    }
})
"""


async def test_server_apps(socketio_server):
    """Test the server apps."""
    api = await connect_to_server({"name": "test client", "server_url": SERVER_URL})
    workspace = api.config["workspace"]
    token = await api.generate_token()

    # Test plugin with custom template
    controller = await api.get_app_controller()
    app_id = await controller.deploy(
        TEST_APP_CODE, "public", "window-plugin.html", "test-window-plugin", True
    )
    apps = await controller.list("public")
    assert app_id in apps
    config = await controller.start(app_id, workspace, token)
    plugin = await api.get_plugin(config.name)
    assert "execute" in plugin
    result = await plugin.execute(2, 4)
    assert result == 6
    webgpu_available = await plugin.check_webgpu()
    assert webgpu_available is True
    await controller.stop(config.name)

    config = await controller.start(app_id, workspace, token)
    plugin = await api.get_plugin(config.name)
    assert "execute" in plugin
    result = await plugin.execute(2, 4)
    assert result == 6
    webgpu_available = await plugin.check_webgpu()
    assert webgpu_available is True
    await controller.stop(config.name)

    # Test window plugin
    try:
        await controller.undeploy("public/Test Window Plugin")
    except Exception:
        pass
    source = (Path(__file__).parent / "testWindowPlugin1.imjoy.html").open().read()
    pid = await controller.deploy(source, user_id="public", template="imjoy")
    assert pid == "public/Test Window Plugin"
    apps = await controller.list("public")
    assert pid in apps
    config = await controller.start(pid, workspace, token)
    plugin = await api.get_plugin(config.name)
    assert "add2" in plugin
    result = await plugin.add2(4)
    assert result == 6
    await controller.stop(config.name)

    try:
        await controller.undeploy("public/WebPythonPlugin")
    except Exception:
        pass
    source = (Path(__file__).parent / "testWebPythonPlugin.imjoy.html").open().read()
    pid = await controller.deploy(source, "public", "imjoy")
    assert pid == "public/WebPythonPlugin"
    apps = await controller.list("public")
    assert pid in apps
    config = await controller.start(pid, workspace, token)
    plugin = await api.get_plugin(config.name)
    assert "add2" in plugin
    result = await plugin.add2(4)
    assert result == 6
    await controller.stop(config.name)

    try:
        await controller.undeploy("public/WebWorkerPlugin")
    except Exception:
        pass
    source = (Path(__file__).parent / "testWebWorkerPlugin.imjoy.html").open().read()
    pid = await controller.deploy(source, "public", "imjoy")
    assert pid == "public/WebWorkerPlugin"
    apps = await controller.list("public")
    assert pid in apps
    config = await controller.start(pid, workspace, token)
    plugin = await api.get_plugin(config.name)
    assert "add2" in plugin
    result = await plugin.add2(4)
    assert result == 6
    await controller.stop(config.name)


TEST_FS_CODE = """
api.export({
    async setup(){
        await api.log("initialized")
    },
    async readFile(path){
        const fs = await api.mount_fs('file', {})
        const file = await fs.open(path, "r")
        try{
            const content = await file.read()
            return content
        }
        catch(e){
            throw e
        }
        finally{
            await file.close()
            await api.disposeObject(file)
        }        
    }
})
"""


@pytest.fixture(name="fs_tmpdir")
def make_fs_tmpdir():
    """Make tempoarary directory for testing fs"""
    tmpdir = tempfile.mkdtemp()
    fn = os.path.join(tmpdir, "one")
    open(fn, "wb").write(b"one")
    os.makedirs(os.path.join(tmpdir, "dir"), exist_ok=True)
    fn2 = os.path.join(tmpdir, "dir", "two")
    open(fn2, "wb").write(b"two")
    yield tmpdir
    shutil.rmtree(tmpdir)


async def test_fs(socketio_server, fs_tmpdir):
    api = await connect_to_server({"name": "test client", "server_url": SERVER_URL})
    workspace = api.config["workspace"]
    token = await api.generate_token()

    async with api.mount_fs("file", {}) as fs:
        assert len(await fs.listdir("/data")) > 0

        fn = os.path.join(fs_tmpdir, "one")
        test_file_path = os.path.join(fs_tmpdir, "test.txt")

        with pytest.raises(
            Exception, match=r".*Methods related to local file path are not available.*"
        ):
            await fs.put(fn, test_file_path)

        # test write file
        async with fs.open(test_file_path, "w") as file:
            await file.write("hello")

        assert open(test_file_path, "rb").read() == b"hello"

        # test read file
        file = await fs.open(test_file_path, "rb")
        assert await file.read() == b"hello"
        await file.close()
        await api.dispose_object(file)
        # test read file from remote
        async with api.get_app_controller() as controller:
            # controller = await api.get_app_controller()
            pid = await controller.deploy(
                TEST_FS_CODE, "public", "window-plugin.html", "test-fs-plugin", True
            )
            assert pid == "public/test-fs-plugin"
            apps = await controller.list("public")
            assert pid in apps
            config = await controller.start(pid, workspace, token)
            plugin = await api.get_plugin(config.name)
            assert "readFile" in plugin
            result = await plugin.readFile(test_file_path)
            assert result == "hello"
            await controller.stop(config.name)

            await fs.move(os.path.join(fs_tmpdir, "dir"), os.path.join(fs_tmpdir, "dir2"), recursive=True)
            assert fs.exists(os.path.join(fs_tmpdir, "dir2"))

            try:
                await controller.undeploy("public/WebPythonFSPlugin")
            except Exception:
                pass
            source = (Path(__file__).parent / "testWebPythonFSPlugin.imjoy.html").open().read()
            pid = await controller.deploy(source, "public", "imjoy")
            assert pid == "public/WebPythonFSPlugin"
            apps = await controller.list("public")
            assert pid in apps
            config = await controller.start(pid, workspace, token)
            plugin = await api.get_plugin(config.name)
            assert "read_file" in plugin
            result = await plugin.read_file(test_file_path)
            assert result == b"hello"
            await controller.stop(config.name)