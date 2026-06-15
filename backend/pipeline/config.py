"""
config.py — Per-turn configuration resolution.

Turns the raw ``settings`` + enabled-tools map into the immutable
:class:`_PipelineConfig` the passes run under: resolves feature flags, builds the
two :class:`ModelLane` call surfaces (writer + agent), folds the length guard,
and assembles the dynamic tool-schema overrides shared byte-identically by every
cached call (so the LLM's KV cache is not busted across passes / magic-rewrite).

Imports the pass modules (length guard, director ``direct_scene`` override,
editor feedback) — which is why the dependency-free predicates live one level
down in ``predicates.py`` rather than here.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..core import ChatMessage, Macros
from ..database.models import PhraseGroup
from ..inference import CachedBase, LLMClient, enabled_schemas
from .passes.director import build_direct_scene_override
from .passes.editor import _feedback_active, build_feedback_override
from .passes.editor.length_guard import (
    LengthGuard,
    apply_length_guard_tools,
    resolve_length_guard,
)
from .predicates import agent_enabled, is_dual_model
from .state import ModelLane, _PipelineConfig


def _resolve_pipeline_config(
    settings: Mapping[str, Any],
    enabled_tools: Mapping[str, bool],
    *,
    macros: Macros,
    client: LLMClient,
    agent_client: LLMClient | None,
    agent_prefix: list[ChatMessage] | None,
    prefix: list[ChatMessage],
    phrase_bank: list[PhraseGroup] | None,
    schema_overrides: Mapping[str, dict],
) -> _PipelineConfig:
    """Build the immutable per-turn config used throughout the pipeline.

    Resolves feature flags (audit, length guard, reasoning per pass), builds
    the two model lanes (writer and agent), and returns a :class:`_PipelineConfig`.
    Called once at the start of each turn by ``orchestrator._run_pipeline`` and
    ``entrypoints.handle_magic_rewrite``.
    """
    agent_on = agent_enabled(settings)
    reasoning_passes = settings.get("reasoning_enabled_passes") or {}

    audit_enabled = agent_on and bool(enabled_tools.get("editor_apply_patch", False)) and phrase_bank is not None

    # editor_rewrite is mirrored into the schema blob when the length guard is on.
    length_guard: LengthGuard | None = resolve_length_guard(settings, agent_on)
    enabled_tools = apply_length_guard_tools(enabled_tools, length_guard)

    # In dual-model mode the writer's KV cache is disjoint; skip tool schemas there.
    dual_model = is_dual_model(agent_client)
    writer_enabled_tools = {} if dual_model else enabled_tools

    writer_lane = ModelLane(
        client=client,
        base=CachedBase(
            prefix=tuple(prefix),
            tools=tuple(enabled_schemas(writer_enabled_tools, schema_overrides)),
            model=settings["model_name"],
            resolve=macros.resolve_prompt_messages,
        ),
    )
    if dual_model:
        assert agent_client is not None
        agent_lane = ModelLane(
            client=agent_client,
            base=CachedBase(
                prefix=tuple(agent_prefix or prefix),
                tools=tuple(enabled_schemas(enabled_tools, schema_overrides)),
                model=settings.get("agent_model_name", settings["model_name"]),
                resolve=macros.resolve_prompt_messages,
            ),
        )
    else:
        # Single-model: agent shares the writer's lane (same KV cache base).
        agent_lane = writer_lane

    return _PipelineConfig(
        agent_on=agent_on,
        enabled_tools=enabled_tools,
        director_reasoning_on=bool(reasoning_passes.get("director", True)),
        writer_reasoning_on=bool(reasoning_passes.get("writer", False)),
        editor_reasoning_on=bool(reasoning_passes.get("editor", False)),
        audit_enabled=audit_enabled,
        length_guard=length_guard,
        do_edit=audit_enabled or length_guard is not None,
        writer_enabled_tools=writer_enabled_tools,
        writer_lane=writer_lane,
        agent_lane=agent_lane,
    )


def _split_interactive_fragments(
    fragments: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Split interactive fragments into writer vs. feedback groups.

    Returns ``(writer_fragments, feedback_fragments)``. ``field_type="feedback"``
    fragments are surfaced to the user via the post-writer feedback step and
    never reach the writer prompt; all others shape the ``direct_scene`` tool
    and the Scene Direction block.
    """
    writer = [df for df in fragments if df.get("field_type") != "feedback"]
    feedback = [df for df in fragments if df.get("field_type") == "feedback"]
    return writer, feedback


def _build_writer_tools_blob(
    settings: Mapping[str, Any],
    interactive_fragments: Sequence[Mapping[str, Any]],
    enabled_tools: dict,
    *,
    agentic_lorebook: bool = False,
) -> dict:
    """Build the dynamic tool schema overrides shared by every writer-cached call.

    Mutates *enabled_tools* in place to add ``give_feedback`` when feedback is
    active. Returns the ``schema_overrides`` dict (``direct_scene`` plus
    optionally ``give_feedback``) that keeps the tool blob byte-identical across
    the main turn and magic-rewrite so the LLM's KV cache is not busted.

    Called by ``context._prepare_turn`` and ``entrypoints.handle_magic_rewrite``.
    """
    writer_fragments, feedback_fragments = _split_interactive_fragments(interactive_fragments)
    overrides: dict = {"direct_scene": build_direct_scene_override(writer_fragments, agentic_lorebook=agentic_lorebook)}
    if _feedback_active(settings, feedback_fragments, agent_on=agent_enabled(settings)):
        overrides["give_feedback"] = build_feedback_override(feedback_fragments)
        enabled_tools["give_feedback"] = True
    return overrides
