"""Provide engine runners."""
from .subprocess import setup_subprocess_runner


def setup_runners(engine):
    """Set up engine runners."""
    setup_subprocess_runner(engine)
