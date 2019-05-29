"""Implement the ImJoy plugin engine."""
import logging
import sys

from imjoy.helper import setup_logging
from imjoy.options import parse_cmd_line
from imjoy.env import bootstrap, prep_env
from imjoy.connection import create_connection_manager


class Engine:
    """Represent the plugin engine."""

    def __init__(self, opt, logger):
        """Set up instance attributes of the engine."""
        self.logger = logger
        self.opt = opt
        self.conn = None
        self.store = None

    def __repr__(self):
        """Return the engine representation."""
        return f"<Engine(opt={self.opt})>"

    def setup(self):
        """Set up the engine."""
        self.conn = create_connection_manager(self)
        self.store = self.conn.store
        self.conn.setup()

    def start(self):
        """Start the engine."""
        self.conn.start()

    async def async_start(self):
        """Start the engine asynchronously."""
        await self.conn.async_start()

    async def async_stop(self):
        """Stop the engine."""
        await self.conn.async_stop()


def run():
    """Run the engine."""
    logging.basicConfig(stream=sys.stdout)
    logger = logging.getLogger("ImJoyPluginEngine")
    opt = parse_cmd_line()
    setup_logging(opt, logger)
    opt = prep_env(opt, logger)
    opt = bootstrap(opt, logger)
    engine = Engine(opt, logger)
    engine.setup()
    engine.start()


if __name__ == "__main__":
    run()
