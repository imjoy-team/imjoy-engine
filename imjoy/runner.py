"""Provide main entrypoint."""
import asyncio
import json
import logging
import os
import re
import sys
import urllib.request

import yaml
from imjoy_rpc import connect_to_server

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("plugin-runner")
logger.setLevel(logging.INFO)


async def run_plugin(plugin_file, default_config):
    """Load plugin file."""
    loop = asyncio.get_event_loop()
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
        fut = connect_to_server(default_config)
        try:
            exec(content, globals())  # pylint: disable=exec-used
            logger.info("Plugin executed")
            await fut
            if opt.quit_on_ready:
                loop.stop()
        except Exception as err:  # pylint: disable=broad-except
            logger.error("Failed to execute plugin %s", err)
            loop.stop()

    elif plugin_file.endswith(".imjoy.html"):
        # load config
        found = re.findall("<config (.*)>\n(.*)</config>", content, re.DOTALL)[0]
        if "json" in found[0]:
            plugin_config = json.loads(found[1])
        elif "yaml" in found[0]:
            plugin_config = yaml.safe_load(found[1])
        default_config.update(plugin_config)
        fut = connect_to_server(default_config)
        # load script
        found = re.findall("<script (.*)>\n(.*)</script>", content, re.DOTALL)[0]
        if "python" in found[0]:
            try:
                exec(found[1], globals())  # pylint: disable=exec-used
                logger.info("Plugin executed")
                await fut
                if opt.quit_on_ready:
                    loop.stop()
            except Exception as err:  # pylint: disable=broad-except
                logger.error("Failed to execute plugin %s", err)
                loop.stop()
        else:
            raise Exception(
                "Invalid script type ({}) in file {}".format(found[0], plugin_file)
            )
    else:
        raise Exception("Invalid script file type ({})".format(plugin_file))


def start_runner(args):
    """Start the plugin runner."""
    loop = asyncio.get_event_loop()

    default_config = {
        "server_url": args.server_url,
        "token": args.token,
    }
    asyncio.ensure_future(run_plugin(args.file, default_config))
    loop.run_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=str, help="path to a plugin file")
    parser.add_argument(
        "--server-url",
        type=str,
        default=None,
        help="url to the plugin socketio server",
    )

    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="token for the plugin socketio server",
    )

    parser.add_argument(
        "--quit-on-ready",
        action="store_true",
        help="quit the server when the plugin is ready",
    )

    opt = parser.parse_args()

    start_runner(opt)
