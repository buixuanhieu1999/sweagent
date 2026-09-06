"""Declarative subagent profiles; the generic main loop has no role branches."""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import Capability, CapabilityRegistry


@dataclass(frozen=True)
class AgentProfile:
    name: str
    description: str
    prompt: str
    tool_role: str


class AgentRegistry:
    def __init__(self, profiles: tuple[AgentProfile, ...]):
        self._profiles = {profile.name: profile for profile in profiles}
        self.capabilities = CapabilityRegistry()
        for profile in profiles:
            self.capabilities.register(
                Capability(profile.name, "subagent", profile.description, "medium")
            )

    def get(self, name: str) -> AgentProfile | None:
        return self._profiles.get(name)

    def names(self) -> list[str]:
        return list(self._profiles)


def builtin_agents() -> AgentRegistry:
    return AgentRegistry(
        (
            AgentProfile(
                "explore",
                "Focused workspace investigation with concise evidence.",
                "Investigate the delegated question using evidence. Report concise findings with paths, symbols, relationships, and uncertainties. Do not modify source files.",
                "explorer",
            ),
            AgentProfile(
                "architect",
                "Focused design and impact analysis.",
                "Analyze the delegated design question. Inspect relevant evidence, identify constraints and tradeoffs, and return a concise plan or recommendation. Do not modify source files.",
                "architect",
            ),
            AgentProfile(
                "reviewer",
                "Focused review of a proposed or current change.",
                "Review against the delegated request, relevant instructions, diff, and verification evidence. Report concrete findings and risks. Do not modify source files.",
                "reviewer",
            ),
        )
    )
