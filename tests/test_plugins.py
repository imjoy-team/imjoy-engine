"""Test plugin engine api."""
import pytest
import asyncio

import numpy as np

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

TEST_PLUGIN_SCRIPT = """
import asyncio
import numpy as np
from imjoy import api

class ImJoyPlugin():
    def setup(self):
        api.log('initialized')

    async def run(self, ctx):
        await api.alert('Hello')
        await api.log('done')

    def get_array(self):
        array = np.zeros(10)
        # array[3] = 93834.356
        return {'array': array}

api.export(ImJoyPlugin())
"""


@pytest.fixture(name="test_plugin")
async def setup_test_plugin(client, event_loop):
    """Initialize the plugin."""
    plugin = await client.init_plugin(TEST_PLUGIN_CONFIG)
    return plugin


@pytest.fixture(name="test_plugin_executed")
async def test_plugin_execute(client, test_plugin, event_loop):
    """Test plugin execute."""
    await test_plugin.execute({"type": "script", "content": TEST_PLUGIN_SCRIPT})
    return test_plugin


async def test_plugin_run(client, test_plugin_executed, event_loop):
    """Test run function."""
    api = test_plugin_executed.get_api()
    await api.run({})


async def test_numpy_plugin(client, test_plugin_executed, event_loop):
    """Test get numpy array."""
    api = test_plugin_executed.get_api()
    result = await api.get_array()
    assert np.array_equal(result["array"], np.zeros(10))
