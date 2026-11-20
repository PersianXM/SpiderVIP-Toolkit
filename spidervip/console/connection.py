"""Shared receiver connection state for SpiderVIP Console (phase 2)."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
# Fixed to the toolkit root (where RUN.bat runs), not the caller's cwd, so a
# launch from another folder does not silently start from a fresh default file.
DEFAULT_STORE_PATH = TOOLKIT_ROOT / ".spidervip_console" / "connection.json"

DEFAULT_HOST = "192.168.100.102"
DEFAULT_USER = "root"
DEFAULT_PASS = "root"


@dataclass
class ReceiverConnection:
    host: str = DEFAULT_HOST
    user: str = DEFAULT_USER
    password: str = DEFAULT_PASS
    # Channels backend mode chosen in the Console shell ("حالت شبیه‌ساز کانال").
    # Mounted UIs must honour it instead of forcing live mode on page load.
    simulate: bool = False

    def normalized(self) -> "ReceiverConnection":
        return ReceiverConnection(
            host=(self.host or "").strip() or DEFAULT_HOST,
            user=(self.user or "").strip() or DEFAULT_USER,
            password=self.password if self.password is not None else DEFAULT_PASS,
            simulate=bool(self.simulate),
        )

    def public_dict(self) -> Dict[str, Any]:
        """Fields safe to show in UI (includes password for local-tool use)."""
        c = self.normalized()
        return {"host": c.host, "user": c.user, "password": c.password, "simulate": c.simulate}

    def inject_dict(self) -> Dict[str, Any]:
        return self.public_dict()


class ConnectionStore:
    """Process-wide connection settings with optional JSON persistence."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or DEFAULT_STORE_PATH)
        self._lock = threading.Lock()
        self._conn = ReceiverConnection()
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._conn = ReceiverConnection(
                host=str(data.get("host") or DEFAULT_HOST),
                user=str(data.get("user") or DEFAULT_USER),
                password=str(data.get("password") if data.get("password") is not None else DEFAULT_PASS),
                simulate=bool(data.get("simulate", False)),
            ).normalized()
        except Exception:
            self._conn = ReceiverConnection()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._conn.public_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get(self) -> ReceiverConnection:
        with self._lock:
            return ReceiverConnection(**asdict(self._conn))

    def set(
        self,
        *,
        host: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        simulate: Optional[bool] = None,
        persist: bool = True,
    ) -> ReceiverConnection:
        with self._lock:
            cur = self._conn
            self._conn = ReceiverConnection(
                host=cur.host if host is None else host,
                user=cur.user if user is None else user,
                password=cur.password if password is None else password,
                simulate=cur.simulate if simulate is None else bool(simulate),
            ).normalized()
            if persist:
                self._save()
            return ReceiverConnection(**asdict(self._conn))


def probe_connection(conn: ReceiverConnection) -> Dict[str, Any]:
    """Best-effort TCP probe of Telnet / FTP / WebIF.

    The three ports are probed in parallel, so an offline receiver costs about
    one timeout (~2 s) instead of three in a row (~6 s) on every shell load.
    """
    from concurrent.futures import ThreadPoolExecutor

    from spidervip.channels.telnet_ftp import probe_tcp

    c = conn.normalized()
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="console-probe") as pool:
        futs = {port: pool.submit(probe_tcp, c.host, port, 2.0) for port in (23, 21, 80)}
        telnet = bool(futs[23].result())
        ftp = bool(futs[21].result())
        webif = bool(futs[80].result())
    online = bool(telnet or ftp or webif)
    if online:
        parts = []
        if telnet:
            parts.append("Telnet")
        if ftp:
            parts.append("FTP")
        if webif:
            parts.append("WebIF")
        label = f"رسیور در دسترس ({c.host}) — " + "، ".join(parts)
    else:
        label = f"رسیور در دسترس نیست ({c.host})"
    return {
        "online": online,
        "host": c.host,
        "telnet": telnet,
        "ftp": ftp,
        "webif": webif,
        "label": label,
    }
