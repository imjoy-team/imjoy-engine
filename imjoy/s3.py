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

    def get_s3_controller(self):
        return None
