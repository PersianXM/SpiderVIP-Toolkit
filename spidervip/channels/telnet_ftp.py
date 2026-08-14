"""Lightweight Telnet + FTP helpers (stdlib only)."""

from __future__ import annotations

import base64
import ftplib
import re
import socket
import time
from io import BytesIO
from typing import Iterable, List, Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class TelnetClient:
    """Minimal interactive Telnet client for SpiderVIP-class boxes.

    Command completion uses a split ``echo`` marker so the shell's echoed
    command line cannot false-match the end token (same trick as
    ``tools/telnet_run.py``).
    """

    def __init__(
        self,
        host: str,
        port: int = 23,
        username: str = "root",
        password: str = "root",
        timeout: float = 10.0,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._cmd_seq = 0

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock = sock
        self._recv_until((b"login:", b"ogin:"))
        self._send(self.username + "\r\n")
        self._recv_until((b"assword:",))
        self._send(self.password + "\r\n")
        buf = self._recv_until((b"# ", b"#\r", b"~#", b"incorrect"))
        if b"incorrect" in buf.lower():
            raise RuntimeError("Telnet login failed: incorrect credentials")
        self._send("export PS1='PROMPT> '\r\n")
        self._recv_until((b"PROMPT> ",))

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def run(self, command: str, timeout: float = 60.0) -> str:
        if self._sock is None:
            raise RuntimeError("not connected")
        self._cmd_seq += 1
        seq = self._cmd_seq
        # Contiguous token appears only in stdout of echo, not in the echoed cmdline.
        token = f"MK{seq}END"
        self._send(command + "\r\n")
        self._send(f'echo "MK""{seq}""END"\r\n')
        raw = self._recv_until((token.encode("ascii"),), timeout=timeout)
        text = strip_ansi(raw.decode("utf-8", "replace"))
        return self._extract_output(text, command=command, token=token)

    def read_file(self, remote_path: str, timeout: float = 120.0) -> str:
        """Read a remote text file via base64 over Telnet (no FTP required)."""

        # Use printf/base64; fall back to cat if base64 missing.
        encoded = self.run(
            f'if command -v base64 >/dev/null 2>&1; then base64 "{remote_path}"; '
            f'else cat "{remote_path}"; fi',
            timeout=timeout,
        )
        # If it looks like base64 (single long lines, no #NAME), try decode
        compact = "".join(encoded.split())
        if compact and re.fullmatch(r"[A-Za-z0-9+/=]+", compact) and "#NAME" not in encoded:
            try:
                return base64.b64decode(compact).decode("utf-8", "replace")
            except Exception:
                pass
        return encoded

    def write_file(self, remote_path: str, content: str, timeout: float = 30.0) -> None:
        """Write a remote text file via base64 over Telnet (no FTP required)."""

        payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
        # Larger chunks = far fewer Telnet round-trips. satellites.xml is often
        # hundreds of KB; 200-byte chunks made Frequency deploy take >5–15 min.
        # BusyBox ash typically accepts ~2–4KB command lines; stay under that.
        chunk_size = 1800
        chunks = [payload[i : i + chunk_size] for i in range(0, len(payload), chunk_size)] or [""]
        tmp = f"{remote_path}.spidervip.tmp"
        self.run(f'rm -f "{tmp}" "{tmp}.b64"', timeout=timeout)
        for chunk in chunks:
            # Append base64 text safely with printf
            safe = chunk.replace("'", "'\\''")
            self.run(f"printf '%s' '{safe}' >> \"{tmp}.b64\"", timeout=timeout)
        self.run(
            f'base64 -d "{tmp}.b64" > "{tmp}" && mv -f "{tmp}" "{remote_path}" && '
            f'rm -f "{tmp}.b64" && sync',
            timeout=timeout,
        )

    def list_paths(self, *globs: str) -> List[str]:
        """List remote paths for the given globs (ANSI-safe).

        Patterns containing shell wildcards must remain unquoted so BusyBox
        can expand them; plain paths may be quoted.
        """

        if not globs:
            return []
        parts = []
        for g in globs:
            if any(ch in g for ch in "*?["):
                parts.append(g)
            else:
                parts.append(f'"{g}"')
        joined = " ".join(parts)
        # BusyBox may ignore --color=never; strip_ansi still applied in run().
        out = self.run(
            f"ls -1 --color=never {joined} 2>/dev/null || ls -1 {joined} 2>/dev/null"
        )
        paths: List[str] = []
        seen = set()
        for line in out.splitlines():
            path = line.strip()
            if not path or path.endswith(":") or path.startswith("ls:"):
                continue
            if path.startswith("PROMPT>"):
                path = path[len("PROMPT>") :].strip()
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
        return paths

    @staticmethod
    def _extract_output(text: str, *, command: str, token: str) -> str:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        cleaned: List[str] = []
        for line in lines:
            if token in line:
                break
            stripped = line.strip()
            if not stripped:
                # keep blank lines inside file dumps? drop leading/trailing later
                cleaned.append("")
                continue
            if stripped == "PROMPT>" or line.endswith("PROMPT> "):
                continue
            if stripped.startswith("PROMPT>"):
                # e.g. "PROMPT> ls -1 ..."
                after = stripped[len("PROMPT>") :].strip()
                if after == command or after.startswith("echo "):
                    continue
                cleaned.append(after)
                continue
            if stripped == command or stripped.startswith("echo "):
                continue
            cleaned.append(line.rstrip())
        # Trim leading/trailing empty lines
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        return "\n".join(cleaned)

    def _send(self, data: str) -> None:
        assert self._sock is not None
        self._sock.sendall(data.encode("utf-8", "replace"))

    def _recv_until(self, markers: Iterable[bytes], timeout: Optional[float] = None) -> bytes:
        assert self._sock is not None
        self._sock.settimeout(0.8)
        deadline = time.time() + (timeout if timeout is not None else self.timeout)
        buf = b""
        markers = tuple(markers)
        while time.time() < deadline:
            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += self._strip_iac(chunk)
                for m in markers:
                    if m in buf:
                        return buf
            except socket.timeout:
                for m in markers:
                    if m in buf:
                        return buf
                continue
        return buf

    def _strip_iac(self, data: bytes) -> bytes:
        IAC, DO, DONT, WILL, WONT, SB, SE = 255, 253, 254, 251, 252, 250, 240
        out = bytearray()
        clean = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b == IAC and i + 2 < len(data):
                cmd, opt = data[i + 1], data[i + 2]
                if cmd == DO:
                    out += bytes([IAC, WONT, opt])
                elif cmd == WILL:
                    out += bytes([IAC, DONT, opt])
                i += 3
                continue
            if b == IAC and i + 1 < len(data) and data[i + 1] == SB:
                j = i + 2
                while j < len(data) and data[j] != SE:
                    j += 1
                i = j + 1
                continue
            clean.append(b)
            i += 1
        if out and self._sock is not None:
            try:
                self._sock.sendall(bytes(out))
            except OSError:
                pass
        return bytes(clean)


class FTPClient:
    """Thin wrapper around stdlib ftplib for text file up/download."""

    def __init__(
        self,
        host: str,
        port: int = 21,
        username: str = "root",
        password: str = "root",
        timeout: float = 15.0,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self._ftp: Optional[ftplib.FTP] = None

    def connect(self) -> None:
        ftp = ftplib.FTP()
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login(self.username, self.password)
        self._ftp = ftp

    def close(self) -> None:
        if self._ftp is not None:
            try:
                self._ftp.quit()
            except Exception:
                try:
                    self._ftp.close()
                except Exception:
                    pass
            self._ftp = None

    def download_text(self, remote_path: str) -> str:
        assert self._ftp is not None
        chunks: List[bytes] = []
        self._ftp.retrbinary(f"RETR {remote_path}", chunks.append)
        return b"".join(chunks).decode("utf-8", "replace")

    def upload_text(self, remote_path: str, content: str) -> None:
        assert self._ftp is not None
        bio = BytesIO(content.encode("utf-8"))
        self._ftp.storbinary(f"STOR {remote_path}", bio)

    def list_names(self, remote_dir: str) -> List[str]:
        assert self._ftp is not None
        try:
            return list(self._ftp.nlst(remote_dir))
        except ftplib.error_perm:
            return []
