"""Provide engine services."""
from .file_server import setup_file_server
from .terminal import setup_terminal


def setup_services(engine):
    """Set up engine services."""
    setup_file_server(engine)
    setup_terminal(engine)
