import os
import fsspec
import inspect
import logging
from pathlib import Path

from functools import partial
from imjoy.utils import safe_join

EXCLUDE_METHODS = ["download", "get", "get_file", "put", "put_file", "upload"]


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


def encode_fsmap(x):
    ret = {
        m: getattr(x, m)
        for m in dir(x)
        if not m.startswith("_") and callable(getattr(x, m))
    }
    ret["_rintf"] = True
    return ret


class FSController:
    """File System Controller."""

    def __init__(
        self,
        event_bus,
        core_interface,
        fs_dir: str = "./data",
        fs_type: str = "file",
        fs_config: dict = None,
    ):
        self.core_interface = core_interface
        core_interface.register_interface("get_file_system", self.get_file_system)
        core_interface.register_interface("getFileSystem", self.get_file_system)
        core_interface.register_codec(
            {"name": "FSMap", "type": fsspec.mapping.FSMap, "encoder": encode_fsmap}
        )
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
        logger = setup_logger(self.fs, workspace.name, str(workspace_dir / "log.txt"))
        workspace._logger = logger

    def cleanup_workspace(self, workspace):
        workspace_dir = self.fs_dir / workspace.name
        self.fs.rm(str(workspace_dir), recursive=True)

    def get_file_system(self, config=None):
        current_workspace = self.core_interface.current_workspace.get()
        workspace_name = current_workspace.name

        export_fs = {}
        workspace_dir = str(os.path.abspath(self.fs_dir / workspace_name))
        self.fs.makedirs(workspace_dir, exist_ok=True)

        def throw_error(*_):
            raise Exception("Methods for local file mainipulation are not available.")

        def secure_func(func, *args, **kwargs):
            """Make sure we prefix the file paths with fs_dir and workspace_name"""
            arg_names = inspect.getargspec(func).args
            if arg_names[0] == "self":
                arg_names = arg_names[1:]
            is_path = [("path" in name or "root" in name) for name in arg_names]
            args = list(args)
            if len(is_path) < len(args):
                raise Exception(
                    f"Too many arguments: {args} (valid arguments are: {arg_names})"
                )

            for i in range(len(args)):
                arg = args[i]
                if is_path[i]:
                    args[i] = safe_join(workspace_dir, arg)
            for k in list(kwargs.keys()):
                arg = kwargs[k]
                if "path" in k or "root" in k:
                    kwargs[k] = safe_join(workspace_dir, arg)
            return func(*args, **kwargs)

        for attr in dir(self.fs):
            v = getattr(self.fs, attr)
            if attr in EXCLUDE_METHODS:
                export_fs[attr] = throw_error
            elif not attr.startswith("_") and (
                isinstance(v, (str, int, float)) or callable(v)
            ):
                export_fs[attr] = partial(secure_func, v)

        export_fs["_rintf"] = True
        return export_fs
