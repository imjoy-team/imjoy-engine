import asyncio
import os
import uuid
from pathlib import Path
import shutil
import shortuuid
import traceback
import threading
import time

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from fastapi.logger import logger
import requests

from playwright.async_api import async_playwright

from imjoy.utils import dotdict, safe_join
from imjoy.core import StatusEnum

dir_path = os.path.dirname(os.path.realpath(__file__))

from jinja2 import Environment, PackageLoader, select_autoescape


def is_safe_path(basedir, path, follow_symlinks=True):
    """Check if the file path is safe."""
    # resolves symbolic links
    if follow_symlinks:
        matchpath = os.path.realpath(path)
    else:
        matchpath = os.path.abspath(path)
    return basedir == os.path.commonpath((basedir, matchpath))


class ServerAppController:
    """Server App Controller."""

    instance_counter: int = 0

    def __init__(
        self,
        event_bus,
        core_interface,
        port: int,
        in_docker=False,
        apps_dir: str = "./apps",
    ):
        """Initialize the class."""
        self._status: StatusEnum = StatusEnum.not_initialized
        self.browser = None
        self.plugin_parser = None
        self.browser_pages = {}
        self.apps_dir = Path(apps_dir)
        os.makedirs(self.apps_dir, exist_ok=True)
        self.controller_id = str(ServerAppController.instance_counter)
        ServerAppController.instance_counter += 1
        self.port = int(port)
        self.in_docker = in_docker
        self.server_url = f"http://127.0.0.1:{self.port}"
        self.event_bus = event_bus
        self.core_interface = core_interface
        core_interface.register_interface("get_app_controller", self.get_public_api)
        core_interface.register_interface("getAppController", self.get_public_api)
        self.core_api = dotdict(core_interface.get_interface())
        self.jinja_env = Environment(
            loader=PackageLoader("imjoy"), autoescape=select_autoescape()
        )
        self.templates_dir = Path(__file__).parent / "templates"
        self.startup_dir = Path(__file__).parent / "startup_apps"
        router = APIRouter()

        @router.get("/apps/{path:path}")
        def get_app_file(path: str):
            path = safe_join(str(self.apps_dir), path)
            if os.path.exists(path):
                return FileResponse(path)
            else:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "detail": f"File not found: {path}"},
                )

        # The following code is a hacky solution to call self.intialize
        # We need to find a better way to call it
        # If we try to run initialize() in the startup event callback,
        # It give connection error.
        @router.get("/initialize-apps")
        async def initialize_apps():
            await self.initialize()
            return JSONResponse({"status": "OK"})

        def do_initialization():
            while True:
                try:
                    time.sleep(0.2)
                    response = requests.get(self.server_url + "/initialize-apps")
                    if response.ok:
                        logger.info("Server apps intialized.")
                        break
                except requests.exceptions.ConnectionError:
                    pass

        threading.Thread(target=do_initialization, daemon=True).start()

        core_interface.register_router(router)

        def close():
            asyncio.get_running_loop().create_task(self.close())

        event_bus.on("shutdown", close)

    def _capture_logs_from_browser_tabs(self, page):
        def _app_info(message):
            if page._plugin and page._plugin.workspace:
                if page._plugin.workspace._logger:
                    page._plugin.workspace._logger.info(message)
                    return
            logger.info(message)

        def _app_error(message):
            if page._plugin and page._plugin.workspace:
                if page._plugin.workspace._logger:
                    page._plugin.workspace._logger.error(message)
                    return
            logger.error(message)

        page.on(
            "targetcreated",
            lambda target: _app_info(str(target)),
        )
        page.on("console", lambda target: _app_info(target.text))
        page.on("error", lambda target: _app_error(target.text))
        page.on("pageerror", lambda target: _app_error(str(target)))

    async def initialize(self):
        """Initialize the app controller."""
        if self._status == StatusEnum.ready:
            return
        if self._status == StatusEnum.initializing:
            return await self._initialize_future

        self._status = StatusEnum.initializing
        self._initialize_future = asyncio.Future()
        try:
            playwright = await async_playwright().start()
            args = [
                "--site-per-process",
                "--enable-unsafe-webgpu",
                "--use-vulkan",
                "--enable-features=Vulkan",
            ]
            # so it works in the docker image
            if self.in_docker:
                args.append("--no-sandbox")
            self.browser = await playwright.chromium.launch(args=args)

            for app_file in self.startup_dir.iterdir():
                if app_file.suffix != ".html" or app_file.name.startswith("."):
                    continue
                source = (app_file).open().read()
                pid = app_file.stem
                await self.deploy(
                    source, user_id="root", template=None, id=pid, overwrite=True
                )
                if pid == "imjoy-plugin-parser":
                    self.plugin_parser = await self._launch_as_root(
                        pid, workspace="root"
                    )
                else:
                    await self._launch_as_root(pid, workspace="root")
            assert self.plugin_parser is not None, "Failed to load the plugin parser"
            self._status = StatusEnum.ready
            self._initialize_future.set_result(None)
        except Exception as exp:
            self._status = StatusEnum.not_initialized
            logger.exception("Failed to initialize the app controller")
            self._initialize_future.set_exception(exp)

    async def close(self):
        """Close the app controller."""
        logger.info("Closing the browser app controller...")
        if self.browser:
            await self.browser.close()
        logger.info("Browser app controller closed.")

    async def get_public_api(self):
        """Get a list of public api."""
        if self._status != StatusEnum.ready:
            await self.initialize()

        # TODO: check permission for each function
        controller = {
            "deploy": self.deploy,
            "undeploy": self.undeploy,
            "start": self.start,
            "stop": self.stop,
            "list": self.list,
        }

        controller["_rintf"] = True
        return controller

    async def list(self, user_id):
        """List the deployed apps."""
        return [
            user_id + "/" + app_name
            for app_name in os.listdir(self.apps_dir / user_id)
            if not app_name.startswith(".")
        ]

    async def deploy(self, source, user_id, template=None, id=None, overwrite=False):
        """Deploy a server app."""
        if template == "imjoy":
            if not source:
                raise Exception("Source should be provided for imjoy plugin.")
            config = await self.plugin_parser.parsePluginCode(source)
            if id and id != config.name:
                raise Exception(
                    f"You cannot specify a different id ({id}) for ImJoy plugin, it has to be `{config.name}`."
                )
            id = config.name
            try:
                temp = self.jinja_env.get_template(config.type + "-plugin.html")
                source = temp.render(
                    script=config.script, requirements=config.requirements
                )
            except Exception:
                raise Exception(
                    f"Failed to compile the imjoy plugin, error: {traceback.format_exc()}"
                )
        elif template:
            temp = self.jinja_env.get_template(template)
            source = temp.render(script=source)
        elif not source:
            raise Exception("Source or template should be provided.")

        id = id or shortuuid.uuid()
        if (self.apps_dir / user_id / id).exists() and not overwrite:
            raise Exception(
                f"Another app with the same id ({id}) already exists in the user's app space {user_id}."
            )

        os.makedirs(self.apps_dir / user_id / id, exist_ok=True)

        with open(self.apps_dir / user_id / id / "index.html", "w") as fil:
            fil.write(source)

        return user_id + "/" + id

    async def undeploy(self, id):
        """Deploy a server app."""
        if "/" not in id:
            raise Exception(
                f"Invalid app id: {id}, the correct format is `user-id/app-id`"
            )
        if (self.apps_dir / id).exists():
            shutil.rmtree(self.apps_dir / id, ignore_errors=True)
        else:
            raise Exception(f"Server app not found: {id}")

    async def start(self, id: str, workspace: str, token: str = None):
        """Start a server app instance."""
        if self.browser is None:
            raise Exception("The app controller is not ready yet")
        # context = await self.browser.createIncognitoBrowserContext()
        page = await self.browser.new_page()
        page._plugin = None
        self._capture_logs_from_browser_tabs(page)
        # TODO: dispose await context.close()
        name = shortuuid.uuid()
        if "/" not in id:
            id = workspace + "/" + id
        url = (
            f"{self.server_url}/apps/{id}/index.html?"
            + f"name={name}&workspace={workspace}&server_url={self.server_url}"
            + (f"&token={token}" if token else "")
        )

        fut = asyncio.Future()

        def registered(plugin):
            if plugin.name == name:
                # return the plugin api
                page._plugin = plugin
                fut.set_result(plugin.config)
                self.event_bus.off("plugin_registered", registered)

        # TODO: Handle timeout
        self.event_bus.on("plugin_registered", registered)
        try:
            response = await page.goto(url)
            assert (
                response.status == 200
            ), f"Failed to start server app instance, status: {response.status}, url: {url}"
            self.browser_pages[name] = page
        except Exception:
            self.event_bus.off("plugin_registered", registered)
            raise

        return await fut

    async def _launch_as_root(self, app_name, workspace="root"):
        """Launch an app as root user."""
        rws = self.core_interface.get_workspace_as_root(workspace)
        token = rws.generate_token()
        config = await self.start(app_name, workspace, token=token)
        return await self.core_interface.get_plugin_as_root(
            config.name, config.workspace
        )

    async def stop(self, name):
        """Stop a server app instance."""
        if name in self.browser_pages:
            await self.browser_pages[name].close()
        else:
            raise Exception(f"Server app instance not found: {name}")
