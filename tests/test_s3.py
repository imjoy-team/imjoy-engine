import os
from pathlib import Path
from . import SIO_SERVER_URL
import boto3

import pytest
from imjoy_rpc import connect_to_server
import requests

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


def find_item(items, key, value):
    filtered = [item for item in items if getattr(item, key) == value]
    if len(filtered) == 0:
        return None
    else:
        return filtered[0]


async def test_s3(minio_server, socketio_server):
    api = await connect_to_server({"name": "test client", "server_url": SIO_SERVER_URL})
    workspace = api.config["workspace"]
    token = await api.generate_token()

    async with api.get_s3_controller() as s3controller:
        info = await s3controller.generate_credential()
        s3 = boto3.Session().resource(
            "s3",
            endpoint_url=info["endpoint_url"],
            aws_access_key_id=info["access_key_id"],
            aws_secret_access_key=info["secret_access_key"],
            region_name="EU",
        )
        bucket = s3.Bucket(info["bucket"])

        # The listing should only work with the prefix
        assert find_item(
            list(bucket.objects.filter(Prefix=info["prefix"])),
            "key",
            f"{workspace}/_workspace_config.json",
        )

        with pytest.raises(Exception, match=r".*An error occurred (AccessDenied)*"):
            print(list(bucket.objects.all()))

        obj = s3.Object(info["bucket"], info["prefix"] + "hello.txt")
        with open("/tmp/hello.txt", "w") as f:
            f.write("hello")
        obj.upload_file("/tmp/hello.txt")

        # Should fail if we don't pass the token
        response = requests.get(f"{SIO_SERVER_URL}/{workspace}/files/hello.txt")
        assert not response.ok

        response = requests.get(
            f"{SIO_SERVER_URL}/{workspace}/files/hello.txt",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.ok
        assert response.content == b"hello"

        assert find_item(
            list(bucket.objects.filter(Prefix=info["prefix"])),
            "key",
            f"{workspace}/hello.txt",
        )

        url = await s3controller.generate_presigned_url(
            info["bucket"], info["prefix"] + "hello.txt"
        )
        assert url.startswith("http") and "X-Amz-Algorithm" in url

        # Upload without the prefix should fail
        obj = s3.Object(info["bucket"], "hello.txt")
        with pytest.raises(Exception, match=r".*An error occurred (AccessDenied)*"):
            obj.upload_file("/tmp/hello.txt")
