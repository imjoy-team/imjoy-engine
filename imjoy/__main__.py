"""Provide main entrypoint."""
import logging
import sys

from imjoy.options import parse_cmd_line
from imjoy.utils import read_or_generate_token, write_token

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("main")
logger.setLevel(logging.INFO)


def main():
    """Run main."""
    opt = parse_cmd_line()
    if opt.serve:
        # pylint: disable=import-outside-toplevel
        from imjoy.server import start_server

        start_server(opt)
    elif opt.jupyter:
        sys.argv = sys.argv[:1]
        sys.argc = 1
        # pylint: disable=import-outside-toplevel
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

        if opt.insecure:
            kwargs["token"] = ""
            kwargs["disable_check_xsrf"] = True
            logger.warning(
                "Running Jupyter notebooks with --insecure flag, "
                "please do not use it for production."
            )

        app = NotebookApp.instance(**kwargs)
        app.initialize()
        if app.port != int(opt.port):
            print(f"\nWARNING: using a different port: {app.port}.\n")
        write_token(app.token)
        app._token_generated = True  # pylint: disable=protected-access
        app.start()

    else:
        print(
            "\nNote: We have migrated the backend of the ImJoy Engine."
            "You can start the Jupyter backend via`imjoy --jupyter`.\n\n"
            "Or, you can start the socketio backend server via `imjoy --serve`\n"
        )


if __name__ == "__main__":
    main()
