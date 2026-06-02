"""Design friction contract — the key mechanism for Design⇄Build feedback."""

import uuid
from dataclasses import dataclass, field
from typing import Literal


FrictionCategory = Literal[
    "testability",
    "coupling",
    "complexity",
    "duplication",
    "readability",
    "workaround",
]

FrictionSeverity = Literal["low", "medium", "high", "critical"]


@dataclass
class FrictionReport:
    """Reported by Build agent when code quality signals a design defect."""

    severity: FrictionSeverity
    category: FrictionCategory
    description: str
    code_location: str  # file:line
    friction_score: float  # 0-10
    suggested_design_change: str


@dataclass
class DesignFrictionEvent:
    """Structured event persisted to design_friction table."""

    session_id: uuid.UUID
    slice_id: uuid.UUID
    severity: FrictionSeverity
    category: FrictionCategory
    description: str
    code_location: str
    friction_score: float
    suggested_design_change: str
    metrics_snapshot: dict = field(default_factory=dict)


@dataclass
class CodeQualityMetrics:
    coverage_pct: float = 0.0
    max_cyclomatic_complexity: float = 0.0
    coupling_score: float = 0.0
    duplication_pct: float = 0.0
    tests_count: int = 0
    tests_passing: int = 0


def severity_from_score(score: float) -> FrictionSeverity:
    if score >= 8.0:
        return "critical"
    elif score >= 6.0:
        return "high"
    elif score >= 4.0:
        return "medium"
    return "low"
