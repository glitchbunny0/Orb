"""Pipeline layer — the Director→Writer→Editor turn engine.

Sits above ``workflows`` in the one-way order
(``api → {pipeline, features} → workflows → {inference, analysis} → {core, database}``).
The turn lifecycle is split into single-purpose modules:

* ``predicates`` — dependency-free turn predicates (the package's ``core`` leaf)
* ``state`` — per-turn contract dataclasses (incl. ``_PipelineResult``)
* ``config`` — per-turn config / tool-blob resolution
* ``context`` — inbound load, prefixes, and pre-pipeline setup
* ``workflow_bridge`` — the pre/post secondary-workflow hook loops
* ``orchestrator`` — the three-pass coordinator (``_run_pipeline``)
* ``persistence`` — outbound consume + persist
* ``entrypoints`` — the public ``handle_*`` turn entry points + ``_generate_reply``
* ``passes/`` — the individual passes

The facade re-exports the public turn entry points and the per-turn contract
types. Private symbols are reached via their owning module directly
(``orchestrator._run_pipeline``, ``persistence._consume_pipeline``,
``workflow_bridge._iterate_pre_pipeline_hooks``, …).
"""

from __future__ import annotations

from .entrypoints import (
    handle_fork_edit,
    handle_magic_rewrite,
    handle_regenerate,
    handle_super_regenerate,
    handle_turn,
)
from .predicates import agent_enabled, resolve_persona_id
from .state import ModelLane, TurnState, _PipelineConfig

__all__ = [
    # entrypoints — turn entry points
    "handle_fork_edit",
    "handle_magic_rewrite",
    "handle_regenerate",
    "handle_super_regenerate",
    "handle_turn",
    # predicates — turn predicates
    "agent_enabled",
    "resolve_persona_id",
    # state — per-turn contracts
    "ModelLane",
    "TurnState",
    "_PipelineConfig",
]
