import os
from pathlib import Path
from . import SIO_SERVER_URL
import aioboto3

import pytest
from imjoy_rpc import connect_to_server

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_s3(minio_server, socketio_server):
    api = await connect_to_server({"name": "test client", "server_url": SIO_SERVER_URL})
    # workspace = api.config["workspace"]
    # token = await api.generate_token()

    async with api.get_s3_controller() as s3controller:
        info = await s3controller.get_info()
        async with aioboto3.Session().resource(
            "s3",
            endpoint_url=info["endpoint_url"],
            aws_access_key_id=info["access_key_id"],
            aws_secret_access_key=info["secret_access_key"],
            region_name="EU",
        ) as s3:
            obj = s3.Object(info["bucket"], info["prefix"] + "/hello.txt")
            with open("/tmp/hello.txt", "w") as f:
                f.write("hello")
            await obj.upload_file("/tmp/hello.txt")

        url = await s3controller.generate_presigned_url("hello.txt")
        assert url
