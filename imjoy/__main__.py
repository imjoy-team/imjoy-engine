"""Provide main entrypoint."""
import json
import os
import re
import subprocess
import sys
import asyncio
from aiohttp import web
import logging
import urllib.request
from imjoy_rpc import default_config

from imjoy.options import parse_cmd_line
from imjoy.utils import read_or_generate_token, write_token

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("main")
logger.setLevel(logging.INFO)


def load_plugin(plugin_file):
    """load plugin file"""
    try:
        import yaml
    except:
        logger.error(
            "It appears that your ImJoy installation is not complete, please reinstall it with 'pip install imjoy[socketio]'"
        )
        raise SystemExit
    if os.path.isfile(plugin_file):
        content = open(plugin_file).read()
    elif plugin_file.startswith("http"):
        with urllib.request.urlopen(plugin_file) as response:
            content = response.read().decode("utf-8")
        # remove query string
        plugin_file = plugin_file.split("?")[0]
    else:
        raise Exception("Invalid input plugin file path: {}".format(plugin_file))
    if plugin_file.endswith(".py"):
        filename, _ = os.path.splitext(os.path.basename(plugin_file))
        default_config["name"] = filename[:32]
        try:
            exec(content, globals())
            logger.info("Plugin executed")
        except Exception as e:
            logger.error("Failed to execute plugin %s", e)

    elif plugin_file.endswith(".imjoy.html"):
        # load config
        found = re.findall("<config (.*)>\n(.*)</config>", content, re.DOTALL)[0]
        if "json" in found[0]:
            plugin_config = json.loads(found[1])
        elif "yaml" in found[0]:
            plugin_config = yaml.safe_load(found[1])
        default_config.update(plugin_config)

        # load script
        found = re.findall("<script (.*)>\n(.*)</script>", content, re.DOTALL)[0]
        if "python" in found[0]:
            try:
                exec(found[1], globals())
                logger.info("Plugin executed")
            except Exception as e:
                logger.error("Failed to execute plugin %s", e)
        else:
            raise Exception(
                "Invalid script type ({}) in file {}".format(found[0], plugin_file)
            )
    else:
        raise Exception("Invalid script file type ({})".format(plugin_file))


def main():
    """Run main."""
    opt = parse_cmd_line()
    background_task = None

    if opt.plugin_file and (opt.plugin_server or opt.serve):

        async def start_plugin(app):
            default_config.update(
                {
                    "name": "ImJoy Plugin",
                    "plugin_server": opt.plugin_server
                    or "http://127.0.0.1:{}".format(opt.serve),
                }
            )

            load_plugin(opt.plugin_file)

        background_task = start_plugin

    if opt.serve:
        try:
            from imjoy.socketio_server import create_socketio_server
        except:
            logger.error(
                "It appears that your ImJoy installation is not complete, please reinstall it with 'pip install imjoy[socketio]'"
            )
            raise SystemExit
        if opt.plugin_server and not opt.plugin_server.endswith(opt.serve):
            print(
                "WARNING: the specified port ({}) does not match the one in the url ({})".format(
                    opt.serve, opt.plugin_server
                )
            )
        app = create_socketio_server()
        if background_task:
            app.on_startup.append(background_task)
        web.run_app(app, port=opt.serve)
    elif opt.plugin_file:
        loop = asyncio.get_event_loop()
        loop.create_task(background_task(app))
        loop.run_forever()
    elif opt.jupyter:
        sys.argv = sys.argv[:1]
        sys.argc = 1
        from notebook.notebookapp import NotebookApp

        kwargs = {
            "open_browser": False,
            "allow_origin": opt.allow_origin,
            "ip": opt.host,
            "notebook_dir": opt.workspace,
            "port": int(opt.port),
            "tornado_settings": {
                "headers": {
                    "Access-Control-Allow-Origin": opt.allow_origin,
                    "Content-Security-Policy": opt.content_security_policy,
                }
            },
        }

        if not opt.token:
            if not opt.random_token:
                opt.token = read_or_generate_token()
                kwargs["token"] = opt.token
        else:
            kwargs["token"] = opt.token

        app = NotebookApp.instance(**kwargs)
        app.initialize()
        if app.port != int(opt.port):
            print("\nWARNING: using a different port: {}.\n".format(app.port))
        write_token(app.token)
        app._token_generated = True
        app.start()

    elif not opt.legacy:
        print(
            "\nNote: We are migrating the backend of the ImJoy Engine to Jupyter, to use it please run `imjoy --jupyter`.\n\nIf you want to use the previous engine, run `imjoy --legacy`, however, please note that it maybe removed soon.\n"
        )


if __name__ == "__main__":
    main()
