"""Provide a web server."""
import json
import os
import sys
import threading
import time
from mimetypes import MimeTypes

import aiohttp_cors
from aiohttp import web, streamer

from imjoy import __version__, API_VERSION
from imjoy.utils import kill_process, scandir

ENGINE = "imjoy_engine"


def create_app(engine):
    """Create and return aiohttp webserver app."""
    app = web.Application()
    app[ENGINE] = engine
    setup_router(engine, app)
    setup_cors(app)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


def run_app(engine, app):
    """Run the app."""
    logger = engine.logger
    try:
        web.run_app(app, host=engine.opt.host, port=int(engine.opt.port))
    except OSError as exc:
        if exc.errno in {48}:
            logger.error(
                "Failed to open port %s for ImJoy Engine, "
                "please try to terminate the process which is using that port, "
                "or restart your computer.",
                engine.opt.port,
            )
        else:
            logger.error("Failed to start ImJoy Engine, error: %s", exc)
    except Exception as e:
        logger.error("Failed to start ImJoy Engine, error: %s", e)


def setup_router(engine, app):
    """Set up router."""
    # pylint: disable=unused-argument
    logger = engine.logger
    if engine.opt.serve and os.path.exists(
        os.path.join(engine.opt.web_app_dir, "index.html")
    ):

        async def index(request):
            """Serve the client-side application."""
            with open(
                os.path.join(engine.opt.web_app_dir, "index.html"),
                "r",
                encoding="utf-8",
            ) as fil:
                return web.Response(text=fil.read(), content_type="text/html")

        app.router.add_static(
            "/static", path=str(os.path.join(engine.opt.web_app_dir, "static"))
        )
        # app.router.add_static('/docs/', path=str(os.path.join(web_app_dir, 'docs')))

        async def docs_handler(request):
            """Handle docs."""
            raise web.HTTPFound(location="https://imjoy.io/docs")

        app.router.add_get("/docs", docs_handler, name="docs")
        logger.info(
            "A local version of Imjoy web app is available at %s", engine.opt.base_url
        )
    else:

        async def index(request):
            """Return index."""
            return web.Response(
                body=(
                    '<H1><a href="https://imjoy.io">ImJoy.IO</a></H1><p>'
                    'You can run "python -m imjoy --serve" '
                    "to serve ImJoy web app locally.</p>"
                ),
                content_type="text/html",
            )

    app.router.add_get("/", index)
    app.router.add_get("/about", about)


def setup_cors(app):
    """Set up cors."""
    cors = aiohttp_cors.setup(
        app,
        defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True, expose_headers="*", allow_headers="*"
            )
        },
    )

    # app.router.add_post('/upload/{urlid}', upload_file)
    cors.add(app.router.add_route("POST", "/upload/{urlid}", upload_file))
    cors.add(app.router.add_get("/file/{urlid}/{name:.+}", download_file))
    cors.add(app.router.add_get("/file/{urlid}@{password}/{name:.+}", download_file))


@streamer
async def file_sender(writer, file_path=None):
    """Read a large file chunk by chunk and send it through HTTP.

    Do not read the chunks into memory.
    """
    with open(file_path, "rb") as f:
        chunk = f.read(2 ** 16)
        while chunk:
            await writer.write(chunk)
            chunk = f.read(2 ** 16)


async def about(request):
    """Return about text."""
    engine = request.app[ENGINE]
    params = request.rel_url.query
    if "token" in params:
        body = (
            "<H1>ImJoy Plugin Engine connection token: </H1><H3>"
            + params["token"]
            + "</H3><br>"
        )
        body += (
            "<p>You have to specify this token when you connect the ImJoy web app "
            "to this Plugin Engine. The token will be saved and automatically reused "
            "when you launch the App again. </p>"
        )
        body += "<br>"
        body += (
            "<p>Alternatively, you can launch a new ImJoy instance "
            "with the link below: </p>"
        )

        if engine.opt.serve:
            body += (
                '<p><a href="'
                + engine.opt.base_url
                + "/#/app?token="
                + params["token"]
                + '">Open ImJoy App</a></p>'
            )
        else:
            body += (
                '<p><a href="https://imjoy.io/#/app?token='
                + params["token"]
                + '">Open ImJoy App</a></p>'
            )

    else:
        if engine.opt.serve:
            body = (
                '<H1><a href="'
                + engine.opt.base_url
                + '/#/app">Open ImJoy App</a></H1>'
            )
        else:
            body = '<H1><a href="https://imjoy.io/#/app">Open ImJoy App</a></H1>'
    body += (
        "<H2>Please use the latest Google Chrome browser to run the ImJoy App."
        '</H2><a href="https://www.google.com/chrome/">Download Chrome</a><p>'
        "Note: Safari is not supported "
        "due to its restrictions on connecting to localhost. "
        "Currently, only FireFox and Chrome (preferred) are supported.</p>"
    )
    return web.Response(body=body, content_type="text/html")


async def upload_file(request):
    """Upload file."""
    engine = request.app[ENGINE]
    logger = engine.logger
    request_upload_files = engine.store.request_upload_files
    urlid = request.match_info["urlid"]  # Could be a HUGE file
    if urlid not in request_upload_files:
        raise web.HTTPForbidden(text="Invalid URL")

    file_info = request_upload_files[urlid]
    try:
        reader = await request.multipart()
        field = None
        while True:
            part = await reader.next()
            logger.debug("Reading part %s of %s", part, part.filename)
            if part.filename is None:
                continue
            field = part
            break
        filename = field.filename
        # You cannot rely on Content-Length if transfer is chunked.
        size = 0
        if "path" in file_info:
            path = file_info["path"]
        else:
            path = filename

        if "dir" in file_info:
            path = os.path.join(file_info["dir"], path)
        else:
            path = os.path.join(engine.opt.workspace_dir, file_info["workspace"], path)

        if os.path.exists(path) and not file_info.get("overwrite", False):
            return web.Response(body="File {} already exists.".format(path), status=404)

        logger.info("Uploading file to %s", path)
        directory, _ = os.path.split(path)
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(path, "wb") as fil:
            while True:
                chunk = await field.read_chunk()  # 8192 bytes by default.
                if not chunk:
                    break
                size += len(chunk)
                fil.write(chunk)
        file_info["size"] = size
        file_info["path"] = path
        logger.info("File saved to %s (size %d)", path, size)
        return web.json_response(file_info)

    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to upload file, error: %s", exc)
        return web.Response(body=f"Failed to upload, error: {exc}", status=404)


async def download_file(request):  # pylint: disable=too-many-return-statements
    """Download file."""
    engine = request.app[ENGINE]
    generated_urls = engine.store.generated_urls
    urlid = request.match_info["urlid"]  # Could be a HUGE file
    name = request.match_info["name"]
    if urlid not in generated_urls:
        raise web.HTTPForbidden(text="Invalid URL")
    file_info = generated_urls[urlid]
    if file_info.get("password", False):
        password = request.match_info.get("password")
        if password != file_info["password"]:
            raise web.HTTPForbidden(text="Incorrect password for accessing this file.")
    headers = file_info.get("headers")
    default_headers = {}
    if file_info["type"] == "dir":
        dirname = os.path.dirname(name)
        # list the folder
        if dirname == "" or dirname is None:
            if name != file_info["name"]:
                raise web.HTTPForbidden(text="File name does not match server record!")
            folder_path = file_info["path"]
            if not os.path.exists(folder_path):
                return web.Response(
                    body="Folder <{folder_path}> does not exist".format(
                        folder_path=folder_path
                    ),
                    status=404,
                )

            file_list = scandir(folder_path, "file", False)
            headers = headers or {
                "Content-Disposition": 'inline; filename="{filename}"'.format(
                    filename=name
                )
            }
            headers.update(default_headers)
            return web.json_response(file_list, headers=headers)
        # list the subfolder or get a file in the folder

        file_path = os.path.join(file_info["path"], os.sep.join(name.split("/")[1:]))
        if not os.path.exists(file_path):
            return web.Response(
                body="File <{file_path}> does not exist".format(file_path=file_path),
                status=404,
            )
        if os.path.isdir(file_path):
            _, folder_name = os.path.split(file_path)
            file_list = scandir(file_path, "file", False)
            headers = headers or {
                "Content-Disposition": 'inline; filename="{filename}"'.format(
                    filename=folder_name
                )
            }
            headers.update(default_headers)
            return web.json_response(file_list, headers=headers)

        _, file_name = os.path.split(file_path)
        mime_type = MimeTypes().guess_type(file_name)[0] or "application/octet-stream"
        file_size = os.path.getsize(file_path)
        headers = headers or {
            "Content-Disposition": 'inline; filename="{filename}"'.format(
                filename=file_name
            ),
            "Content-Type": mime_type,
            "Content-Length": str(file_size),
        }
        headers.update(default_headers)
        return web.Response(body=file_sender(file_path=file_path), headers=headers)
    if file_info["type"] == "file":
        file_path = file_info["path"]
        if name != file_info["name"]:
            raise web.HTTPForbidden(text="File name does not match server record!")
        file_name = file_info["name"]
        if not os.path.exists(file_path):
            return web.Response(
                body="File <{file_name}> does not exist".format(file_name=file_path),
                status=404,
            )
        mime_type = MimeTypes().guess_type(file_name)[0] or "application/octet-stream"
        file_size = os.path.getsize(file_path)
        headers = headers or {
            "Content-Disposition": 'inline; filename="{filename}"'.format(
                filename=file_name
            ),
            "Content-Type": mime_type,
            "Content-Length": str(file_size),
        }
        headers.update(default_headers)
        return web.Response(body=file_sender(file_path=file_path), headers=headers)

    raise web.HTTPForbidden(text="Unsupported file type: " + file_info["type"])


async def on_startup(app):
    """Run on server start."""
    engine = app[ENGINE]
    logger = engine.logger
    logger.info(
        "ImJoy Python Plugin Engine (version %s, api_version %s)",
        __version__,
        API_VERSION,
    )

    if engine.opt.serve:
        logger.info(
            "You can access your local ImJoy web app through %s , imjoy!",
            engine.opt.base_url,
        )
    else:
        logger.info(
            "Please go to https://imjoy.io/#/app "
            "with your web browser (Chrome or FireFox)"
        )
    print("========>> Connection token: {} <<========".format(engine.opt.token))
    sys.stdout.flush()


async def on_shutdown(app):
    """Run on server shut down."""
    engine = app[ENGINE]
    logger = engine.logger
    logger.info("Shutting down the plugin engine")
    stopped = threading.Event()

    def loop():  # executed in another thread
        for i in range(5):
            logger.info("Exiting: %s", 5 - i)
            time.sleep(0.5)
            if stopped.is_set():
                break
        logger.debug("Plugin engine is killed")
        kill_process(os.getpid(), logger)

    loop_thread = threading.Thread(target=loop)
    loop_thread.daemon = True  # stop if the program exits
    loop_thread.start()

    # stopped.set()  # TODO: Should we uncomment this?
    logger.info("Plugin engine exited")
    pid_file = os.path.join(engine.opt.workspace_dir, ".pid")
    try:
        os.remove(pid_file)
    except Exception:  # pylint: disable=broad-except
        logger.info("Failed to remove the pid file")
