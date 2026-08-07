#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gadget_fsm.py — event-driven lifecycle FSM for the Spider VIP USB device-mode gadget.

Project B (firmware optimization). Independent of the freeze RCA.

Policy: g_service stays Idle by default; becomes Active ONLY when a legitimate USB
Device-Mode feature calls demand(). Reference-counted. A grace timer on release
debounces flapping. Any mechanism failure rolls back deterministically to Idle.

HARD RULE: this FSM never does rmmod/insmod. It drives a pluggable *mechanism*
(bind/unbind or soft-connect pull-up) that is injected — so the same policy runs
against L1 (configfs UDC) or L2 (soft-connect) or an off-device fake for unit tests.

This module is pure policy + is import-safe off-device (no I/O of its own).
"""

from enum import Enum


class State(str, Enum):
    IDLE = "Idle"
    INITIALIZING = "Initializing"
    ACTIVE = "Active"
    RELEASING = "Releasing"


class Mechanism:
    """Interface a concrete backend must implement. All methods must be
    idempotent and must raise on failure so the FSM can roll back."""
    def activate(self):   # bring gadget up (bind UDC / assert pull-up)
        raise NotImplementedError
    def deactivate(self):  # take gadget down (unbind UDC / drop pull-up)
        raise NotImplementedError


class GadgetFSM:
    def __init__(self, mechanism, clock, grace_seconds=8, default_active=False):
        """clock: a callable returning a monotonic float 'now' (injected so tests
        control time; no Date.now on-device dependency). default_active mirrors the
        backward-compat 'legacy' mode where the gadget boots straight to Active."""
        self._mech = mechanism
        self._now = clock
        self._grace = grace_seconds
        self._refcount = 0
        self._state = State.IDLE
        self._release_deadline = None
        self.transitions = []  # audit log of (from, to, reason)
        if default_active:
            # legacy/back-compat: behave exactly like today (gadget up at boot)
            self.demand("__boot_compat__")

    # ---- introspection ----
    @property
    def state(self):
        return self._state
    @property
    def refcount(self):
        return self._refcount

    def _go(self, new, reason):
        if new != self._state:
            self.transitions.append((self._state.value, new.value, reason))
            self._state = new

    # ---- events ----
    def demand(self, feature_id):
        """A legitimate feature requires device mode. Refcount++ and ensure Active."""
        self._refcount += 1
        # A pending release is cancelled by any new demand.
        self._release_deadline = None
        if self._state == State.ACTIVE:
            return self._state
        if self._state == State.RELEASING:
            # Mechanism is still bound (deactivate hasn't run) — snap straight back
            # to Active WITHOUT re-activating. This is the anti-flap fast path.
            self._go(State.ACTIVE, f"re-demand-during-grace({feature_id})")
            return self._state
        if self._state == State.IDLE:
            self._go(State.INITIALIZING, f"demand({feature_id})")
            try:
                self._mech.activate()
            except Exception as e:
                # deterministic rollback — never leave a half-state
                self._refcount = max(0, self._refcount - 1)
                self._go(State.IDLE, f"activate-failed:{e}")
                raise
            self._go(State.ACTIVE, "bind-ok")
        return self._state

    def release(self, feature_id):
        """A feature finished. Refcount--; when zero, start the grace timer."""
        if self._refcount == 0:
            return self._state
        self._refcount -= 1
        if self._refcount == 0 and self._state == State.ACTIVE:
            self._go(State.RELEASING, f"release({feature_id})")
            self._release_deadline = self._now() + self._grace
        return self._state

    def tick(self):
        """Drive time-based transitions. Call periodically. When the grace timer
        expires with refcount still 0, deactivate and return to Idle."""
        if self._state == State.RELEASING and self._release_deadline is not None:
            if self._refcount > 0:
                # a demand arrived during grace → snap back to Active
                self._release_deadline = None
                self._go(State.ACTIVE, "re-demand-during-grace")
            elif self._now() >= self._release_deadline:
                try:
                    self._mech.deactivate()
                    self._go(State.IDLE, "grace-expired")
                except Exception as e:
                    # stay in Releasing; caller/watchdog may retry. Never crash.
                    self.transitions.append((self._state.value, self._state.value,
                                             f"deactivate-failed:{e}"))
                finally:
                    self._release_deadline = None
        return self._state
