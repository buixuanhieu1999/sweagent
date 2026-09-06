"""Durable turn lifecycle, mutable plans, and loop detection for the universal loop."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum


class TurnState(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    BLOCKED_USER = "BLOCKED_USER"
    BLOCKED_PERMISSION = "BLOCKED_PERMISSION"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    COMPLETE = "COMPLETE"


PLAN_STATUSES = {"pending", "in_progress", "completed"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_plan(steps: list[dict]) -> list[dict]:
    if not isinstance(steps, list) or len(steps) > 50:
        raise ValueError("Plan must contain 0 to 50 steps")
    normalized = []
    in_progress = 0
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"text", "status"}:
            raise ValueError("Every plan step requires only text and status")
        text, status = step["text"], step["status"]
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ValueError("Plan step text must be 1 to 500 characters")
        if status not in PLAN_STATUSES:
            raise ValueError(
                "Plan step status must be pending, in_progress, or completed"
            )
        in_progress += status == "in_progress"
        normalized.append({"text": text.strip(), "status": status})
    if in_progress > 1:
        raise ValueError("A plan may have at most one in_progress step")
    return normalized


class SessionRuntime:
    """Stores lifecycle metadata in Session JSON without making plans executable."""

    def __init__(self, session):
        self.session = session
        data = session.data
        data.setdefault("runtime", {"active_turn": None, "queued_turns": []})
        data.setdefault("plan", [])

    def start(self, request: str) -> dict:
        data = self.session.data
        number = data.get("turn", 0) + 1
        data["turn"] = number
        turn = {
            "id": f"turn-{number}",
            "status": TurnState.RUNNING,
            "request": request,
            "started_at": utcnow(),
            "updated_at": utcnow(),
            "tool_calls": [],
            "steering_queue": [],
        }
        data["runtime"]["active_turn"] = turn
        data["state"] = TurnState.RUNNING
        return turn

    def active(self) -> dict | None:
        return self.session.data["runtime"].get("active_turn")

    def state(self, status: TurnState) -> None:
        turn = self.active()
        if turn:
            turn["status"] = status
            turn["updated_at"] = utcnow()
            if status in {TurnState.COMPLETE, TurnState.INTERRUPTED, TurnState.FAILED}:
                turn["finished_at"] = utcnow()
        self.session.data["state"] = status

    def update_plan(self, steps: list[dict]) -> list[dict]:
        steps = validate_plan(steps)
        self.session.data["plan"] = steps
        if turn := self.active():
            turn["plan"] = steps
            turn["updated_at"] = utcnow()
        return steps

    def question(self, question: str, options: list[str]) -> dict:
        if not question.strip() or len(question) > 2000:
            raise ValueError("Question must be 1 to 2,000 characters")
        if not isinstance(options, list) or not all(
            isinstance(option, str) and option.strip() for option in options
        ):
            raise ValueError("Question options must be a list of nonempty strings")
        pending = {"question": question.strip(), "options": options}
        self.session.data["pending_question"] = pending
        self.state(TurnState.BLOCKED_USER)
        return pending

    def answer(self, text: str) -> str:
        pending = self.session.data.pop("pending_question", None)
        if not pending:
            return text
        self.state(TurnState.RUNNING)
        return "User answer to the pending question: " + text

    def enqueue(self, message: str) -> None:
        if not message.strip():
            raise ValueError("Follow-up message must not be empty")
        self.session.data["runtime"]["queued_turns"].append(message.strip())

    def next_queued(self) -> str | None:
        queue = self.session.data["runtime"]["queued_turns"]
        return queue.pop(0) if queue else None


class ToolLoopGuard:
    """Detect repeated no-progress calls while permitting normal retries."""

    def __init__(self, session, limit: int = 30):
        self.session = session
        self.limit = limit
        self.history = session.data.setdefault("tool_loop_history", [])

    @staticmethod
    def _digest(value) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    def before(self, name: str, arguments: dict) -> str | None:
        fingerprint = self._digest({"name": name, "arguments": arguments})
        repeated = [
            item for item in self.history[-6:] if item["fingerprint"] == fingerprint
        ]
        if len(repeated) >= 3:
            return "Loop detected: identical tool call already made three times without progress"
        if len(repeated) == 2:
            return "Loop warning: this is the third identical tool call; change strategy if it fails"
        return None

    def record(self, name: str, arguments: dict, result: dict) -> None:
        self.history.append(
            {
                "fingerprint": self._digest({"name": name, "arguments": arguments}),
                "result": self._digest(result),
            }
        )
        del self.history[: -self.limit]
