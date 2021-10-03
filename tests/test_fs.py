import os
from pathlib import Path
from . import SIO_SERVER_URL

import pytest
from imjoy_rpc import connect_to_server

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


TEST_FS_CODE = """
api.export({
    async setup(){
        await api.log("initialized")
    },
    async readFile(path){
        const fs = await api.get_file_system()
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


async def test_fs(socketio_server):
    api = await connect_to_server({"name": "test client", "server_url": SIO_SERVER_URL})
    workspace = api.config["workspace"]
    token = await api.generate_token()

    async with api.get_file_system() as fs:
        with pytest.raises(Exception, match=r".*Illegal file path*"):
            await fs.listdir("../")
        with pytest.raises(Exception, match=r".*Illegal file path*"):
            await fs.listdir("/")
        with pytest.raises(Exception, match=r".*Illegal file path*"):
            await fs.listdir("/data")

        test_file_path = os.path.join("test.txt")

        with pytest.raises(
            Exception,
            match=r".*Methods for local file mainipulation are not available.*",
        ):
            await fs.put("one", test_file_path)

        # test write file
        async with fs.open(test_file_path, "w") as file:
            await file.write("hello")

        mapper = await fs.get_mapper("mydata")
        assert callable(mapper.getitems)

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

            await fs.makedirs("dir", exist_ok=True)
            fn2 = os.path.join("dir", "two")
            async with fs.open(fn2, "wb") as fil:
                await fil.write(b"two")
            await fs.move("dir", "dir2", recursive=True)
            assert await fs.exists("dir2")

            try:
                await controller.undeploy("public/WebPythonFSPlugin")
            except Exception:
                pass
            source = (
                (Path(__file__).parent / "testWebPythonFSPlugin.imjoy.html")
                .open()
                .read()
            )
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
