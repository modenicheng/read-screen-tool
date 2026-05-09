"""OCR engine wrapper using PaddleOCR v3.x."""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class OcrEngine:
    """Lazy-initialized PaddleOCR wrapper for text recognition.

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
        self._ocr: object = None

    @property
    def is_loaded(self) -> bool:
        """Whether the OCR model has been loaded."""
        return self._ocr is not None

    def _ensure_loaded(self):
        """Load PaddleOCR model if not already loaded."""
        if self._ocr is None:
            logger.info(
                f"Loading PaddleOCR (lang={self._language}, device={self._device})..."
            )
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(lang=self._language,
                                  use_gpu=(self._device == "gpu"))
            logger.info("PaddleOCR loaded successfully.")

    def recognize(self, image: np.ndarray) -> str:
        """Recognize text from an image array.

        Args:
            image: numpy array (H, W, C) in BGR format (from mss)
                   or (H, W, 3) RGB format

        Returns:
            Extracted text string, empty string if no text detected
        """
        self._ensure_loaded()

        # PaddleOCR v3 predict() accepts numpy array directly
        # Returns list of dicts: [{"rec_text": "...", "rec_score": 0.99, ...}, ...]
        results = self._ocr.predict(image)

        if not results:
            return ""

        # Extract text from results
        texts = []
        for result_set in results:
            if isinstance(result_set, dict):
                # Single result: {"rec_text": "...", ...}
                rec_text = result_set.get("rec_text", "")
                if rec_text:
                    texts.append(rec_text)
            elif isinstance(result_set, list):
                # List of results (per-line): [{"rec_text": "...", ...}, ...]
                for item in result_set:
                    if isinstance(item, dict):
                        text = item.get("rec_text", "")
                        if text:
                            texts.append(text)

        return "\n".join(texts)

    def recognize_from_pil(self, image) -> str:
        """Recognize text from a PIL Image.
        
        Args:
            image: PIL.Image object
            
        Returns:
            Extracted text string
        """
        # Convert PIL to numpy
        arr = np.array(image)
        return self.recognize(arr)
