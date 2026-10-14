---
title: rag-llm
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
pinned: false
license: apache-2.0
short_description: Génération (Ministral 3 8B) pour l'assistant RH/IT Nexalis
---

# rag-llm — génération pour l'assistant Nexalis (ZeroGPU)

Space **privé**, matériel **ZeroGPU**. Il ne fait que générer du texte à partir d'un prompt construit par l'API (recherche, filtre RGPD et sources restent côté API).

| Point d'API | Rôle |
| --- | --- |
| `/generate` | réponse en streaming (texte cumulé), utilisée par l'assistant |
| `/generate_json` | réponse complète + mesures : tokens, durée de génération, tokens/s, VRAM maximale |

Variables du Space : `MODEL_ID` (défaut `mistralai/Ministral-3-8B-Instruct-2512-BF16`), `QUANTIZATION` (`bf16`, `int8`, `nf4`), `MAX_NEW_TOKENS` (600), `TEMPERATURE` (0,1), `GPU_DURATION` (30 s).

Appel depuis l'API (`LLM_PROVIDER=zerogpu`, `LLM_SPACE_ID=Lulu18/rag-llm`, `HF_TOKEN`) :

```python
from gradio_client import Client
client = Client("Lulu18/rag-llm", token=HF_TOKEN)
client.predict(system_prompt, user_prompt, api_name="/generate")
```

Publication depuis le dépôt du projet : `python -m scripts.deploy_space`.
