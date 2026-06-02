"""Integration test: graph builder produces a compilable graph."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from contextlib import asynccontextmanager


@pytest.fixture
def mock_db_factory():
    """Mock AsyncSession factory as async context manager."""
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.add = MagicMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory


@pytest.fixture
def mock_llm():
    from studio.ai.llm_client import LLMResponse
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(
        content="{}",
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.001,
        model="claude-sonnet-4-6",
        latency_ms=100,
    ))
    return llm


@pytest.fixture
def mock_prompt_loader():
    from studio.ai.prompt_loader import PromptTemplate
    loader = MagicMock()
    tpl = PromptTemplate(content="test prompt {{var}}", hash="abc123", path="/fake/path")
    loader.load.return_value = tpl
    loader.render.return_value = "rendered prompt"
    return loader


def test_graph_builder_compiles(mock_db_factory, mock_llm, mock_prompt_loader):
    """Graph should compile without errors."""
    from studio.graph.builder import build_sprint1_graph

    compiled = build_sprint1_graph(
        db_factory=mock_db_factory,
        llm=mock_llm,
        prompt_loader=mock_prompt_loader,
    )
    assert compiled is not None
    # LangGraph compiled graphs have get_graph method
    assert hasattr(compiled, "ainvoke") or hasattr(compiled, "invoke")


def test_graph_has_expected_nodes(mock_db_factory, mock_llm, mock_prompt_loader):
    """Graph should contain all Sprint 1 nodes."""
    from studio.graph.builder import build_sprint1_graph

    compiled = build_sprint1_graph(
        db_factory=mock_db_factory,
        llm=mock_llm,
        prompt_loader=mock_prompt_loader,
    )
    # Access the underlying graph
    graph = compiled.get_graph()
    node_names = set(graph.nodes.keys())
    expected = {"init_session", "design_agent", "skeleton_build", "skeleton_verify", "complete"}
    assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"
