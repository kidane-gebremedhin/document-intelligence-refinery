#!/usr/bin/env python3
"""
Run Docling on a single PDF document.
Converts the PDF with Docling and exports to Markdown and/or JSON.
Run: uv run python scripts/run_docling.py path/to/document.pdf
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Suppress verbose RapidOCR/Docling INFO logs before imports (reduces stall-like noise and improves perceived speed)
for name in ("rapidocr", "RapidOCR", "rapidocr_onnxruntime", "docling", "docling_core", "PIL", "pdfminer"):
    logging.getLogger(name).setLevel(logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

# Project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from docling.document_converter import DocumentConverter
except ImportError:
    DocumentConverter = None  # type: ignore[misc, assignment]


def _make_converter():
    """Build DocumentConverter with optimized OCR (GPU if available, higher batch size)."""
    converter = DocumentConverter()
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption
        pipeline_opts = PdfPipelineOptions()
        # Use GPU if available; increase batch size for faster OCR
        if hasattr(pipeline_opts, "accelerator_options"):
            from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
            pipeline_opts.accelerator_options = AcceleratorOptions(
                device=AcceleratorDevice.AUTO,
                num_threads=4,
            )
        if hasattr(pipeline_opts, "ocr_options") and hasattr(pipeline_opts.ocr_options, "batch_size"):
            pipeline_opts.ocr_options.batch_size = 16
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
        )
    except (ImportError, AttributeError):
        pass
    return converter


def run_docling(pdf_path: Path, output: Path | None = None, max_pages: int | None = None) -> int:
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        print(f"Not a file: {pdf_path}", file=sys.stderr)
        return 1
    if pdf_path.suffix.lower() != ".pdf":
        print(f"Not a PDF: {pdf_path}", file=sys.stderr)
        return 1

    if DocumentConverter is None:
        print("Docling is not installed. Install with: pip install docling", file=sys.stderr)
        return 1

    converter = _make_converter()
    convert_kw: dict = {}
    if max_pages is not None and max_pages > 0:
        convert_kw["max_num_pages"] = max_pages
    result = converter.convert(pdf_path, **convert_kw)
    doc = result.document
    if doc is None:
        print("Docling conversion failed (no document).", file=sys.stderr)
        return 1

    # Summary counts
    data = doc.export_to_dict() if hasattr(doc, "export_to_dict") else {}
    texts = data.get("texts", []) or getattr(doc, "texts", [])
    tables = data.get("tables", []) or getattr(doc, "tables", [])
    pictures = data.get("pictures", []) or getattr(doc, "pictures", [])
    n_texts = len(texts) if isinstance(texts, list) else 0
    n_tables = len(tables) if isinstance(tables, list) else 0
    n_pictures = len(pictures) if isinstance(pictures, list) else 0

    print(f"\n{'='*60}")
    print(f"  Docling: {pdf_path.name}")
    print(f"  Texts: {n_texts}  |  Tables: {n_tables}  |  Pictures: {n_pictures}")
    print(f"{'='*60}\n")

    stem = pdf_path.stem
    out_path = output.resolve() if output else None
    written: list[str] = []

    # Markdown
    if hasattr(doc, "export_to_markdown"):
        md = doc.export_to_markdown()
        if out_path:
            if out_path.is_dir():
                md_path = out_path / f"{stem}.md"
            elif out_path.suffix.lower() == ".md":
                md_path = out_path
            else:
                md_path = out_path.parent / f"{out_path.stem}.md"
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(md, encoding="utf-8")
            written.append(str(md_path))
            print(f"Markdown written to {md_path}")
        else:
            print(md)

    # JSON: when output is a directory (write stem.json) or output is a .json file
    write_json = out_path and (out_path.is_dir() or out_path.suffix.lower() == ".json")
    if write_json:
        if hasattr(doc, "export_to_dict"):
            d = doc.export_to_dict()
        else:
            d = data
        json_path = out_path / f"{stem}.json" if out_path.is_dir() else out_path
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        written.append(str(json_path))
        print(f"JSON written to {json_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Docling on a single PDF: convert and export to Markdown and/or JSON."
    )
    parser.add_argument(
        "pdf_path",
        type=Path,
        help="Path to a single PDF file (pass at runtime)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output path: directory (write <name>.md and <name>.json) or file (.md or .json)",
    )
    parser.add_argument(
        "-n", "--max-pages",
        type=int,
        default=None,
        help="Limit conversion to first N pages (faster for large scanned PDFs)",
    )
    args = parser.parse_args()
    return run_docling(args.pdf_path, args.output, args.max_pages)


if __name__ == "__main__":
    sys.exit(main())
