from . import SIO_SERVER_URL
import requests
import msgpack

import pytest
from imjoy_rpc import connect_to_server

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

TEST_APP_CODE = """
api.export({
    async setup(){
        await api.register_service(
            {
                "_rintf": true,
                "name": "test_service",
                "type": "#test",
                echo( data ){
                    console.log("Echo: ", data)
                    return data
                }
            }
        )
    }
})
"""


def find_item(items, key, value):
    filtered = [item for item in items if item[key] == value]
    if len(filtered) == 0:
        return None
    else:
        return filtered[0]


async def test_http_proxy(minio_server, socketio_server):
    # SIO_SERVER_URL = "http://127.0.0.1:9527"
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
    assert "setup" in plugin
    await plugin.setup()

    service_ws = plugin.config.workspace
    service = await api.get_service(service_ws + "/test_service")
    assert await service.echo("233d") == "233d"

    response = requests.get(f"{SIO_SERVER_URL}/services")
    assert response.ok
    assert find_item(response.json(), "name", "test_service")

    response = requests.get(f"{SIO_SERVER_URL}/services/{service_ws}")
    assert response.ok
    assert find_item(response.json(), "name", "test_service")

    response = requests.get(f"{SIO_SERVER_URL}/services/{service_ws}/test_service")
    assert response.ok
    service_info = response.json()
    assert service_info["name"] == "test_service"

    response = requests.get(
        f"{SIO_SERVER_URL}/services/{service_ws}/test_service/echo?v=33"
    )
    assert response.ok, response.json()["detail"]
    service_info = response.json()
    assert service_info["v"] == 33

    response = requests.post(
        f"{SIO_SERVER_URL}/services/{service_ws}/test_service/echo",
        data=msgpack.dumps({"data": 123}),
        headers={"Content-type": "application/msgpack"},
    )
    assert response.ok
    result = msgpack.loads(response.content)
    assert result["data"] == 123
