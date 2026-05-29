"""RunConfig for reproducible LLM runs."""

from dataclasses import dataclass, field


@dataclass
class RunConfig:
    """Captures all parameters needed to reproduce an LLM run."""

    model_version: str
    prompt_hashes: dict[str, str] = field(default_factory=dict)
    seed: int = 0
    temperature: float = 0.0
    max_tokens: int = 4096
