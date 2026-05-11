"""Tests for OCR engine wrapper."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest


@pytest.fixture
def ocr_engine():
    from ocr import OcrEngine

    return OcrEngine(language="ch", device="cpu")


@pytest.fixture
def fake_ocr_modules(monkeypatch):
    reader = MagicMock()
    reader.readtext.return_value = []
    reader_cls = MagicMock(return_value=reader)

    monkeypatch.setitem(sys.modules, "easyocr", SimpleNamespace(Reader=reader_cls))

    return reader_cls, reader


class TestOcrInitialization:
    def test_opencv_runtime_is_available_for_easyocr(self):
        """EasyOCR needs a real OpenCV module, not an empty cv2 namespace."""
        import cv2

        assert hasattr(cv2, "cvtColor")

    def test_engine_not_loaded_initially(self, ocr_engine):
        """OCR model should NOT be loaded at init time (lazy loading)."""
        assert not ocr_engine.is_loaded
        assert ocr_engine._language == "ch"
        assert ocr_engine._device == "cpu"

    def test_engine_loaded_after_recognize(self, ocr_engine, fake_ocr_modules):
        """recognize() should trigger model loading."""
        reader_cls, reader = fake_ocr_modules

        image = np.zeros((100, 100, 3), dtype=np.uint8)
        result = ocr_engine.recognize(image)

        assert ocr_engine.is_loaded
        assert result == ""
        reader_cls.assert_called_once_with(["ch_sim", "en"], gpu=False)
        reader.readtext.assert_called_once_with(image, detail=0)

    def test_default_language_and_device(self):
        """Default values should be 'ch' and 'cpu'."""
        from ocr import OcrEngine

        engine = OcrEngine()
        assert engine._language == "ch"
        assert engine._device == "cpu"

    def test_gpu_device_config(self):
        """GPU device should be configurable."""
        from ocr import OcrEngine

        engine = OcrEngine(device="gpu")
        assert engine._device == "gpu"


class TestTextRecognition:
    def test_recognize_single_result(self, ocr_engine, fake_ocr_modules):
        """Single EasyOCR text result should be returned."""
        _, reader = fake_ocr_modules
        reader.readtext.return_value = ["Hello World"]

        result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == "Hello World"

    def test_recognize_multiple_results(self, ocr_engine, fake_ocr_modules):
        """Multiple EasyOCR text results should be joined with newlines."""
        _, reader = fake_ocr_modules
        reader.readtext.return_value = ["Line 1", "Line 2"]

        result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == "Line 1\nLine 2"

    def test_recognize_empty_results(self, ocr_engine, fake_ocr_modules):
        """Empty results list should return empty string."""
        _, reader = fake_ocr_modules
        reader.readtext.return_value = []

        result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == ""

    def test_recognize_none_results(self, ocr_engine, fake_ocr_modules):
        """None results should return empty string."""
        _, reader = fake_ocr_modules
        reader.readtext.return_value = None

        result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == ""

    def test_recognize_skips_empty_text(self, ocr_engine, fake_ocr_modules):
        """Results with empty rec_text should be skipped."""
        _, reader = fake_ocr_modules
        reader.readtext.return_value = ["", "Valid Text", "   "]

        result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == "Valid Text"

    def test_recognize_default_easyocr_tuple_results(self, ocr_engine, fake_ocr_modules):
        """Default EasyOCR tuple results should also be handled defensively."""
        _, reader = fake_ocr_modules
        reader.readtext.return_value = [
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "Line A", 0.99),
            ([[0, 20], [10, 20], [10, 30], [0, 30]], "Line B", 0.97),
        ]

        result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == "Line A\nLine B"


class TestPILConversion:
    def test_recognize_from_pil(self, ocr_engine, fake_ocr_modules):
        """PIL Image should be converted to numpy and recognized."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="white")

        _, reader = fake_ocr_modules
        reader.readtext.return_value = ["PIL Text"]

        result = ocr_engine.recognize_from_pil(img)

        assert result == "PIL Text"

    def test_reader_is_reused_across_captures(self, ocr_engine, fake_ocr_modules):
        """Reader is created once and reused across captures to avoid re-init crashes."""
        reader_cls, _ = fake_ocr_modules

        ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        assert reader_cls.call_count == 1

    @pytest.mark.parametrize(
        ("language", "expected_languages"),
        [
            ("ch", ["ch_sim", "en"]),
            ("ch_sim", ["ch_sim", "en"]),
            ("en", ["en"]),
            ("ja,en", ["ja", "en"]),
        ],
    )
    def test_language_config_maps_to_easyocr_lang_list(
        self, fake_ocr_modules, language, expected_languages
    ):
        """Configured language should be converted to EasyOCR language list."""
        from ocr import OcrEngine

        reader_cls, _ = fake_ocr_modules
        engine = OcrEngine(language=language, device="cpu")

        engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        reader_cls.assert_called_once_with(expected_languages, gpu=False)

    @pytest.mark.parametrize(
        ("device", "expected_gpu"),
        [
            ("cpu", False),
            ("gpu", True),
            ("cuda:1", "cuda:1"),
        ],
    )
    def test_device_config_maps_to_easyocr_gpu(self, fake_ocr_modules, device, expected_gpu):
        """Configured device should be converted to EasyOCR gpu setting."""
        from ocr import OcrEngine

        reader_cls, _ = fake_ocr_modules
        engine = OcrEngine(language="en", device=device)

        engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))

        reader_cls.assert_called_once_with(["en"], gpu=expected_gpu)
