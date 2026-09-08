"""Configure the environment before server.server is imported.

The server reads its API keys at import time and only registers tools when they
are present, so the keys must exist before the module is first imported.
"""

import os

os.environ.setdefault("WINDY_POINT_API_KEY", "test-point-key")
os.environ.setdefault("WINDY_MAP_API_KEY", "test-map-key")
