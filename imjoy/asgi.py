from imjoy.core import ServiceInfo
from starlette.types import Receive, Scope, Send


class RemoteASGIApp:
    def __init__(self, service: ServiceInfo) -> None:
        self.service = service
        assert self.service.serve is not None, "No serve function defined"
        # super().__init__(**kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope = {
            k: scope[k]
            for k in scope
            if isinstance(scope[k], (str, int, float, bool, tuple, list, dict, bytes))
        }
        interface = {
            "scope": scope,
            "receive": receive,
            "send": send,
            "_rintf": True,
        }
        await self.service.serve(interface)
        # clear the object store to avoid gabage collection issue
        # this means the service plugin cannot have extra interface registered
        self.service._provider.dispose_object(interface)


class ASGIGateway:
    """ASGI gateway for running web servers in the browser apps."""

    def __init__(self, event_bus, core_interface):
        self.core_interface = core_interface
        event_bus.on("service_registered", self.register_wsgi_service)

    def register_wsgi_service(self, service):
        if service.type == "ASGI":
            subpath = f'/{service.config["workspace"]}/app/{service.name}'
            self.core_interface.mount_app(subpath, RemoteASGIApp(service), priority=-1)
