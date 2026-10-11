"""
Configuration loading and validation.
"""

import os
from pathlib import Path
from typing import Optional
import yaml
from dotenv import load_dotenv

from jyot_monitor.models import MonitorConfig, SourceConfig


class ConfigError(Exception):
    """Configuration validation errors."""
    pass


def load_env() -> None:
    """Load environment variables from .env if present."""
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)


def load_sources_config(config_path: Path) -> MonitorConfig:
    """
    Load and validate sources configuration from YAML.
    
    Args:
        config_path: Path to sources.yaml
        
    Returns:
        Validated MonitorConfig
        
    Raises:
        ConfigError: If config is invalid or missing required fields
    """
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML: {e}")
    
    if not isinstance(data, dict):
        raise ConfigError("Config must be a YAML object")
    
    try:
        config = MonitorConfig(**data)
    except Exception as e:
        raise ConfigError(f"Config validation failed: {e}")
    
    # Additional validation
    if not config.sources:
        raise ConfigError("At least one source must be configured")
    
    for source in config.sources:
        if not source.allowed_hosts:
            raise ConfigError(f"Source {source.name} must have allowed_hosts")
    
    return config


def get_env_var(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """
    Get environment variable with validation.
    
    Args:
        name: Variable name
        default: Default value if not set
        required: If True, raise ConfigError if not set
        
    Returns:
        Variable value or default
        
    Raises:
        ConfigError: If required variable is not set
    """
    value = os.getenv(name, default)
    
    if required and value is None:
        raise ConfigError(f"Required environment variable not set: {name}")
    
    return value


def get_data_dir() -> Path:
    """Get the data directory for SQLite and caches."""
    data_dir = Path(get_env_var("DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_artifacts_dir() -> Path:
    """Get the artifacts directory for traces, digests, etc."""
    artifacts_dir = Path(get_env_var("ARTIFACTS_DIR", "artifacts"))
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir


def get_database_path() -> Path:
    """Get the SQLite database path."""
    return get_data_dir() / "state.sqlite3"
