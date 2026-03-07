#!/usr/bin/env python3
"""
Run Docling on a single PDF document optimized for Dual-Core CPUs.
Converts the PDF with Docling and exports to Markdown and/or JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import shutil
from pathlib import Path

# Force CPU-only mode at the OS level to prevent CUDA sm_50 errors
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

# Suppress verbose logs to see actual progress
for name in ("rapidocr", "RapidOCR", "docling", "huggingface_hub"):
    logging.getLogger(name).setLevel(logging.WARNING)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions, AcceleratorDevice
except ImportError:
    DocumentConverter = None


def _make_converter():
    """Build DocumentConverter optimized for i7-7500U (2 Cores)."""
    if DocumentConverter is None:
        return None

    from docling.datamodel.pipeline_options import RapidOcrOptions, TesseractOcrOptions
    
    pipeline_opts = PdfPipelineOptions()
    
    # Check for Tesseract first as it's much lighter for a dual-core i7
    if shutil.which("tesseract"):
        pipeline_opts.ocr_options = TesseractOcrOptions()
        print("INFO: Using Tesseract engine (Lightweight C++).")
    else:
        # RapidOcrOptions handles its own batching; 
        # removing manual batch_size to fix Pydantic ValueError
        pipeline_opts.ocr_options = RapidOcrOptions()
        print("INFO: Using RapidOCR engine (Torch CPU).")

    pipeline_opts.do_ocr = True
    
    # This is the most important part for your i7-7500U stability
    pipeline_opts.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU,
        num_threads=2, 
    )

    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
    )

def run_docling(pdf_path: Path, output: Path | None = None, max_pages: int | None = None) -> int:
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        print(f"Error: {pdf_path} not found.")
        return 1

    converter = _make_converter()
    if converter is None:
        print("Error: Docling not installed.")
        return 1

    print(f"Processing: {pdf_path.name} (This may take a few minutes for scanned images)...")
    
    convert_kw = {}
    if max_pages:
        convert_kw["max_num_pages"] = max_pages

    try:
        # result = next(converter.convert_all([pdf_path], **convert_kw))
        result = converter.convert(pdf_path, **convert_kw)
        doc = result.document
    except Exception as e:
        print(f"Conversion failed: {e}")
        print("TIP: If you see a timeout, run 'python -c \"from huggingface_hub import snapshot_download; snapshot_download(repo_id=\"ds4sd/docling-models\")\"' to cache models first.")
        return 1

    # Markdown Export
    md = doc.export_to_markdown()
    if output:
        output.mkdir(parents=True, exist_ok=True)
        md_file = output / f"{pdf_path.stem}.md"
        md_file.write_text(md, encoding="utf-8")
        print(f"Successfully saved Markdown to: {md_file}")
    else:
        print(md)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Docling Optimized for Dual-Core CPUs")
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("-n", "--max-pages", type=int, default=None)
    args = parser.parse_args()
    return run_docling(args.pdf_path, args.output, args.max_pages)


if __name__ == "__main__":
    sys.exit(main())