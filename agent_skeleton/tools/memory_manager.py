from __future__ import annotations

from dataclasses import asdict
from typing import Any

from models import CustomerProfile, SessionState


class MemoryManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_session(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]

    def set_customer_id(self, session_id: str, customer_id: str) -> None:
        state = self.get_session(session_id)
        if state.customer_id and state.customer_id != customer_id:
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
