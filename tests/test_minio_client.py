import pytest
import subprocess
import tempfile
import requests
import time
import os
import shutil
from requests import RequestException
import uuid

from imjoy.minio import setup_minio_executables, MinioController

PORT = 38483
BASE_URL = f"http://127.0.0.1:{PORT}"
ROOT_USER = "minio"
ROOT_PASSWORD = str(uuid.uuid4())


@pytest.fixture(name="minio_server")
def minio_server_fixture():
    """Start minio server as test fixture and tear down after test."""
    setup_minio_executables()
    dirpath = tempfile.mkdtemp()
    my_env = os.environ.copy()
    my_env["MINIO_ROOT_USER"] = ROOT_USER
    my_env["MINIO_ROOT_PASSWORD"] = ROOT_PASSWORD
    with subprocess.Popen(
        [
            "./bin/minio",
            "server",
            f"--address=:{PORT}",
            f"--console-address=:{PORT+1}",
            f"{dirpath}",
        ],
        env=my_env,
    ) as proc:

        timeout = 10
        while timeout > 0:
            try:
                response = requests.get(f"{BASE_URL}/minio/health/live")
                if response.ok:
                    break
            except RequestException:
                pass
            timeout -= 0.1
            time.sleep(0.1)
        yield

        proc.terminate()
        shutil.rmtree(dirpath)


def find_item(items, key, value):
    filtered = [item for item in items if item[key] == value]
    if len(filtered) == 0:
        return None
    else:
        return filtered[0]


def test_minio(minio_server):
    mc = MinioController(
        BASE_URL,
        ROOT_USER,
        ROOT_PASSWORD,
    )
    username = "tmp-user"
    username2 = "tmp-user-2"
    # print(mc.ls("/", recursive=True))
    mc.admin_user_add(username, "239udslfj3")
    mc.admin_user_add(username2, "234slfj3")
    user_list = mc.admin_user_list()

    assert len(user_list) == 2
    assert find_item(user_list, "accessKey", username)
    assert find_item(user_list, "accessKey", username2)
    mc.admin_user_disable(username)
    user_list = mc.admin_user_list()
    user1 = find_item(user_list, "accessKey", username)
    assert user1["userStatus"] == "disabled"
    mc.admin_user_enable(username)
    user_list = mc.admin_user_list()
    user1 = find_item(user_list, "accessKey", username)
    assert user1["userStatus"] == "enabled"
    user = mc.admin_user_info(username)
    assert user["userStatus"] == "enabled"
    mc.admin_user_remove(username2)
    user_list = mc.admin_user_list()
    assert find_item(user_list, "accessKey", username2) is None

    mc.admin_group_add("my-group", username)
    ginfo = mc.admin_group_info("my-group")
    assert ginfo["groupName"] == "my-group"
    assert username in ginfo["members"]
    assert ginfo["groupStatus"] == "enabled"

    mc.admin_group_disable("my-group")
    ginfo = mc.admin_group_info("my-group")
    assert ginfo["groupStatus"] == "disabled"

    mc.admin_user_add(username2, "234slfj3")
    mc.admin_group_add("my-group", username2)
    userinfo = mc.admin_user_info(username2)
    assert "my-group" in userinfo["memberOf"]

    ginfo = mc.admin_group_info("my-group")
    assert username in ginfo["members"] and username2 in ginfo["members"]

    mc.admin_group_enable("my-group")
    ginfo = mc.admin_group_info("my-group")
    assert ginfo["groupStatus"] == "enabled"

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
    policy_list = mc.admin_policy_list()
    print(policy_list)
    assert find_item(policy_list, "policy", "admins")

    mc.admin_policy_set("admins", user=username)
    userinfo = mc.admin_user_info(username)
    assert userinfo["policyName"] == "admins"

    mc.admin_policy_set("admins", group="my-group")
    ginfo = mc.admin_group_info("my-group")
    assert ginfo['groupPolicy'] == 'admins'

