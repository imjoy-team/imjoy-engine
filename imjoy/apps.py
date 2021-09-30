import asyncio
import os
import uuid
from pathlib import Path
import shutil
import traceback

from starlette.routing import Router
from fastapi import APIRouter, HTTPException, Request
from fastapi.logger import logger
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from playwright.async_api import async_playwright

from imjoy.utils import dotdict

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
        self.browser = None
        self.plugin_parser = None
        self.browser_pages = {}
        self.apps_dir = Path(apps_dir)
        os.makedirs(self.apps_dir, exist_ok=True)
        self.controller_id = str(ServerAppController.instance_counter)
        ServerAppController.instance_counter += 1
        self.port = port
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

        self.router = Router()
        # we mount it under root, then the router will be mounted under /apps
        self.router.mount("/", StaticFiles(directory=self.apps_dir), name="apps")

    def _capture_logs_from_browser_tabs(self, page):
        page.on(
            "targetcreated",
            lambda target: logger.error("Target created: %s", str(target)),
        )
        page.on(
            "console", lambda target: logger.error("Console message: %s", target.text)
        )
        page.on("error", lambda target: logger.error("Error: %s", target.text))
        page.on("pageerror", lambda target: logger.error("Page error: %s", target))

    async def initialize(self):
        """Initialize the app controller."""
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
        await self.deploy(template="imjoy-plugin-parser.html", id="imjoy-plugin-parser")
        self.plugin_parser = await self.launch_as_root("imjoy-plugin-parser", workspace="root")

    async def close(self):
        """Close the app controller."""
        if self.browser:
            await self.browser.close()

    async def get_public_api(self):
        """Get a list of public api."""
        if not self.browser:
            await self.initialize()

        controller = {
            m: getattr(self, m)
            for m in dir(self)
            if not m.startswith("__") and callable(getattr(self, m))
        }
        del controller["router"]
        del controller["get_public_api"]
        controller["_rintf"] = True
        return controller

    async def list_apps(self):
        """List the deployed apps."""
        return os.listdir(self.apps_dir)

    async def deploy(self, source=None, template="imjoy", id=None):
        """Deploy a server app."""
        id = id or str(uuid.uuid4())
        os.makedirs(self.apps_dir / id, exist_ok=True)

        if template == "imjoy":
            if not source:
                raise Exception("Source should be provided for imjoy plugin.")
            config = await self.plugin_parser.parsePluginCode(source)
            try:
                temp = self.jinja_env.get_template(config.type + "-plugin.html")
                source = temp.render(script=config.script)
            except Exception:
                raise Exception(
                    f"Failed to compile the imjoy plugin, error: {traceback.format_exc()}"
                )

        elif template:
            temp = self.jinja_env.get_template(template)
            source = temp.render(script=source)
        elif not source:
            raise Exception("Source or template should be provided.")

        with open(self.apps_dir / id / "index.html", "w") as fil:
            fil.write(source)

        return id

    async def undeploy(self, id):
        """Deploy a server app."""
        if (self.apps_dir / id).exists():
            shutil.rmtree(self.apps_dir / id, ignore_errors=True)
            return {"success": True}
        else:
            return {"success": False, "detail": f"Server app not found: {id}"}

    async def start(self, id: str, workspace: str, token: str = None):
        """Start a server app instance."""
        if self.browser is None:
            raise Exception("The app controller is not ready yet")
        # context = await self.browser.createIncognitoBrowserContext()
        page = await self.browser.new_page()
        self._capture_logs_from_browser_tabs(page)
        # TODO: dispose await context.close()
        name = "app-" + str(uuid.uuid4())
        url = (
            f"{self.server_url}/apps/{id}/index.html?"
            + f"name={name}&workspace={workspace}&server_url={self.server_url}"
            + (f"&token={token}" if token else "")
        )

        fut = asyncio.Future()

        def registered(plugin):
            if plugin.name == name:
                # return the plugin api
                fut.set_result(plugin.config)
                self.event_bus.off("plugin_registered", registered)

        # TODO: Handle timeout
        self.event_bus.on("plugin_registered", registered)
        try:
            response = await page.goto(url)
            # await page.screenshot({"path": "./example.png"})
            assert (
                response.status == 200
            ), f"Failed to start server app instance, status: {response.status}, url: {url}"
            self.browser_pages[name] = page
        except Exception:
            self.event_bus.off("plugin_registered", registered)
            raise

        return await fut

    async def launch_as_root(self, app_name, workspace="root"):
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
            return {"success": True}
        else:
            return {
                "success": False,
                "detail": f"Server app instance not found: {name}",
            }
