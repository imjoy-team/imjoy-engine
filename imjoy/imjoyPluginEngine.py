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

    def setup(self):
        """Set up the engine."""
        self.conn = create_connection_manager(self)
        self.store = self.conn.store

    def start(self):
        """Start the engine."""
        self.conn.start()


def main():
    """Run app."""
    logging.basicConfig(stream=sys.stdout)
    logger = logging.getLogger("ImJoyPluginEngine")
    opt = parse_cmd_line()
    setup_logging(opt, logger)
    opt = prep_env(opt, logger)
    opt = bootstrap(opt, logger)
    eng = Engine(opt, logger)
    eng.setup()
    eng.start()


if __name__ == "__main__":
    main()
