"""SpiderVIP Console — unified local dashboard (phase 1).

Product UI name: **SpiderVIP Console** / **کنسول SpiderVIP**

Phase 1 mounts the existing Frequency Manager and Channel dashboards behind one
host/port with a shared shell. Shared receiver connection (phase 2) comes later.
"""

from .server import run_console

__all__ = ["PRODUCT_NAME", "PRODUCT_NAME_FA", "run_console"]

PRODUCT_NAME = "SpiderVIP Console"
PRODUCT_NAME_FA = "کنسول SpiderVIP"
