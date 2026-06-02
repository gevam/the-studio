"""Contract test: the design agent's output schema (LivingDesign).

The agent now produces LivingDesign via native structured output (no
prompt-and-parse), so the contract is the schema itself: it must accept the
documented shapes and normalize the LLM quirks we still tolerate.
"""

from studio.design.schema import LivingDesign

MINIMAL_LIVING_DESIGN = {
    "version": 1,
    "content_hash": "",
    "modules": [],
    "data_model": [],
    "ux_flows": [],
    "open_questions": ["TBD"],
    "known_friction": [],
    "sections": [],
}


def test_minimal_design_validates():
    design = LivingDesign(**MINIMAL_LIVING_DESIGN)
    assert design.version == 1
    assert design.open_questions == ["TBD"]


def test_design_with_real_modules():
    data = dict(MINIMAL_LIVING_DESIGN)
    data["modules"] = [{
        "name": "cli",
        "responsibility": "Entry point",
        "interfaces": ["CLIRunner"],
        "dependencies": ["storage"],
        "injection_points": ["storage"],
    }]
    design = LivingDesign(**data)
    assert len(design.modules) == 1
    assert design.modules[0].name == "cli"


def test_unwrap_llm_quirk_dict_wrapped_lists():
    # LLMs sometimes wrap list fields in a dict; the validator normalizes them.
    data = dict(MINIMAL_LIVING_DESIGN)
    data["modules"] = {"modules": [{"name": "svc", "responsibility": "r"}]}
    data["data_model"] = {"entities": [{"name": "Todo"}]}
    design = LivingDesign(**data)
    assert design.modules[0].name == "svc"
    assert design.data_model[0].name == "Todo"


def test_empty_payload_uses_defaults():
    # The schema is all-optional — an empty object is a valid (empty) design.
    design = LivingDesign()
    assert design.version == 1
    assert design.modules == []
