"""Faux LLM qui renvoie toujours la même réponse : tests et démo sans réseau."""

from collections.abc import Iterator

from app.llm.base import Generation


class StaticClient:
    name = "static"
    model = "static"

    def __init__(self, answer: str) -> None:
        self.answer = answer

    def generate(self, system_prompt: str, user_prompt: str) -> Generation:
        return Generation(self.answer)

    def stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        words = self.answer.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "
