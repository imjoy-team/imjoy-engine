import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.logger import logger

from fastapi.templating import Jinja2Templates

os.environ["PYPPETEER_CHROMIUM_REVISION"] = "901912"

from pyppeteer import launch, defaultArgs  # noqa: E402


dir_path = os.path.dirname(os.path.realpath(__file__))

templates = Jinja2Templates(directory=os.path.join(dir_path, "templates"))


class ServerAppController:
    """Server App Controller."""

    instance_counter: int = 0

    def __init__(self, port: int, in_docker=False, app_dir: str = "./apps"):
        """Initialize the class."""
        self.browser = None
        self.browser_pages = {}
        self.app_dir = Path(app_dir)
        self.controller_id = str(ServerAppController.instance_counter)
        ServerAppController.instance_counter += 1
        self.port = port
        self.in_docker = in_docker
        self.server_url = f"http://127.0.0.1:{self.port}"
        self.router = APIRouter()

        @self.router.get(
            "/apps/" + self.controller_id + "/{id}", response_class=HTMLResponse
        )
        async def serve_app(request: Request, id: str) -> templates.TemplateResponse:
            """Serve ImJoy server app file."""
            if not (self.app_dir / id).exists():
                raise HTTPException(
                    status_code=404, detail=f"Server app file not found: {id}"
                )

            script = (self.app_dir / id).open().read()
            return templates.TemplateResponse(
                "window_plugin.html",
                {
                    "request": request,
                    "server_url": self.server_url,
                    "script": script,
                },
            )

    def capture_logs_from_browser_tabs(self, page):
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
        args = defaultArgs()
        args.append("--site-per-process")
        # so it works in the docker image
        if self.in_docker:
            args.append("--no-sandbox")
        executablePath = None  # "/usr/bin/chromium"
        self.browser = await launch(args=args, executablePath=executablePath)
        logger.info("Chrome version: %s", await self.browser.version())

    async def close(self):
        """Close the app controller."""
        await self.browser.close()

    def get_public_api(self):
        """Get a list of public api."""
        controller = {
            m: getattr(self, m)
            for m in dir(self)
            if not m.startswith("__") and callable(getattr(self, m))
        }
        del controller["router"]
        del controller["get_public_api"]
        controller["_rintf"] = True
        return controller

    def list_apps(self):
        """List the deployed apps."""
        return os.listdir(self.app_dir)

    def deploy(self, src):
        """Deploy a server app."""
        id = str(uuid.uuid4())
        os.makedirs(self.app_dir, exist_ok=True)
        with open(self.app_dir / id, "w") as fil:
            fil.write(src)
        return id

    def undeploy(self, id):
        """Deploy a server app."""
        if (self.app_dir / id).exists():
            (self.app_dir / id).unlink()
            return {"success": True}
        else:
            return {"success": False, "detail": f"Server app not found: {id}"}

    async def start(self, id: str, workspace: str, token: str = None):
        """Start a server app instance."""
        if self.browser is None:
            await self.initialize()
        # context = await self.browser.createIncognitoBrowserContext()
        page = await self.browser.newPage()
        await page.setJavaScriptEnabled(True)
        self.capture_logs_from_browser_tabs(page)
        # TODO: dispose await context.close()
        name = "app-" + str(uuid.uuid4())
        url = (
            f"{self.server_url}/apps/{self.controller_id}/{id}?"
            + f"name={name}&workspace={workspace}"
            + (f"&token={token}" if token else "")
        )
        response = await page.goto(url)
        await page.screenshot({"path": "./example.png"})
        assert (
            response.status == 200
        ), f"Failed to start server app instance, status: {response.status}"
        self.browser_pages[name] = page

        return name

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
