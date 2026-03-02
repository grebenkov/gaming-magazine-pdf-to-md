#!/usr/bin/env python3
"""
Gaming Magazine PDF Processor
==============================
Extracts, OCRs (3 passes), corrects, structures, and formats content from
gaming magazine PDFs into organised Markdown files.

Requirements:
    pip install PyMuPDF Pillow ollama openai pytesseract tqdm

System requirements:
    - Tesseract OCR installed (apt install tesseract-ocr / brew install tesseract)
    - Ollama running with models: deepseek-ocr, lightonocr, gemma3n
    - Access to an OpenAI-compatible API endpoint

Usage:
    python magazine_processor.py magazine.pdf
    python magazine_processor.py magazine.pdf --openai-api-key sk-... --openai-model gpt-4o
    python magazine_processor.py magazine.pdf --skip-to 4   # resume from step 4
    python magazine_processor.py magazine.pdf --step5-use-remote --openai-api-key sk-...
"""

import argparse
import base64
import json
import os
import re
import sys
import time
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
import ollama
import pytesseract
from openai import OpenAI
from PIL import Image
from tqdm import tqdm


# ───────────────────────────── Utility helpers ─────────────────────────────

def pil_to_b64(image: Image.Image) -> str:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"_+", "_", name).strip("_.")
    return name[:120] or "untitled"


def ollama_chat(model: str, prompt: str, images: list[str] | None = None,
                retries: int = 3, options: dict | None = None) -> str:
    """Chat with an Ollama model. *images* = list of base64-encoded PNGs."""
    msg: dict = {"role": "user", "content": prompt}
    if images:
        msg["images"] = images

    for attempt in range(1, retries + 1):
        try:
            kwargs = {"model": model, "messages": [msg]}
            if options:
                kwargs["options"] = options
            resp = ollama.chat(**kwargs)
            return resp["message"]["content"]
        except Exception as exc:
            print(f"  [ollama/{model}] attempt {attempt}/{retries}: {exc}",
                  file=sys.stderr)
            if attempt == retries:
                raise
            time.sleep(2 * attempt)
    return ""


def openai_chat(client: OpenAI, model: str, prompt: str,
                max_tokens: int = 16000, temperature: float = 0.1) -> str:
    """Chat with an OpenAI-compatible API."""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def read_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path and path.exists() else ""


# ───────────── Step 1 — extract pages as images + PDF text layer ──────────

def step1_extract(pdf_path: Path, work_dir: Path,
                  dpi: int = 300) -> tuple[list[Path], list[Path | None]]:
    images_dir = work_dir / "page_images"
    text_dir   = work_dir / "pdf_text"
    images_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    image_paths: list[Path] = []
    text_paths:  list[Path | None] = []

    print(f"[Step 1] Extracting {len(doc)} pages @ {dpi} dpi …")
    for idx in tqdm(range(len(doc)), desc="Pages"):
        page = doc.load_page(idx)
        tag  = f"page_{idx:04d}"

        # rasterise
        pix = page.get_pixmap(dpi=dpi)
        img_path = images_dir / f"{tag}.png"
        pix.save(str(img_path))
        image_paths.append(img_path)

        # embedded text layer
        raw = page.get_text("text")
        if raw and raw.strip():
            txt_path = text_dir / f"{tag}_pdf.txt"
            txt_path.write_text(raw, encoding="utf-8")
            text_paths.append(txt_path)
        else:
            text_paths.append(None)

    doc.close()
    return image_paths, text_paths


# ────────────────────── Step 2 — three OCR passes ─────────────────────────

def truncate_if_long(text: str, max_size: int = 20000, truncate_to: int = 8192) -> str:
    """
    Truncate text to truncate_to bytes if it exceeds max_size bytes.
    This prevents model repetition artifacts from bloating output files.
    """
    encoded = text.encode('utf-8')
    if len(encoded) > max_size:
        # Truncate to 8192 bytes, handling UTF-8 character boundaries safely
        return encoded[:truncate_to].decode('utf-8', errors='ignore')
    return text

# Add RefDet and RefImage classes from ref.py
class RefDet:
    """Parse DeepSeek-OCR reference detection tags."""
    def __init__(self, ref, det):
        self.ref = ref
        self.det = det
    
    @staticmethod
    def ref_det(content):
        ref = re.search(r'<\|ref\|>(.*?)<\|/ref\|>', content, re.DOTALL)
        det = re.search(r'<\|det\|>(.*?)<\|/det\|>', content, re.DOTALL)
        if ref and det:
            return ref.group(1).strip(), det.group(1).strip()
        return None, None
    
    @staticmethod
    def dets_boxes(dets):
        boxes = re.findall(r'$$([^\[]*?)$$', dets)
        def dets_coords(box):
            coords = re.findall(r'(\d+)', box)
            return [int(coord) for coord in coords]
        return [dets_coords(box.strip()) for box in boxes]
    
    @staticmethod
    def elements_boxes(content):
        """Extract text and reference elements from deepseek-ocr output."""
        elements = content.split('\n')
        ref_dets = []
        for el in elements:
            ref, dets = RefDet.ref_det(el)
            if not ref or not dets:
                # Plain text line
                ref_dets.append(el)
                continue
            # Referenced element (image, table, etc.)
            rd = RefDet(ref, [det for det in RefDet.dets_boxes(dets)])
            ref_dets.append(rd)
        return ref_dets


def step2_ocr(image_paths: list[Path],
              work_dir: Path) -> dict[str, list[Path]]:
    passes = {"deepseek": [], "lightonocr": [], "tesseract": []}
    for name in passes:
        (work_dir / f"ocr_{name}").mkdir(parents=True, exist_ok=True)

    print(f"[Step 2] Running 3 OCR passes on {len(image_paths)} pages …")
    
    # Ollama options for token limit
    ollama_options = {"num_predict": 8192, "temperature": 0.0}
    
    # ── Pass 1: deepseek-ocr ──
    print("  Pass 1/3: deepseek-ocr ...")
    for img_path in tqdm(image_paths, desc="DeepSeek-OCR"):
        tag = img_path.stem
        output_path = work_dir / "ocr_deepseek" / f"{tag}_deepseek.txt"
        
        # Skip if output already exists
        if output_path.exists():
            passes["deepseek"].append(output_path)
            continue
        
        image = Image.open(img_path)
        b64   = pil_to_b64(image)
        
        try:
            response = ollama.chat(
                model="deepseek-ocr",
                messages=[{
                    "role": "user",
                    "content": "<image>\n<|grounding|>Convert the document (gaming magazine scan) to markdown.",
                    "images": [b64]
                }],
                options=ollama_options
            )
            raw_content = response["message"]["content"]
            
            # Process using RefDet to extract proper markdown/text
            elements = RefDet.elements_boxes(raw_content)
            content_parts = []
            
            for element in elements:
                if isinstance(element, RefDet):
                    # Referenced element (image, table, etc.) - note its presence
                    if element.ref.lower() == "image":
                        content_parts.append("[Image element]")
                    else:
                        content_parts.append(f"[{element.ref} element]")
                else:
                    # Plain text - keep as is
                    content_parts.append(str(element))
            
            txt = "\n".join(content_parts)
            
        except Exception as e:
            print(f"  deepseek-ocr failed [{tag}]: {e}", file=sys.stderr)
            txt = ""

        # Truncate if likely model repetition
        txt = truncate_if_long(txt)
        
        output_path.write_text(txt, encoding="utf-8")
        passes["deepseek"].append(output_path)
    
    # ── Pass 2: lightonocr ──
    print("  Pass 2/3: lightonocr ...")
    for img_path in tqdm(image_paths, desc="lightonocr"):
        tag = img_path.stem
        output_path = work_dir / "ocr_lightonocr" / f"{tag}_lightonocr.txt"
        
        # Skip if output already exists
        if output_path.exists():
            passes["lightonocr"].append(output_path)
            continue
        
        image = Image.open(img_path)
        b64   = pil_to_b64(image)
        
        try:
            response = ollama.chat(
                model="maternion/LightOnOCR-2",
                messages=[{
                    "role": "user",
                    "content": "You are an OCR engine. Extract ALL text from this scanned gaming magazine "
                               "page exactly as it appears. Preserve layout, headings, columns, "
                               "captions. Output only the extracted text. ",
                    "images": [b64]
                }],
                options=ollama_options
            )
            txt = response["message"]["content"]
        except Exception as e:
            print(f"  lightonocr failed [{tag}]: {e}", file=sys.stderr)
            txt = ""

        # Truncate if likely model repetition
        txt = truncate_if_long(txt)
        
        output_path.write_text(txt, encoding="utf-8")
        passes["lightonocr"].append(output_path)
    
    # ── Pass 3: Tesseract (no token limit needed - not an LLM) ──
    print("  Pass 3/3: tesseract ...")
    for img_path in tqdm(image_paths, desc="Tesseract"):
        tag = img_path.stem
        output_path = work_dir / "ocr_tesseract" / f"{tag}_tesseract.txt"
        
        # Skip if output already exists
        if output_path.exists():
            passes["tesseract"].append(output_path)
            continue
        
        image = Image.open(img_path)
        
        try:
            txt = pytesseract.image_to_string(image)
        except Exception as e:
            print(f"  tesseract failed [{tag}]: {e}", file=sys.stderr)
            txt = ""
        
        output_path.write_text(txt, encoding="utf-8")
        passes["tesseract"].append(output_path)

    return passes



# ──────────── Step 3 — merge / correct per page with gemma3n ──────────────

MERGE_SYSTEM = (
    "You are an expert text editor specialising in scanned gaming magazines. "
    "You receive multiple OCR outputs of the SAME page from different engines. "
    "They may contain errors, garbage characters, and layout artefacts."
)

MERGE_INSTRUCTIONS = (
    "Reconcile all versions into ONE correct text.\n"
    "• Fix OCR errors (mis-recognised characters, merged/split words).\n"
    "• Preserve the logical structure: headings, sub-headings, paragraphs, "
    "lists, tables, captions.\n"
    "• Use Markdown formatting.\n"
    "• Do NOT add information that is not present. Do NOT summarise.\n"
    "• Output ONLY the corrected text.\n"
)


def step3_merge(image_paths: list[Path],
                pdf_text_paths: list[Path | None],
                ocr_results: dict[str, list[Path]],
                work_dir: Path) -> list[Path]:
    merged_dir = work_dir / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    corrected: list[Path] = []

    print(f"[Step 3] Merging OCR outputs with gemma3n ({len(image_paths)} pages) …")
    for idx in tqdm(range(len(image_paths)), desc="Merge"):
        tag = image_paths[idx].stem
        out = merged_dir / f"{tag}_corrected.txt"
        
        # Skip if output already exists
        if out.exists():
            corrected.append(out)
            continue
        
        parts: list[str] = []

        pdf_txt = read_if_exists(pdf_text_paths[idx]) if pdf_text_paths[idx] else ""
        if pdf_txt.strip():
            parts.append(f"=== PDF TEXT LAYER ===\n{pdf_txt}")

        for label, key in [("DEEPSEEK-OCR", "deepseek"),
                           ("LIGHTONOCR OCR", "lightonocr"),
                           ("TESSERACT OCR", "tesseract")]:
            t = read_if_exists(ocr_results[key][idx])
            if t.strip():
                parts.append(f"=== {label} ===\n{t}")

        combined = "\n\n".join(parts)
        prompt = f"{MERGE_SYSTEM}\n\n{MERGE_INSTRUCTIONS}\n\n{combined}"

        try:
            result = ollama_chat("gemma3n", prompt, options={"num_predict": 8192})
        except Exception as e:
            print(f"  gemma3n merge failed [{tag}]: {e}", file=sys.stderr)
            result = max(parts, key=len) if parts else ""

        out.write_text(result, encoding="utf-8")
        corrected.append(out)

    return corrected


# ──────── Step 4 — structure extraction via OpenAI-compatible API ──────────

CONTENT_CATEGORIES = [
    "game_previews",
    "game_reviews",
    "hardware_and_software_reviews",
    "game_walkthroughs_and_guides",
    "stories_about_game_development",
    "news_and_industry_reports",
    "feature_articles",
    "ratings_and_sales_charts",
    "bits_and_pieces",
]

STRUCTURE_PROMPT = """\
You are a meticulous editorial assistant for gaming magazines.

Below is the full OCR-corrected text of a gaming magazine, page by page.
Each page is preceded by a header: `### PAGE: <filename>`.

Identify every distinct editorial content item and classify each into
EXACTLY one category:

• game_previews
• game_reviews
• hardware_and_software_reviews
• game_walkthroughs_and_guides
• stories_about_game_development
• news_and_industry_reports
• feature_articles
• ratings_and_sales_charts
• bits_and_pieces  (release dates, rumours, brief mentions — NOT full reviews/previews)

Rules:
- Skip advertisements entirely.
- An article may span NON-CONTIGUOUS pages (interrupted by ads and other pages).
  List ALL page filenames carrying text relevant to the item.
- For each item give: a short descriptive title (game name, product, topic),
  the category, and the list of page filenames.

Return ONLY a JSON array.  Each element:
{
  "title": "<descriptive title>",
  "category": "<category>",
  "pages": ["page_0002_corrected.txt", ...]
}

No markdown fences. No commentary.

--- MAGAZINE TEXT ---
"""


def step4_structure(corrected_paths: list[Path],
                    work_dir: Path,
                    base_url: str,
                    api_key: str,
                    model: str) -> list[dict]:
    print("[Step 4] Extracting magazine structure via remote LLM …")

    sections = [
        f"### PAGE: {p.name}\n\n{p.read_text(encoding='utf-8')}"
        for p in corrected_paths
    ]
    full_text = "\n\n".join(sections)

    concat_path = work_dir / "full_magazine_text.txt"
    concat_path.write_text(full_text, encoding="utf-8")

    client = OpenAI(base_url=base_url, api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": STRUCTURE_PROMPT + full_text}],
        temperature=0.1,
        max_tokens=128000,
    )
    raw = resp.choices[0].message.content.strip()
    (work_dir / "structure_raw.json").write_text(raw, encoding="utf-8")

    # strip markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  WARNING: JSON parse error: {e}", file=sys.stderr)
        print(f"  Raw answer saved to {work_dir / 'structure_raw.json'}",
              file=sys.stderr)
        items = []

    validated: list[dict] = []
    for it in items:
        cat = it.get("category", "")
        if cat not in CONTENT_CATEGORIES:
            print(f"  WARNING: unknown category '{cat}' for "
                  f"'{it.get('title')}' → bits_and_pieces", file=sys.stderr)
            cat = "bits_and_pieces"
        validated.append({
            "title":    it.get("title", "Untitled"),
            "category": cat,
            "pages":    it.get("pages", []),
        })

    (work_dir / "structure.json").write_text(
        json.dumps(validated, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Identified {len(validated)} content items.")
    return validated


# ──── Step 5 — generate output directories & Markdown ─────────

CATEGORY_LABELS = {
    "game_previews":                  "Game Previews",
    "game_reviews":                   "Game Reviews",
    "hardware_and_software_reviews":  "Hardware & Software Reviews",
    "game_walkthroughs_and_guides":   "Walkthroughs & Guides",
    "stories_about_game_development": "Game Development Stories",
    "news_and_industry_reports":      "News & Industry Reports",
    "feature_articles":               "Feature Articles",
    "ratings_and_sales_charts":       "Ratings & Sales Charts",
    "bits_and_pieces":                "Bits & Pieces",
}

EXTRACT_PROMPT_TEMPLATE = """\
You are a specialist editor working on a gaming magazine archive.

Below is OCR-corrected text from magazine pages that belong to a single
content item.

Content item title: "{title}"
Category: {category_label}

Tasks:
1. Extract ONLY text relevant to this content item ("{title}").
2. Ignore advertisements and unrelated articles on the same pages.
3. Format as clean Markdown — preserve the original text, do NOT summarise.
4. Perform final text cleanup. Correct order of paragraphs, typos, OCR defects.
5. Use appropriate headings, lists, bold/italic as in the original.
6. Start the file with a YAML front-matter block:
   ---
   title: "{title}"
   category: {category}
   source_pages:
   {pages_yaml}
   ---
7. Output ONLY the final Markdown document.

--- SOURCE TEXT ---
{source}
"""


def step5_output(items: list[dict],
                 corrected_paths: list[Path],
                 work_dir: Path,
                 output_dir: Path,
                 magazine_name: str,
                 use_remote: bool = False,
                 remote_client: OpenAI | None = None,
                 remote_model: str | None = None):
    """
    Generate structured Markdown output from identified content items.
    
    Args:
        items: List of content items from step 4
        corrected_paths: Paths to corrected page texts
        work_dir: Working directory
        output_dir: Output directory
        magazine_name: Magazine name for output folder
        use_remote: If True, use remote API instead of local ollama
        remote_client: OpenAI client instance (required if use_remote=True)
        remote_model: Model name for remote API (required if use_remote=True)
    """
    mag_dir = output_dir / sanitize_filename(magazine_name)
    model_desc = f"remote {remote_model}" if use_remote else "local gemma3n"
    print(f"[Step 5] Writing structured output → {mag_dir} (using {model_desc})")

    # page text lookup
    page_map: dict[str, str] = {
        p.name: p.read_text(encoding="utf-8") for p in corrected_paths
    }

    # create category sub-dirs
    for cat in CONTENT_CATEGORIES:
        (mag_dir / cat).mkdir(parents=True, exist_ok=True)

    for item in tqdm(items, desc="Formatting articles"):
        title = item["title"]
        cat   = item["category"]
        pages = item["pages"]

        source_parts = []
        for pname in pages:
            txt = page_map.get(pname, "")
            if txt:
                source_parts.append(f"### PAGE: {pname}\n\n{txt}")
            else:
                print(f"  WARNING: page '{pname}' not found for '{title}'",
                      file=sys.stderr)
        if not source_parts:
            continue

        pages_yaml = "\n".join(f"     - {p}" for p in pages)
        prompt = EXTRACT_PROMPT_TEMPLATE.format(
            title=title,
            category_label=CATEGORY_LABELS.get(cat, cat),
            category=cat,
            pages_yaml=pages_yaml,
            source="\n\n".join(source_parts),
        )

        try:
            if use_remote:
                # Use remote OpenAI-compatible API
                if not remote_client or not remote_model:
                    raise ValueError("Remote client and model required when use_remote=True")
                md = openai_chat(remote_client, remote_model, prompt, 
                               max_tokens=16000, temperature=0.1)
            else:
                # Use local ollama
                md = ollama_chat("gemma3n", prompt, options={"num_predict": 8192})
        except Exception as e:
            print(f"  Formatting failed for '{title}': {e}", file=sys.stderr)
            md = (
                f"---\ntitle: \"{title}\"\ncategory: {cat}\n"
                f"source_pages:\n{pages_yaml}\n---\n\n"
                f"# {title}\n\n" + "\n\n".join(source_parts)
            )

        fname = sanitize_filename(title) + ".md"
        (mag_dir / cat / fname).write_text(md, encoding="utf-8")

    print(f"  Done → {mag_dir}")


# ─────────────── Resume helpers — reconstruct paths for --skip-to ─────────

def _reconstruct_image_paths(work_dir: Path) -> list[Path]:
    return sorted((work_dir / "page_images").glob("page_*.png"))


def _reconstruct_pdf_text(image_paths: list[Path],
                          work_dir: Path) -> list[Path | None]:
    text_dir = work_dir / "pdf_text"
    out: list[Path | None] = []
    for ip in image_paths:
        tp = text_dir / f"{ip.stem}_pdf.txt"
        out.append(tp if tp.exists() else None)
    return out


def _reconstruct_ocr(image_paths: list[Path],
                     work_dir: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {"deepseek": [], "lightonocr": [], "tesseract": []}
    for ip in image_paths:
        tag = ip.stem
        for key, suffix in [("deepseek", "_deepseek.txt"),
                            ("lightonocr",   "_lightonocr.txt"),
                            ("tesseract","_tesseract.txt")]:
            result[key].append(work_dir / f"ocr_{key}" / f"{tag}{suffix}")
    return result


def _reconstruct_corrected(work_dir: Path) -> list[Path]:
    return sorted((work_dir / "merged").glob("page_*_corrected.txt"))


# ──────────────────────────────── main ────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Process a gaming magazine PDF: OCR → correction → "
                    "structured extraction → Markdown output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pdf", type=Path,
                        help="Path to the input PDF file")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("output"),
                        help="Base output directory (default: ./output)")
    parser.add_argument("-w", "--work-dir", type=Path, default=None,
                        help="Working dir for intermediate files "
                             "(default: ./work/<pdf_stem>)")
    parser.add_argument("--dpi", type=int, default=300,
                        help="DPI for PDF page rasterisation (default: 300)")
    parser.add_argument("--magazine-name", type=str, default=None,
                        help="Name for the output directory (default: PDF stem)")

    # OpenAI-compatible endpoint for Step 4
    grp4 = parser.add_argument_group("OpenAI-compatible API (Step 4)")
    grp4.add_argument("--openai-base-url", type=str,
                     default=os.environ.get("OPENAI_BASE_URL",
                                            "https://api.openai.com/v1"),
                     help="Base URL (env: OPENAI_BASE_URL)")
    grp4.add_argument("--openai-api-key", type=str,
                     default=os.environ.get("OPENAI_API_KEY", ""),
                     help="API key (env: OPENAI_API_KEY)")
    grp4.add_argument("--openai-model", type=str,
                     default=os.environ.get("OPENAI_MODEL", "gpt-4o"),
                     help="Model name (env: OPENAI_MODEL, default: gpt-4o)")

    # Step 5 model selection
    grp5 = parser.add_argument_group("Step 5 model selection")
    grp5.add_argument("--step5-use-remote", action="store_true",
                     help="Use remote API for Step 5 instead of local ollama gemma3n")
    grp5.add_argument("--step5-base-url", type=str, default=None,
                     help="Base URL for Step 5 (defaults to --openai-base-url)")
    grp5.add_argument("--step5-api-key", type=str, default=None,
                     help="API key for Step 5 (defaults to --openai-api-key)")
    grp5.add_argument("--step5-model", type=str, default=None,
                     help="Model name for Step 5 (defaults to --openai-model)")

    # Resume
    parser.add_argument("--skip-to", type=int, choices=[1, 2, 3, 4, 5],
                        default=1,
                        help="Resume from this step (prior outputs must exist)")

    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.exists():
        parser.error(f"PDF not found: {pdf_path}")

    magazine_name = args.magazine_name or pdf_path.stem
    work_dir = (args.work_dir or Path("work") / pdf_path.stem).resolve()
    output_dir = args.output_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    skip = args.skip_to

    # ── Step 1 ──
    if skip <= 1:
        image_paths, pdf_text_paths = step1_extract(pdf_path, work_dir,
                                                    dpi=args.dpi)
    else:
        image_paths = _reconstruct_image_paths(work_dir)
        pdf_text_paths = _reconstruct_pdf_text(image_paths, work_dir)
    if not image_paths:
        sys.exit("ERROR: no pages extracted / found.")

    # ── Step 2 ──
    if skip <= 2:
        ocr_results = step2_ocr(image_paths, work_dir)
    else:
        ocr_results = _reconstruct_ocr(image_paths, work_dir)

    # ── Step 3 ──
    if skip <= 3:
        corrected_paths = step3_merge(image_paths, pdf_text_paths,
                                      ocr_results, work_dir)
    else:
        corrected_paths = _reconstruct_corrected(work_dir)
    if not corrected_paths:
        sys.exit("ERROR: no corrected texts found.")

    # ── Step 4 ──
    if skip <= 4:
        if not args.openai_api_key:
            sys.exit("ERROR: --openai-api-key (or OPENAI_API_KEY env var) "
                     "is required for Step 4.")
        items = step4_structure(corrected_paths, work_dir,
                                base_url=args.openai_base_url,
                                api_key=args.openai_api_key,
                                model=args.openai_model)
    else:
        sp = work_dir / "structure.json"
        if not sp.exists():
            sys.exit("ERROR: structure.json not found in work dir.")
        items = json.loads(sp.read_text(encoding="utf-8"))

    # ── Step 5 ──
    step5_client = None
    step5_model = None
    
    if args.step5_use_remote:
        # Use remote API for step 5
        step5_base_url = args.step5_base_url or args.openai_base_url
        step5_api_key = args.step5_api_key or args.openai_api_key
        step5_model = args.step5_model or args.openai_model
        
        if not step5_api_key:
            sys.exit("ERROR: API key required for Step 5 remote model. "
                    "Use --step5-api-key or --openai-api-key.")
        
        step5_client = OpenAI(base_url=step5_base_url, api_key=step5_api_key)
    
    step5_output(items, corrected_paths, work_dir, output_dir, magazine_name,
                use_remote=args.step5_use_remote,
                remote_client=step5_client,
                remote_model=step5_model)

    print("\n✓ All steps complete.")


if __name__ == "__main__":
    main()
