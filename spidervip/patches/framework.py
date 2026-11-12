"""Generic on-box patch: files + a boot hook line + start/stop + status.

A patch is installed by copying its files (gzip+base64 over Telnet, md5
checked, atomic tmp+mv — ``spidervip.frequency.deploy.BoxFiles``), adding one
tagged line to the vendor boot hook ``/home/gx/local/user_script`` (run by
``bianbiang.sh`` at every boot) and starting it now. Removal stops it, deletes
the tagged hook line and its folder. Everything is idempotent.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

HOOK = "/home/gx/local/user_script"
BOOT_ID = "/proc/sys/kernel/random/boot_id"


def _q(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


@dataclass
class PatchFile:
    local: Path
    remote: str
    mode: str = "644"

    def data(self) -> bytes:
        # Shell scripts must reach the box with LF line endings.
        return self.local.read_bytes().replace(b"\r\n", b"\n")

    def md5(self) -> str:
        return hashlib.md5(self.data()).hexdigest()  # noqa: S324 — integrity check only


@dataclass
class Patch:
    id: str
    title: str
    summary: str
    box_dir: str
    files: List[PatchFile]
    hook_tag: str
    hook_line: str = ""
    start_cmd: str = ""
    pid_file: str = ""            # "<pid> <boot_id>" written by the running script
    log_file: str = ""
    disable_flag: str = ""        # touched before stopping so a running copy exits
    available: bool = True
    note: str = ""
    extra_status: Optional[Callable[[Dict[str, str]], Dict[str, object]]] = None
    details: List[str] = field(default_factory=list)   # short, plain bullets shown on the card
    tech: List[str] = field(default_factory=list)      # technical notes, collapsed under «جزئیات فنی»
    # Files written at install time with fresh content (config, clock floor…); not md5-tracked.
    generated: Optional[Callable[[], Dict[str, bytes]]] = None
    run_cmd: str = ""             # "run now", started in the background on the box
    report_file: str = ""         # JSON the Console shows on the card

    def public(self) -> Dict[str, object]:
        return {"id": self.id, "title": self.title, "summary": self.summary, "available": self.available,
                "note": self.note, "details": self.details, "tech": self.tech, "box_dir": self.box_dir,
                "can_run": bool(self.run_cmd), "has_report": bool(self.report_file)}


def _stop_cmd(p: Patch) -> str:
    if not p.pid_file:
        return ":"
    # Kill only the copy started in this boot (pid recycled across boots is ignored).
    return (f"[ -e {_q(p.pid_file)} ] && set -- $(cat {_q(p.pid_file)}) && "
            f"[ \"$2\" = \"$(cat {BOOT_ID})\" ] && kill $1 2>/dev/null; sleep 1")


def status(rx, p: Patch) -> Dict[str, object]:
    """Read-only state of one patch on the box."""

    files = " ".join(f"{_q(f.remote)}" for f in p.files)
    pid = _q(p.pid_file) if p.pid_file else "''"
    out = rx.run(
        f"for f in {files}; do if [ -f \"$f\" ]; then echo \"FILE $(md5sum \"$f\" | cut -d' ' -f1) $f\"; "
        f"else echo \"NOFILE - $f\"; fi; done; "
        f"echo \"HOOK $(grep -c {_q(p.hook_tag)} {HOOK} 2>/dev/null || echo 0)\"; "
        f"P=no; [ -e {pid} ] && set -- $(cat {pid}) && [ \"$2\" = \"$(cat {BOOT_ID})\" ] && "
        f"kill -0 $1 2>/dev/null && P=$1; echo \"RUN $P\"; "
        + (f"[ -e {_q(p.disable_flag)} ] && echo DISABLED; " if p.disable_flag else "")
        + (f"tail -n 8 {_q(p.log_file)} 2>/dev/null | sed 's/^/LOG /'" if p.log_file else "true"),
        timeout=30.0,
    )
    md5 = {f.remote: f.md5() for f in p.files}
    present, current, logs = [], [], []
    hook = 0
    running = None
    disabled = False
    for line in out.splitlines():
        if line.startswith("FILE "):
            _tag, digest, path = line.split(" ", 2)
            present.append(path)
            if md5.get(path) == digest:
                current.append(path)
        elif line.startswith("HOOK "):
            tok = line.split()[1] if len(line.split()) > 1 else "0"
            hook = int(tok) if tok.isdigit() else 0
        elif line.startswith("RUN "):
            val = line.split()[1] if len(line.split()) > 1 else "no"
            running = None if val == "no" else val
        elif line.strip() == "DISABLED":
            disabled = True
        elif line.startswith("LOG "):
            logs.append(line[4:])
    installed = len(present) == len(p.files) and hook > 0
    state = {
        "id": p.id,
        "installed": installed,
        "partial": bool(present or hook) and not installed,
        "up_to_date": installed and len(current) == len(p.files),
        "running": running,
        "hook_lines": hook,
        "disabled": disabled,
        "log": logs,
    }
    if p.extra_status:
        state.update(p.extra_status({"raw": out}))
    return state


def install(rx, files_io, p: Patch, log: Callable[[str], None] = lambda m: None) -> Dict[str, object]:
    """Copy files (md5 checked), add the boot hook line, (re)start. Idempotent."""

    if not p.available:
        raise RuntimeError(f"وصلهٔ «{p.title}» هنوز آماده نیست.")
    dirs = {p.box_dir, posixpath.dirname(HOOK)} | {posixpath.dirname(f.remote) for f in p.files}
    rx.run("mkdir -p " + " ".join(_q(d) for d in sorted(dirs)), timeout=15.0)
    for f in p.files:
        log(f"کپی {f.remote} …")
        files_io.write(f.remote, f.data())
        rx.run(f"chmod {f.mode} {_q(f.remote)}", timeout=15.0)
    if p.generated:
        for remote, data in p.generated().items():
            log(f"نوشتن {remote} …")
            files_io.write(remote, data)
    if p.disable_flag:
        rx.run(f"rm -f {_q(p.disable_flag)}", timeout=15.0)
    if p.pid_file:
        log("توقف نسخهٔ در حال اجرا (اگر هست) …")
        rx.run(_stop_cmd(p), timeout=20.0)
    if p.hook_line:
        log("افزودن به اجرای خودکار هنگام روشن شدن (user_script) …")
        rx.run(f"[ -e {HOOK} ] || printf '#!/bin/sh\\n' > {HOOK}", timeout=15.0)
        rx.run(f"grep -q {_q(p.hook_tag)} {HOOK} || echo {_q(p.hook_line)} >> {HOOK}", timeout=15.0)
        rx.run(f"chmod 755 {HOOK}", timeout=15.0)
    if p.start_cmd:
        log("شروع …")
        rx.run(f"( if command -v setsid >/dev/null; then setsid {p.start_cmd}; else nohup {p.start_cmd}; fi "
               f"</dev/null >/dev/null 2>&1 & ) ; sleep 2", timeout=20.0)
    return status(rx, p)


def run_now(rx, p: Patch) -> None:
    """Start the patch's one-shot job in the background (the HTTP call does not wait)."""

    if not p.run_cmd:
        raise RuntimeError("این وصله اجرای فوری ندارد.")
    rx.run(f"( {p.run_cmd} ) </dev/null >/dev/null 2>&1 &", timeout=15.0)


def read_report(files_io, p: Patch) -> Optional[Dict[str, object]]:
    if not p.report_file:
        return None
    import json

    try:
        data = files_io.read(p.report_file)
    except Exception:  # noqa: BLE001 — no report yet
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        return None


def remove(rx, p: Patch, log: Callable[[str], None] = lambda m: None) -> Dict[str, object]:
    """Stop, delete the tagged hook line and the patch folder. Idempotent."""

    if p.disable_flag:
        rx.run(f"mkdir -p {_q(p.box_dir)} && touch {_q(p.disable_flag)}", timeout=15.0)
    if p.pid_file:
        log("توقف …")
        rx.run(_stop_cmd(p), timeout=20.0)
    log("حذف از اجرای خودکار (user_script) …")
    rx.run(f"[ -e {HOOK} ] && sed -i '/{p.hook_tag}/d' {HOOK}; "
           f"[ -e {HOOK} ] && [ \"$(grep -cv '^#!' {HOOK})\" = 0 ] && rm -f {HOOK}; true", timeout=15.0)
    log(f"پاک کردن {p.box_dir} …")
    if not p.box_dir.startswith("/data/") or p.box_dir.rstrip("/") in ("/data", "/data/gx"):
        raise RuntimeError(f"مسیر وصله برای حذف امن نیست: {p.box_dir}")
    rx.run(f"rm -rf {_q(p.box_dir)}", timeout=30.0)
    return status(rx, p)
