"""OCR engine wrapper using EasyOCR."""

import gc
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_LANGUAGE_ALIASES = {
    "ch": "ch_sim",
    "cn": "ch_sim",
    "zh": "ch_sim",
    "zh-cn": "ch_sim",
}


class OcrEngine:
    """Lazy-initialized EasyOCR wrapper for text recognition.

    Accepts numpy arrays (from mss screenshots) and returns extracted text.
    """

    def __init__(self, language: str = "ch", device: str = "cpu"):
        """Initialize OCR engine configuration. Model loads lazily on first use.

        Args:
            language: OCR language code (default: "ch" for Chinese)
            device: Computation device ("cpu" or "gpu")
        """
        self._language = language
        self._device = device
        self._ocr: Any = None

    @property
    def is_loaded(self) -> bool:
        """Whether the OCR model has been loaded."""
        return self._ocr is not None

    def _release_reader(self) -> None:
        """Drop any cached EasyOCR reader before the next capture."""
        if self._ocr is not None:
            self._ocr = None
            gc.collect()

    def _ensure_loaded(self) -> None:
        """Load EasyOCR model if not already loaded."""
        if self._ocr is None:
            languages = self._easyocr_languages()
            gpu = self._easyocr_gpu()
            logger.info("Loading EasyOCR (langs=%s, gpu=%s)...", languages, gpu)
            import easyocr

            self._ocr = easyocr.Reader(languages, gpu=gpu)
            logger.info("EasyOCR loaded successfully.")

    def _easyocr_languages(self) -> list[str]:
        """Convert configured language codes to EasyOCR's language list."""
        raw_languages = [
            part.strip().lower()
            for part in self._language.replace("+", ",").split(",")
            if part.strip()
        ]
        if not raw_languages:
            raw_languages = ["ch"]

        languages: list[str] = []
        for raw_language in raw_languages:
            language = _LANGUAGE_ALIASES.get(raw_language, raw_language)
            if language not in languages:
                languages.append(language)

        if "ch_sim" in languages and "en" not in languages:
            languages.append("en")

        return languages

    def _easyocr_gpu(self) -> bool | str:
        """Convert configured device to EasyOCR's gpu parameter."""
        device = self._device.strip()
        normalized = device.lower()
        if normalized in {"cpu", "false", "none", "off"}:
            return False
        if normalized in {"gpu", "cuda", "true", "on"}:
            return True
        return device

    def recognize(self, image: np.ndarray) -> str:
        """Recognize text from an image array.

        Args:
            image: numpy array (H, W, C) in BGR format (from mss)
                   or (H, W, 3) RGB format

        Returns:
            Extracted text string, empty string if no text detected
        """
        self._ensure_loaded()

        results = self._ocr.readtext(image, detail=0)

        if not results:
            return ""

        texts: list[str] = []
        for result in results:
            text = self._extract_text(result)
            if text.strip():
                texts.append(text)

        return "\n".join(texts)

    @staticmethod
    def _extract_text(result: Any) -> str:
        """Extract text from EasyOCR result formats."""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            text = result.get("text") or result.get("rec_text") or ""
            return text if isinstance(text, str) else ""
        if isinstance(result, (list, tuple)) and len(result) >= 2 and isinstance(result[1], str):
            return result[1]
        return ""

    def recognize_from_pil(self, image) -> str:
        """Recognize text from a PIL Image.

        Args:
            image: PIL.Image object

        Returns:
            Extracted text string
        """
        arr = np.array(image)
        return self.recognize(arr)
