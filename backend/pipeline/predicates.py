"""
predicates.py — Dependency-free turn predicates.

The three pure functions every pipeline module needs to ask "what mode is this
turn in?": ``agent_enabled`` (global Agent toggle), ``is_dual_model`` (separate
agent endpoint?), and ``resolve_persona_id`` (effective persona). They read a
settings/conversation mapping and return a flag or id — nothing else.

This is the pipeline-local mirror of ``core/``: a leaf that imports nothing
upward, so modules far apart in the dependency order (``config`` resolving the
lanes, ``persistence`` deciding whether to write director state) can share these
predicates without dragging in the heavy pass modules. It sits *below* ``config``
deliberately — ``config`` imports the pass stages, so the predicates cannot live
there without coupling every importer to ``passes/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ..inference import LLMClient


def is_dual_model(agent_client: "LLMClient | None") -> bool:
    """Return True when a separate agent endpoint is configured (dual-model mode).

    Single-model: writer and agent share one endpoint and KV cache.
    Dual-model: agent (director + editor) runs on its own endpoint with a
    separate KV cache.
    """
    return agent_client is not None


def agent_enabled(settings: Mapping[str, Any]) -> bool:
    """Return True when the global Agent toggle is on (default).

    All agent-gated features — director, editor, length guard, feedback,
    mood/state persistence — read this single function so the default-on
    semantics stay consistent everywhere.
    """
    return bool(settings.get("enable_agent", 1))


def resolve_persona_id(
    conv: Mapping[str, Any],
    card: Mapping[str, Any] | None,
    settings: Mapping[str, Any],
) -> int | None:
    """Resolve the effective persona id for a turn.

    A locked persona overrides the global active persona within its scope.
    Priority: conversation lock → character-card lock → global active persona.
    """
    return conv.get("persona_lock_id") or (card.get("persona_lock_id") if card else None) or settings.get("active_persona_id")
