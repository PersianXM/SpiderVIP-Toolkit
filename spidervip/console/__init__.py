"""SpiderVIP Console — unified local dashboard.

Product UI name: **SpiderVIP Console** / **کنسول SpiderVIP**

- Phase 1: one host/port mounting Frequency + Channels UIs
- Phase 2: shared receiver connection panel/API for both workspaces
"""

from .server import run_console

__all__ = ["PRODUCT_NAME", "PRODUCT_NAME_FA", "run_console"]

PRODUCT_NAME = "SpiderVIP Console"
PRODUCT_NAME_FA = "کنسول SpiderVIP"
