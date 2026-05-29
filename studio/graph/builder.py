"""LangGraph builder: assembles the Sprint 1 StateGraph."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from studio.graph.edges import build_friction_router, skeleton_verify_router
from studio.graph.state import GraphState


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

    # Inject dependencies into each node via closure
    def _inject(fn):
        async def wrapped(state: GraphState) -> dict:
            async with db_factory() as db:
                result = await fn(
                    state,
                    db=db,
                    llm=llm,
                    prompt_loader=prompt_loader,
                )
                await db.commit()
                return result
        wrapped.__name__ = fn.__name__
        return wrapped

    graph = StateGraph(GraphState)

    graph.add_node("init_session", _inject(init_session_node))
    graph.add_node("design_agent", _inject(design_agent_node))
    graph.add_node("skeleton_build", _inject(skeleton_build_node))
    graph.add_node("skeleton_verify", _inject(skeleton_verify_node))
    graph.add_node("complete", _inject(complete_node))

    # Edges
    graph.add_edge(START, "init_session")
    graph.add_edge("init_session", "design_agent")
    graph.add_edge("design_agent", "skeleton_build")

    graph.add_conditional_edges(
        "skeleton_build",
        build_friction_router,
        {
            "design_agent": "design_agent",
            "skeleton_verify": "skeleton_verify",
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
