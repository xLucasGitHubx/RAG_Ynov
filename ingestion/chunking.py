"""Découpage du Markdown en chunks : d'abord par titres, puis par taille (en tokens BGE-M3).

Règles (voir le plan d'action, « Stratégie de chunking ») :
1. une section = le texte sous un titre `#`, `##` ou `###`... : un article reste un bloc logique ;
2. une section trop longue est redécoupée (paragraphe, ligne, phrase, mot) en comptant les tokens
   du tokenizer de BGE-M3, pas les caractères ;
3. un tableau n'est jamais coupé (sauf s'il est énorme : coupé par lignes, en-tête répété) ;
4. les fragments trop courts (titres orphelins, paragraphes isolés) sont fusionnés avec un voisin ;
5. chaque chunk est préfixé par son chemin « Document > Section > Sous-section ».
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from ingestion.parsing import PAGE_MARKER_RE

TokenCounter = Callable[[str], int]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class ChunkingConfig:
    # None = « par section » : pas de redécoupage, une section = un chunk.
    chunk_size: int | None = 512
    chunk_overlap: int = 64
    # Fragments plus courts que ce seuil fusionnés avec un voisin (0 = pas de fusion).
    min_tokens: int = 100
    # Un tableau plus grand que chunk_size × ce facteur est découpé par lignes.
    max_table_factor: float = 2.0

    @property
    def label(self) -> str:
        size = "section" if self.chunk_size is None else str(self.chunk_size)
        return f"size={size}_overlap={self.chunk_overlap}_min={self.min_tokens}"


@dataclass
class Section:
    path: list[str]
    page: int | None
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        """Corps de la section ; les marqueurs de page y restent pour dater chaque bloc."""
        return "\n".join(self.lines).strip()

    @property
    def has_content(self) -> bool:
        return any(line.strip() and not PAGE_MARKER_RE.match(line.strip()) for line in self.lines)


@dataclass
class Chunk:
    text: str  # texte indexé : chemin + contenu
    body: str  # contenu seul
    section: str  # chemin de section, « A > B > C »
    sections: list[str]  # titres de toutes les sections couvertes (après fusion)
    page: int | None
    n_tokens: int
    index: int = 0


# --------------------------------------------------------------------------- tokenizer


@lru_cache(maxsize=2)
def bge_token_counter(model_name: str = "BAAI/bge-m3") -> TokenCounter:
    """Compteur de tokens du tokenizer de BGE-M3 (seul le tokenizer est téléchargé)."""
    from transformers import AutoTokenizer

    # Dans l'image Docker, le tokenizer est embarqué avec BGE-M3 (voir app/rag/embeddings.py).
    local_only = os.environ.get("MODELS_LOCAL_ONLY") == "1"
    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=local_only)

    def count(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False))

    count.tokenizer = tokenizer  # type: ignore[attr-defined]
    return count


# --------------------------------------------------------------------------- sections


def split_sections(markdown: str, max_depth: int = 4) -> list[Section]:
    """Découpe le Markdown en sections selon les titres, en suivant les marqueurs de page."""
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    page: int | None = None
    current = Section(path=[], page=None)

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if m := PAGE_MARKER_RE.match(line.strip()):
            page = int(m.group(1))
            if not current.has_content:
                current.page = page
            current.lines.append(line.strip())
            continue
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) <= max_depth:
            sections.append(current)
            level, title = len(m.group(1)), _clean_title(m.group(2))
            stack = [(lvl, t) for lvl, t in stack if lvl < level] + [(level, title)]
            current = Section(path=[t for _, t in stack], page=page)
            continue
        current.lines.append(line)
    sections.append(current)
    return [s for s in sections if s.has_content]


def _clean_title(title: str) -> str:
    return " ".join(title.replace("**", "").split())


# --------------------------------------------------------------------------- blocs


def _split_blocks(body: str, page: int | None) -> list[tuple[str, str, int | None]]:
    """Sépare le corps d'une section en blocs (type, texte, page), type "text" ou "table" :
    un tableau n'est jamais coupé. Un marqueur de page ferme le bloc en cours."""
    blocks: list[tuple[str, str, int | None]] = []
    buffer: list[str] = []
    kind, block_page = "text", page

    def flush():
        text = "\n".join(buffer).strip()
        if text:
            blocks.append((kind, text, block_page))
        buffer.clear()

    for line in body.splitlines():
        if m := PAGE_MARKER_RE.match(line.strip()):
            flush()
            page = int(m.group(1))
            continue
        line_kind = "table" if line.lstrip().startswith("|") else "text"
        if line_kind != kind:
            flush()
            kind = line_kind
        if not buffer:
            block_page = page
        buffer.append(line)
    flush()
    return blocks


def _split_table(table: str, max_tokens: int, count: TokenCounter) -> list[str]:
    """Découpe un très grand tableau par lignes, en répétant l'en-tête dans chaque morceau."""
    rows = table.splitlines()
    header, rows = rows[:2], rows[2:]
    pieces, current = [], list(header)
    for row in rows:
        if len(current) > 2 and count("\n".join(current + [row])) > max_tokens:
            pieces.append("\n".join(current))
            current = list(header)
        current.append(row)
    pieces.append("\n".join(current))
    return pieces


def _text_splitter(config: ChunkingConfig, count: TokenCounter):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        length_function=count,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        keep_separator="end",
    )


# --------------------------------------------------------------------------- chunks


def chunk_markdown(
    markdown: str,
    doc_title: str,
    config: ChunkingConfig,
    count: TokenCounter,
) -> list[Chunk]:
    sections = split_sections(markdown)
    splitter = _text_splitter(config, count) if config.chunk_size else None

    # 1. Morceaux par section (tableaux intacts, texte redécoupé si trop long).
    pieces: list[Chunk] = []
    for section in sections:
        path = _display_path(section.path, doc_title)
        blocks = _merge_small_text_into_tables(_split_blocks(section.body, section.page), count)
        for kind, block, page in blocks:
            if splitter is None:
                texts = [block]
            elif kind == "table":
                limit = int(config.chunk_size * config.max_table_factor)
                texts = _split_table(block, limit, count) if count(block) > limit else [block]
            else:
                texts = splitter.split_text(block) if count(block) > config.chunk_size else [block]
            for text in texts:
                pieces.append(Chunk(text="", body=text.strip(), section=path,
                                    sections=[path], page=page, n_tokens=count(text)))
        if splitter is None:  # une section = un chunk, même avec des tableaux
            pieces = _collapse_last_section(pieces, path)

    # 2. Fusion des fragments trop courts avec un voisin de la même section (ou section sœur).
    if config.min_tokens:
        limit = (config.chunk_size or 10**9) + config.min_tokens
        pieces = _merge_small(pieces, config.min_tokens, limit, count)

    # 3. Préfixe : chemin de la section, pour que chaque chunk se comprenne seul.
    for i, chunk in enumerate(pieces):
        chunk.index = i
        chunk.text = f"{chunk.section}\n\n{chunk.body}"
    return pieces


def _display_path(path: list[str], doc_title: str) -> str:
    """« Titre du document > Section > Sous-section » (le titre `#` du fichier est remplacé par
    le titre officiel issu des métadonnées)."""
    parts = path[1:] if path and _same_title(path[0], doc_title) else path
    return " > ".join([doc_title, *parts])


def _same_title(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()  # noqa: E731
    return norm(a) in norm(b) or norm(b) in norm(a)


def _merge_small_text_into_tables(blocks, count: TokenCounter):
    """Une phrase d'introduction courte (« Les montants sont les suivants : ») reste avec son
    tableau, plutôt que de devenir un fragment isolé."""
    merged = []
    for kind, block, page in blocks:
        if kind == "table" and merged and merged[-1][0] == "text" and count(merged[-1][1]) < 60:
            merged[-1] = ("table", f"{merged[-1][1]}\n\n{block}", merged[-1][2])
        else:
            merged.append((kind, block, page))
    return merged


def _collapse_last_section(pieces: list[Chunk], path: str) -> list[Chunk]:
    tail = [p for p in pieces if p.section == path]
    head = pieces[: len(pieces) - len(tail)]
    if len(tail) <= 1:
        return pieces
    body = "\n\n".join(p.body for p in tail)
    return head + [Chunk(text="", body=body, section=path, sections=[path], page=tail[0].page,
                         n_tokens=sum(p.n_tokens for p in tail))]


def _parent(path: str) -> str:
    return path.rsplit(" > ", 1)[0]


def _merge_small(pieces: list[Chunk], min_tokens: int, limit: int, count) -> list[Chunk]:
    """Fusionne chaque fragment court avec le chunk précédent s'ils sont dans la même section,
    dans une section et sa sous-section, ou dans deux sections sœurs, sans dépasser `limit`."""
    merged: list[Chunk] = []
    for piece in pieces:
        prev = merged[-1] if merged else None
        if (
            prev
            and (prev.n_tokens < min_tokens or piece.n_tokens < min_tokens)
            and prev.n_tokens + piece.n_tokens <= limit
            and (joined := _join(prev, piece, count)) is not None
        ):
            merged[-1] = joined
            continue
        merged.append(piece)
    return merged


def _join(a: Chunk, b: Chunk, count) -> Chunk | None:
    if a.section == b.section:
        section, body = a.section, f"{a.body}\n\n{b.body}"
    elif a.section == _parent(b.section):  # introduction d'une section + sa sous-section
        section, body = a.section, f"{a.body}\n\n{_with_title(b)}"
    elif _parent(a.section) == _parent(b.section):  # deux sections sœurs
        section, body = _parent(a.section), f"{_with_title(a)}\n\n{_with_title(b)}"
    else:
        return None
    sections = a.sections + [s for s in b.sections if s not in a.sections]
    return Chunk(text="", body=body, section=section, sections=sections,
                 page=a.page if a.page is not None else b.page, n_tokens=count(body))


def _with_title(chunk: Chunk) -> str:
    """Remet le titre de la section dans le corps quand le chunk remonte au chemin parent."""
    title = chunk.section.rsplit(" > ", 1)[-1]
    return f"### {title}\n{chunk.body}"
