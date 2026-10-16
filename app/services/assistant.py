"""Logique métier de l'assistant : recherche du contexte, puis génération par le LLM.

Si la recherche ne trouve aucun extrait assez pertinent, l'assistant refuse directement, sans
appeler le LLM : la réponse est plus fiable et ne consomme aucune minute GPU.
"""

import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from app.llm import Generation, LLMClient, LLMError
from app.prompts import (
    FAITHFULNESS_SYSTEM_PROMPT,
    REFUSAL,
    REFUSAL_HINT,
    SYSTEM_PROMPT,
    build_faithfulness_prompt,
    build_retry_prompt,
    build_user_prompt,
    format_context_block,
    is_refusal,
    parse_verdict,
)
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas import AskResponse, Source

EXCERPT_CHARS = 300
logger = logging.getLogger("rag.assistant")


def _add_tokens(main: Generation, other: Generation) -> Generation:
    """`main` avec les tokens de `other` en plus (coût total des appels d'une question)."""
    def total(a: int | None, b: int | None) -> int | None:
        return None if a is None and b is None else (a or 0) + (b or 0)
    return replace(main, prompt_tokens=total(main.prompt_tokens, other.prompt_tokens),
                   completion_tokens=total(main.completion_tokens, other.completion_tokens))


@dataclass
class AnswerResult:
    response: AskResponse
    chunks: list[RetrievedChunk] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    llm_meta: dict | None = None
    refused: bool = False
    llm_called: bool = True
    # "skipped" (pas de contrôle), "ok", "retried", "unreadable" ou "error" : voir _check_and_retry.
    faithfulness: str = "skipped"


@dataclass
class PreparedPrompt:
    chunks: list[RetrievedChunk]
    user_prompt: str
    timings_ms: dict[str, float]


class Assistant:
    def __init__(self, llm: LLMClient, retriever: Retriever | None = None,
                 verify: bool = False) -> None:
        self.llm = llm
        self.retriever = retriever
        self.verify = verify  # contrôle de fidélité après génération (2 à 3 appels au LLM)

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
        faithfulness = "skipped"
        if self.verify and not is_refusal(generation.text):
            generation, faithfulness, extra = self._check_and_retry(prepared, generation)
            timings |= extra
        refused = is_refusal(generation.text)
        sources = [] if refused else build_sources(prepared.chunks, generation.text)
        return AnswerResult(
            AskResponse(answer=generation.text, sources=sources),
            chunks=prepared.chunks,
            timings_ms=timings,
            prompt_tokens=generation.prompt_tokens,
            completion_tokens=generation.completion_tokens,
            llm_meta=generation.meta,
            refused=refused,
            faithfulness=faithfulness,
        )

    # ----------------------------------------------------------------- contrôle de fidélité

    def _check_and_retry(self, prepared: PreparedPrompt,
                         generation: Generation) -> tuple[Generation, str, dict[str, float]]:
        """Un contrôle de fidélité, puis au plus une nouvelle génération si la réponse n'est pas
        soutenue par les extraits. Toute erreur du LLM ou verdict illisible garde la réponse
        initiale : le contrôle ne doit jamais empêcher de répondre.

        Statut : "ok" (fidèle), "retried" (réponse régénérée), "unreadable" (verdict illisible)
        ou "error" (LLM indisponible pendant le contrôle ou la nouvelle tentative)."""
        blocks = [format_context_block(i, c.text, c.metadata)
                  for i, c in enumerate(prepared.chunks, 1)]
        timings: dict[str, float] = {}
        start = time.perf_counter()
        try:
            verdict = self.llm.generate(FAITHFULNESS_SYSTEM_PROMPT,
                                        build_faithfulness_prompt(blocks, generation.text))
        except LLMError as exc:
            logger.warning("Contrôle de fidélité indisponible : %s", exc)
            return generation, "error", {"check": (time.perf_counter() - start) * 1000}
        timings["check"] = (time.perf_counter() - start) * 1000
        faithful, reason = parse_verdict(verdict.text)
        generation = _add_tokens(generation, verdict)
        if faithful is None:
            return generation, "unreadable", timings
        if faithful:
            return generation, "ok", timings

        start = time.perf_counter()
        try:
            retry = self.llm.generate(
                SYSTEM_PROMPT,
                build_retry_prompt(prepared.user_prompt, generation.text, reason))
        except LLMError as exc:
            logger.warning("Nouvelle tentative impossible : %s", exc)
            return generation, "error", timings
        timings["retry"] = (time.perf_counter() - start) * 1000
        if not retry.text.strip():
            return generation, "error", timings
        return _add_tokens(retry, generation), "retried", timings

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
        faithfulness = "skipped"
        if self.verify and not is_refusal(text):
            # Les mots sont déjà affichés : "done" porte la réponse finale, qui remplace le texte.
            checked, faithfulness, extra = self._check_and_retry(prepared, Generation(text))
            text = checked.text.strip()
            timings |= extra
        refused = is_refusal(text)
        sources = [] if refused else build_sources(prepared.chunks, text)
        yield "done", {"answer": text, "sources": sources, "timings_ms": timings,
                       "chunks": prepared.chunks,
                       "stats": {"refused": refused, "llm_called": True,
                                 "faithfulness": faithfulness}}


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
