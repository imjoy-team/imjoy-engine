from imjoy_rpc import api
import asyncio


class ImJoyPlugin:
    def authorizer(self, user_info, context):
        return True

    async def setup(self):
        # plugin id: test namespace/my awesome plugin
        # imjoy = await api.getPlugin("ImJoy")

        # viewer = await imjoy.createWindow(src="https://kaibu.org")
        # await viewer.view_image("https://images.proteinatlas.org/115/672_E2_1_blue_red_green.jpg")
        # await viewer.add_shapes([], name="annotation")
        await api.registerService(
            {"name": "echo service", "echo": lambda x: print("echo: " + str(x))}
        )
        s = await api.getService("echo service")
        await s.echo("a message")
        await api.log("initialized")

    async def run(self, ctx):
        await api.log("hello world.")


api.export(ImJoyPlugin(), config={"name": "test-plugin", "namespace": "123"})
