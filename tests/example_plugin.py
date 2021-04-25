"""Provide an example plugin."""
from imjoy_rpc import api

# pylint: disable=no-self-use


class ImJoyPlugin:
    """Represent an ImJoy plugin."""

    def authorizer(self, user_info, context):
        """Authorize users."""
        return True

    async def setup(self):
        """Set up the plugin."""
        token = await api.generateToken({})
        assert token["success"]
        print(f'Generated token: {token["result"]}')

        await api.registerService(
            {"name": "echo service", "echo": lambda x: print("echo: " + str(x))}
        )
        service = await api.getService("echo service")
        await service.echo("a message")
        await api.log("initialized")

    async def run(self, ctx):
        """Run the plugin."""
        await api.log("hello world")


api.export(ImJoyPlugin(), config={"name": "test-plugin", "workspace": "123"})
