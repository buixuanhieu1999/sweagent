"""Lifecycle manager for optional, independently running child agents."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable


class AgentState(StrEnum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


@dataclass
class AgentHandle:
    agent_id: str
    role: str
    task: str
    parent_id: str | None = None
    state: AgentState = AgentState.RUNNING
    inbox: list[str] = field(default_factory=list)
    result: dict | None = None
    future: Future | None = None


class AgentManager:
    """Runs bounded child agents without imposing a role pipeline on the parent."""

    def __init__(
        self,
        runner: Callable[[AgentHandle], dict],
        *,
        max_agents: int = 4,
        max_depth: int = 1,
    ):
        self.runner = runner
        self.max_agents, self.max_depth = max_agents, max_depth
        self.handles: dict[str, AgentHandle] = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(
            max_workers=max_agents, thread_name_prefix="agent"
        )

    def spawn(self, role: str, task: str, parent_id: str | None = None) -> AgentHandle:
        if parent_id and self.max_depth < 1:
            raise ValueError("Maximum agent depth reached")
        with self.lock:
            active = sum(
                handle.state == AgentState.RUNNING for handle in self.handles.values()
            )
            if active >= self.max_agents:
                raise ValueError("Maximum concurrent agents reached")
            handle = AgentHandle("agent-" + uuid.uuid4().hex[:8], role, task, parent_id)
            self.handles[handle.agent_id] = handle
            handle.future = self.pool.submit(self._run, handle)
            return handle

    def _run(self, handle: AgentHandle) -> None:
        try:
            result = self.runner(handle)
            with self.lock:
                if handle.state != AgentState.CLOSED:
                    handle.result, handle.state = result, AgentState.COMPLETE
        except Exception as exc:
            with self.lock:
                if handle.state != AgentState.CLOSED:
                    handle.result = {"ok": False, "error": str(exc)}
                    handle.state = AgentState.FAILED

    def send(self, agent_id: str, message: str) -> None:
        if not message.strip():
            raise ValueError("Agent message must not be empty")
        with self.lock:
            handle = self._get(agent_id)
            if handle.state == AgentState.CLOSED:
                raise ValueError("Agent is closed")
            handle.inbox.append(message.strip())

    def wait(self, agent_ids: list[str], timeout: float | None = None) -> list[dict]:
        result = []
        for agent_id in agent_ids:
            handle = self._get(agent_id)
            if handle.future:
                handle.future.result(timeout=timeout)
            result.append(self.public(handle))
        return result

    def resume(self, agent_id: str, message: str = "") -> AgentHandle:
        with self.lock:
            handle = self._get(agent_id)
            if handle.state == AgentState.RUNNING:
                return handle
            if message:
                handle.inbox.append(message)
            handle.state, handle.result = AgentState.RUNNING, None
            handle.future = self.pool.submit(self._run, handle)
            return handle

    def close(self, agent_id: str) -> None:
        with self.lock:
            handle = self._get(agent_id)
            if handle.future:
                handle.future.cancel()
            handle.state = AgentState.CLOSED

    def _get(self, agent_id: str) -> AgentHandle:
        if agent_id not in self.handles:
            raise ValueError(f"Unknown agent: {agent_id}")
        return self.handles[agent_id]

    @staticmethod
    def public(handle: AgentHandle) -> dict:
        return {
            "agent_id": handle.agent_id,
            "role": handle.role,
            "status": handle.state,
            "result": handle.result,
            "queued_messages": len(handle.inbox),
        }
