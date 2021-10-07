import json
import traceback
from typing import Optional, Any
from starlette.types import Receive, Scope, Send

import msgpack
from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response, JSONResponse
from imjoy.core import get_workspace
from imjoy.core.auth import login_optional


class MsgpackResponse(Response):
    media_type = "application/msgpack"

    def render(self, content: Any) -> bytes:
        return msgpack.dumps(content)


def normalize(s):
    if s.isnumeric():
        return int(s)
    else:
        try:
            return float(s)
        except ValueError:
            return s


def serialize(obj):
    if obj is None:
        return None
    if isinstance(obj, (int, float, tuple, str, bool)):
        return obj
    elif isinstance(obj, dict):
        return {k: serialize(obj[k]) for k in obj}
    elif isinstance(obj, list):
        return [serialize(k) for k in obj]
    elif callable(obj):
        return f"<function: {str(obj)}>"
    else:
        raise ValueError(f"unsupported data type: {type(obj)}")


def get_value(keys, service):
    keys = keys.split(".")
    key = keys[0]
    value = service[key]
    if len(keys) > 1:
        for key in keys[1:]:
            value = value.get(key)
            if value is None:
                break
    return value


class RemoteResponse(Response):
    chunk_size = 4096

    def __init__(self, app, **kwargs) -> None:
        self.app = app
        assert self.app.serve is not None, "No serve function defined"
        super().__init__(**kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope = {
            k: scope[k]
            for k in scope
            if isinstance(scope[k], (str, int, float, bool, tuple, list, dict))
        }
        # TODO: we need to dispose the interface after the send function if done
        await self.app.serve(
            {"scope": scope, "receive": receive, "send": send, "_rintf": True}
        )
        # await send(
        #     {
        #         "type": "http.response.start",
        #         "status": 200,
        #         "headers": scope["headers"],
        #     }
        # )
        # if self.send_header_only:
        #     await send(
        #         {"type": "http.response.body", "body": b"", "more_body": False}
        #     )
        # else:
        #     await send(
        #         {
        #             "type": "http.response.body",
        #             "body": chunk,
        #             "more_body": sent_size < total_size,
        #         }
        #     )


class HTTPProxy:
    """File System Controller."""

    def __init__(self, event_bus, core_interface):
        router = APIRouter()

        @router.get("/services")
        def get_all_services(
            user_info: login_optional = Depends(login_optional),
        ):
            try:
                core_interface.current_user.set(user_info)
                services = core_interface.list_services()
                info = serialize(services)
                return JSONResponse(
                    status_code=200,
                    content=info,
                )
            except Exception as exp:
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "detail": str(exp)},
                )

        @router.get("/{workspace}/app/{app}")
        async def call_app_api(
            workspace: str,
            app: str,
            user_info: login_optional = Depends(login_optional),
        ):
            try:
                core_interface.current_user.set(user_info)
                ws = get_workspace(workspace)
                core_interface.current_workspace.set(ws)
                if not ws:
                    return JSONResponse(
                        status_code=404,
                        content={
                            "success": False,
                            "detail": f"Workspace does not exists: {ws}",
                        },
                    )
                plugin = await core_interface.get_plugin(app)
                if not plugin:
                    raise Exception("App not found: " + app)
                return RemoteResponse(plugin)
            except Exception as exp:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "detail": str(exp)},
                )

        @router.get("/{workspace}/services")
        def get_workspace_services(
            workspace: str,
            user_info: login_optional = Depends(login_optional),
        ):
            try:
                core_interface.current_user.set(user_info)
                services = core_interface.list_services({"workspace": workspace})
                info = serialize(services)
                return JSONResponse(
                    status_code=200,
                    content=info,
                )
            except Exception as exp:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "detail": str(exp)},
                )

        @router.get("/{workspace}/services/{service}")
        async def get_service_info(
            workspace: str,
            service: str,
            user_info: login_optional = Depends(login_optional),
        ):
            try:
                core_interface.current_user.set(user_info)
                service = await core_interface.get_service(f"{workspace}/{service}")
                info = serialize(service)
                return JSONResponse(
                    status_code=200,
                    content=info,
                )
            except Exception as exp:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "detail": str(exp)},
                )

        @router.get("/{workspace}/services/{service}/{keys}")
        @router.post("/{workspace}/services/{service}/{keys}")
        async def service_function(
            workspace: str,
            service: str,
            keys: str,
            request: Request,
            user_info: login_optional = Depends(login_optional),
        ):
            """Get function info, keys can contain dot to refer deeper object"""
            try:
                core_interface.current_user.set(user_info)
                service = await core_interface.get_service(f"{workspace}/{service}")
                value = get_value(keys, service)
                if not value:
                    return JSONResponse(
                        status_code=200,
                        content={"success": False, "detail": f"{keys} not found."},
                    )
                content_type = request.headers.get("content-type", "application/json")
                if request.method == "GET":
                    kwargs = list(request.query_params.items())
                    kwargs = {
                        kwargs[k][0]: normalize(kwargs[k][1])
                        for k in range(len(kwargs))
                    }
                elif request.method == "POST":
                    if content_type == "application/msgpack":
                        kwargs = msgpack.loads(await request.body())
                    elif content_type == "application/json":
                        kwargs = json.loads(await request.body())
                    else:
                        return JSONResponse(
                            status_code=500,
                            content={
                                "success": False,
                                "detail": f"Invalid content-type (supported types: application/msgpack, application/json, text/plain)",
                            },
                        )
                else:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "success": False,
                            "detail": f"Invalid request method: {request.method}",
                        },
                    )
                if callable(value):
                    try:
                        result = await value(**kwargs)
                    except Exception:
                        return JSONResponse(
                            status_code=500,
                            content={
                                "success": False,
                                "detail": traceback.format_exc(),
                            },
                        )

                    if request.method == "GET":
                        return JSONResponse(
                            status_code=200,
                            content=result,
                        )
                    elif request.method == "POST":
                        if content_type == "application/json":
                            return JSONResponse(
                                status_code=200,
                                content=result,
                            )
                        elif content_type == "application/msgpack":
                            return MsgpackResponse(
                                status_code=200,
                                content=result,
                            )
                else:
                    return JSONResponse(status_code=200, content=serialize(value))

            except Exception:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "detail": traceback.format_exc()},
                )

        core_interface.register_router(router)
