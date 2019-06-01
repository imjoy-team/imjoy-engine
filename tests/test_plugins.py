"""Test plugin engine api."""
import pytest

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio  # pylint: disable=invalid-name

TEST_PLUGIN_CONFIG = {
    "name": "test-plugin",
    "type": "native-python",
    "version": "0.1.12",
    "api_version": "0.1.2",
    "description": "This is a test plugin.",
    "tags": ["CPU", "GPU", "macOS CPU"],
    "ui": "",
    "inputs": None,
    "outputs": None,
    "flags": [],
    "icon": None,
    "env": "",
    "requirements": "",
    "dependencies": [],
}


@pytest.fixture(name="test_plugin")
async def setup_test_plugin(client, event_loop):
    """Initialize the plugin."""
    plugin = await client.init_plugin(TEST_PLUGIN_CONFIG)
    return plugin


async def test_plugin_execute(client, test_plugin, event_loop):
    """Test plugin execute."""
    result = await test_plugin.execute({"type": "script", "content": "print('hello')"})
    assert result == {"type": "executeSuccess"}
