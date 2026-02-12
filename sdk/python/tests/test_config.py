from agentguard.config import GuardConfig
from agentguard.models import ThresholdConfig


def test_guard_config_defaults():
    config = GuardConfig()
    assert config.mode == "async"
    assert config.correction == "none"
    assert config.transparency == "opaque"
    assert config.flush_interval_s == 1.0
    assert config.flush_batch_size == 50
    assert config.timeout_s == 30.0


def test_guard_config_custom():
    config = GuardConfig(
        mode="sync",
        correction="cascade",
        transparency="transparent",
        api_url="http://localhost:8000",
    )
    assert config.mode == "sync"
    assert config.api_url == "http://localhost:8000"


def test_guard_config_with_custom_thresholds():
    config = GuardConfig(
        confidence_threshold=ThresholdConfig(
            pass_threshold=0.9,
            flag_threshold=0.6,
            block_threshold=0.2,
        )
    )
    assert config.confidence_threshold.pass_threshold == 0.9
