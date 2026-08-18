from apps.config import DebugConfig, ProductionConfig, TestingConfig, resolve_config


def test_runtime_environment_resolution_preserves_testing_isolation():
    assert resolve_config("testing") is TestingConfig
    assert resolve_config("Testing") is TestingConfig


def test_runtime_environment_resolution_selects_production_and_safe_default():
    assert resolve_config("production") is ProductionConfig
    assert resolve_config("unknown") is DebugConfig
