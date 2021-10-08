"""Provide common pytest fixtures."""
import subprocess
import sys
import time

import pytest
import requests
from requests import RequestException

from . import SIO_PORT, SIO_PORT2


@pytest.fixture(name="socketio_server", scope="session")
def socketio_server_fixture():
    """Start server as test fixture and tear down after test."""
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.server",
            f"--port={SIO_PORT}",
        ]
    ) as proc:

        timeout = 10
        while timeout > 0:
            try:
                response = requests.get(f"http://127.0.0.1:{SIO_PORT}/liveness")
                if response.ok:
                    break
            except RequestException:
                pass
            timeout -= 0.1
            time.sleep(0.1)
        yield
        proc.kill()
        proc.terminate()


@pytest.fixture(name="socketio_subpath_server")
def socketio_subpath_server_fixture():
    """Start server (under /my/engine) as test fixture and tear down after test."""
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "imjoy.server",
            f"--port={SIO_PORT2}",
            "--base-path=/my/engine",
        ]
    ) as proc:

        timeout = 10
        while timeout > 0:
            try:
                response = requests.get(
                    f"http://127.0.0.1:{SIO_PORT2}/my/engine/liveness"
                )
                if response.ok:
                    break
            except RequestException:
                pass
            timeout -= 0.1
            time.sleep(0.1)
        yield
        proc.kill()
        proc.terminate()
