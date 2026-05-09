"""Shared fixtures for read-screen-tool tests."""

import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def temp_dir():
    """Create a temporary directory that cleans up after the test."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_config_dict():
    """Return a minimal valid config dictionary for testing."""
    return {
        "provider": [
            {
                "name": "deepseek",
                "api_key": "sk-test-key",
                "base_url": "https://api.deepseek.com",
            }
        ],
        "models": [
            {
                "name": "deepseek-v4-pro",
                "provider": "deepseek",
                "context": 1048576,
                "vision": False,
            }
        ],
        "system_prompt": "You are a helpful assistant.",
        "default_model": "deepseek-v4-pro",
        "ocr": {
            "language": "ch",
            "device": "cpu",
        },
        "screenshot": {
            "hotkey_modifiers": ["ctrl", "shift"],
            "hotkey_button": "left",
        },
        "output_window": {
            "position": {"x": 100, "y": 100},
            "size": {"width": 600, "height": 400},
            "font": {"family": "Microsoft YaHei", "size": 14, "color": "#FFFFFF"},
            "shadow": True,
        },
        "systray": {
            "show_icon": True,
        },
        "knowledge": {
            "enabled": True,
            "directory": "knowledge",
        },
    }


@pytest.fixture
def sample_config_path(temp_dir, sample_config_dict):
    """Write a sample config to a temp file and return the path."""
    config_path = temp_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_config_dict, f, allow_unicode=True)
    return config_path
