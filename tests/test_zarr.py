from . import SIO_SERVER_URL, find_item
import pytest
from imjoy_rpc import connect_to_server
from pathlib import Path
import zarr
import fsspec

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_zarr(minio_server, socketio_server):
    api = await connect_to_server(
        {"name": "test client zarr", "server_url": SIO_SERVER_URL}
    )
    workspace = api.config["workspace"]
    token = await api.generate_token()

    async with api.get_s3_controller() as s3controller:
        info = await s3controller.generate_credential()
        s3fs = fsspec.filesystem(
            "s3",
            key=info["access_key_id"],
            secret=info["secret_access_key"],
            client_kwargs={"endpoint_url": info["endpoint_url"], "region_name": "EU"},
        )
        store_dir = f'{info["bucket"]}/{info["prefix"]}zarr-demo/store'
        store = s3fs.get_mapper(root=store_dir, check=False, create=False)
        # cache = zarr.LRUStoreCache(store, max_size=2 ** 28)
        # root = zarr.group(store=cache)
        z = zarr.zeros((10000, 10000), chunks=(1000, 1000), dtype="f8", store=store)
        z[0:20, 1:10] = 100
        assert z[10, 2] == 100
        files = s3fs.listdir(store_dir)
        assert find_item(files, "Key", f"{store_dir}/.zarray")

        async with api.get_app_controller() as controller:
            source = (
                (Path(__file__).parent / "testZarrWebWorkerPlugin.imjoy.html")
                .open()
                .read()
            )
            pid = await controller.deploy(
                source, "public", template="imjoy", overwrite=True
            )
            assert pid == "public/ZarrWebWorkerPlugin"
            apps = await controller.list("public")
            assert pid in apps
            config = await controller.start(pid, workspace, token)
            plugin = await api.get_plugin(config.name)
            assert "test_zarr" in plugin
            result = await plugin.test_zarr([4, 10])
            assert result == [2, 10]

            # assert (
            #     await plugin.test_read_zarr(f'{SIO_SERVER_URL}/files/{info["prefix"]}', "/zarr-demo/store")
            #     == True
            # )
            await controller.stop(config.name)
