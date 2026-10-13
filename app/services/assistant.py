"""Logique métier de l'assistant : recherche du contexte, puis génération par le LLM.

Si la recherche ne trouve aucun extrait assez pertinent, l'assistant refuse directement, sans
appeler le LLM : la réponse est plus fiable et ne consomme aucune minute GPU.
"""

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.llm import LLMClient
from app.prompts import (
    REFUSAL,
    REFUSAL_HINT,
    SYSTEM_PROMPT,
    build_user_prompt,
    format_context_block,
    is_refusal,
)
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas import AskResponse, Source

EXCERPT_CHARS = 300


@dataclass
class AnswerResult:
    response: AskResponse
    chunks: list[RetrievedChunk] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    refused: bool = False
    llm_called: bool = True


@dataclass
class PreparedPrompt:
    chunks: list[RetrievedChunk]
    user_prompt: str
    timings_ms: dict[str, float]


class Assistant:
    def __init__(self, llm: LLMClient, retriever: Retriever | None = None) -> None:
        self.llm = llm
        self.retriever = retriever

    # ----------------------------------------------------------------- étapes

    def prepare(self, question: str) -> PreparedPrompt:
        chunks, timings = [], {}
        if self.retriever is not None:
            result = self.retriever.search(question)
            chunks, timings = result.chunks, dict(result.timings_ms)
        blocks = [format_context_block(i, c.text, c.metadata) for i, c in enumerate(chunks, 1)]
        return PreparedPrompt(chunks, build_user_prompt(question, blocks), timings)

    def should_refuse_without_llm(self, prepared: PreparedPrompt) -> bool:
        """Recherche active mais aucun extrait pertinent : inutile d'appeler le LLM."""
        return self.retriever is not None and not prepared.chunks

    # ----------------------------------------------------------------- réponse complète

    def answer(self, question: str) -> AnswerResult:
        prepared = self.prepare(question)
        if self.should_refuse_without_llm(prepared):
            return AnswerResult(AskResponse(answer=f"{REFUSAL} {REFUSAL_HINT}", sources=[]),
                                timings_ms=prepared.timings_ms, refused=True, llm_called=False)

        start = time.perf_counter()
        generation = self.llm.generate(SYSTEM_PROMPT, prepared.user_prompt)
        timings = {**prepared.timings_ms, "llm": (time.perf_counter() - start) * 1000}
        refused = is_refusal(generation.text)
        sources = [] if refused else build_sources(prepared.chunks, generation.text)
        return AnswerResult(
            AskResponse(answer=generation.text, sources=sources),
            chunks=prepared.chunks,
            timings_ms=timings,
            prompt_tokens=generation.prompt_tokens,
            completion_tokens=generation.completion_tokens,
            refused=refused,
        )

    # ----------------------------------------------------------------- streaming

    def stream(self, question: str) -> Iterator[tuple[str, object]]:
        """Événements (type, contenu) : "sources" (liste de Source), "token" (texte),
        puis "done" (réponse complète, sources citées, durées ; "chunks" et "stats" servent
        au suivi et sont retirés avant l'envoi au client)."""
        prepared = self.prepare(question)
        if self.should_refuse_without_llm(prepared):
            text = f"{REFUSAL} {REFUSAL_HINT}"
            yield "sources", []
            yield "token", text
            yield "done", {"answer": text, "sources": [], "timings_ms": prepared.timings_ms,
                           "chunks": [], "stats": {"refused": True, "llm_called": False}}
            return

        yield "sources", build_sources(prepared.chunks)
        start = time.perf_counter()
        pieces = []
        for piece in self.llm.stream(SYSTEM_PROMPT, prepared.user_prompt):
            pieces.append(piece)
            yield "token", piece
        text = "".join(pieces).strip()
        timings = {**prepared.timings_ms, "llm": (time.perf_counter() - start) * 1000}
        refused = is_refusal(text)
        sources = [] if refused else build_sources(prepared.chunks, text)
        yield "done", {"answer": text, "sources": sources, "timings_ms": timings,
                       "chunks": prepared.chunks,
                       "stats": {"refused": refused, "llm_called": True}}


def build_sources(chunks: list[RetrievedChunk], answer: str | None = None) -> list[Source]:
    """Sources dédupliquées (document + section). Si la réponse cite des documents entre
    crochets, on ne garde que ceux-là."""
    cited = set(re.findall(r"\[([^\[\]]+?\.(?:pdf|docx|md|txt|pptx|html))\]", answer or ""))
    if cited:
        chunks = [c for c in chunks if c.metadata.get("document") in cited] or chunks
    sources, seen = [], set()
    for chunk in chunks:
        meta = chunk.metadata
        key = (meta.get("document"), meta.get("section"))
        if key in seen:
            continue
        seen.add(key)
        body = chunk.text.split("\n\n", 1)[-1]
        page = meta.get("page")
        sources.append(Source(
            document=meta.get("document", "?"),
            titre=meta.get("titre"),
            section=meta.get("section"),
            page=page if isinstance(page, int) and page > 0 else None,
            score=round(chunk.relevance, 4),
            extrait=body[:EXCERPT_CHARS] + ("…" if len(body) > EXCERPT_CHARS else ""),
        ))
    return sources
