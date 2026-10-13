"""Recherche lexicale BM25 en mémoire, pour la recherche hybride (BM25 + vecteurs).

La recherche vectorielle comprend les reformulations mais rate parfois un mot exact décisif
(« astreinte », « déménagement ») ; BM25 fait l'inverse. Les deux classements sont fusionnés par
Reciprocal Rank Fusion (RRF). Le corpus tient en mémoire (quelques centaines de chunks) : l'index
est reconstruit au démarrage à partir de la collection Chroma.
"""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

STOPWORDS = set("""
a à ai au aux avec ce ces cet cette dans de des du elle en est et être il ils je la le les
leur leurs lui ma mais me mes mon ne nos notre nous on ou où par pas pour qu que qui sa se
ses son sont sur ta te tes ton tu un une vos votre vous y d l j n s c m t qu est-ce
combien quel quelle quels quelles comment quand puis-je dois-je ai-je peut-on faut-il
""".split())

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


class Analyzer:
    """Minuscules, mots, sans mots vides, racinisation Snowball française, sans accents."""

    def __init__(self) -> None:
        import snowballstemmer

        self._stemmer = snowballstemmer.stemmer("french")

    def __call__(self, text: str) -> list[str]:
        words = [w for w in _WORD_RE.findall(text.lower()) if w not in STOPWORDS]
        return [_strip_accents(s) for s in self._stemmer.stemWords(words) if s]


@dataclass
class LexicalHit:
    id: str
    text: str
    metadata: dict
    score: float


class BM25Index:
    def __init__(self, ids: list[str], texts: list[str], metadatas: list[dict],
                 k1: float = 1.5, b: float = 0.75) -> None:
        self.analyzer = Analyzer()
        self.ids, self.texts, self.metadatas = ids, texts, metadatas
        self.k1, self.b = k1, b
        self.docs = [Counter(self.analyzer(t)) for t in texts]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_length = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_collection(cls, collection) -> "BM25Index":
        data = collection.get(include=["documents", "metadatas"])
        return cls(data["ids"], data["documents"], [m or {} for m in data["metadatas"]])

    def search(self, query: str, n: int, exclude_obsolete: bool = True) -> list[LexicalHit]:
        terms = [t for t in set(self.analyzer(query)) if t in self.idf]
        scores = []
        for i, doc in enumerate(self.docs):
            if exclude_obsolete and self.metadatas[i].get("statut") == "obsolete":
                continue
            norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg_length)
            score = sum(self.idf[t] * doc[t] * (self.k1 + 1) / (doc[t] + norm)
                        for t in terms if t in doc)
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return [LexicalHit(self.ids[i], self.texts[i], self.metadatas[i], s)
                for s, i in scores[:n]]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60,
                           weights: list[float] | None = None) -> list[str]:
    """Fusionne plusieurs classements d'identifiants : score = somme de poids / (k + rang)."""
    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights or [1.0] * len(rankings), strict=True):
        for rank, id_ in enumerate(ranking, 1):
            scores[id_] = scores.get(id_, 0.0) + weight / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)
