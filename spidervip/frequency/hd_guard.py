"""Keep HEVC HD services (lamedb type 31) and their favorites across a
``servicelistreload`` started from the PC (Console frequency deploy, Channels Apply).

Why (live box 2026-11-20): the reload re-imports ``lamedb``, and the vendor
importer does not know service type 31. It marks every such service as radio
in ``live_prog`` and zeroes its channel number, so the channels drop out of the
TV favorites (10 of 13 in "IRAN HD"). Proven fix, same as the on-box runner
(``spidervip/patches/freq_auto/runner.py``, ``repair-hd`` verified live):

1. before the reload, write type 25 (``lamedb.STANDIN_TYPES``) for those
   services in ``lamedb`` and ``19`` in their favorite references;
2. after the reload, set the type byte back to 31 in ``live_prog``
   (``liveprog.restore_service_types``) — any service that came back as
   radio or without a number is a failure and the caller must roll back;
3. write the real type back into the box's export (it is not re-exported at
   boot); 4. force-reboot (the caller does this, as for Motor);
5. after boot, check ``live_prog`` again (:meth:`HdGuard.verify`).
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional

from .core import lamedb, liveprog
from .deploy import ENIGMA_DB, LAMEDB, LIVE_PROG, BoxFiles, _q


class HdGuardError(RuntimeError):
    pass


class HdGuard:
    def __init__(self, rx, *, sleep: Callable[[float], None]):
        self.rx = rx
        self.sleep = sleep
        self.keys: List[str] = []
        self.restored: List[str] = []
        self.hd: List[list] = []
        self._before_raw: Optional[bytes] = None
        self._before_md5 = ""

    def _files(self) -> BoxFiles:
        return BoxFiles(self.rx)

    def _bouquet_paths(self) -> List[str]:
        out = self.rx.run(f"ls -1 {_q(ENIGMA_DB)}/userbouquet.*.tv {_q(ENIGMA_DB)}/userbouquet.*.radio 2>/dev/null",
                          timeout=15.0)
        return sorted(p.strip() for p in out.splitlines() if p.strip().startswith(ENIGMA_DB + "/userbouquet."))

    # -- 1. before the reload -------------------------------------------------
    def check(self) -> List[str]:
        """Read lamedb + live_prog; refuse unknown types. Returns the stand-in keys (nothing written)."""

        files = self._files()
        text = files.read(LAMEDB).decode("utf-8", "replace")
        unknown = lamedb.unknown_types(text)
        if unknown:
            raise HdGuardError("نوع سرویسی در lamedb هست که رسیور هنگام ثبت لیست نمی‌شناسد و آن کانال‌ها را از "
                               f"Favoriteها بیرون می‌اندازد: {unknown}. اعمال انجام نشد.")
        self._lamedb_text = text
        _new, self.keys = lamedb.substitute_types(text)
        if not self.keys:  # nothing the importer would mangle: no restore needed
            return self.keys
        data = files.read(LIVE_PROG)
        self._before_raw = liveprog.unpack(data)
        self._before_md5 = hashlib.md5(data).hexdigest()  # noqa: S324 — change check only
        return self.keys

    def write_standin(self, *, bouquets_on_box: bool = True) -> None:
        """Write the stand-in type into lamedb (and the box's favorites)."""

        if not self.keys:
            return
        files = self._files()
        new, _ = lamedb.substitute_types(self._lamedb_text)
        files.write(LAMEDB, new.encode("utf-8"))
        if bouquets_on_box:
            for path in self._bouquet_paths():
                text = files.read(path).decode("utf-8", "replace")
                sub, n = lamedb.substitute_bouquet_types(text, self.keys)
                if n:
                    files.write(path, sub.encode("utf-8"))

    def undo_standin(self) -> None:
        """Put the original lamedb back (a failure before the reload; best effort)."""

        if self.keys and getattr(self, "_lamedb_text", None) is not None:
            try:
                self._files().write(LAMEDB, self._lamedb_text.encode("utf-8"))
            except Exception:  # noqa: BLE001
                pass

    def standin_texts(self, texts: Dict[str, str]) -> Dict[str, str]:
        """Stand-in references in bouquet texts about to be uploaded (Channels Apply)."""

        if not self.keys:
            return dict(texts)
        return {name: (lamedb.substitute_bouquet_types(t, self.keys)[0] if name.endswith((".tv", ".radio")) else t)
                for name, t in texts.items()}

    # -- 2./3. after the reload -----------------------------------------------
    def restore(self, settle: Callable[[], None]) -> List[str]:
        """Put the real type back in live_prog and in the export. Raises on any lost service."""

        if not self.keys:
            return []
        if self._before_raw is None:
            raise HdGuardError("HdGuard.check was not run")
        files = self._files()
        for _ in range(10):
            if files.md5(LIVE_PROG) != self._before_md5:
                break
            self.sleep(1.0)
        settle()
        raw0 = liveprog.unpack(files.read(LIVE_PROG))
        raw, self.restored, problems = liveprog.restore_service_types(
            self._before_raw, raw0, lamedb.STANDIN_TYPES)
        if problems:
            raise HdGuardError("کانال‌های HD پس از ثبت لیست درست برنگشتند: " + "؛ ".join(problems[:6]))
        if raw != raw0:
            files.write(LIVE_PROG, liveprog.pack(raw))
        self.hd = [[s["sid"], s["name"].hex(), s["type"]] for s in liveprog.services(raw)
                   if s["type"] in lamedb.STANDIN_TYPES and not s["radio"]]
        if self.keys:
            inv = {v: k for k, v in lamedb.STANDIN_TYPES.items()}
            text = files.read(LAMEDB).decode("utf-8", "replace")
            new, changed = lamedb.substitute_types(text, standin=inv, only=self.keys)
            if changed:
                files.write(LAMEDB, new.encode("utf-8"))
            for path in self._bouquet_paths():
                text = files.read(path).decode("utf-8", "replace")
                sub, n = lamedb.substitute_bouquet_types(text, self.keys, standin=inv)
                if n:
                    files.write(path, sub.encode("utf-8"))
        return self.restored

    @property
    def needs_forced_reboot(self) -> bool:
        return bool(self.restored)

    # -- 5. after the forced reboot -------------------------------------------
    def verify(self) -> List[str]:
        """Names of HD services that are no longer TV (with a number and type 31) in live_prog."""

        if not self.hd:
            return []
        now = {(s["sid"], s["name"].hex()): s for s in liveprog.services(liveprog.unpack(self._files().read(LIVE_PROG)))}
        lost = []
        for sid, h, t in self.hd:
            s = now.get((sid, h))
            if not (s and s["type"] == t and not s["radio"] and s["number"]):
                lost.append(bytes.fromhex(h).decode("utf-8", "replace"))
        return lost
