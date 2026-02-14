from __future__ import annotations

from pydantic import BaseModel, Field

from vex.models import ThresholdConfig


class VexConfig(BaseModel):
    mode: str = "async"  # "sync" | "async"
    correction: str = "none"  # "cascade" | "none"
    transparency: str = "opaque"  # "opaque" | "transparent"
    confidence_threshold: ThresholdConfig = Field(default_factory=ThresholdConfig)
    api_url: str = "https://api.tryvex.dev"
    flush_interval_s: float = 1.0
    flush_batch_size: int = 50
    timeout_s: float = 10.0
    conversation_window_size: int = 10
    max_buffer_size: int = 10000
    log_event_ids: bool = False
