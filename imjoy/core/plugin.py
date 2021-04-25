"""Provide a plugin interface."""
import asyncio
import logging
import sys
import uuid

from imjoy_rpc.rpc import RPC
from imjoy_rpc.utils import ContextLocal, dotdict

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("dynamic-plugin")
logger.setLevel(logging.INFO)


class DynamicPlugin:
    """Represent a dynamic plugin."""

    # pylint: disable=too-many-instance-attributes

    def __init__(self, config, interface, connection, workspace):
        """Set up instance."""
        self.loop = asyncio.get_event_loop()
        self.config = dotdict(config)
        assert self.config.workspace == workspace.name
        self.workspace = workspace
        self.id = self.config.id or str(uuid.uuid4())  # pylint: disable=invalid-name
        self.name = self.config.name
        self.initializing = False
        self._disconnected = True
        self._log_history = []
        self.connection = connection
        self.authorizer = None
        self.api = None
        self.running = False
        self.terminating = False

        # Note: we don't need to bind the interface
        # to the plugin as we do in the js version
        # We will use context variables `current_plugin`
        # to obtain the current plugin
        self._initial_interface = dotdict(interface)
        self._initial_interface._intf = True
        self._initial_interface.config = self.config.copy()
        if "token" in self._initial_interface.config:
            del self._initial_interface.config["token"]
        self.initialize_if_needed(self.connection, self.config)

        def initialized(data):
            """Handle initialized message."""
            if "error" in data:
                self.error(data["error"])
                logger.error("Plugin failed to initialize: %s", data["error"])
                raise Exception(data["error"])

            asyncio.ensure_future(self._setup_rpc(connection, data["config"]))

        self.connection.on("initialized", initialized)
        self.connection.connect()

    async def _setup_rpc(self, connection, plugin_config):
        """Set up rpc."""
        self.initializing = True
        logger.info("Setting up imjoy-rpc for %s", plugin_config["name"])
        _rpc_context = ContextLocal()
        _rpc_context.api = self._initial_interface
        _rpc_context.default_config = {}
        self._rpc = RPC(connection, _rpc_context)
        self._register_rpc_events()
        self._rpc.set_interface(self._initial_interface)
        await self._send_interface()
        self._allow_execution = plugin_config.get("allow_execution")
        if self._allow_execution:
            await self._execute_plugin()

        self.config.passive = self.config.passive or plugin_config.get("passive")
        if self.config.passive:

            async def func(*args):
                pass

            self.api = dotdict(
                passive=True, _rintf=True, setup=func, on=func, off=func, emit=func
            )
        else:
            self.api = await self._request_remote()

        self.api["config"] = dotdict(
            id=self.id,
            name=self.config.name,
            namespace=self.config.namespace,
            type=self.config.type,
            workspace=self.config.workspace,
            tag=self.config.tag,
        )

        self._disconnected = False
        self.initializing = False
        logger.info(
            "Plugin loaded successfully (workspace=%s, "
            "name=%s, description=%s, api=%s)",
            self.config.workspace,
            self.name,
            self.config.description,
            list(self.api),
        )

    def error(self, *args):
        """Log an error."""
        self._log_history.append({"type": "error", "value": args})
        logger.error("Error in Plugin %s: $%s", self.id, args)

    def log(self, *args):
        """Log."""
        if isinstance(args[0], dict):
            self._log_history.append(args[0])
            logger.info("Plugin $%s:%s", self.id, args[0])
        else:
            msg = " ".join(map(str, args))
            self._log_history.append({"type": "info", "value": msg})
            logger.info("Plugin $%s: $%s", self.id, msg)

    def _set_disconnected(self):
        """Set disconnected state."""
        self._disconnected = True
        self.running = False
        self.initializing = False
        self.terminating = False

    def _register_rpc_events(self):
        """Register rpc events."""

        def disconnected(details):
            """Handle disconnected."""
            if details:
                if "error" in details:
                    self.error(details["message"])
                if "info" in details:
                    self.log(details.info)
            self._set_disconnected()

        self._rpc.on("disconnected", disconnected)

        def remote_ready(_):
            """Handle remote ready."""
            api = self._rpc.get_remote()
            # this make sure if reconnect, setup will be called again
            if "setup" in api:
                asyncio.ensure_future(api.setup())

        self._rpc.on("remoteReady", remote_ready)

        def remote_idle():
            """Handle remote idle."""
            self.running = False

        self._rpc.on("remoteIdle", remote_idle)

        def remote_busy():
            """Handle remote busy."""
            self.running = True

        self._rpc.on("remoteBusy", remote_busy)

    async def _execute_plugin(self):
        """Execute plugin."""
        raise NotImplementedError

    def _send_interface(self):
        """Send the interface."""
        fut = self.loop.create_future()

        def interface_set_as_remote(result):
            """Set interface as remote."""
            fut.set_result(result)

        # pylint: disable=protected-access
        self._rpc._connection.once("interfaceSetAsRemote", interface_set_as_remote)
        self._rpc.send_interface()
        return fut

    def _request_remote(self):
        """Request remote."""
        fut = self.loop.create_future()

        def remote_ready(result):
            """Set remote ready."""
            try:
                fut.set_result(self._rpc.get_remote())
            # TODO: this happens when the the plugin is reconnected
            except asyncio.InvalidStateError:
                pass

        self._rpc.once("remoteReady", remote_ready)
        self._rpc.request_remote()
        return fut

    @staticmethod
    def initialize_if_needed(connection, default_config):
        """Initialize if needed."""

        def imjoy_rpc_ready(data):
            """Handle rpc ready message."""
            config = data["config"] or {}
            forwarding_functions = ["close", "on", "off", "emit"]
            type_ = config.get("type") or default_config.get("type")
            if type_ in ["rpc-window", "window"]:
                forwarding_functions = forwarding_functions + [
                    "resize",
                    "show",
                    "hide",
                    "refresh",
                ]

            credential = None
            if config.get("credential_required"):
                if isinstance(config.credential_fields, list):
                    raise Exception(
                        "Please specify the `config.credential_fields` "
                        "as an array of object."
                    )

                if default_config["credential_handler"]:
                    credential = default_config["credential_handler"](
                        config["credential_fields"]
                    )

                else:
                    credential = {}
                    # for k in config['credential_fields']:
                    #     credential[k.id] = prompt(k.label, k.value)
            connection.emit(
                {
                    "type": "initialize",
                    "config": {
                        "name": default_config.get("name"),
                        "type": default_config.get("type"),
                        "allow_execution": True,
                        "enable_service_worker": True,
                        "forwarding_functions": forwarding_functions,
                        "expose_api_globally": True,
                        "credential": credential,
                    },
                    "peer_id": data["peer_id"],
                }
            )

        connection.once("imjoyRPCReady", imjoy_rpc_ready)

    async def terminate(self, force=False):
        """Terminate."""
        try:
            if self.api and self.api.exit and callable(self.api.exit):
                logger.info(
                    "Terminating plugin %s/%s", self.config.workspace, self.name
                )
                self.api.exit()
        finally:
            logger.info("Plugin %s terminated.", self.config.name)
            self._set_disconnected()
