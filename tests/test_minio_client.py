import pytest
from imjoy.minio import MinioClient
from . import MINIO_SERVER_URL, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, find_item

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_minio(minio_server):
    mc = MinioClient(
        MINIO_SERVER_URL,
        MINIO_ROOT_USER,
        MINIO_ROOT_PASSWORD,
    )
    username = "tmp-user"
    username2 = "tmp-user-2"
    # print(mc.ls("/", recursive=True))
    mc.admin_user_add(username, "239udslfj3")
    # overwrite the password
    mc.admin_user_add(username, "23923432423j3")
    mc.admin_user_add(username2, "234slfj3")
    user_list = mc.admin_user_list()

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

    mc.admin_group_add("my-group", username)

    mc.admin_group_disable("my-group")
    ginfo = mc.admin_group_info("my-group")
    assert ginfo["groupStatus"] == "disabled"

    mc.admin_group_remove("my-group", ginfo["members"])
    ginfo = mc.admin_group_info("my-group")
    assert ginfo.get("members") is None

    # remove empty group
    mc.admin_group_remove("my-group")
    with pytest.raises(Exception, match=r".*Failed to run mc command*"):
        mc.admin_group_info("my-group")

    mc.admin_group_add("my-group", username)

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
    assert ginfo["groupPolicy"] == "admins"
