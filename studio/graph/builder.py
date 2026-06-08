"""LangGraph builder: assembles the Sprint 1 StateGraph."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from studio.graph.edges import (
    build_friction_router,
    design_to_build_router,
    skeleton_verify_router,
)
from studio.graph.state import GraphState


def _make_inject(db_factory, llm, prompt_loader):
    """Wrap a node fn so it runs in a fresh DB session, committed on return.

    Shared by both graph builders so node dependency-injection lives in one place.
    """
    def _inject(fn):
        async def wrapped(state: GraphState) -> dict:
            async with db_factory() as db:
                result = await fn(state, db=db, llm=llm, prompt_loader=prompt_loader)
                await db.commit()
                return result
        wrapped.__name__ = fn.__name__
        return wrapped
    return _inject


def build_sprint1_graph(
    db_factory,  # callable returning AsyncSession (context manager)
    llm,         # LLMClient
    prompt_loader,  # PromptLoader
) -> Any:  # CompiledStateGraph
    """Build and compile the Sprint 1 LangGraph.

    Graph topology:
        START
          → init_session
          → design_agent
          → skeleton_build  ─── friction? → design_agent
                            └── clean    → skeleton_verify
          → skeleton_verify ─── fail?    → design_agent
                            └── pass     → complete
          → complete
          → END
    """
    from studio.graph.nodes.complete import complete_node
    from studio.graph.nodes.design_agent import design_agent_node
    from studio.graph.nodes.init_session import init_session_node
    from studio.graph.nodes.skeleton_build import skeleton_build_node
    from studio.graph.nodes.skeleton_verify import skeleton_verify_node

    _inject = _make_inject(db_factory, llm, prompt_loader)
    graph = StateGraph(GraphState)

    graph.add_node("init_session", _inject(init_session_node))
    graph.add_node("design_agent", _inject(design_agent_node))
    graph.add_node("skeleton_build", _inject(skeleton_build_node))
    graph.add_node("skeleton_verify", _inject(skeleton_verify_node))
    graph.add_node("complete", _inject(complete_node))

    # Edges
    graph.add_edge(START, "init_session")
    graph.add_edge("init_session", "design_agent")

    # design_agent → skeleton_build, unless a hard stop (budget) set an error.
    graph.add_conditional_edges(
        "design_agent",
        design_to_build_router,
        {
            "skeleton_build": "skeleton_build",
            "complete": "complete",
        },
    )

    graph.add_conditional_edges(
        "skeleton_build",
        build_friction_router,
        {
            "design_agent": "design_agent",
            "skeleton_verify": "skeleton_verify",
            "complete": "complete",
        },
    )

    graph.add_conditional_edges(
        "skeleton_verify",
        skeleton_verify_router,
        {
            "design_agent": "design_agent",
            "complete": "complete",
        },
    )

    graph.add_edge("complete", END)

    return graph.compile()


def build_sprint2_graph(db_factory, llm, prompt_loader, *, checkpointer=None):  # noqa: C901
    """Build the full Sprint 2 graph: all 15 nodes from §2.2, wired per §2.1.

    Three loops — Design⇄UX, Design⇄Build (friction), Build⇄Verify (retry) — plus
    design and ship human gates. Compile with a checkpointer to support interactive
    human gates; benchmark runs use config.auto_approve_gates and need none.
    """
    from studio.graph.edges import (
        design_agent_router,
        design_ux_router,
        feature_friction_router,
        human_gate_design_router,
        reviewer_router,
        skeleton_friction_router,
        skeleton_verify_gate_router,
        slice_done_router,
        ux_review_router,
        verify_router,
    )
    from studio.graph.nodes.complete import complete_node
    from studio.graph.nodes.design_agent import design_agent_node
    from studio.graph.nodes.feature_nodes import (
        build_agent_node,
        design_ux_gate_node,
        reviewer_node,
        slice_done_node,
        slice_plan_node,
        ux_agent_node,
        ux_review_node,
        verify_node,
    )
    from studio.graph.nodes.human_gate import make_human_gate_node
    from studio.graph.nodes.init_session import init_session_node
    from studio.graph.nodes.skeleton_build import skeleton_build_node
    from studio.graph.nodes.skeleton_verify import skeleton_verify_node

    _inject = _make_inject(db_factory, llm, prompt_loader)
    g = StateGraph(GraphState)
    nodes = {
        "init_session": init_session_node,
        "design_agent": design_agent_node,
        "ux_agent": ux_agent_node,
        "design_ux_gate": design_ux_gate_node,
        "skeleton_build": skeleton_build_node,
        "skeleton_verify": skeleton_verify_node,
        "human_gate_design": make_human_gate_node("design"),
        "slice_plan": slice_plan_node,
        "build_agent": build_agent_node,
        "verify": verify_node,
        "ux_review": ux_review_node,
        "reviewer": reviewer_node,
        "slice_done": slice_done_node,
        "human_gate_ship": make_human_gate_node("ship"),
        "complete": complete_node,
    }
    for name, fn in nodes.items():
        g.add_node(name, _inject(fn))

    g.add_edge(START, "init_session")
    g.add_edge("init_session", "design_agent")
    g.add_conditional_edges("design_agent", design_agent_router, {
        "ux_agent": "ux_agent", "build_agent": "build_agent", "complete": "complete",
    })
    g.add_edge("ux_agent", "design_ux_gate")
    g.add_conditional_edges("design_ux_gate", design_ux_router, {
        "design_agent": "design_agent", "skeleton_build": "skeleton_build", "complete": "complete",
    })
    g.add_conditional_edges("skeleton_build", skeleton_friction_router, {
        "design_agent": "design_agent", "skeleton_verify": "skeleton_verify",
        "complete": "complete",
    })
    g.add_conditional_edges("skeleton_verify", skeleton_verify_gate_router, {
        "design_agent": "design_agent", "human_gate_design": "human_gate_design",
        "complete": "complete",
    })
    g.add_conditional_edges("human_gate_design", human_gate_design_router, {
        "design_agent": "design_agent", "slice_plan": "slice_plan", "complete": "complete",
    })
    g.add_edge("slice_plan", "build_agent")
    g.add_conditional_edges("build_agent", feature_friction_router, {
        "design_agent": "design_agent", "verify": "verify", "complete": "complete",
    })
    g.add_conditional_edges("verify", verify_router, {
        "build_agent": "build_agent", "design_agent": "design_agent",
        "ux_review": "ux_review", "complete": "complete",
    })
    g.add_conditional_edges("ux_review", ux_review_router, {
        "design_agent": "design_agent", "reviewer": "reviewer", "complete": "complete",
    })
    g.add_conditional_edges("reviewer", reviewer_router, {
        "build_agent": "build_agent", "slice_done": "slice_done", "complete": "complete",
    })
    g.add_conditional_edges("slice_done", slice_done_router, {
        "slice_plan": "slice_plan", "human_gate_ship": "human_gate_ship", "complete": "complete",
    })
    g.add_edge("human_gate_ship", "complete")
    g.add_edge("complete", END)

    return g.compile(checkpointer=checkpointer) if checkpointer else g.compile()
