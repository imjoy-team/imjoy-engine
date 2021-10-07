from . import SIO_SERVER_URL
import requests
import msgpack

from pathlib import Path
import pytest
from imjoy_rpc import connect_to_server

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


def find_item(items, key, value):
    filtered = [item for item in items if item[key] == value]
    if len(filtered) == 0:
        return None
    else:
        return filtered[0]


async def test_http_proxy(minio_server, socketio_server):
    api = await connect_to_server({"name": "test client", "server_url": SIO_SERVER_URL})
    workspace = api.config["workspace"]
    token = await api.generate_token()

    # Test plugin with custom template
    controller = await api.get_app_controller()

    source = (
        (Path(__file__).parent / "testASGIWebPythonPlugin.imjoy.html").open().read()
    )
    pid = await controller.deploy(source, "public", "imjoy", overwrite=True)
    assert pid == "public/ASGIWebPythonPlugin"
    apps = await controller.list("public")
    assert pid in apps
    config = await controller.start(pid, workspace, token)
    plugin = await api.get_plugin(config.name)
    assert "serve" in plugin

    response = requests.get(f"{SIO_SERVER_URL}/{workspace}/app/{config.name}")
    assert response.ok
    assert response.json()["message"] == "Hello World"

    await controller.stop(config.name)
