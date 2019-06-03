"""Implement the ImJoy plugin engine."""
import logging
import sys

from imjoy.options import parse_cmd_line
from imjoy.env import bootstrap, prepare_env
from imjoy.connection import create_connection_manager
from imjoy.runners import setup_runners
from imjoy.services import setup_services


def setup_logging(opt, logger):
    """Set up logging."""
    if opt.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)


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

    @classmethod
    def create(cls, args):
        """Prepare and and return an Engine instance."""
        logging.basicConfig(stream=sys.stdout)
        logger = logging.getLogger("ImJoyPluginEngine")
        opt = parse_cmd_line(args)
        setup_logging(opt, logger)
        opt = prepare_env(opt, logger)
        opt = bootstrap(opt, logger)
        return cls(opt, logger)

    def setup(self):
        """Set up the engine."""
        self.conn = create_connection_manager(self)
        self.store = self.conn.store
        self.conn.setup()
        setup_services(self)
        setup_runners(self)

    def start(self):
        """Start the engine."""
        self.conn.start()


def run(args=None):
    """Run the engine."""
    engine = Engine.create(args)
    engine.setup()
    engine.start()


if __name__ == "__main__":
    run()
