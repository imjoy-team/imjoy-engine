"""Test ASGI services."""
from pathlib import Path

import pytest
import requests
from imjoy_rpc import connect_to_server

from . import SIO_SERVER_URL

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_asgi(socketio_server):
    """Test the ASGI gateway apps."""
    api = await connect_to_server({"name": "test client", "server_url": SIO_SERVER_URL})
    workspace = api.config["workspace"]
    token = await api.generate_token()

    # Test plugin with custom template
    controller = await api.get_app_controller()

    source = (
        (Path(__file__).parent / "testASGIWebPythonPlugin.imjoy.html")
        .open(encoding="utf-8")
        .read()
    )
    pid = await controller.deploy(source, "public", "imjoy", overwrite=True)
    assert pid == "public/ASGIWebPythonPlugin"
    apps = await controller.list("public")
    assert pid in apps
    config = await controller.start(pid, workspace, token)
    plugin = await api.get_plugin(config.name)
    await plugin.setup()
    service = await api.get_service(config.workspace + "/hello-fastapi")
    assert "serve" in service

    response = requests.get(f"{SIO_SERVER_URL}/{workspace}/app/hello-fastapi/")
    assert response.ok
    assert response.json()["message"] == "Hello World"

    service = await api.get_service(config.workspace + "/hello-flask")
    assert "serve" in service
    response = requests.get(f"{SIO_SERVER_URL}/{workspace}/app/hello-flask/")
    assert response.ok
    assert response.text == "<p>Hello, World!</p>"

    await controller.stop(config.name)
