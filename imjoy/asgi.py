from imjoy.core import ServiceInfo


class ASGIGateway:
    """ASGI gateway for running web servers in the browser apps."""

    def __init__(self, event_bus, core_interface):
        event_bus.on("service_registered", self.handle_service)

    def handle_service(self, service: ServiceInfo):
        pass
