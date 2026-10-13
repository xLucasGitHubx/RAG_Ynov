"""Conversion des documents (PDF, DOCX, PPTX, HTML, Markdown, TXT) en Markdown structuré.

Docling convertit les formats binaires en gardant titres, listes et tableaux. Pour les formats
paginés, on exporte page par page et on insère un marqueur `<!-- page: N -->` avant chaque page :
le découpage s'en sert ensuite pour attribuer un numéro de page à chaque chunk.
"""

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("rag.ingestion.parsing")

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
DOCLING_SUFFIXES = {".pdf", ".docx", ".pptx", ".html", ".htm", ".xlsx"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | DOCLING_SUFFIXES

PAGE_MARKER = "<!-- page: {} -->"
PAGE_MARKER_RE = re.compile(r"^<!-- page: (\d+) -->$")
# En dessous de ce nombre de caractères, une page est probablement mal lue (scan sans OCR...).
MIN_CHARS_PER_PAGE = 200


@dataclass
class ParsedDocument:
    filename: str
    markdown: str
    pages: int | None = None
    chars_per_page: dict[int, int] = field(default_factory=dict)

    @property
    def suspicious_pages(self) -> list[int]:
        return [p for p, n in self.chars_per_page.items() if n < MIN_CHARS_PER_PAGE]


@lru_cache(maxsize=1)
def _converter():
    from docling.document_converter import DocumentConverter

    return DocumentConverter()


def parse_file(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return ParsedDocument(path.name, path.read_text(encoding="utf-8"))
    if suffix not in DOCLING_SUFFIXES:
        raise ValueError(f"Format non pris en charge : {path.name}")

    document = _converter().convert(path).document
    if not document.pages:  # DOCX, HTML : pas de pagination
        return ParsedDocument(path.name, document.export_to_markdown())

    parts, chars = [], {}
    for page_no in sorted(document.pages):
        page_md = document.export_to_markdown(page_no=page_no).strip()
        chars[page_no] = len(page_md)
        parts.append(f"{PAGE_MARKER.format(page_no)}\n\n{page_md}")
    markdown = relevel_headings("\n\n".join(parts))
    parsed = ParsedDocument(path.name, markdown, pages=len(document.pages), chars_per_page=chars)
    if parsed.suspicious_pages:
        logger.warning("%s : peu de texte extrait sur les pages %s", path.name,
                       parsed.suspicious_pages)
    return parsed


_NUMBERED = [
    (re.compile(r"^\d+\.\d+\.\d+\.?\s"), 4),  # 1.2.3 Sous-sous-section
    (re.compile(r"^\d+\.\d+\.?\s"), 3),  # 1.2 Sous-section
    (re.compile(r"^(\d+\.|Article\s+\d+|Chapitre\s+\d+|Titre\s+[IVX\d]+)", re.I), 2),
]


def relevel_headings(markdown: str) -> str:
    """Docling met tous les titres d'un PDF au même niveau (`##`). On recrée la hiérarchie à partir
    de la numérotation : le premier titre devient le titre du document (`#`), « 1. » ou
    « Article 3 » un niveau 2, « 1.2 » un niveau 3. Les titres non numérotés situés sous une
    section numérotée prennent le niveau inférieur à celle-ci."""
    lines = markdown.splitlines()
    heading_idx = [i for i, line in enumerate(lines) if re.match(r"^#{1,6}\s", line)]
    levels = {len(re.match(r"^(#+)", lines[i]).group(1)) for i in heading_idx}
    if len(levels) > 1:  # la hiérarchie existe déjà : on n'y touche pas
        return markdown

    last_numbered = 1
    for n, i in enumerate(heading_idx):
        title = re.sub(r"^#+\s*", "", lines[i]).strip()
        if n == 0:
            level = 1
        else:
            level = next((lvl for pattern, lvl in _NUMBERED if pattern.match(title)), None)
            if level is None:
                level = 2 if last_numbered <= 2 else last_numbered
            else:
                last_numbered = level
        lines[i] = f"{'#' * level} {title}"
    return "\n".join(lines)
