"""Configuration tests."""

import pytest
from pathlib import Path
import tempfile
import os

from jyot_monitor.config import (
    load_sources_config,
    ConfigError,
    get_env_var,
)


def test_load_valid_sources_config():
    """Test loading a valid sources configuration."""
    config_yaml = """
sources:
  - name: "Test Source"
    type: rss
    url: "https://example.com/feed"
    allowed_hosts:
      - "example.com"
    poll_interval_seconds: 3600

limits:
  max_items_per_run: 50
  max_steps_per_item: 10

budgets:
  per_item_usd: 0.10
  per_run_usd: 5.00

thresholds:
  ocr_confidence_second_opinion: 0.7
  urgency_critique_threshold: 75
  urgency_alert_threshold: 85
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_yaml)
        config_path = Path(f.name)
    
    try:
        config = load_sources_config(config_path)
        
        assert len(config.sources) == 1
        assert config.sources[0].name == "Test Source"
        assert config.limits.max_items_per_run == 50
        assert config.budgets.per_item_usd == 0.10
        assert config.thresholds.urgency_alert_threshold == 85
    finally:
        config_path.unlink()


def test_load_nonexistent_config():
    """Test loading nonexistent config raises error."""
    with pytest.raises(ConfigError, match="not found"):
        load_sources_config(Path("/nonexistent/config.yaml"))


def test_invalid_yaml():
    """Test invalid YAML raises error."""
    config_yaml = """
sources:
  - name: "Test"
    invalid: {unclosed
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_yaml)
        config_path = Path(f.name)
    
    try:
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_sources_config(config_path)
    finally:
        config_path.unlink()


def test_config_requires_at_least_one_source():
    """Test config validation requires at least one source."""
    config_yaml = """
sources: []
limits:
  max_items_per_run: 100
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_yaml)
        config_path = Path(f.name)
    
    try:
        with pytest.raises(ConfigError, match="At least one source"):
            load_sources_config(config_path)
    finally:
        config_path.unlink()


def test_source_requires_allowed_hosts():
    """Test source validation requires allowed_hosts."""
    config_yaml = """
sources:
  - name: "Test"
    type: rss
    url: "https://example.com/feed"
    allowed_hosts: []
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_yaml)
        config_path = Path(f.name)
    
    try:
        with pytest.raises(ConfigError):
            load_sources_config(config_path)
    finally:
        config_path.unlink()


def test_get_env_var_with_default():
    """Test getting environment variable with default."""
    # Clear any existing value
    os.environ.pop("TEST_VAR", None)
    
    value = get_env_var("TEST_VAR", default="default_value")
    assert value == "default_value"


def test_get_env_var_required():
    """Test required environment variable raises error if missing."""
    os.environ.pop("REQUIRED_VAR", None)
    
    with pytest.raises(ConfigError, match="Required environment variable"):
        get_env_var("REQUIRED_VAR", required=True)


def test_get_env_var_exists():
    """Test getting existing environment variable."""
    os.environ["EXISTING_VAR"] = "test_value"
    
    try:
        value = get_env_var("EXISTING_VAR")
        assert value == "test_value"
    finally:
        os.environ.pop("EXISTING_VAR", None)
