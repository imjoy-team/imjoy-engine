import json
import traceback
from typing import Optional, Any


import msgpack
from fastapi import APIRouter, Request
from fastapi.responses import Response, JSONResponse


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
    if isinstance(obj, (int, float, str, bool)):
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


class HTTPProxy:
    """File System Controller."""

    def __init__(self, event_bus, core_interface):
        router = APIRouter()

        @router.get("/services")
        def get_all_services():
            try:
                # REMOVE THIS IN PRODUCTION
                core_interface.current_user.set(core_interface.root_user)
                services = core_interface.list_services()
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

        @router.get("/services/{workspace}")
        def get_workspace_services(workspace: str):
            try:
                # REMOVE THIS IN PRODUCTION
                core_interface.current_user.set(core_interface.root_user)
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

        @router.get("/services/{workspace}/{service}")
        async def get_service_info(workspace: str, service: str):
            try:
                # REMOVE THIS IN PRODUCTION
                core_interface.current_user.set(core_interface.root_user)
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

        @router.get("/services/{workspace}/{service}/{keys}")
        @router.post("/services/{workspace}/{service}/{keys}")
        async def service_function(
            workspace: str, service: str, keys: str, request: Request
        ):
            """Get function info, keys can contain dot to refer deeper object"""
            try:
                # REMOVE THIS IN PRODUCTION
                core_interface.current_user.set(core_interface.root_user)
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
