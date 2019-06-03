"""Provide a terminal service."""
import asyncio
import os
import select
import shlex
import struct
import subprocess
import sys

from imjoy import __version__
from imjoy.connection.decorator import socketio_handler as sio_on
from imjoy.utils import get_psutil

if sys.platform != "win32":
    import fcntl
    import pty
    import termios


def setup_terminal(engine):
    """Set up the terminal service."""
    engine.conn.register_event_handler(on_start_terminal)
    engine.conn.register_event_handler(on_terminal_input)
    engine.conn.register_event_handler(on_terminal_window_resize)


async def read_and_forward_terminal_output(engine):
    """Read from terminal and forward to the client."""
    terminal_session = engine.store.terminal_session
    max_read_bytes = 1024 * 20
    try:
        terminal_session["output_monitor_running"] = True
        while True:
            await asyncio.sleep(0.01)
            if "fd" in terminal_session:
                timeout_sec = 0
                (data_ready, _, _) = select.select(
                    [terminal_session["fd"]], [], [], timeout_sec
                )
                if data_ready:
                    output = os.read(terminal_session["fd"], max_read_bytes).decode()
                    if output:
                        await engine.conn.sio.emit(
                            "terminal_output", {"output": output}
                        )
    finally:
        terminal_session["output_monitor_running"] = False


@sio_on("start_terminal")
async def on_start_terminal(engine, sid, kwargs):
    """Handle new terminal client connected."""
    if sys.platform == "win32":
        return {"success": False, "error": "Terminal is not available on Windows yet."}
    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    terminal_session = engine.store.terminal_session
    try:
        if sid not in registered_sessions:
            logger.debug("Client %s is not registered", sid)
            return {"success": False, "error": "client not registered."}

        if "child_pid" in terminal_session and "fd" in terminal_session:
            process_exists = True
            psutil = get_psutil()
            if psutil is not None:
                process_exists = False
                current_process = psutil.Process()
                children = current_process.children(recursive=True)
                for proc in children:
                    if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                        if proc.pid == terminal_session["child_pid"]:
                            process_exists = True
                            break
            if process_exists:
                # already started child process, don't start another
                return {
                    "success": True,
                    "exists": True,
                    "message": (
                        f"Welcome to ImJoy Plugin Engine Terminal (v{__version__})."
                    ),
                }

        if sys.platform == "linux" or sys.platform == "linux2":
            # linux
            default_terminal_command = ["bash"]
        elif sys.platform == "darwin":
            # OS X
            default_terminal_command = ["bash"]
        elif sys.platform == "win32":
            # Windows
            default_terminal_command = ["cmd.exe"]
        else:
            default_terminal_command = ["bash"]
        cmd = kwargs.get("cmd", default_terminal_command)

        # create child process attached to a pty we can read from and write to
        (child_pid, fdesc) = pty.fork()
        if child_pid == 0:
            # this is the child process fork.
            # anything printed here will show up in the pty, including the output
            # of this subprocess
            term_env = os.environ.copy()
            term_env["TERM"] = "xterm-256color"
            subprocess.run(cmd, env=term_env)
            subprocess.run(cmd)
        else:
            # this is the parent process fork.
            # store child fd and pid
            terminal_session["fd"] = fdesc
            terminal_session["child_pid"] = child_pid
            set_winsize(fdesc, 50, 50)
            cmd = " ".join(shlex.quote(c) for c in cmd)
            logger.info(
                "Terminal subprocess started, command: %s, pid: %s", cmd, child_pid
            )
            logger.debug("Terminal session %s started", terminal_session)
            if (
                "output_monitor_running" not in terminal_session
                or not terminal_session["output_monitor_running"]
            ):
                asyncio.ensure_future(
                    read_and_forward_terminal_output(engine),
                    loop=asyncio.get_event_loop(),
                )

        return {
            "success": True,
            "message": f"Welcome to ImJoy Plugin Engine Terminal (v{__version__}).",
        }
    except Exception as exc:  # pylint: disable=broad-except
        return {"success": False, "error": str(exc)}


@sio_on("terminal_input")
async def on_terminal_input(engine, sid, data):
    """Write to the terminal as if you are typing in a real terminal."""
    if sys.platform == "win32":
        return "Terminal is not available on Windows yet."

    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    terminal_session = engine.store.terminal_session
    if sid not in registered_sessions:
        return
    try:
        if "fd" in terminal_session:
            os.write(terminal_session["fd"], data["input"].encode())
        else:
            return "Terminal session is closed"
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to write to terminal process: %s", exc)
        return str(exc)


def set_winsize(fdesc, row, col, xpix=0, ypix=0):
    """Set window size."""
    if sys.platform == "win32":
        return
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fdesc, termios.TIOCSWINSZ, winsize)


@sio_on("terminal_window_resize")
async def on_terminal_window_resize(engine, sid, data):
    """Resize terminal window."""
    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    terminal_session = engine.store.terminal_session
    if sid not in registered_sessions:
        return
    try:
        if "fd" in terminal_session:
            set_winsize(terminal_session["fd"], data["rows"], data["cols"])
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to resize the terminal window: %s", exc)
        return str(exc)
