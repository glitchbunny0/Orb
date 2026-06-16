"""
state.py — The per-turn contract dataclasses shared across passes.

``ModelLane`` / ``_PipelineConfig`` / ``TurnState`` are the turn-state contract
every pass reads: the orchestrator builds them and the director / writer / editor
passes consume them. They live here — a focused leaf the passes point *down* into
— rather than at the top in ``orchestrator.py``, so the dependency runs one
direction (passes → ``state``) instead of the passes reaching up into the
coordinator.

Only the dataclass *shapes* live here. Their construction and behaviour
(``_resolve_pipeline_config`` in ``config.py``, ``_make_result`` in
``orchestrator.py``, ``is_dual_model`` in ``predicates.py``, …) stay with their
callers. ``TurnState`` carries a turn end-to-end: the passes mutate it, the
orchestrator projects its result-subset into the terminal ``_result`` event via
``as_result_event_data``, and ``persistence._consume_pipeline`` rehydrates a
``TurnState`` from that dict to drive the saves — so one object (not a separate
result contract) follows each value from the director pass through to persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..core import ContentPart
from ..inference import CachedBase, LLMClient
from .passes.editor.length_guard import LengthGuard


@dataclass(frozen=True)
class ModelLane:
    """One model's call surface for the turn: a client paired with its
    byte-identical cached bottom (prefix + tools + model + the macro ``resolve``
    hook that scrubs placeholders from the final wire bytes).

    A turn has two lanes — ``writer`` and ``agent`` (director + editor). In
    single-model mode they are the *same object* (the writer's lane is reused for
    the agent), so the byte-identity invariant "director + editor + writer ride
    the same base" is structural, not a convention each call site must honour. In
    dual-model mode they are distinct: the agent lane carries the agent server's
    client, its own prefix + tool blob, and the agent model; the writer lane
    carries the writer client with an empty tools blob (Invariant 5).

    ``reasoning`` stays per-pass (director and editor share the agent lane but
    toggle reasoning independently), so it is not part of the lane.
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


# Result-subset of ``TurnState`` — the fields the terminal ``_result`` event
# carries and that ``persistence`` reads back. Listed explicitly (rather than
# all of ``TurnState``) so the wire dict stays the same JSON shape it was when a
# separate result dataclass existed, and so non-result working fields
# (``writer_content``, ``progressive_state``, ``valid_progressive_ids``, …) stay
# off the wire. Every name here is a ``TurnState`` field with a default, so the
# dict rehydrates cleanly via ``TurnState(**event["data"])``.
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
    """Mutable per-turn state threaded by reference through the three pass
    stages (``director_stage`` / ``writer_stage`` / ``editor_stage``), then
    carried out through persistence.

    These were ``_run_pipeline``'s ~20 turn-state locals. One object follows each
    value from the director pass through to the save: the passes mutate it, the
    orchestrator projects its result-subset (``_RESULT_FIELDS``) into the
    terminal ``_result`` event via :meth:`as_result_event_data`, and
    ``persistence._consume_pipeline`` rehydrates a fresh ``TurnState`` from that
    dict. Every field defaults, so a turn aborted before ``_result`` fires (or a
    test injecting a partial payload) still produces a usable instance.

    Seeded in ``_run_pipeline`` from ``director`` (``active_moods`` and the
    progressive seed filtered to valid fragment ids) and the resolved
    ``user_message`` (``effective_msg``). ``progressive_state`` /
    ``valid_progressive_ids`` are turn inputs (not result fields): the director
    seed map and the id set used to filter director output into
    ``progressive_fields``. ``staged_attachments`` / ``staged_message_state`` are
    set by the orchestrator from the post-pipeline workflow hooks just before
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
        """Shallow result-subset dict for the ``_result`` SSE envelope. Shallow
        on purpose: ``staged_attachments`` carries raw artifact bytes that must
        not be deep-copied."""
        return {name: getattr(self, name) for name in _RESULT_FIELDS}
