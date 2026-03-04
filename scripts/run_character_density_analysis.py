#!/usr/bin/env python3
"""
Character density analysis on a single PDF.
Reports per-document and per-page: character density, bbox distributions, whitespace ratios.
Run: uv run python scripts/run_character_density_analysis.py /path/to/document.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Project root on path for src imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber


def collect_page_stats(pdf_path: Path) -> list[dict] | None:
    """Collect per-page stats (char count, areas, bbox widths/heights) using pdfplumber."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = []
            for page_num, page in enumerate(pdf.pages, start=1):
                w = page.width
                h = page.height
                page_area = w * h

                words = page.extract_words(x_tolerance=3, y_tolerance=3) or []
                # Line-level aggregation (same as fast_text)
                line_tol = 5
                lines: list[list[dict]] = []
                for word in sorted(words, key=lambda x: (x["top"], x["x0"])):
                    x0, top, x1, bottom = word["x0"], word["top"], word["x1"], word["bottom"]
                    text = word.get("text", "")
                    if not lines or abs(lines[-1][0]["top"] - top) > line_tol:
                        lines.append([{"x0": x0, "top": top, "x1": x1, "bottom": bottom, "text": text}])
                    else:
                        lines[-1].append({"x0": x0, "top": top, "x1": x1, "bottom": bottom, "text": text})

                char_count = 0
                text_area = 0.0
                bbox_widths: list[float] = []
                bbox_heights: list[float] = []
                for line in lines:
                    if not line:
                        continue
                    x0 = min(ww["x0"] for ww in line)
                    x1 = max(ww["x1"] for ww in line)
                    top = min(ww["top"] for ww in line)
                    bottom = max(ww["bottom"] for ww in line)
                    text_area += (x1 - x0) * (bottom - top)
                    line_text = " ".join(ww["text"] for ww in line)
                    char_count += len(line_text)
                    bbox_widths.append(x1 - x0)
                    bbox_heights.append(bottom - top)

                imgs = getattr(page, "images", []) or []
                image_area = sum(
                    (img.get("x1", 0) - img.get("x0", 0)) * (img.get("bottom", 0) - img.get("top", 0))
                    for img in imgs
                )
                chars = page.chars or []
                has_font = any(c.get("fontname") for c in chars) if chars else False

                text_area_ratio = text_area / page_area if page_area else 0.0
                image_area_ratio = image_area / page_area if page_area else 0.0
                whitespace_ratio = max(0.0, 1.0 - text_area_ratio - image_area_ratio)
                char_density = (char_count / (page_area / 10_000.0)) if page_area else 0.0

                def bbox_stats(vals: list[float]) -> dict:
                    if not vals:
                        return {"min": 0, "max": 0, "mean": 0, "count": 0}
                    return {
                        "min": round(min(vals), 2),
                        "max": round(max(vals), 2),
                        "mean": round(sum(vals) / len(vals), 2),
                        "count": len(vals),
                    }

                pages.append({
                    "page": page_num,
                    "width": w,
                    "height": h,
                    "page_area": page_area,
                    "char_count": char_count,
                    "char_density_per_10k_pts2": round(char_density, 4),
                    "text_area_ratio": round(text_area_ratio, 4),
                    "image_area_ratio": round(image_area_ratio, 4),
                    "whitespace_ratio": round(whitespace_ratio, 4),
                    "has_font_metadata": has_font,
                    "bbox_width_pts": bbox_stats(bbox_widths),
                    "bbox_height_pts": bbox_stats(bbox_heights),
                })
            return pages
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}", file=sys.stderr)
        return None


def analyze_pdf(pdf_path: Path, output_json: Path | None = None) -> None:
    pdf_path = pdf_path.resolve()
    if not pdf_path.is_file():
        print(f"Not a file: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    if pdf_path.suffix.lower() != ".pdf":
        print(f"Not a PDF: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    pages = collect_page_stats(pdf_path)
    if pages is None:
        sys.exit(1)

    total_chars = sum(p["char_count"] for p in pages)
    total_area = sum(p["page_area"] for p in pages)
    doc_char_density = (total_chars / (total_area / 10_000.0)) if total_area else 0.0
    total_text_ratio = sum(p["text_area_ratio"] * p["page_area"] for p in pages) / total_area if total_area else 0
    total_img_ratio = sum(p["image_area_ratio"] * p["page_area"] for p in pages) / total_area if total_area else 0
    doc_whitespace = max(0.0, 1.0 - total_text_ratio - total_img_ratio)

    result = {
        "file": pdf_path.name,
        "path": str(pdf_path),
        "num_pages": len(pages),
        "doc_char_count": total_chars,
        "doc_char_density_per_10k_pts2": round(doc_char_density, 4),
        "doc_whitespace_ratio": round(doc_whitespace, 4),
        "doc_text_area_ratio": round(total_text_ratio, 4),
        "doc_image_area_ratio": round(total_img_ratio, 4),
        "per_page": pages,
    }

    print(f"\n{'='*60}")
    print(f"  {pdf_path.name}")
    print(f"  Pages: {len(pages)}  |  Total chars: {total_chars}")
    print(f"  Char density (per 10k pts²): {doc_char_density:.4f}")
    print(f"  Whitespace ratio:           {doc_whitespace:.4f}")
    print(f"  Text area ratio:            {total_text_ratio:.4f}  |  Image area ratio: {total_img_ratio:.4f}")
    print(f"  Bbox distribution (across pages):")
    all_widths = [p["bbox_width_pts"]["mean"] for p in pages if p["bbox_width_pts"]["count"]]
    all_heights = [p["bbox_height_pts"]["mean"] for p in pages if p["bbox_height_pts"]["count"]]
    if all_widths:
        print(f"    Width  (pts): min={min(all_widths):.1f}  max={max(all_widths):.1f}  mean={sum(all_widths)/len(all_widths):.1f}")
    if all_heights:
        print(f"    Height (pts): min={min(all_heights):.1f}  max={max(all_heights):.1f}  mean={sum(all_heights)/len(all_heights):.1f}")
    print(f"  Per-page:")
    for p in pages:
        bw, bh = p["bbox_width_pts"], p["bbox_height_pts"]
        print(f"    p{p['page']}: chars={p['char_count']:5d}  density={p['char_density_per_10k_pts2']:.4f}  "
              f"whitespace={p['whitespace_ratio']:.4f}  bbox_w mean={bw['mean']:.1f}  bbox_h mean={bh['mean']:.1f}")

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"\nFull results written to {output_json}")

    print(f"\n{'='*60}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run character density, bbox distribution, and whitespace analysis on a single PDF."
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
        help="Optional path to write full JSON results",
    )
    args = parser.parse_args()
    analyze_pdf(args.pdf_path, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
