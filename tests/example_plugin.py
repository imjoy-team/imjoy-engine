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
        token = await api.generateToken()
        assert token["token"]
        print(f'Generated token: {token["token"]}')

        await api.register_service(
            {"name": "echo service", "echo": lambda x: print("echo: " + str(x))}
        )
        service = await api.get_services({"name": "echo service"})
        await service[0].echo("a message")
        await api.log("initialized")

    async def run(self, ctx):
        """Run the plugin."""
        await api.log("hello world")


api.export(ImJoyPlugin(), config={"name": "test-plugin", "workspace": "123"})
