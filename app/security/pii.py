"""Détection des données personnelles (RGPD) dans les questions et les journaux.

Approche par expressions régulières **validées** (clé du NIR, modulo 97 de l'IBAN, algorithme de
Luhn pour les cartes) : peu de faux positifs sur des questions RH qui contiennent des chiffres
(« 3 000 km », « 2,50 euros », « article 15 »). Presidio pourra compléter (noms, adresses).

Types détectés : numéro de sécurité sociale (NIR), IBAN, carte bancaire, e-mail, téléphone.
"""

import re
from dataclasses import dataclass

LABELS = {
    "NIR": "numéro de sécurité sociale",
    "IBAN": "IBAN",
    "CARTE": "numéro de carte bancaire",
    "EMAIL": "adresse e-mail",
    "TELEPHONE": "numéro de téléphone",
}


@dataclass(frozen=True)
class PIIMatch:
    kind: str
    start: int
    end: int

    @property
    def label(self) -> str:
        return LABELS[self.kind]


_SEP = r"[ .\- ]?"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
PHONE_RE = re.compile(
    rf"(?<![\w+])(?:(?:\+|00)33{_SEP}(?:\(0\))?{_SEP}|0)[1-9](?:{_SEP}\d{{2}}){{4}}(?!\d)"
)
NIR_RE = re.compile(
    rf"(?<!\d)([12]){_SEP}(\d{{2}}){_SEP}(0[1-9]|1[0-2]|[2-9]\d){_SEP}(\d{{2}}|2[AB]){_SEP}"
    rf"(\d{{3}}){_SEP}(\d{{3}})(?:{_SEP}(\d{{2}}))?(?!\d)",
    re.IGNORECASE,
)
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?)\b",
                     re.IGNORECASE)
CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){11,18}\d(?!\d)")


def _nir_valid(m: re.Match) -> bool:
    sex, year, month, dept, commune, order, key = m.groups()
    if key is None:  # sans clé, 13 chiffres de cette forme : on considère que c'est un NIR
        return True
    dept_num = dept.upper().replace("2A", "19").replace("2B", "18")
    number = int(f"{sex}{year}{month}{dept_num}{commune}{order}")
    return 97 - number % 97 == int(key)


def _iban_valid(value: str) -> bool:
    iban = value.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34:
        return False
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def _luhn_valid(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if not 12 <= len(digits) <= 19:  # Maestro : 12 chiffres possibles
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def detect_pii(text: str) -> list[PIIMatch]:
    matches: list[PIIMatch] = []

    def add(kind: str, m: re.Match) -> None:
        if not any(m.start() < x.end and x.start < m.end() for x in matches):
            matches.append(PIIMatch(kind, m.start(), m.end()))

    for m in EMAIL_RE.finditer(text):
        add("EMAIL", m)
    for m in IBAN_RE.finditer(text):
        if _iban_valid(m.group(1)):
            add("IBAN", m)
    for m in NIR_RE.finditer(text):
        if _nir_valid(m):
            add("NIR", m)
    for m in CARD_RE.finditer(text):
        if _luhn_valid(m.group()):
            add("CARTE", m)
    for m in PHONE_RE.finditer(text):
        add("TELEPHONE", m)
    return sorted(matches, key=lambda x: x.start)


def mask_pii(text: str) -> str:
    """Remplace chaque donnée personnelle par son type entre crochets, ex. [EMAIL]."""
    for m in reversed(detect_pii(text)):
        text = f"{text[:m.start]}[{m.kind}]{text[m.end:]}"
    return text


def describe(matches: list[PIIMatch]) -> str:
    labels = sorted({m.label for m in matches})
    return ", ".join(labels)
