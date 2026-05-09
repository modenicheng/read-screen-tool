"""Tests for OCR engine wrapper."""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def ocr_engine():
    from ocr import OcrEngine
    return OcrEngine(language="ch", device="cpu")


class TestOcrInitialization:
    def test_engine_not_loaded_initially(self, ocr_engine):
        """OCR model should NOT be loaded at init time (lazy loading)."""
        assert not ocr_engine.is_loaded
        assert ocr_engine._language == "ch"
        assert ocr_engine._device == "cpu"
    
    def test_engine_loaded_after_recognize(self, ocr_engine):
        """recognize() should trigger model loading."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = []
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        assert ocr_engine.is_loaded
        assert result == ""
    
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
    def test_recognize_single_result(self, ocr_engine):
        """Single dict result should extract rec_text."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [{"rec_text": "Hello World", "rec_score": 0.99}]
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        assert result == "Hello World"
    
    def test_recognize_multiple_results(self, ocr_engine):
        """Multiple dict results should be joined with newlines."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [
            {"rec_text": "Line 1", "rec_score": 0.99},
            {"rec_text": "Line 2", "rec_score": 0.98},
        ]
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        assert result == "Line 1\nLine 2"
    
    def test_recognize_empty_results(self, ocr_engine):
        """Empty results list should return empty string."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = []
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        assert result == ""
    
    def test_recognize_none_results(self, ocr_engine):
        """None results should return empty string."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = None
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        assert result == ""
    
    def test_recognize_skips_empty_text(self, ocr_engine):
        """Results with empty rec_text should be skipped."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [
            {"rec_text": "", "rec_score": 0.5},
            {"rec_text": "Valid Text", "rec_score": 0.95},
            {"rec_text": "", "rec_score": 0.3},
        ]
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        assert result == "Valid Text"
    
    def test_recognize_list_of_lists(self, ocr_engine):
        """Nested list format (per-line results) should be handled."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [
            [{"rec_text": "Line A", "rec_score": 0.99}],
            [{"rec_text": "Line B", "rec_score": 0.97}],
        ]
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        assert result == "Line A\nLine B"


class TestPILConversion:
    def test_recognize_from_pil(self, ocr_engine):
        """PIL Image should be converted to numpy and recognized."""
        from PIL import Image
        img = Image.new("RGB", (100, 100), color="white")
        
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [{"rec_text": "PIL Text", "rec_score": 0.95}]
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr):
            result = ocr_engine.recognize_from_pil(img)
        
        assert result == "PIL Text"
    
    def test_model_loaded_only_once(self, ocr_engine):
        """Multiple recognize() calls should load model only once."""
        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = []
        
        with patch("paddleocr.PaddleOCR", return_value=mock_ocr) as mock_paddle:
            ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
            ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
            ocr_engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8))
        
        # PaddleOCR should be instantiated only once
        assert mock_paddle.call_count == 1
