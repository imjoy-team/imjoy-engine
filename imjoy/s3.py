import sys
import logging
import asyncio

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from imjoy.core import get_workspace
from imjoy.core.auth import check_permission, login_optional
from aiobotocore.session import get_session
import botocore
from imjoy.utils import safe_join
from starlette.types import Receive, Scope, Send
from email.utils import formatdate
from datetime import datetime
from typing import Any
import json

from imjoy.minio import MinioClient
from imjoy.utils import generate_password

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("s3")
logger.setLevel(logging.INFO)


class FSFileResponse(FileResponse):
    chunk_size = 4096

    def __init__(self, s3client, bucket: str, key: str, **kwargs) -> None:
        self.s3client = s3client
        self.bucket = bucket
        self.key = key
        super().__init__(key, **kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with self.s3client as s3:
            try:
                obj_info = await s3.get_object(Bucket=self.bucket, Key=self.key)
                last_modified = formatdate(
                    datetime.timestamp(obj_info["LastModified"]), usegmt=True
                )
                self.headers.setdefault(
                    "content-length", str(obj_info["ContentLength"])
                )
                self.headers.setdefault("last-modified", last_modified)
                self.headers.setdefault("etag", obj_info["ETag"])
            except Exception as exp:
                raise RuntimeError(
                    f"File at path {self.path} does not exist, details: {exp}"
                )
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            if self.send_header_only:
                await send(
                    {"type": "http.response.body", "body": b"", "more_body": False}
                )
            else:
                # Tentatively ignoring type checking failure to work around the wrong type
                # definitions for aiofile that come with typeshed. See
                # https://github.com/python/typeshed/pull/4650

                total_size = obj_info["ContentLength"]
                sent_size = 0
                chunks = obj_info["Body"].iter_chunks(chunk_size=self.chunk_size)
                async for chunk in chunks:
                    sent_size += len(chunk)
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": sent_size < total_size,
                        }
                    )

            if self.background is not None:
                await self.background()


class JSONResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=str,  # This will convert everything unknown to a string
        ).encode("utf-8")


class S3Controller:
    def __init__(
        self,
        event_bus,
        core_interface,
        endpoint_url=None,
        access_key_id=None,
        secret_access_key=None,
        default_bucket="imjoy-workspaces",
    ):
        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.mc = MinioClient(
            endpoint_url,
            access_key_id,
            secret_access_key,
        )
        self.core_interface = core_interface
        self.default_bucket = default_bucket

        s3client = self.create_client_sync()
        try:
            s3client.create_bucket(Bucket=self.default_bucket)
            logger.info("Bucket created: %s", self.default_bucket)
        except s3client.exceptions.BucketAlreadyExists:
            pass

        self.mc.admin_user_add(core_interface.root_user.id, generate_password())
        core_interface.register_interface("get_s3_controller", self.get_s3_controller)
        core_interface.register_interface("getS3Controller", self.get_s3_controller)

        event_bus.on("workspace_registered", self.setup_workspace)
        event_bus.on("workspace_unregistered", self.cleanup_workspace)
        event_bus.on("user_connected", self.setup_user)
        event_bus.on("plugin_registered", self.setup_plugin)
        event_bus.on("user_entered_workspace", self.enter_workspace)

        router = APIRouter()

        @router.put("/{workspace}/files/{path:path}")
        async def upload_file(
            workspace: str,
            path: str,
            request: Request,
            user_info: login_optional = Depends(login_optional),
        ):
            ws = get_workspace(workspace)
            if not ws:
                return JSONResponse(
                    status_code=404,
                    content={
                        "success": False,
                        "detail": f"Workspace does not exists: {ws}",
                    },
                )
            if not check_permission(ws, user_info):
                return JSONResponse(
                    status_code=403,
                    content={"success": False, "detail": f"Permission denied: {ws}"},
                )
            path = safe_join(workspace, path)

            async with self.create_client_async() as s3:
                mpu = await s3.create_multipart_upload(
                    Bucket=self.default_bucket, Key=path
                )
                parts_info = {}
                futs = []
                count = 0
                # Stream support: https://github.com/tiangolo/fastapi/issues/58#issuecomment-469355469
                current_chunk = b""
                async for chunk in request.stream():
                    current_chunk += chunk
                    if len(current_chunk) > 5 * 1024 * 1024:
                        count += 1
                        part_fut = s3.upload_part(
                            Bucket=self.default_bucket,
                            ContentLength=len(current_chunk),
                            Key=path,
                            PartNumber=count,
                            UploadId=mpu["UploadId"],
                            Body=current_chunk,
                        )
                        futs.append(part_fut)
                        current_chunk = b""
                # if multipart upload is activated
                if len(futs) > 0:
                    if len(current_chunk) > 0:
                        # upload the last chunk
                        count += 1
                        part_fut = s3.upload_part(
                            Bucket=self.default_bucket,
                            ContentLength=len(current_chunk),
                            Key=path,
                            PartNumber=count,
                            UploadId=mpu["UploadId"],
                            Body=current_chunk,
                        )
                        futs.append(part_fut)

                    parts = await asyncio.gather(*futs)
                    parts_info["Parts"] = [
                        {"PartNumber": i + 1, "ETag": part["ETag"]}
                        for i, part in enumerate(parts)
                    ]

                    response = await s3.complete_multipart_upload(
                        Bucket=self.default_bucket,
                        Key=path,
                        UploadId=mpu["UploadId"],
                        MultipartUpload=parts_info,
                    )
                else:
                    response = await s3.put_object(
                        Body=current_chunk,
                        Bucket=self.default_bucket,
                        Key=path,
                        ContentLength=len(current_chunk),
                    )

                assert "ETag" in response
                return JSONResponse(
                    status_code=200,
                    content=response,
                )

        @router.get("/{workspace}/files/{path:path}")
        @router.delete("/{workspace}/files/{path:path}")
        async def get_or_delete_file(
            workspace: str,
            path: str,
            request: Request,
            user_info: login_optional = Depends(login_optional),
        ):
            ws = get_workspace(workspace)
            if not ws:
                return JSONResponse(
                    status_code=404,
                    content={
                        "success": False,
                        "detail": f"Workspace does not exists: {ws}",
                    },
                )
            if not check_permission(ws, user_info):
                return JSONResponse(
                    status_code=403,
                    content={"success": False, "detail": f"Permission denied: {ws}"},
                )
            path = safe_join(workspace, path)
            if request.method == "GET":
                async with self.create_client_async() as s3:
                    if path.endswith("/"):
                        response = await s3.list_objects_v2(
                            Bucket=self.default_bucket, Prefix=path
                        )
                        items = response["Contents"]
                        while response["IsTruncated"]:
                            response = await s3.list_objects_v2(
                                Bucket=self.default_bucket,
                                Prefix=path,
                                ContinuationToken=response["NextContinuationToken"],
                            )
                            items += response["Contents"]
                        if len(items) == 0:
                            return JSONResponse(
                                status_code=404,
                                content={
                                    "success": False,
                                    "detail": f"Directory does not exists: {path}",
                                },
                            )
                        else:
                            return JSONResponse(
                                status_code=200,
                                content={
                                    "success": False,
                                    "type": "directory",
                                    "children": items,
                                },
                            )
                    try:
                        response = await s3.head_object(
                            Bucket=self.default_bucket, Key=path
                        )
                        return FSFileResponse(
                            self.create_client_async(), self.default_bucket, path
                        )
                    except ClientError:
                        return JSONResponse(
                            status_code=404,
                            content={
                                "success": False,
                                "detail": f"File does not exists: {path}",
                            },
                        )

            if request.method == "DELETE":
                if path.endswith("/"):
                    return JSONResponse(
                        status_code=404,
                        content={
                            "success": False,
                            "detail": f"Removing directory is not supported.",
                        },
                    )
                async with self.create_client_async() as s3:
                    try:
                        response = await s3.delete_object(
                            Bucket=self.default_bucket, Key=path
                        )
                        response["success"] = True
                        return JSONResponse(
                            status_code=200,
                            content=response,
                        )
                    except ClientError:
                        return JSONResponse(
                            status_code=404,
                            content={
                                "success": False,
                                "detail": f"File does not exists: {path}",
                            },
                        )

        core_interface.register_router(router)

    def create_client_sync(self):
        return botocore.session.get_session().create_client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="EU",
        )

    def create_client_async(self):
        return get_session().create_client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="EU",
        )

    def setup_user(self, user_info):
        try:
            self.mc.admin_user_info(user_info.id)
        except Exception:
            # Note: we don't store the credentials, it can only be regenerated
            self.mc.admin_user_add(user_info.id, generate_password())

    def setup_plugin(self, plugin):
        self.mc.admin_group_add(plugin.workspace.name, plugin.user_info.id)

    def cleanup_workspace(self, workspace):
        # TODO: if the program shutdown unexcpetedly, we need to clean it up
        # We should empty the group before removing it
        ginfo = self.mc.admin_group_info(workspace.name)
        # remove all the members
        self.mc.admin_group_remove(workspace.name, ginfo["members"])
        # now remove the empty group
        self.mc.admin_group_remove(workspace.name)

    def setup_workspace(self, workspace):
        # make sure we have the root user in every workspace
        self.mc.admin_group_add(workspace.name, self.core_interface.root_user.id)
        policy_name = "policy-ws-" + workspace.name
        # policy example: https://aws.amazon.com/premiumsupport/knowledge-center/iam-s3-user-specific-folder/
        self.mc.admin_policy_add(
            policy_name,
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowUserToSeeTheBucketInTheConsole",
                        "Action": ["s3:ListAllMyBuckets", "s3:GetBucketLocation"],
                        "Effect": "Allow",
                        "Resource": [f"arn:aws:s3:::{self.default_bucket}"],
                    },
                    {
                        "Sid": "AllowListingOfWorkspaceFolder",
                        "Action": ["s3:ListBucket"],
                        "Effect": "Allow",
                        "Resource": [f"arn:aws:s3:::{self.default_bucket}"],
                        "Condition": {
                            "StringLike": {"s3:prefix": [f"{workspace.name}/*"]}
                        },
                    },
                    {
                        "Sid": "AllowAllS3ActionsInWorkspaceFolder",
                        "Action": ["s3:*"],
                        "Effect": "Allow",
                        "Resource": [
                            f"arn:aws:s3:::{self.default_bucket}/{workspace.name}/*"
                        ],
                    },
                ],
            },
        )

        self.mc.admin_policy_set(policy_name, group=workspace.name)

    def enter_workspace(self, ev):
        user_info, workspace = ev
        self.mc.admin_group_add(workspace.name, user_info.id)

    def generate_credential(self):
        user_info = self.core_interface.current_user.get()
        workspace = self.core_interface.current_workspace.get()
        password = generate_password()
        self.mc.admin_user_add(user_info.id, password)
        # Make sure the user is in the workspace
        self.mc.admin_group_add(workspace.name, user_info.id)
        return {
            "endpoint_url": self.endpoint_url,
            "access_key_id": user_info.id,
            "secret_access_key": password,
            "bucket": self.default_bucket,
            "prefix": workspace.name + "/",  # important to have the trailing slash
        }

    async def generate_presigned_url(
        self, bucket_name, object_name, client_method="get_object", expiration=3600
    ):
        try:
            workspace = self.core_interface.current_workspace.get()
            if bucket_name != self.default_bucket or not object_name.startswith(
                workspace.name + "/"
            ):
                raise Exception(
                    f"Permission denied: bucket name must be {self.default_bucket} and the object name should be prefixed with workspace.name + '/'."
                )
            async with self.create_client_async() as s3:
                return await s3.generate_presigned_url(
                    client_method,
                    Params={"Bucket": bucket_name, "Key": object_name},
                    ExpiresIn=expiration,
                )
        except ClientError as e:
            logging.error(e)
            raise

    def get_s3_controller(self):
        return {
            "_rintf": True,
            "generate_credential": self.generate_credential,
            "generate_presigned_url": self.generate_presigned_url,
        }
