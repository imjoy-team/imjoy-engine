import logging
import sys

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("imjoy-core")
logger.setLevel(logging.INFO)


class Services:
    def __init__(self, plugins=None, imjoy_api=None):
        self._services = []
        self.imjoy_api = imjoy_api
        self.plugins = plugins

    def register_service(self, plugin, service):
        service.provider = plugin.name
        service.providerId = plugin.id
        self._services.append(service)

    def get_plugin(self, plugin, name):
        ws_plugins = self.plugins.get(plugin.workspace)
        if ws_plugins:
            return ws_plugins[name].api

    def generate_presigned_token(self, plugin):
        pass

    def get_service(self, plugin, name):
        return next(
            service for service in self._services if service.get("name") == name
        )

    def log(self, plugin, msg):
        logger.info(f"{plugin.name}: {msg}")

    def error(self, plugin, msg):
        logger.error(f"{plugin.name}: {msg}")

    def alert(self, plugin, msg):
        raise NotImplementedError

    def confirm(self, plugin, msg):
        raise NotImplementedError

    def prompt(self, plugin, *arg):
        raise NotImplementedError

    def get_interface(self):
        return {
            "log": self.log,
            "error": self.error,
            "alert": self.alert,
            "confirm": self.confirm,
            "prompt": self.prompt,
            "registerService": self.register_service,
            "getService": self.get_service,
            "utils": {},
            "getPlugin": self.get_plugin,
        }

    def removePluginServices(self, plugin):
        for service in self._services.copy():
            if service.providerId == plugin.id:
                self._services.remove(service)
