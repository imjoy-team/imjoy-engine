import os
from pathlib import Path
from . import SIO_SERVER_URL
import requests
import pytest
from imjoy_rpc import connect_to_server

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio
