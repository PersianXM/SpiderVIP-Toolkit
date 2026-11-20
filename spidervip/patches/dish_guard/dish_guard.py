#!/usr/bin/env python3
"""Dish-drive key guard for the Spider VIP receiver (Python 3.9, standard library only).

Why (measured on the box, 2026-11-13, docs/freeze/DISH_DRIVE_CRASH_2026-11.md):
when a channel on another USALS satellite is selected, the vendor app detaches
the tuner (kernel line ``hi_dvb_set_source [.. tuner: -1 ..]``), drives the dish
and re-attaches it (``tuner: 0``) about 17 s later for a 52 degree move. If the
satellite is changed again inside that window (zapping, the Favourite edit
screen, the "recall" key), the kernel dies about 10 s later and the box reboots:
unsaved Favourite edits are lost. One change per window is harmless.

What this does: while the tuner is detached *and* the tuner link shows its
drive-time request storm (``service gadget`` lines at ~87/s instead of ~13/s),
it holds the remote's input device (EVIOCGRAB), so the app receives no keys.
Keys pressed during an ordinary retune (no storm, ~0.6 s) are given back to
the app unchanged. It never talks to the tuner, the app or the drivers.

Safety: a grab ends at ``tuner: 0``, when the storm stops, or after MAX_GRAB
seconds, whichever comes first; a dead guard releases the grab automatically
(the kernel drops it with the file descriptor); ``disable`` in the folder stops it.

Files in the folder: pid ("<pid> <boot_id>"), log, disable.
Environment overrides exist only for tests (DG_*).
"""

import collections
import errno
import os
import select
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.environ.get("DG_DIR", HERE)
KMSG = os.environ.get("DG_KMSG", "/dev/kmsg")
INPUT = os.environ.get("DG_INPUT", "")           # empty: find the remote by name
DEVICES = os.environ.get("DG_DEVICES", "/proc/bus/input/devices")
BOOT_ID = os.environ.get("DG_BOOT_ID", "/proc/sys/kernel/random/boot_id")

EVIOCGRAB = 0x40044590
EVENT = struct.Struct("llHHi")      # struct input_event on 32-bit ARM
EV_SYN, EV_KEY, EV_MSC = 0, 1, 4   # the app needs the EV_MSC scan code that precedes each key

PROVISIONAL = 0.35   # s: hold keys this long after a detach while deciding
STORM_WINDOW = 0.30  # s: sliding window for the request-rate test
STORM_LINES = 12     # lines in STORM_WINDOW (normal ~4, during a drive ~26)
STORM_QUIET = 2.0    # s without a storm ends a drive hold
MAX_GRAB = 45.0      # s: never hold the remote longer than this

DETACH = b"tuner: -1"
ATTACH = b"tuner: 0"
SOURCE = b"hi_dvb_set_source"
GADGET = b"service gadget"

IDLE, DECIDING, DRIVING, WATCH = "idle", "deciding", "driving", "watch"


class Guard:
    """The decision logic, free of I/O so it can be tested with made-up log lines.

    ``feed(line, now)`` and ``tick(now)`` return a list of actions:
    ``("grab",)``, ``("release", replay: bool, reason: str)``.
    """

    def __init__(self):
        self.state = IDLE
        self.t_state = 0.0
        self.t_storm = 0.0
        self.recent = collections.deque()

    # -- helpers ---------------------------------------------------------------
    def _storm(self, now):
        while self.recent and now - self.recent[0] > STORM_WINDOW:
            self.recent.popleft()
        return len(self.recent) >= STORM_LINES

    def _to(self, state, now):
        self.state, self.t_state = state, now

    # -- events ----------------------------------------------------------------
    def feed(self, line, now):
        acts = []
        if GADGET in line:
            self.recent.append(now)
            if self._storm(now):
                self.t_storm = now
                if self.state == DECIDING:
                    self._to(DRIVING, now)          # keep the provisional hold
                elif self.state == WATCH:
                    self._to(DRIVING, now)
                    acts.append(("grab",))
        elif SOURCE in line:
            if DETACH in line:
                if self.state in (IDLE, WATCH):
                    self.recent.clear()
                    self._to(DECIDING, now)
                    acts.append(("grab",))
            elif ATTACH in line:
                if self.state == DECIDING:
                    acts.append(("release", True, "retune"))
                elif self.state == DRIVING:
                    acts.append(("release", False, "tuner back"))
                self._to(IDLE, now)
        return acts + self.tick(now)

    def tick(self, now):
        acts = []
        if self.state == DECIDING and now - self.t_state >= PROVISIONAL:
            acts.append(("release", True, "no drive"))
            self._to(WATCH, now)
        elif self.state == DRIVING:
            if now - self.t_state >= MAX_GRAB:
                acts.append(("release", False, "time limit"))
                self._to(IDLE, now)
            elif now - self.t_storm >= STORM_QUIET:
                acts.append(("release", False, "drive ended"))
                self._to(IDLE, now)
        return acts


# ------------------------------------------------------------------- I/O side
def log(msg):
    path = os.path.join(D, "log")
    try:
        up = open("/proc/uptime").read().split()[0]
    except OSError:
        up = "?"
    with open(path, "a") as fh:
        fh.write("%s up=%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), up, msg))
    try:
        if os.path.getsize(path) > 65536:
            lines = open(path).read().splitlines()[-300:]
            with open(path + ".tmp", "w") as fh:
                fh.write("\n".join(lines) + "\n")
            os.replace(path + ".tmp", path)
    except OSError:
        pass


def find_remote(devices_text):
    """``/dev/input/eventN`` of the IR remote from /proc/bus/input/devices text
    (the box names it "dreambox advanced remote control"); None when absent."""

    for block in devices_text.split("\n\n"):
        name, handlers = "", ""
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line[8:].strip().strip('"').lower()
            elif line.startswith("H: Handlers="):
                handlers = line[12:]
        if "remote control" in name:
            for word in handlers.split():
                if word.startswith("event") and word[5:].isdigit():
                    return "/dev/input/" + word
    return None


def _grab_ioctl(fd, on):
    import fcntl  # Linux only; kept out of module import so the logic is testable anywhere

    fcntl.ioctl(fd, EVIOCGRAB, 1 if on else 0)


class Remote:
    """The remote's input device: grab, collect keys while held, give them back."""

    def __init__(self, path=""):
        self.fixed = path
        self.path = path
        self.fd = None
        self.held = False
        self.keys = []
        self.t_grab = 0.0
        self.warned = False

    def ensure(self):
        """Open the device if it is there (at boot it appears a few seconds after us)."""

        if self.fd is not None:
            return True
        path = self.fixed
        if not path:
            try:
                path = find_remote(open(DEVICES).read())
            except OSError:
                path = None
        if not path:
            return False
        try:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return False
        self.path = path
        log("remote: %s" % path)
        return True

    def _lost(self, exc):
        log("remote lost (%s); will look for it again" % exc)
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd, self.held, self.keys = None, False, []

    def _drain(self, keep):
        while True:
            try:
                data = os.read(self.fd, EVENT.size * 64)
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                    self._lost(exc)                  # e.g. ENODEV: the device was re-created
                return
            if not data:
                return
            if keep:
                for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _s, _u, etype, code, value = EVENT.unpack_from(data, off)
                    if etype in (EV_SYN, EV_KEY, EV_MSC):
                        self.keys.append((etype, code, value))

    def grab(self, now):
        if self.held:
            return True
        if not self.ensure():
            if not self.warned:
                self.warned = True
                log("remote input device not found; nothing is held")
            return False
        self._drain(keep=False)              # forget anything typed before the hold
        if self.fd is None:
            return False
        try:
            _grab_ioctl(self.fd, True)
        except OSError as exc:
            log("grab failed: %s" % exc)
            return False
        self.held, self.keys, self.t_grab = True, [], now
        return True

    def poll(self):
        if self.held:
            self._drain(keep=True)

    def release(self, replay):
        if not self.held:
            return 0, 0
        self._drain(keep=True)
        if self.fd is None:                  # lost while held: the kernel dropped the grab
            return 0, 0
        try:
            _grab_ioctl(self.fd, False)
        except OSError as exc:
            log("release failed: %s" % exc)
        self.held = False
        keys, self.keys = self.keys, []
        presses = sum(1 for etype, _c, v in keys if etype == EV_KEY and v == 1)
        if replay and presses:
            try:
                with open(self.path, "wb", buffering=0) as out:
                    frame = b""
                    for etype, code, value in keys:      # same order, one write per SYN frame
                        frame += EVENT.pack(0, 0, etype, code, value)
                        if etype == EV_SYN:
                            out.write(frame)
                            frame = b""
                    if frame:
                        out.write(frame + EVENT.pack(0, 0, EV_SYN, 0, 0))
            except OSError as exc:
                log("replay failed: %s" % exc)
            self._drain(keep=False)          # our own echo
            return presses, presses
        return presses, 0


def already_running():
    try:
        pid, boot = open(os.path.join(D, "pid")).read().split()
        if boot == open(BOOT_ID).read().strip() and int(pid) != os.getpid():
            os.kill(int(pid), 0)
            return True
    except (OSError, ValueError):
        pass
    return False


def main():
    if already_running():
        return 0
    with open(os.path.join(D, "pid"), "w") as fh:
        fh.write("%d %s\n" % (os.getpid(), open(BOOT_ID).read().strip()))
    kfd = os.open(KMSG, os.O_RDONLY | os.O_NONBLOCK)
    try:
        os.lseek(kfd, 0, os.SEEK_END)
    except OSError:
        pass
    remote = Remote(INPUT)
    guard = Guard()
    log("start")
    remote.ensure()
    t_check = 0.0
    while True:
        now = time.monotonic()
        if now - t_check > 2.0:
            t_check = now
            if os.path.exists(os.path.join(D, "disable")):
                remote.release(replay=False)
                log("disabled, exit")
                return 0
            remote.ensure()
        try:
            ready, _w, _x = select.select([kfd], [], [], 0.1)
        except InterruptedError:
            continue
        acts = []
        if ready:
            for _ in range(200):             # at most a burst per loop
                try:
                    line = os.read(kfd, 8192)
                except OSError as exc:
                    if exc.errno == errno.EPIPE:      # records overwritten: carry on
                        continue
                    break                              # EAGAIN: nothing more now
                if not line:
                    break
                acts += guard.feed(line, time.monotonic())
        acts += guard.tick(time.monotonic())
        remote.poll()
        for act in acts:
            if act[0] == "grab":
                remote.grab(time.monotonic())
            else:
                _name, replay, reason = act
                held_for = time.monotonic() - remote.t_grab if remote.held else 0.0
                pressed, replayed = remote.release(replay)
                if not replay:               # a drive hold; ordinary retunes are not logged
                    log("dish drive: remote held %.1fs (%s), %d key press(es) dropped"
                        % (held_for, reason, pressed))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
