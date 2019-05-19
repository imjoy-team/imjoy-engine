"""Provide a web server."""
import os
import sys
import threading
import time
import traceback
from mimetypes import MimeTypes

import aiohttp_cors
from aiohttp import web

from imjoy.const import ENG, __version__
from imjoy.helper import killProcess, scandir
from imjoy.util.aiohttp import file_sender


def setup_app(eng, app):
    """Set up app."""
    setup_router(eng, app)
    setup_cors(app)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)


def run_app(eng, app):
    """Run the app."""
    try:
        web.run_app(app, host=eng.opt.host, port=int(eng.opt.port))
    except OSError as exc:
        if exc.errno in {48}:
            print(
                "ERROR: Failed to open port {}, "
                "please try to terminate the process which is using that port, "
                "or restart your computer.".format(eng.opt.port)
            )


def setup_router(eng, app):
    """Set up router."""
    # pylint: disable=unused-argument
    if eng.opt.serve and os.path.exists(
        os.path.join(eng.opt.WEB_APP_DIR, "index.html")
    ):

        async def index(request):
            """Serve the client-side application."""
            with open(
                os.path.join(eng.opt.WEB_APP_DIR, "index.html"), "r", encoding="utf-8"
            ) as fil:
                return web.Response(text=fil.read(), content_type="text/html")

        app.router.add_static(
            "/static", path=str(os.path.join(eng.opt.WEB_APP_DIR, "static"))
        )
        # app.router.add_static('/docs/', path=str(os.path.join(WEB_APP_DIR, 'docs')))

        async def docs_handler(request):
            """Handle docs."""
            raise web.HTTPFound(location="https://imjoy.io/docs")

        app.router.add_get("/docs", docs_handler, name="docs")
        print("A local version of Imjoy web app is available at " + eng.opt.base_url)
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


async def about(request):
    """Return about text."""
    eng = request.app[ENG]
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

        if eng.opt.serve:
            body += (
                '<p><a href="'
                + eng.opt.base_url
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
        if eng.opt.serve:
            body = (
                '<H1><a href="' + eng.opt.base_url + '/#/app">Open ImJoy App</a></H1>'
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
    eng = request.app[ENG]
    logger = eng.logger
    requestUploadFiles = eng.store.requestUploadFiles
    urlid = request.match_info["urlid"]  # Could be a HUGE file
    if urlid not in requestUploadFiles:
        raise web.HTTPForbidden(text="Invalid URL")

    fileInfo = requestUploadFiles[urlid]
    try:
        reader = await request.multipart()
        field = None
        while True:
            part = await reader.next()
            print(part, part.filename)
            if part.filename is None:
                continue
            field = part
            break
        filename = field.filename
        # You cannot rely on Content-Length if transfer is chunked.
        size = 0
        if "path" in fileInfo:
            path = fileInfo["path"]
        else:
            path = filename

        if "dir" in fileInfo:
            path = os.path.join(fileInfo["dir"], path)
        else:
            path = os.path.join(eng.opt.WORKSPACE_DIR, fileInfo["workspace"], path)

        if os.path.exists(path) and not fileInfo.get("overwrite", False):
            return web.Response(body="File {} already exists.".format(path), status=404)

        logger.info("uploading file to %s", path)
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
        fileInfo["size"] = size
        fileInfo["path"] = path
        logger.info("file saved to %s (size %d)", path, size)
        return web.json_response(fileInfo)

    except Exception as exc:  # pylint: disable=broad-except
        print(traceback.format_exc())
        logger.error("failed to upload file error: %s", str(exc))
        return web.Response(
            body="Failed to upload, error: {}".format(str(exc)), status=404
        )


async def download_file(request):
    """Download file."""
    eng = request.app[ENG]
    generatedUrls = eng.store.generatedUrls
    urlid = request.match_info["urlid"]  # Could be a HUGE file
    name = request.match_info["name"]
    if urlid not in generatedUrls:
        raise web.HTTPForbidden(text="Invalid URL")
    fileInfo = generatedUrls[urlid]
    if fileInfo.get("password", False):
        password = request.match_info.get("password")
        if password != fileInfo["password"]:
            raise web.HTTPForbidden(text="Incorrect password for accessing this file.")
    headers = fileInfo.get("headers")
    default_headers = {}
    if fileInfo["type"] == "dir":
        dirname = os.path.dirname(name)
        # list the folder
        if dirname == "" or dirname is None:
            if name != fileInfo["name"]:
                raise web.HTTPForbidden(text="File name does not match server record!")
            folder_path = fileInfo["path"]
            if not os.path.exists(folder_path):
                return web.Response(
                    body="Folder <{folder_path}> does not exist".format(
                        folder_path=folder_path
                    ),
                    status=404,
                )
            else:
                file_list = scandir(folder_path, "file", False)
                headers = headers or {
                    "Content-Disposition": 'inline; filename="{filename}"'.format(
                        filename=name
                    )
                }
                headers.update(default_headers)
                return web.json_response(file_list, headers=headers)
        # list the subfolder or get a file in the folder
        else:
            file_path = os.path.join(fileInfo["path"], os.sep.join(name.split("/")[1:]))
            if not os.path.exists(file_path):
                return web.Response(
                    body="File <{file_path}> does not exist".format(
                        file_path=file_path
                    ),
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
            else:
                _, file_name = os.path.split(file_path)
                mime_type = (
                    MimeTypes().guess_type(file_name)[0] or "application/octet-stream"
                )
                file_size = os.path.getsize(file_path)
                headers = headers or {
                    "Content-Disposition": 'inline; filename="{filename}"'.format(
                        filename=file_name
                    ),
                    "Content-Type": mime_type,
                    "Content-Length": str(file_size),
                }
                headers.update(default_headers)
                return web.Response(
                    body=file_sender(file_path=file_path), headers=headers
                )
    elif fileInfo["type"] == "file":
        file_path = fileInfo["path"]
        if name != fileInfo["name"]:
            raise web.HTTPForbidden(text="File name does not match server record!")
        file_name = fileInfo["name"]
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
    else:
        raise web.HTTPForbidden(text="Unsupported file type: " + fileInfo["type"])


async def on_startup(app):
    """Run on server start."""
    eng = app[ENG]
    print("ImJoy Python Plugin Engine (version {})".format(__version__))

    if eng.opt.serve:
        print(
            "You can access your local ImJoy web app through "
            + eng.opt.base_url
            + " , imjoy!"
        )
    else:
        print(
            "Please go to https://imjoy.io/#/app "
            "with your web browser (Chrome or FireFox)"
        )
    print("Connection Token: " + eng.opt.token)
    sys.stdout.flush()


async def on_shutdown(app):
    """Run on server shut down."""
    eng = app[ENG]
    logger = eng.logger
    print("Shutting down...")
    logger.info("Shutting down the plugin engine...")
    stopped = threading.Event()

    def loop():  # executed in another thread
        for i in range(5):
            print("Exiting: " + str(5 - i), flush=True)
            time.sleep(0.5)
            if stopped.is_set():
                break
        print("Force shutting down now!", flush=True)
        logger.debug("Plugin engine is killed.")
        killProcess(logger, os.getpid())
        # os._exit(1)

    t = threading.Thread(target=loop)
    t.daemon = True  # stop if the program exits
    t.start()

    print("Shutting down the plugins...", flush=True)
    # stopped.set()
    logger.info("Plugin engine exited.")
    pid_file = os.path.join(eng.opt.WORKSPACE_DIR, ".pid")
    try:
        os.remove(pid_file)
    except Exception:  # pylint: disable=broad-except
        logger.info("Failed to remove the pid file.")
