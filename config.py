"""Configuration loading and validation for read-screen-tool."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ProviderConfig:
    name: str
    api_key: str
    base_url: str


@dataclass
class ModelConfig:
    name: str
    provider: str
    context: int = 1048576
    vision: bool = False


@dataclass
class OcrConfig:
    language: str = "ch"
    device: str = "cpu"


@dataclass
class ScreenshotConfig:
    hotkey_modifiers: list[str] = field(default_factory=lambda: ["ctrl", "shift"])
    hotkey_button: str = "left"


@dataclass
class FontConfig:
    family: str = "Microsoft YaHei"
    size: int = 14
    color: str = "#FFFFFF"


@dataclass
class PositionConfig:
    x: int = 100
    y: int = 100


@dataclass
class SizeConfig:
    width: int = 600
    height: int = 400


@dataclass
class OutputWindowConfig:
    position: PositionConfig = field(default_factory=PositionConfig)
    size: SizeConfig = field(default_factory=SizeConfig)
    font: FontConfig = field(default_factory=FontConfig)
    shadow: bool = True


@dataclass
class SystrayConfig:
    show_icon: bool = True


@dataclass
class OverlayConfig:
    toggle_hotkey: str = "ctrl+alt+a"


@dataclass
class KnowledgeConfig:
    enabled: bool = True
    directory: str = "knowledge"


@dataclass
class AppConfig:
    providers: list[ProviderConfig] = field(default_factory=list)
    models: list[ModelConfig] = field(default_factory=list)
    system_prompt: str = "You are a helpful assistant."
    default_model: str = ""
    ocr: OcrConfig = field(default_factory=OcrConfig)
    screenshot: ScreenshotConfig = field(default_factory=ScreenshotConfig)
    output_window: OutputWindowConfig = field(default_factory=OutputWindowConfig)
    systray: SystrayConfig = field(default_factory=SystrayConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)

    def get_provider(self, name: str) -> ProviderConfig | None:
        """Look up a provider by name. Returns None if not found."""
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def get_model(self, name: str) -> ModelConfig | None:
        """Look up a model by name. Returns None if not found."""
        for m in self.models:
            if m.name == name:
                return m
        return None

    def get_active_model(self) -> tuple[ModelConfig, ProviderConfig]:
        """Return the active model and its provider based on ``default_model``.

        Returns:
            A tuple of ``(model, provider)``.  If ``default_model`` is set,
            the matching model is used; otherwise the first model is returned.

        Raises:
            ValueError: If the provider referenced by the model cannot be found.
        """
        if self.default_model:
            model = self.get_model(self.default_model)
            if model is None:
                raise ValueError(
                    f"default_model '{self.default_model}' not found among configured models"
                )
        else:
            model = self.models[0]

        provider = self.get_provider(model.provider)
        if provider is None:
            raise ValueError(
                f"Provider '{model.provider}' referenced by model '{model.name}' not found"
            )

        return model, provider


# ---------------------------------------------------------------------------
# Internal helpers — mapping between YAML keys and plural dataclass field names
# ---------------------------------------------------------------------------
_YAML_TO_FIELD = {
    "provider": "providers",
}


def _build_providers(data: list[dict]) -> list[ProviderConfig]:
    return [ProviderConfig(**p) for p in data]


def _build_models(data: list[dict]) -> list[ModelConfig]:
    return [ModelConfig(**m) for m in data]


def _build_ocr(data: dict) -> OcrConfig:
    return OcrConfig(**data)


def _build_screenshot(data: dict) -> ScreenshotConfig:
    return ScreenshotConfig(**data)


def _build_output_window(data: dict) -> OutputWindowConfig:
    font = FontConfig(**data.pop("font", {}))
    position = PositionConfig(**data.pop("position", {}))
    size = SizeConfig(**data.pop("size", {}))
    return OutputWindowConfig(font=font, position=position, size=size, **data)


def _build_systray(data: dict) -> SystrayConfig:
    return SystrayConfig(**data)


def _build_overlay(data: dict) -> OverlayConfig:
    return OverlayConfig(**data)


def _build_knowledge(data: dict) -> KnowledgeConfig:
    return KnowledgeConfig(**data)


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------
def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Load and validate config from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        An :class:`AppConfig` instance populated with the file contents.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file contains invalid YAML.
        ValueError: If validation fails (e.g. no providers or models,
            or ``default_model`` references a model that does not exist).
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            raw: dict = yaml.safe_load(f)
    except yaml.YAMLError:
        raise

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a top-level mapping")

    # Remap YAML keys to plural field names
    for yaml_key, field_name in _YAML_TO_FIELD.items():
        if yaml_key in raw:
            raw[field_name] = raw.pop(yaml_key)

    providers_raw = raw.pop("providers", [])
    models_raw = raw.pop("models", [])

    if not providers_raw:
        raise ValueError("At least one provider must be configured")
    if not models_raw:
        raise ValueError("At least one model must be configured")

    providers = _build_providers(providers_raw)
    models = _build_models(models_raw)

    ocr = _build_ocr(raw.pop("ocr", {}))
    screenshot = _build_screenshot(raw.pop("screenshot", {}))
    output_window = _build_output_window(raw.pop("output_window", {}))
    systray = _build_systray(raw.pop("systray", {}))
    overlay = _build_overlay(raw.pop("overlay", {}))
    knowledge = _build_knowledge(raw.pop("knowledge", {}))

    app = AppConfig(
        providers=providers,
        models=models,
        system_prompt=raw.pop("system_prompt", "You are a helpful assistant."),
        default_model=raw.pop("default_model", ""),
        ocr=ocr,
        screenshot=screenshot,
        output_window=output_window,
        systray=systray,
        overlay=overlay,
        knowledge=knowledge,
    )

    # Validate default_model if set
    if app.default_model and app.get_model(app.default_model) is None:
        raise ValueError(f"default_model '{app.default_model}' does not match any configured model")

    return app
