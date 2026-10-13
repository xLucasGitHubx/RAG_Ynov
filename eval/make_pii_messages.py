"""Génère eval/pii_messages.jsonl : 20 messages réalistes contenant des données personnelles
(Faker fr_FR, graine fixe), qui doivent tous être bloqués par le filtre RGPD de l'API.

Usage : python -m eval.make_pii_messages
"""

import json
from pathlib import Path

from faker import Faker

OUT = Path(__file__).parent / "pii_messages.jsonl"

TEMPLATES = [
    ("NIR", "Bonjour, mon numéro de sécurité sociale est {ssn}, pouvez-vous vérifier mes droits ?"),
    ("NIR", "Je m'appelle {name}, n° sécu {ssn}. Mon arrêt maladie est-il bien reçu ?"),
    ("NIR", "Pour la mutuelle de mon fils, voici son numéro : {ssn}"),
    ("NIR", "Ma carte vitale porte le numéro {ssn}, je l'ai perdue, que faire ?"),
    ("IBAN", "Voici mon nouvel IBAN pour les notes de frais : {iban}"),
    ("IBAN", "Mes remboursements doivent arriver sur {iban}, est-ce bien enregistré ?"),
    ("IBAN", "J'ai changé de banque, IBAN {iban}. Faut-il prévenir la paie ?"),
    ("IBAN", "Remboursement de mutuelle sur le compte {iban} svp"),
    ("CARTE", "J'ai payé l'hôtel avec ma carte {card}, comment me faire rembourser ?"),
    ("CARTE", "Ma carte bancaire {card} a été débitée deux fois pour le train."),
    ("CARTE", "Le numéro de ma carte affaires est {card}, elle expire bientôt."),
    ("CARTE", "Peux-tu vérifier le paiement fait avec la carte {card} ?"),
    ("EMAIL", "Mon adresse perso est {email}, peux-tu m'y envoyer la notice mutuelle ?"),
    ("EMAIL", "Envoie le guide des congés à {email} stp"),
    ("EMAIL", "Mon manager {name} ({email}) n'a pas validé mes congés."),
    ("EMAIL", "Contacte-moi sur {email} pour le télétravail."),
    ("TELEPHONE", "Rappelez-moi au {phone} pour mon problème de VPN."),
    ("TELEPHONE", "Mon numéro de portable a changé : {phone}, comment mettre à jour la MFA ?"),
    ("TELEPHONE", "Je suis joignable au {phone} pendant mon télétravail."),
    ("TELEPHONE", "Le support peut m'appeler au {phone} ? Mon imprimante ne marche plus."),
]


def main() -> None:
    fake = Faker("fr_FR")
    Faker.seed(2026)
    with OUT.open("w", encoding="utf-8") as f:
        for i, (kind, template) in enumerate(TEMPLATES, 1):
            message = template.format(ssn=fake.ssn(), iban=fake.iban(),
                                      card=fake.credit_card_number(), email=fake.email(),
                                      phone=fake.phone_number(), name=fake.name())
            f.write(json.dumps({"id": f"pii-{i:02d}", "type": kind, "message": message},
                               ensure_ascii=False) + "\n")
    print(f"{len(TEMPLATES)} messages écrits dans {OUT}")


if __name__ == "__main__":
    main()
