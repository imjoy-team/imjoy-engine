import logging
from pathlib import Path
import fsspec


class FSRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating file handler for working with fsspec"""

    def __init__(self, fs, *args, **kwargs):
        """Initialize file handler"""
        self.fs = fs
        super().__init__(*args, **kwargs)

    def _open(self):
        """
        Open the current base file with the (original) mode and encoding.
        Return the resulting stream.
        """
        return self.fs.open(self.baseFilename, self.mode, encoding=self.encoding)


def setup_logger(fs, name, log_file, level=logging.INFO):
    """To setup as many loggers as you want"""
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    handler = FSRotatingFileHandler(fs, log_file, maxBytes=2000000)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


class FSController:
    """File System Controller."""

    def __init__(
        self,
        event_bus,
        core_interface,
        fs_dir: str = "imjoy-workspaces",
        fs_type: str = "file",
        fs_config: dict = None,
    ):
        self.core_interface = core_interface
        self.fs_dir = Path(fs_dir)
        self.fs_type = fs_type
        self.fs_config = fs_config or {}
        self.fs = fsspec.filesystem(self.fs_type, **self.fs_config)
        event_bus.on("workspace_registered", self.setup_workspace)
        event_bus.on("workspace_unregistered", self.cleanup_workspace)

    def setup_workspace(self, workspace):
        workspace_dir = self.fs_dir / workspace.name
        self.fs.makedirs(str(workspace_dir), exist_ok=True)
        with self.fs.open(str(workspace_dir / "_workspace_config.json"), "w") as fil:
            fil.write(workspace.json())
        # logger = setup_logger(self.fs, workspace.name, str(workspace_dir / "log.txt"))
        # workspace._logger = logger

    def cleanup_workspace(self, workspace):
        workspace_dir = self.fs_dir / workspace.name
        self.fs.rm(str(workspace_dir), recursive=True)

    def get_file_system(self):
        return self.fs
