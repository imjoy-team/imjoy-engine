import json
import re
import os
import sys
import subprocess
import logging
import tempfile
import urllib.request
import stat

logging.basicConfig(stream=sys.stdout)
logger = logging.getLogger("mc-utils")
logger.setLevel(logging.INFO)

MATH_PATTERN = re.compile("{(.+?)}")

EXECUTABLE_PATH = "bin"


def setup_minio_executables():
    os.makedirs(EXECUTABLE_PATH, exist_ok=True)
    assert (
        sys.platform == "linux"
    ), "Manual setup required to, please download minio and minio client from https://min.io/ and place them under ./bin"
    mc_path = EXECUTABLE_PATH + "/mc"
    minio_path = EXECUTABLE_PATH + "/minio"
    if not os.path.exists(minio_path):
        print("Minio server executable not found, downloading... ")
        urllib.request.urlretrieve(
            "https://dl.min.io/server/minio/release/linux-amd64/minio", minio_path
        )

    if not os.path.exists(mc_path):
        print("Minio client executable not found, downloading... ")
        urllib.request.urlretrieve(
            "https://dl.min.io/client/mc/release/linux-amd64/mc", mc_path
        )

    st = os.stat(minio_path)
    if not bool(st.st_mode & stat.S_IEXEC):
        os.chmod(minio_path, st.st_mode | stat.S_IEXEC)
    st = os.stat(mc_path)
    if not bool(st.st_mode & stat.S_IEXEC):
        os.chmod(mc_path, st.st_mode | stat.S_IEXEC)

    print("Minio executable are ready.")


def kwarg_to_flag(**kwargs):
    _args = []
    for _key, _value in kwargs.items():
        key = "--" + _key.replace("_", "-")
        if _value in (True, False):
            _args.append(key)
        else:
            _args.append(f"{key} {_value}")
    return " ".join(_args)


def flag_to_kwarg(flag):
    _flag, *_value = flag.split()
    flag_name = _flag.replace("--", "").replace("-", "_")
    if _value:
        value = _value.pop()
    else:
        value = True
    return {flag_name: value}


def convert_to_json(subprocess_output, wrap=True, pair=("[", "]")):
    s = subprocess_output.strip("\n")
    s = s.replace("\n", ",")
    s = s.replace("{,", "{")
    s = s.replace(",}", "}")
    preprocessed = s.replace(",,", ",")
    try:
        json.loads(preprocessed)
    except json.JSONDecodeError:
        opening, closing = pair
        sequence_to_load = f"{opening}{preprocessed}{closing}"
    else:
        sequence_to_load = preprocessed
    return json.loads(sequence_to_load)


def generate_command(cmd_template, **kwargs):
    params = MATH_PATTERN.findall(cmd_template)
    cmd_params = dict(zip(params, [None] * len(params)))
    _args = {key: value for key, value in kwargs.items() if key not in cmd_params}
    flags = kwarg_to_flag(**_args)
    kwargs.setdefault("flags", flags)
    return cmd_template.format(**kwargs)


def execute_command(cmd_template, mc_executable=EXECUTABLE_PATH + "/mc", **kwargs):
    command_string = generate_command(cmd_template, json=True, **kwargs)
    # override the executable
    command_string = mc_executable + command_string.lstrip("mc")
    try:
        _output = subprocess.check_output(
            command_string.split(),
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        output = e.output.decode("utf-8")
        status = "failed"
        content = output
    else:
        output = _output.decode("utf-8")
        try:
            content = convert_to_json(output)
            if isinstance(content, dict):
                status = content.get("status", "success")
            else:
                status = "success"
        except json.decoder.JSONDecodeError:
            status = "success"
            content = output

    if status == "success":
        logger.info(f"mc command[status='{status}', command='{command_string}']")
    else:
        if isinstance(content, dict):
            message = content.get("error", {}).get("message", "")
            cause = content.get("error", {}).get("cause", {}).get("message", "")
        else:
            message = str(content)
            cause = ""
        logger.error(
            f"mc command[status='{status}', message='{message}', cause='{cause}', command='{command_string}']"
        )
        raise Exception(
            f"Failed to run mc command: ${command_string}, message='{message}', cause='{cause}'"
        )
    return content


class MinioController:
    """A client class for managing minio"""

    def __init__(
        self,
        endpoint_url,
        access_key_id,
        secret_access_key,
        alias="s3",
        mc_executable=EXECUTABLE_PATH + "/mc",
        **kwargs,
    ):
        setup_minio_executables()
        self.alias = alias
        self.mc_executable = mc_executable
        self.execute(
            "mc alias set {alias} {endpoint_url} {username} {password}",
            alias=self.alias,
            endpoint_url=endpoint_url,
            username=access_key_id,
            password=secret_access_key,
            **kwargs,
        )

    def execute(self, *args, **kwargs):
        if "target" in kwargs:

            kwargs["target"] = self.alias + "/" + kwargs["target"].lstrip("/")
        return execute_command(*args, mc_executable=self.mc_executable, **kwargs)

    def ls(self, target, **kwargs):
        """List files on MinIO"""
        return self.execute("mc ls {flags} {target}", target=target, **kwargs)

    def admin_user_add(self, username, password, **kwargs):
        """Add a new user on MinIO."""
        return self.execute(
            "mc {flags} admin user add {alias} {username} {password}",
            alias=self.alias,
            username=username,
            password=password,
            **kwargs,
        )

    def admin_user_remove(self, username, **kwargs):
        """Remove user on MinIO."""
        return self.execute(
            "mc {flags} admin user remove {alias} {username}",
            alias=self.alias,
            username=username,
            **kwargs,
        )

    def admin_user_enable(self, username, **kwargs):
        """Enable a user on MinIO."""
        return self.execute(
            "mc {flags} admin user enable {alias} {username}",
            alias=self.alias,
            username=username,
            **kwargs,
        )

    def admin_user_disable(self, username, **kwargs):
        """Disable a user on MinIO."""
        return self.execute(
            "mc {flags} admin user disable {alias} {username}",
            alias=self.alias,
            username=username,
            **kwargs,
        )

    def admin_user_list(self, **kwargs):
        """List all users on MinIO."""
        ret = self.execute(
            "mc {flags} admin user list {alias}", alias=self.alias, **kwargs
        )
        if isinstance(ret, dict):
            ret = [ret]
        return ret

    def admin_user_info(self, username, **kwargs):
        """Display info of a user."""
        return self.execute(
            "mc {flags} admin user info {alias} {username}",
            alias=self.alias,
            username=username,
            **kwargs,
        )

    def admin_group_add(self, group, members, **kwargs):
        """Adds a user to a group on the MinIO deployment.
        Creates the group if it does not exist."""
        if not isinstance(members, str):
            members = " ".join(members)

        return self.execute(
            "mc {flags} admin group add {alias} {group} {members}",
            alias=self.alias,
            group=group,
            members=members,
            **kwargs,
        )

    def admin_group_remove(self, group, members, **kwargs):
        """Remove group or members from a group."""
        if not isinstance(members, str):
            members = " ".join(members)

        return self.execute(
            "mc {flags} admin group remove {alias} {group} {members}",
            alias=self.alias,
            group=group,
            members=members ** kwargs,
        )

    def admin_group_info(self, group, **kwargs):
        """Display group info."""
        return self.execute(
            "mc {flags} admin group info {alias} {group}",
            alias=self.alias,
            group=group,
            **kwargs,
        )

    def admin_group_list(self, **kwargs):
        """Display list of groups."""
        ret = self.execute(
            "mc {flags} admin group list {alias}", alias=self.alias, **kwargs
        )
        if isinstance(ret, dict):
            ret = [ret]
        return ret

    def admin_group_enable(self, group, **kwargs):
        """Enable a group."""
        return self.execute(
            "mc {flags} admin group enable {alias} {group}",
            alias=self.alias,
            group=group,
            **kwargs,
        )

    def admin_group_disable(self, group, **kwargs):
        """Disable a group."""
        return self.execute(
            "mc {flags} admin group disable {alias} {group}",
            alias=self.alias,
            group=group,
            **kwargs,
        )

    def admin_policy_add(self, name, policy, **kwargs):
        """Add new canned policy on MinIO."""
        if isinstance(policy, dict):
            content = json.dumps(policy)
            with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
                print(tmp.name)
                tmp.write(content.encode("utf-8"))
                tmp.flush()
                file = tmp.name
                return self.execute(
                    "mc {flags} admin policy add {alias} {name} {file}",
                    alias=self.alias,
                    name=name,
                    file=file,
                    **kwargs,
                )
        else:
            file = policy
            return self.execute(
                "mc {flags} admin policy add {alias} {name} {file}",
                alias=self.alias,
                name=name,
                file=file,
                **kwargs,
            )

    def admin_policy_remove(self, name, **kwargs):
        """Remove canned policy from MinIO."""
        return self.execute(
            "mc {flags} admin policy remove {alias} {name}",
            alias=self.alias,
            name=name,
            **kwargs,
        )

    def admin_policy_list(self, **kwargs):
        """List all policies on MinIO."""
        ret = self.execute(
            "mc {flags} admin policy list {alias}", alias=self.alias, **kwargs
        )
        if isinstance(ret, dict):
            ret = [ret]
        return ret

    def admin_policy_info(self, name, **kwargs):
        """Show info on a policy."""
        return self.execute(
            "mc {flags} admin policy info {alias} {name}",
            alias=self.alias,
            name=name,
            **kwargs,
        )

    def admin_policy_set(self, name, **kwargs):
        """Set IAM policy on a user or group."""

        if {"user", "group"}.issubset(kwargs.keys()):
            raise KeyError("Only one of user or group arguments can be set.")

        if "group" in kwargs:
            return self.execute(
                "mc {flags} admin policy set {alias} {name} group={group}",
                alias=self.alias,
                name=name,
                **kwargs,
            )
        else:
            return self.execute(
                "mc {flags} admin policy set {alias} {name} user={user}",
                alias=self.alias,
                name=name,
                **kwargs,
            )


if __name__ == "__main__":
    mc = MinioController(
        "http://127.0.0.1:9555",
        "minio",
        "miniostorage",
    )
    username = "tmp-user"
    # print(mc.ls("/", recursive=True))
    mc.admin_user_add(username, "239udslfj3")
    mc.admin_user_add(username + "2", "234slfj3")
    user_list = mc.admin_user_list()
    assert len(user_list) >= 2
    mc.admin_user_disable(username)
    print(mc.admin_user_list())
    mc.admin_user_enable(username)
    print(mc.admin_user_info(username))
    print(mc.admin_user_list())

    mc.admin_user_remove(username + "2")
    print(mc.admin_user_list())
    mc.admin_policy_add(
        "admins",
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListAllMyBuckets"],
                    "Resource": ["arn:aws:s3:::*"],
                }
            ],
        },
    )
    response = mc.admin_policy_info("admins")
    assert response["policy"] == "admins"
    response = mc.admin_policy_list()
    assert len(response) > 1
    mc.admin_policy_set("admins", user=username)
    response = mc.admin_user_info(username)
    assert response["policyName"] == "admins"
    # mc.admin_policy_remove("admins")
    # mc.admin_user_remove(username)
    # print("Done")
