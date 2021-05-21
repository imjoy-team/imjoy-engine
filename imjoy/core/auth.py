"""Provide authentication."""
import json
import logging
import ssl
import sys
import time
import traceback
import uuid
from os import environ as env
from typing import List, Optional
from urllib.request import urlopen

from dotenv import find_dotenv, load_dotenv
from fastapi import Header, HTTPException, Request
from jose import jwt
from pydantic import BaseModel  # pylint: disable=no-name-in-module

from imjoy.core import UserInfo, VisibilityEnum, TokenConfig, all_users, all_workspaces

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("imjoy-core")
logger.setLevel(logging.INFO)

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

AUTH0_DOMAIN = env.get("AUTH0_DOMAIN", "imjoy.eu.auth0.com")
AUTH0_AUDIENCE = env.get("AUTH0_AUDIENCE", "https://imjoy.eu.auth0.com/api/v2/")
JWT_SECRET = env.get("JWT_SECRET")
if not JWT_SECRET:
    logger.warning("JWT_SECRET is not defined")
    JWT_SECRET = str(uuid.uuid4())


class AuthError(Exception):
    """Represent an authentication error."""

    def __init__(self, error, status_code):
        """Set up instance."""
        super().__init__()
        self.error = error
        self.status_code = status_code


class ValidToken(BaseModel):
    """Represent a valid token."""

    credentials: dict
    scopes: List[str] = []

    def has_scope(self, checked_token):
        """Return True if the token has the correct scope."""
        if checked_token in self.scopes:
            return True

        raise HTTPException(
            status_code=403, detail="Not authorized to perform this action"
        )


def login_required(request: Request, authorization: str = Header(None)):
    """Return token if login is ok."""
    return valid_token(authorization, request)


def admin_required(request: Request, authorization: str = Header(None)):
    """Return token if the token has an admin role."""
    token = valid_token(authorization, request)
    roles = token.credentials.get("https://api.imjoy.io/roles", [])
    if "admin" not in roles:
        raise HTTPException(status_code=401, detail="Admin required")
    return token


def is_admin(token):
    """Check if token has an admin role."""
    roles = token.credentials.get("https://api.imjoy.io/roles", [])
    if "admin" not in roles:
        return False
    return True


def get_user_email(token):
    """Return the user email from the token."""
    return token.credentials.get("https://api.imjoy.io/email")


def get_user_id(token):
    """Return the user id from the token."""
    return token.credentials.get("sub")


def get_user_info(token):
    """Return the user info from the token."""
    return {
        "user_id": token.credentials.get("sub"),
        "email": token.credentials.get("https://api.imjoy.io/email"),
        "roles": token.credentials.get("https://api.imjoy.io/roles", []),
    }


JWKS = None


def get_rsa_key(kid, refresh=False):
    """Return an rsa key."""
    global JWKS  # pylint: disable=global-statement
    if JWKS is None or refresh:
        with urlopen(
            f"https://{AUTH0_DOMAIN}/.well-known/jwks.json",
            # pylint: disable=protected-access
            context=ssl._create_unverified_context(),
        ) as jsonurl:
            JWKS = json.loads(jsonurl.read())
    rsa_key = {}
    for key in JWKS["keys"]:
        if key["kid"] == kid:
            rsa_key = {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"],
            }
            break
    return rsa_key


def simulate_user_token(returned_token, request):
    """Allow admin all_users to simulate another user."""
    if "user_id" in request.query_params:
        returned_token.credentials["sub"] = request.query_params["user_id"]
    if "email" in request.query_params:
        returned_token.credentials["https://api.imjoy.io/email"] = request.query_params[
            "email"
        ]
    if "roles" in request.query_params:
        returned_token.credentials["https://api.imjoy.io/roles"] = request.query_params[
            "roles"
        ].split(",")


def valid_token(authorization: str, request: Optional[Request] = None):
    """Validate token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is expected")

    parts = authorization.split()

    if parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401, detail="Authorization header must start with" " Bearer"
        )
    if len(parts) == 1:
        raise HTTPException(status_code=401, detail="Token not found")
    if len(parts) > 2:
        raise HTTPException(
            status_code=401, detail="Authorization header must be 'Bearer' token"
        )

    authorization = parts[1]
    try:
        unverified_header = jwt.get_unverified_header(authorization)

        # Get RSA key
        rsa_key = get_rsa_key(unverified_header["kid"], refresh=False)
        # Try to refresh jwks if failed
        if not rsa_key:
            rsa_key = get_rsa_key(unverified_header["kid"], refresh=True)

        # Decode token
        payload = jwt.decode(
            authorization,
            rsa_key,
            algorithms=["RS256"],
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/",
        )

        returned_token = ValidToken(
            credentials=payload, scopes=payload["scope"].split(" ")
        )

        # This is needed for patching the test token
        if "create:roles" in payload["scope"]:
            if "https://api.imjoy.io/roles" not in returned_token.credentials:
                returned_token.credentials["https://api.imjoy.io/roles"] = ["admin"]
            if "https://api.imjoy.io/email" not in returned_token.credentials:
                returned_token.credentials["https://api.imjoy.io/email"] = None

        if (
            "admin" in returned_token.credentials["https://api.imjoy.io/roles"]
            and request
        ):
            simulate_user_token(returned_token, request)

        return returned_token

    except jwt.ExpiredSignatureError as err:
        raise HTTPException(
            status_code=401, detail="The token has expired. Please fetch a new one"
        ) from err
    except jwt.JWTError as err:
        raise HTTPException(status_code=401, detail=traceback.format_exc()) from err


def parse_token(authorization):
    """Parse the token."""
    parts = authorization.split()
    if parts[0].lower() != "bearer":
        raise Exception("Authorization header must start with" " Bearer")
    if len(parts) == 1:
        raise Exception("Token not found")
    if len(parts) > 2:
        raise Exception("Authorization header must be 'Bearer' token")

    token = parts[1]
    if not token.startswith("imjoy@"):
        # auth0 token
        return get_user_info(valid_token(authorization))
    # generated token
    token = token.lstrip("imjoy@")
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


def generate_presigned_token(user_info: UserInfo, config: TokenConfig):
    """Generate presigned tokens.

    This will generate a token which will be connected as a child user.
    Child user may generate more child user token if it has admin permission.
    """
    scopes = config.scopes
    for scope in scopes:
        if not check_permission(scope, user_info):
            raise PermissionError(f"User has no permission to scope: {scope}")

    # always generate a new user id
    uid = str(uuid.uuid4())
    expires_in = config.expires_in
    if expires_in:
        expires_at = time.time() + expires_in
    else:
        expires_at = None
    token = jwt.encode(
        {
            "scopes": scopes,
            "expires_at": expires_at,
            "user_id": uid,
            "parent": user_info.parent if user_info.parent else user_info.id,
            "email": config.email,
            "roles": [],
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"token": "imjoy@" + token, "id": uid}


def check_permission(workspace, user_info):
    """Check user permission for a workspace."""
    # pylint: disable=too-many-return-statements
    if isinstance(workspace, str):
        workspace = all_workspaces.get(workspace)
        if not workspace:
            logger.warning("Workspace %s not found", workspace)
            return False

    if workspace.name == user_info.id:
        return True

    if user_info.parent:
        parent = all_users.get(user_info.parent)
        if not parent:
            return False
        if not check_permission(workspace, parent):
            return False
        # if the parent has access
        # and the workspace is in the scopes
        # then we allow the access
        if workspace.name in user_info.scopes:
            return True

    _id = user_info.email or user_info.id

    if _id in workspace.owners:
        return True

    if workspace.visibility == VisibilityEnum.public:
        if workspace.deny_list and user_info.email not in workspace.deny_list:
            return True
    elif workspace.visibility == VisibilityEnum.protected:
        if workspace.allow_list and user_info.email in workspace.allow_list:
            return True

    if "admin" in user_info.roles:
        logger.info(
            "Allowing access to %s for admin user %s", workspace.name, user_info.id
        )
        return True

    return False
