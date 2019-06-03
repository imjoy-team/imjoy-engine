"""Provide setup function to prepare the engine."""
import argparse
from imjoy import __version__


def parse_cmd_line(args=None):
    """Parse the command line options."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", type=str, default=None, help="connection token")
    parser.add_argument("--debug", action="store_true", help="debug mode")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="download ImJoy web app and serve it locally",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="socketio host")
    parser.add_argument(
        "--base_url",
        type=str,
        default=None,
        help="the base url for accessing this plugin engine",
    )
    parser.add_argument("--port", type=str, default="9527", help="socketio port")
    parser.add_argument(
        "--force_quit_timeout",
        type=int,
        default=5,
        help=(
            "the time (in seconds) for waiting before killing a plugin process, "
            "default: 5 s"
        ),
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="~/ImJoyWorkspace",
        help="workspace folder for plugins",
    )
    parser.add_argument(
        "--freeze", action="store_true", help="disable conda and pip commands"
    )
    parser.add_argument(
        "--engine_container_token",
        type=str,
        default=None,
        help="A token set by the engine container which launches the engine",
    )
    parser.add_argument(
        "--dev", action="store_true", help="run ImJoy Engine in development mode"
    )

    parser.add_argument(
        "-v", "--version", action="version", version="%(prog)s " + __version__
    )

    opt = parser.parse_args(args=args)

    if opt.base_url is None or opt.base_url == "":
        opt.base_url = "http://{}:{}".format(opt.host, opt.port)

    if opt.base_url.endswith("/"):
        opt.base_url = opt.base_url[:-1]

    return opt
