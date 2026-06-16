"""
state.py — Per-turn dataclasses shared across passes.

``ModelLane``, ``_PipelineConfig``, and ``TurnState`` are built by the
orchestrator and consumed by the director, writer, and editor passes. They live
here so the passes depend downward into ``state`` rather than upward into the
orchestrator.

``TurnState`` travels the full turn: passes mutate it, the orchestrator
serializes a result-subset into the ``_result`` SSE event via
``as_result_event_data``, and persistence rehydrates a fresh ``TurnState`` from
that dict to drive the saves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..core import ContentPart
from ..inference import CachedBase, LLMClient
from .passes.editor.length_guard import LengthGuard


@dataclass(frozen=True)
class ModelLane:
    """One model's call surface for a turn: an LLM client paired with its
    cached base (prefix + tool blob + model name + macro resolver).

    A turn has two lanes — ``writer`` and ``agent`` (director + editor). In
    single-model mode both lanes are the same object, making the KV-cache
    byte-identity invariant structural rather than a per-call-site convention.
    In dual-model mode the agent lane carries its own client and prefix, while
    the writer lane has an empty tool blob (Invariant 5).

    Reasoning is per-pass (director and editor share the agent lane but toggle
    reasoning independently), so it is not part of the lane.
    """

    client: LLMClient
    base: CachedBase


@dataclass
class _PipelineConfig:
    """Resolved per-turn flags, lanes, and prefixes for ``_run_pipeline``."""

    agent_on: bool
    enabled_tools: Mapping[str, bool]
    director_reasoning_on: bool
    writer_reasoning_on: bool
    editor_reasoning_on: bool
    audit_enabled: bool
    length_guard: LengthGuard | None
    do_edit: bool
    writer_enabled_tools: Mapping[str, bool]
    # The two call surfaces for the turn. ``writer_lane`` runs the writer pass;
    # ``agent_lane`` runs director + editor. In single-model mode they are the
    # same object by construction (see :class:`ModelLane`).
    writer_lane: ModelLane
    agent_lane: ModelLane


# Fields the terminal ``_result`` event carries — a fixed subset of ``TurnState``
# so the wire shape stays stable and working fields (``writer_content``,
# ``progressive_state``, etc.) stay off the wire. Every name here is a
# ``TurnState`` field with a default, so the dict rehydrates cleanly via
# ``TurnState(**event["data"])``.
_RESULT_FIELDS = (
    "active_moods",
    "agent_raw",
    "calls",
    "latency",
    "rewritten_msg",
    "effective_msg",
    "resp_text",
    "inj_block",
    "extra_fields",
    "progressive_fields",
    "reasoning_director",
    "reasoning_writer",
    "reasoning_editor",
    "feedback_values",
    "staged_attachments",
    "staged_message_state",
)


@dataclass
class TurnState:
    """Mutable state threaded through all three pass stages, then consumed by persistence.

    Seeded at the start of ``_run_pipeline`` from the director state and user
    message; mutated by each stage; serialized into the ``_result`` event by
    ``as_result_event_data``; then rehydrated from that dict by persistence.
    Every field has a default so a partially-completed turn (aborted or under
    test) still produces a valid instance.

    ``progressive_state`` and ``valid_progressive_ids`` are inputs, not outputs:
    they hold the director's seed values and the id set used to filter its output
    into ``progressive_fields``. ``staged_attachments`` / ``staged_message_state``
    are set by the orchestrator from post-pipeline workflow hooks just before
    ``_result`` is emitted.
    """

    # --- seeds / inputs ---
    user_message: str = ""
    effective_msg: str = ""
    active_moods: list[str] = field(default_factory=list)
    progressive_state: dict = field(default_factory=dict)
    valid_progressive_ids: set[str] = field(default_factory=set)

    # --- director outputs ---
    agent_raw: str = ""
    calls: list[dict] = field(default_factory=list)
    latency: int = 0
    rewritten_msg: str | None = None
    extra_fields: dict = field(default_factory=dict)
    progressive_fields: dict = field(default_factory=dict)
    selected_lorebook_entries: list[str] = field(default_factory=list)
    inj_block: str = ""
    writer_lorebook_block: str = ""

    # --- writer / editor outputs ---
    resp_text: str = ""
    writer_content: "str | list[ContentPart]" = ""
    reasoning_director: str = ""
    reasoning_writer: str = ""
    reasoning_editor: str = ""
    feedback_values: dict = field(default_factory=dict)

    # --- post-pipeline workflow staging (set by the orchestrator) ---
    staged_attachments: list[dict] = field(default_factory=list)
    staged_message_state: dict = field(default_factory=dict)

    def as_result_event_data(self) -> dict:
        """Return the result-subset dict for the ``_result`` SSE envelope.

        Shallow copy on purpose: ``staged_attachments`` carries raw artifact bytes.
        """
        return {name: getattr(self, name) for name in _RESULT_FIELDS}
