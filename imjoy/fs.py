import io
import fsspec


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
        # core_interface.register_codec(
        #     {"name": "io.IOBase", "type": io.IOBase, "encoder": encode_iobase}
        # )

    def mount(self, type, config):
        fs = fsspec.filesystem(type, **config)
        export_fs = {}
        LOCAL_METHODS = ["download", "get", "get_file", "put", "put_file", "upload"]

        def throw_error(*_):
            raise Exception("Methods related to local file path are not available.")

        for attr in dir(fs):
            v = getattr(fs, attr)
            if attr in LOCAL_METHODS:
                export_fs[attr] = throw_error
            elif not attr.startswith("_") and (
                isinstance(v, (str, int, float)) or callable(v)
            ):
                export_fs[attr] = v
        export_fs["_rintf"] = True
        return export_fs
