from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from models import CustomerProfile, SessionState

_MAX_SESSIONS = 1000
_SESSION_TTL = 3600  # 1 hour


class MemoryManager:
    def __init__(self) -> None:
        self._sessions: dict[str, tuple[float, SessionState]] = {}

    def get_session(self, session_id: str) -> SessionState:
        now = time.time()
        if session_id in self._sessions:
            ts, state = self._sessions[session_id]
            if now - ts > _SESSION_TTL:
                del self._sessions[session_id]
            else:
                self._sessions[session_id] = (now, state)
                return state
        state = SessionState(session_id=session_id)
        self._sessions[session_id] = (now, state)
        self._evict_oldest_if_needed()
        return state

    def _evict_oldest_if_needed(self) -> None:
        if len(self._sessions) > _MAX_SESSIONS:
            oldest = min(self._sessions, key=lambda k: self._sessions[k][0])
            del self._sessions[oldest]

    def set_customer_id(self, session_id: str, customer_id: str) -> None:
        state = self.get_session(session_id)
        if state.customer_id is not None and state.customer_id != customer_id:
            self.clear_customer_context(session_id)
        state.customer_id = customer_id

    def clear_customer_context(self, session_id: str) -> None:
        state = self.get_session(session_id)
        state.profile.clear()
        state.preferences.clear()
        state.focus_points.clear()
        state.scenario.clear()

    def remember_profile(self, session_id: str, profile: CustomerProfile) -> None:
        state = self.get_session(session_id)
        state.customer_id = profile.user_id
        state.profile = asdict(profile)

    def remember_preferences(self, session_id: str, payload: dict[str, Any]) -> None:
        state = self.get_session(session_id)
        state.preferences.update(payload)
        for point in payload.get("focus_points", []):
            if point not in state.focus_points:
                state.focus_points.append(point)

    def remember_scenario(self, session_id: str, payload: dict[str, Any]) -> None:
        state = self.get_session(session_id)
        state.scenario.update(payload)

    def clear_scenario(self, session_id: str) -> None:
        state = self.get_session(session_id)
        state.scenario.clear()
