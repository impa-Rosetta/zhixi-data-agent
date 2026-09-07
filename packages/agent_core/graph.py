"""Bounded LangGraph topology; durable domain checkpoints live in platform tables."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph


class GraphState(TypedDict, total=False):
    run_id: str
    message: str
    current_node: str
    status: str
    needs_clarification: bool
    needs_confirmation: bool
    verification_failed: bool
    replans: int


def _enter(name: str) -> Callable[[GraphState], GraphState]:
    def node(_: GraphState) -> GraphState:
        return {"current_node": name}

    return node


def _after_policy(state: GraphState) -> str:
    if state.get("needs_clarification"):
        return "clarify"
    if state.get("needs_confirmation"):
        return "confirm"
    return "execute"


def _after_verify(state: GraphState) -> str:
    if state.get("verification_failed") and state.get("replans", 0) < 1:
        return "replan"
    return "present"


def build_agent_graph() -> Any:
    builder = StateGraph(GraphState)
    for name in (
        "understand",
        "bind",
        "plan",
        "policy_check",
        "clarify",
        "confirm",
        "execute",
        "verify",
        "replan",
        "present",
    ):
        builder.add_node(name, cast(Any, _enter(name)))
    builder.add_edge(START, "understand")
    builder.add_edge("understand", "bind")
    builder.add_edge("bind", "plan")
    builder.add_edge("plan", "policy_check")
    builder.add_conditional_edges(
        "policy_check",
        _after_policy,
        {"clarify": "clarify", "confirm": "confirm", "execute": "execute"},
    )
    builder.add_edge("clarify", END)
    builder.add_edge("confirm", END)
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges(
        "verify", _after_verify, {"replan": "replan", "present": "present"}
    )
    builder.add_edge("replan", "execute")
    builder.add_edge("present", END)
    return builder.compile()
