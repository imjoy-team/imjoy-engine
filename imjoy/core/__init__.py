"""Provide the ImJoy core API interface."""
from enum import Enum
from contextvars import ContextVar
from typing import Any, Callable, Dict, List, Optional

from pydantic import (  # pylint: disable=no-name-in-module
    BaseModel,
    EmailStr,
    PrivateAttr,
)


class TokenConfig(BaseModel):
    """Represent a token configuration."""

    scopes: List[str]
    expires_in: Optional[int]
    email: Optional[EmailStr]


class VisibilityEnum(str, Enum):
    """Represent the visibility of the workspace."""

    public = "public"
    protected = "protected"


class UserInfo(BaseModel):
    """Represent user info."""

    id: str
    roles: List[str]
    email: Optional[EmailStr]
    parent: Optional[str]
    scopes: Optional[List[str]]  # a list of workspace
    expires_at: Optional[int]
    _plugins: Dict[str, Any] = PrivateAttr(default_factory=lambda: {})  # id:plugin
    _sessions: List[str] = PrivateAttr(default_factory=lambda: [])  # session ids


class WorkspaceInfo(BaseModel):
    """Represent a workspace."""

    name: str
    persistent: bool
    owners: List[str]
    visibility: VisibilityEnum
    description: Optional[str]
    icon: Optional[str]
    covers: Optional[List[str]]
    docs: Optional[str]
    allow_list: Optional[List[str]]
    deny_list: Optional[List[str]]
    authorizer: Optional[str]
    _authorizer: Optional[Callable] = PrivateAttr(default_factory=lambda: None)
    _plugins: Dict[str, Any] = PrivateAttr(default_factory=lambda: {})  # name: plugin
    _services: List[Dict[str, Any]] = PrivateAttr(default_factory=lambda: [])


current_user = ContextVar("current_user")
current_plugin = ContextVar("current_plugin")
current_workspace = ContextVar("current_workspace")
all_sessions: Dict[str, UserInfo] = {}  # sid:user_info
all_users: Dict[str, UserInfo] = {}  # uid:user_info
all_workspaces: Dict[str, WorkspaceInfo] = {}  # wid:workspace_info
