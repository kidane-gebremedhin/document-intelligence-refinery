# Extraction strategies: BaseExtractor interface and result type.

from .base import BaseExtractor, ExtractionResult
from .fast_text_extractor import FastTextExtractor

__all__ = ["BaseExtractor", "ExtractionResult", "FastTextExtractor"]
