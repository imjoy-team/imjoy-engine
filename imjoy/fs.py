import os
import fsspec
import inspect
import posixpath
from functools import partial
from typing import List, Optional

_os_alt_seps: List[str] = list(
    sep for sep in [os.path.sep, os.path.altsep] if sep is not None and sep != "/"
)


def safe_join(directory: str, *pathnames: str) -> Optional[str]:
    """Safely join zero or more untrusted path components to a base
    directory to avoid escaping the base directory.
    :param directory: The trusted base directory.
    :param pathnames: The untrusted path components relative to the
        base directory.
    :return: A safe path, otherwise ``None``.

    This function is copied from: https://github.com/pallets/werkzeug/blob/fb7ddd89ae3072e4f4002701a643eb247a402b64/src/werkzeug/security.py#L222
    """
    parts = [directory]

    for filename in pathnames:
        if filename != "":
            filename = posixpath.normpath(filename)

        if (
            any(sep in filename for sep in _os_alt_seps)
            or os.path.isabs(filename)
            or filename == ".."
            or filename.startswith("../")
        ):
            raise Exception(
                f"Illegal file path: `{filename}`, please use file path within the current directory."
            )

        parts.append(filename)

    return posixpath.join(*parts)


def encode_fsmap(x):
    return {}


class FSController:
    """File System Controller."""

    def __init__(
        self,
        event_bus,
        core_interface,
        fs_dir: str = "./data",
    ):
        self.core_interface = core_interface
        core_interface.register_interface("mount_fs", self.mount)
        core_interface.register_interface("mountFs", self.mount)
        core_interface.register_codec(
            {"name": "FSMap", "type": fsspec.mapping.FSMap, "encoder": encode_fsmap}
        )
        self.fs_dir = fs_dir

    def mount(self, type, config):
        current_workspace = self.core_interface.current_workspace.get()
        workspace_name = current_workspace.name
        fs = fsspec.filesystem(type, **config)
        export_fs = {}
        LOCAL_METHODS = ["download", "get", "get_file", "put", "put_file", "upload"]
        # ALLOWD_METHODS = ['blocksize', 'cachable', 'cat', 'cat_file', 'cat_ranges', 'checksum', 'chmod', 'clear_instance_cache', 'copy', 'cp', 'cp_file', 'created', 'current', 'delete', 'dircache', 'disk_usage', 'download', 'du', 'end_transaction', 'exists', 'expand_path', 'find', 'from_json', 'get', 'get_file', 'get_mapper', 'glob', 'head', 'info', 'invalidate_cache', 'isdir', 'isfile', 'lexists', 'listdir', 'local_file', 'ls', 'makedir', 'makedirs', 'mkdir', 'mkdirs', 'modified', 'move', 'mv', 'mv_file', 'open', 'pipe', 'pipe_file', 'protocol', 'put', 'put_file', 'read_block', 'rename', 'rm', 'rm_file', 'rmdir', 'root_marker', 'sep', 'sign', 'size', 'start_transaction', 'stat', 'storage_args', 'storage_options', 'tail', 'to_json', 'touch', 'transaction', 'ukey', 'upload', 'walk']

        user_dir = os.path.abspath(os.path.join(self.fs_dir, workspace_name))
        fs.makedirs(user_dir, exist_ok=True)

        def throw_error(*_):
            raise Exception("Methods related to local file path are not available.")

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
                    args[i] = safe_join(user_dir, arg)
            for k in list(kwargs.keys()):
                arg = kwargs[k]
                if "path" in k or "root" in k:
                    kwargs[k] = safe_join(user_dir, arg)
            return func(*args, **kwargs)

        for attr in dir(fs):
            v = getattr(fs, attr)
            if attr in LOCAL_METHODS:
                export_fs[attr] = throw_error
            elif not attr.startswith("_") and (
                isinstance(v, (str, int, float)) or callable(v)
            ):
                export_fs[attr] = partial(secure_func, v)

        export_fs["_rintf"] = True
        return export_fs
