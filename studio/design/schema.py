"""Living Design artifact schema — the single source of design truth."""

import hashlib
from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator
from typing import Any


class DesignSection(BaseModel):
    id: str
    title: str
    content: str
    content_hash: str = ""

    @field_validator("content_hash", mode="before")
    @classmethod
    def compute_hash(cls, v: str, info: object) -> str:
        if not v and hasattr(info, "data") and "content" in info.data:
            return hashlib.sha256(info.data["content"].encode()).hexdigest()
        return v


class ModuleBoundary(BaseModel):
    name: str
    responsibility: str
    interfaces: list[str] = []
    dependencies: list[str] = []
    injection_points: list[str] = []


class DataEntity(BaseModel):
    name: str
    fields: list[dict] = []
    relationships: list[str] = []
    privacy_classification: str = "internal"


class UXFlow(BaseModel):
    name: str
    steps: list[str] = []
    entry_point: str = ""
    success_criteria: str = ""
    error_states: list[str] = []
    i18n_considerations: list[str] = []


class ArchitectureDecision(BaseModel):
    id: str
    title: str
    context: str
    decision: str
    rationale: str
    consequences: list[str]
    status: str = "accepted"  # "proposed" | "accepted" | "superseded"
    date: datetime = datetime.now()


class ThreatModelEntry(BaseModel):
    threat_type: str  # S/T/R/I/D/E
    description: str
    component: str = ""
    mitigation: str = ""
    status: str = "open"  # "open" | "mitigated" | "accepted"


class PrivacyDataItem(BaseModel):
    data_element: str
    classification: str = "internal"
    purpose: str = ""
    retention: str = ""
    encryption: str = ""
    erasure_path: str = ""


class LivingDesign(BaseModel):
    """Complete living design artifact."""

    version: int = 1
    content_hash: str = ""

    # Core sections
    modules: list[ModuleBoundary] = []
    data_model: list[DataEntity] = []
    ux_flows: list[UXFlow] = []
    customer_journey: str = ""
    experience_metric: dict = {}

    # Cross-cutting
    architecture_decisions: list[ArchitectureDecision] = []
    threat_model: list[ThreatModelEntry] = []
    privacy_inventory: list[PrivacyDataItem] = []
    i18n_plan: dict = {}

    # Health
    open_questions: list[str] = []
    known_friction: list[str] = []

    # Sections index
    sections: list[DesignSection] = []

    @model_validator(mode="before")
    @classmethod
    def unwrap_llm_quirks(cls, data: Any) -> Any:
        """Normalize LLM output quirks before validation.

        LLMs sometimes wrap list fields in dicts, e.g.:
          data_model: {"entities": [...]} → data_model: [...]
          modules: {"modules": [...]}     → modules: [...]
        """
        if not isinstance(data, dict):
            return data
        for field in ("data_model", "modules", "ux_flows", "architecture_decisions",
                      "threat_model", "privacy_inventory", "sections"):
            val = data.get(field)
            if isinstance(val, dict):
                # Take the first list-valued key in the dict
                for v in val.values():
                    if isinstance(v, list):
                        data[field] = v
                        break
                else:
                    data[field] = []
        return data

    def compute_and_set_hash(self) -> "LivingDesign":
        content = self.model_dump_json(exclude={"content_hash"})
        return self.model_copy(update={"content_hash": hashlib.sha256(content.encode()).hexdigest()})
