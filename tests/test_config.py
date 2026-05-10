"""Tests for the configuration module."""

from pathlib import Path

import pytest
import yaml

from config import (
    FontConfig,
    KnowledgeConfig,
    ModelConfig,
    OcrConfig,
    OutputWindowConfig,
    OverlayConfig,
    PositionConfig,
    ProviderConfig,
    ScreenshotConfig,
    SizeConfig,
    SystrayConfig,
    load_config,
)


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_valid_config(self, sample_config_path: Path) -> None:
        """Load a full valid config and verify every section is populated."""
        cfg = load_config(sample_config_path)

        assert len(cfg.providers) == 1
        assert cfg.providers[0].name == "deepseek"

        assert len(cfg.models) == 1
        assert cfg.models[0].name == "deepseek-v4-pro"

        assert cfg.system_prompt == "You are a helpful assistant."
        assert cfg.default_model == "deepseek-v4-pro"

        assert isinstance(cfg.ocr, OcrConfig)
        assert cfg.ocr.language == "ch"
        assert cfg.ocr.device == "cpu"

        assert isinstance(cfg.screenshot, ScreenshotConfig)
        assert cfg.screenshot.hotkey_modifiers == ["ctrl", "shift"]
        assert cfg.screenshot.hotkey_button == "left"

        assert isinstance(cfg.output_window, OutputWindowConfig)
        assert isinstance(cfg.output_window.position, PositionConfig)
        assert cfg.output_window.position.x == 100
        assert cfg.output_window.position.y == 100
        assert isinstance(cfg.output_window.size, SizeConfig)
        assert cfg.output_window.size.width == 600
        assert cfg.output_window.size.height == 400
        assert isinstance(cfg.output_window.font, FontConfig)
        assert cfg.output_window.font.family == "Microsoft YaHei"
        assert cfg.output_window.font.size == 14
        assert cfg.output_window.font.color == "#FFFFFF"
        assert cfg.output_window.shadow is True

        assert isinstance(cfg.systray, SystrayConfig)
        assert cfg.systray.show_icon is True

        assert isinstance(cfg.overlay, OverlayConfig)
        assert cfg.overlay.toggle_hotkey == "ctrl+alt+a"

        assert isinstance(cfg.knowledge, KnowledgeConfig)
        assert cfg.knowledge.enabled is True
        assert cfg.knowledge.directory == "knowledge"

    def test_missing_optional_fields_defaults(self, temp_dir: Path) -> None:
        """Config with only provider+models gets sensible defaults for all optional sections."""
        minimal = {
            "provider": [
                {"name": "test-provider", "api_key": "key", "base_url": "https://example.com"}
            ],
            "models": [{"name": "test-model", "provider": "test-provider"}],
        }
        cfg_path = temp_dir / "minimal.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(minimal, f)

        cfg = load_config(cfg_path)

        # Providers and models loaded
        assert len(cfg.providers) == 1
        assert len(cfg.models) == 1

        # Defaults
        assert cfg.system_prompt == "You are a helpful assistant."
        assert cfg.default_model == ""

        assert cfg.ocr.language == "ch"
        assert cfg.ocr.device == "cpu"

        assert cfg.screenshot.hotkey_modifiers == ["ctrl", "shift"]
        assert cfg.screenshot.hotkey_button == "left"

        assert cfg.output_window.position.x == 100
        assert cfg.output_window.position.y == 100
        assert cfg.output_window.size.width == 600
        assert cfg.output_window.size.height == 400
        assert cfg.output_window.font.family == "Microsoft YaHei"
        assert cfg.output_window.font.color == "#FFFFFF"
        assert cfg.output_window.shadow is True

        assert cfg.systray.show_icon is True

        assert cfg.overlay.toggle_hotkey == "ctrl+alt+a"

        assert cfg.knowledge.enabled is True
        assert cfg.knowledge.directory == "knowledge"

    def test_load_file_not_found(self) -> None:
        """Non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent_config_file_xyz.yaml")

    def test_load_invalid_yaml(self, temp_dir: Path) -> None:
        """Garbled YAML content raises yaml.YAMLError."""
        bad_path = temp_dir / "bad.yaml"
        bad_path.write_text("{invalid: yaml: [unclosed", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_config(bad_path)

    def test_no_providers_raises(self, temp_dir: Path) -> None:
        """Config with an empty or missing provider list raises ValueError."""
        no_prov = temp_dir / "no_providers.yaml"
        with open(no_prov, "w", encoding="utf-8") as f:
            yaml.dump({"provider": [], "models": [{"name": "m", "provider": "p"}]}, f)
        with pytest.raises(ValueError, match="At least one provider"):
            load_config(no_prov)

    def test_no_models_raises(self, temp_dir: Path) -> None:
        """Config with an empty model list raises ValueError."""
        no_models = temp_dir / "no_models.yaml"
        with open(no_models, "w", encoding="utf-8") as f:
            yaml.dump(
                {"provider": [{"name": "p", "api_key": "k", "base_url": "u"}], "models": []}, f
            )
        with pytest.raises(ValueError, match="At least one model"):
            load_config(no_models)

    def test_default_model_unknown_raises(self, temp_dir: Path) -> None:
        """default_model referencing a non-existent model raises ValueError."""
        bad = temp_dir / "bad_default.yaml"
        with open(bad, "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "provider": [{"name": "p", "api_key": "k", "base_url": "u"}],
                    "models": [{"name": "real-model", "provider": "p"}],
                    "default_model": "ghost-model",
                },
                f,
            )
        with pytest.raises(ValueError, match="default_model.*ghost-model"):
            load_config(bad)

    def test_extra_unknown_fields_loads(self, temp_dir: Path) -> None:
        """Config with extra unknown top-level keys still loads (forward compat)."""
        config_with_extras = {
            "provider": [{"name": "p", "api_key": "k", "base_url": "https://example.com"}],
            "models": [{"name": "m", "provider": "p"}],
            "future_feature": True,
            "experimental": {"nested": "value"},
        }
        cfg_path = temp_dir / "extra_fields.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(config_with_extras, f)

        cfg = load_config(cfg_path)
        assert cfg.providers[0].name == "p"
        assert cfg.models[0].name == "m"


class TestProviders:
    """Tests for provider lookup."""

    def test_get_provider_found(self, sample_config_path: Path) -> None:
        """get_provider returns the correct ProviderConfig for an existing name."""
        cfg = load_config(sample_config_path)
        provider = cfg.get_provider("deepseek")
        assert provider is not None
        assert isinstance(provider, ProviderConfig)
        assert provider.name == "deepseek"
        assert provider.api_key == "sk-test-key"
        assert provider.base_url == "https://api.deepseek.com"

    def test_get_provider_not_found(self, sample_config_path: Path) -> None:
        """get_provider returns None for a non-existent name."""
        cfg = load_config(sample_config_path)
        assert cfg.get_provider("nonexistent") is None


class TestModels:
    """Tests for model lookup."""

    def test_get_model_found(self, sample_config_path: Path) -> None:
        """get_model returns the correct ModelConfig for an existing name."""
        cfg = load_config(sample_config_path)
        model = cfg.get_model("deepseek-v4-pro")
        assert model is not None
        assert isinstance(model, ModelConfig)
        assert model.name == "deepseek-v4-pro"
        assert model.provider == "deepseek"
        assert model.context == 1048576
        assert model.vision is False

    def test_get_model_not_found(self, sample_config_path: Path) -> None:
        """get_model returns None for a non-existent name."""
        cfg = load_config(sample_config_path)
        assert cfg.get_model("nonexistent") is None


class TestActiveModel:
    """Tests for get_active_model()."""

    def test_get_active_model_explicit(self, sample_config_path: Path) -> None:
        """When default_model is set, returns that model and its provider."""
        cfg = load_config(sample_config_path)
        model, provider = cfg.get_active_model()
        assert model.name == "deepseek-v4-pro"
        assert provider.name == "deepseek"
        assert provider.api_key == "sk-test-key"
        assert provider.base_url == "https://api.deepseek.com"

    def test_get_active_model_implicit(self, temp_dir: Path) -> None:
        """When default_model is not set, returns the first model and its provider."""
        cfg_dict = {
            "provider": [
                {"name": "p1", "api_key": "k", "base_url": "u"},
            ],
            "models": [
                {"name": "alpha", "provider": "p1"},
                {"name": "beta", "provider": "p1"},
            ],
        }
        cfg_path = temp_dir / "no_default.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg_dict, f)

        cfg = load_config(cfg_path)
        model, provider = cfg.get_active_model()
        assert model.name == "alpha"
        assert provider.name == "p1"


class TestRoundTrip:
    """Verify config serialisation round-trip preserves data."""

    def test_config_roundtrip(self, temp_dir: Path) -> None:
        """Dump a full config dict to YAML, load it back, and verify equality."""
        original = {
            "provider": [
                {"name": "p1", "api_key": "k1", "base_url": "https://p1.example.com"},
                {"name": "p2", "api_key": "k2", "base_url": "https://p2.example.com"},
            ],
            "models": [
                {"name": "m1", "provider": "p1", "context": 8192, "vision": True},
                {"name": "m2", "provider": "p2", "context": 4096, "vision": False},
            ],
            "system_prompt": "Custom prompt.",
            "default_model": "m1",
            "ocr": {"language": "en", "device": "gpu"},
            "screenshot": {"hotkey_modifiers": ["alt"], "hotkey_button": "right"},
            "output_window": {
                "position": {"x": 50, "y": 60},
                "size": {"width": 800, "height": 600},
                "font": {"family": "Arial", "size": 12, "color": "#000000"},
                "shadow": False,
            },
            "systray": {"show_icon": False},
            "overlay": {"toggle_hotkey": "ctrl+shift+z"},
            "knowledge": {"enabled": False, "directory": "custom_kb"},
        }

        cfg_path = temp_dir / "roundtrip.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(original, f)

        cfg = load_config(cfg_path)

        # Providers
        assert len(cfg.providers) == 2
        assert cfg.providers[0].name == "p1"
        assert cfg.providers[0].api_key == "k1"
        assert cfg.providers[1].name == "p2"
        assert cfg.providers[1].base_url == "https://p2.example.com"

        # Models
        assert len(cfg.models) == 2
        assert cfg.models[0].name == "m1"
        assert cfg.models[0].context == 8192
        assert cfg.models[0].vision is True
        assert cfg.models[1].name == "m2"
        assert cfg.models[1].context == 4096
        assert cfg.models[1].vision is False

        # Strings
        assert cfg.system_prompt == "Custom prompt."
        assert cfg.default_model == "m1"

        # Sub-configs
        assert cfg.ocr.language == "en"
        assert cfg.ocr.device == "gpu"

        assert cfg.screenshot.hotkey_modifiers == ["alt"]
        assert cfg.screenshot.hotkey_button == "right"

        assert cfg.output_window.position.x == 50
        assert cfg.output_window.position.y == 60
        assert cfg.output_window.size.width == 800
        assert cfg.output_window.size.height == 600
        assert cfg.output_window.font.family == "Arial"
        assert cfg.output_window.font.size == 12
        assert cfg.output_window.font.color == "#000000"
        assert cfg.output_window.shadow is False

        assert cfg.systray.show_icon is False

        assert cfg.overlay.toggle_hotkey == "ctrl+shift+z"

        assert cfg.knowledge.enabled is False
        assert cfg.knowledge.directory == "custom_kb"
