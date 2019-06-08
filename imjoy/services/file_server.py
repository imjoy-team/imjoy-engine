"""Provide a file server service."""
import os
import shutil
import sys
import uuid
from urllib.parse import urlparse

from imjoy.connection.decorator import socketio_handler as sio_on
from imjoy.utils import scandir

if sys.platform == "win32":
    from imjoy.utils import get_drives


def setup_file_server(engine):
    """Set up the file server service."""
    engine.conn.register_event_handler(on_list_dir)
    engine.conn.register_event_handler(on_get_file_url)
    engine.conn.register_event_handler(on_get_file_path)
    engine.conn.register_event_handler(on_remove_files)
    engine.conn.register_event_handler(on_request_upload_url)


@sio_on("list_dir")
async def on_list_dir(engine, sid, kwargs):
    """List files in directory."""
    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered."}

    try:
        workspace_dir = os.path.join(
            engine.opt.workspace_dir, registered_sessions[sid]["workspace"]
        )

        path = kwargs.get("path", workspace_dir)
        path = os.path.normpath(os.path.expanduser(path))
        if not os.path.isabs(path):
            path = os.path.join(workspace_dir, path)
        path = os.path.abspath(path)

        type_ = kwargs.get("type")
        recursive = kwargs.get("recursive", False)
        files_list = {"success": True}
        files_list["sep"] = os.sep
        files_list["path"] = path
        files_list["name"] = os.path.basename(os.path.abspath(path))
        files_list["type"] = "dir"
        files_list["children"] = scandir(files_list["path"], type_, recursive)

        if sys.platform == "win32":
            files_list["drives"] = get_drives()

        return files_list
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("List dir error: %s", exc)
        return {"success": False, "error": str(exc)}


@sio_on("remove_files")
async def on_remove_files(engine, sid, kwargs):
    """Remove files."""
    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered."}
    logger.info("Removing files: %s", kwargs)
    workspace_dir = os.path.join(
        engine.opt.workspace_dir, registered_sessions[sid]["workspace"]
    )
    path = kwargs.get("path", workspace_dir)
    if not os.path.isabs(path):
        path = os.path.join(workspace_dir, path)
    path = os.path.normpath(os.path.expanduser(path))
    type_ = kwargs.get("type")
    recursive = kwargs.get("recursive", False)

    if os.path.exists(path) and not os.path.isdir(path) and type_ == "file":
        try:
            os.remove(path)
            return {"success": True}
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Remove files error: %s", str(exc))
            return {"success": False, "error": str(exc)}
    elif os.path.exists(path) and os.path.isdir(path) and type_ == "dir":
        try:
            if recursive:
                dirname, filename = os.path.split(path)
                shutil.move(path, os.path.join(dirname, "." + filename))
                # shutil.rmtree(path)
            else:
                os.rmdir(path)
            return {"success": True}
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Remove files error: %s", str(exc))
            return {"success": False, "error": str(exc)}
    else:
        logger.error("Remove files error: File does not exists or type mismatch")
        return {"success": False, "error": "File not exists or type mismatch."}


@sio_on("request_upload_url")
async def on_request_upload_url(engine, sid, kwargs):
    """Request upload url."""
    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    request_upload_files = engine.store.request_upload_files
    request_urls = engine.store.request_urls
    logger.info("Requesting file upload url: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered"}

    urlid = str(uuid.uuid4())
    file_info = {
        "id": urlid,
        "overwrite": kwargs.get("overwrite", False),
        "workspace": registered_sessions[sid]["workspace"],
    }
    if "path" in kwargs:
        file_info["path"] = kwargs["path"]

    if "dir" in kwargs:
        path = os.path.expanduser(kwargs["dir"])
        if not os.path.isabs(path):
            path = os.path.join(engine.opt.workspace_dir, file_info["workspace"], path)
        file_info["dir"] = path

    if "path" in file_info:
        path = file_info["path"]
        if "dir" in file_info:
            path = os.path.join(file_info["dir"], path)
        else:
            path = os.path.join(engine.opt.workspace_dir, file_info["workspace"], path)

        if os.path.exists(path) and not kwargs.get("overwrite", False):
            return {"success": False, "error": "file already exist."}

    base_url = kwargs.get("base_url", registered_sessions[sid]["base_url"])
    url = "{}/upload/{}".format(base_url, urlid)
    request_urls[url] = file_info
    request_upload_files[urlid] = file_info
    return {"success": True, "id": urlid, "url": url}


@sio_on("get_file_url")
async def on_get_file_url(engine, sid, kwargs):
    """Return file url."""
    logger = engine.logger
    generated_url_files = engine.store.generated_url_files
    generated_urls = engine.store.generated_urls
    registered_sessions = engine.store.registered_sessions
    logger.info("Generating file url: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered"}

    path = os.path.abspath(os.path.expanduser(kwargs["path"]))
    if not os.path.exists(path):
        return {"success": False, "error": "file does not exist."}
    file_info = {"path": path}
    if os.path.isdir(path):
        file_info["type"] = "dir"
    else:
        file_info["type"] = "file"
    if kwargs.get("headers"):
        file_info["headers"] = kwargs["headers"]
    _, name = os.path.split(path)
    file_info["name"] = name
    if path in generated_url_files:
        return {"success": True, "url": generated_url_files[path]}
    urlid = str(uuid.uuid4())
    generated_urls[urlid] = file_info
    base_url = kwargs.get("base_url", registered_sessions[sid]["base_url"])
    if kwargs.get("password"):
        file_info["password"] = kwargs["password"]
        generated_url_files[path] = "{}/file/{}@{}/{}".format(
            base_url, urlid, file_info["password"], name
        )
    else:
        generated_url_files[path] = "{}/file/{}/{}".format(base_url, urlid, name)
    return {"success": True, "url": generated_url_files[path]}


@sio_on("get_file_path")
async def on_get_file_path(engine, sid, kwargs):
    """Return file path."""
    logger = engine.logger
    generated_urls = engine.store.generated_urls
    registered_sessions = engine.store.registered_sessions
    logger.info("Generating file url: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered"}

    url = kwargs["url"]
    urlid = urlparse(url).path.replace("/file/", "")
    if urlid in generated_urls:
        file_info = generated_urls[urlid]
        return {"success": True, "path": file_info["path"]}
    return {"success": False, "error": "url not found."}
