#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Off-device unit tests for the g_service lifecycle FSM (Project B, B1).
Runs anywhere with plain python3 — NO device, NO module ops. Pure policy verification."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "patches", "usr", "local", "gadgetd"))
from gadget_fsm import GadgetFSM, State, Mechanism  # noqa: E402


class FakeClock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s


class FakeMech(Mechanism):
    def __init__(self, fail_activate=False, fail_deactivate=False):
        self.active = False
        self.activate_calls = 0
        self.deactivate_calls = 0
        self.fail_activate = fail_activate
        self.fail_deactivate = fail_deactivate
    def activate(self):
        self.activate_calls += 1
        if self.fail_activate: raise RuntimeError("bind-fail")
        self.active = True
    def deactivate(self):
        self.deactivate_calls += 1
        if self.fail_deactivate: raise RuntimeError("unbind-fail")
        self.active = False


results = []
def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name)


# 1. Default is Idle (lazy by default) — the core optimization
clk = FakeClock(); m = FakeMech()
fsm = GadgetFSM(m, clk, grace_seconds=8)
check("boot default = Idle (lazy)", fsm.state == State.IDLE and not m.active)

# 2. demand() brings it Active exactly once; second demand doesn't re-activate
fsm.demand("massstorage")
check("demand -> Active", fsm.state == State.ACTIVE and m.active)
check("activate called once", m.activate_calls == 1)
fsm.demand("adb")
check("2nd demand no re-activate", m.activate_calls == 1 and fsm.refcount == 2)

# 3. release with refs remaining stays Active
fsm.release("massstorage")
check("release with refs left -> still Active", fsm.state == State.ACTIVE and fsm.refcount == 1)

# 4. last release -> Releasing (grace), not yet deactivated
fsm.release("adb")
check("last release -> Releasing", fsm.state == State.RELEASING)
check("not deactivated during grace", m.active and m.deactivate_calls == 0)

# 5. tick before grace expiry keeps Releasing
clk.advance(3); fsm.tick()
check("tick pre-grace stays Releasing", fsm.state == State.RELEASING)

# 6. tick after grace -> Idle + deactivate once
clk.advance(6); fsm.tick()
check("grace expired -> Idle", fsm.state == State.IDLE and not m.active)
check("deactivate called once", m.deactivate_calls == 1)

# 7. anti-flap: demand during grace snaps back to Active without extra bind
clk2 = FakeClock(); m2 = FakeMech(); fsm2 = GadgetFSM(m2, clk2, grace_seconds=8)
fsm2.demand("f1"); fsm2.release("f1")
check("in grace", fsm2.state == State.RELEASING)
fsm2.demand("f2")          # arrives during grace
check("re-demand keeps refcount", fsm2.refcount == 1)
check("re-demand -> Active immediately (no flap)", fsm2.state == State.ACTIVE and m2.active)
check("no second activate needed", m2.activate_calls == 1 and m2.deactivate_calls == 0)
fsm2.tick()
check("tick after re-demand stays Active", fsm2.state == State.ACTIVE)

# 8. activate failure -> deterministic rollback to Idle, refcount restored
clk3 = FakeClock(); m3 = FakeMech(fail_activate=True); fsm3 = GadgetFSM(m3, clk3)
raised = False
try:
    fsm3.demand("x")
except RuntimeError:
    raised = True
check("activate failure raises", raised)
check("rollback to Idle on failure", fsm3.state == State.IDLE and fsm3.refcount == 0)

# 9. backward-compat legacy mode: default_active boots straight to Active
clk4 = FakeClock(); m4 = FakeMech(); fsm4 = GadgetFSM(m4, clk4, default_active=True)
check("legacy mode boots Active", fsm4.state == State.ACTIVE and m4.active)

# 10. deactivate failure -> stays Releasing (never crash), logged
clk5 = FakeClock(); m5 = FakeMech(fail_deactivate=True); fsm5 = GadgetFSM(m5, clk5, grace_seconds=2)
fsm5.demand("y"); fsm5.release("y"); clk5.advance(5); fsm5.tick()
check("deactivate failure stays Releasing", fsm5.state == State.RELEASING)

failed = [n for n, ok in results if not ok]
print("\n%d/%d passed" % (sum(1 for _, ok in results if ok), len(results)))
sys.exit(1 if failed else 0)
