from imjoy.minio import MinioClient


class S3Controller:
    def __init__(
        self,
        event_bus,
        core_interface,
        endpoint_url=None,
        access_key_id=None,
        secret_access_key=None,
    ):
        self.mc = MinioClient(
            endpoint_url,
            access_key_id,
            secret_access_key,
        )
        core_interface.register_interface("get_s3_controller", self.get_s3_controller)
        core_interface.register_interface("getS3Controller", self.get_s3_controller)
        self.core_interface = core_interface
        event_bus.on("workspace_registered", self.setup_workspace)
        event_bus.on("workspace_unregistered", self.cleanup_workspace)

    def cleanup_workspace(self, workspace):
        pass

    def setup_workspace(self, workspace):
        pass  # self.mc.admin_group_add(workspace.name)

    def get_info(self):
        return {}

    def generate_presigned_url(self):
        return 123

    def list(self):
        return

    def get_s3_controller(self):
        # workspace = self.core_interface.current_workspace
        # self.mc.admin_group_add
        return {
            "_rintf": True,
            "get_info": self.get_info,
            "list": self.list,
            "generate_presigned_url": self.generate_presigned_url,
        }
