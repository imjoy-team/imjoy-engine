"""Provide setup function to prepare the engine."""
import argparse
import os
from imjoy import __version__


def parse_cmd_line(args=None):
    """Parse the command line options."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jupyter", action="store_true", help="start jupyter notebook server"
    )
    parser.add_argument("--token", type=str, default=None, help="connection token")
    parser.add_argument(
        "--random-token", action="store_true", help="randomly generate a token"
    )
    parser.add_argument("--debug", action="store_true", help="debug mode")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="download ImJoy web app and serve it locally",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="socketio host")
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="the base url for accessing this plugin engine",
    )
    parser.add_argument(
        "--allow-origin",
        type=str,
        default="https://lib.imjoy.io",
        help="the allow origin header to prevent unintended access from other website",
    )
    parser.add_argument(
        "--content-security-policy",
        type=str,
        default="frame-ancestors 'self' https://imjoy.io https://*.imjoy.io",
        help="the Content-Security-Policy header to prevent unintended access from other website",
    )
    parser.add_argument("--port", type=str, default="9527", help="socketio port")
    parser.add_argument(
        "--workspace",
        type=str,
        default=os.path.abspath(os.getcwd()),
        help="workspace folder for plugins",
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
