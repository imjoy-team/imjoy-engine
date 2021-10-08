from pathlib import Path


import pytest

from imjoy_rpc import connect_to_server

from . import SIO_SERVER_URL

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

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
    api = await connect_to_server({"name": "test client", "server_url": SIO_SERVER_URL})
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
