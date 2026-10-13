---
title: rag-llm
sdk: gradio
app_file: app.py
pinned: false
---

# rag-llm — génération pour l'assistant Nexalis (ZeroGPU)

Space **privé**, matériel **ZeroGPU**. Il ne fait que générer du texte à partir d'un prompt
construit par l'API (recherche, sécurité et sources restent côté API).

Appel depuis l'API (`LLM_PROVIDER=zerogpu`, `LLM_SPACE_ID=<compte>/rag-llm`, `HF_TOKEN`) :

```python
from gradio_client import Client
client = Client("<compte>/rag-llm", token=HF_TOKEN)
client.predict(system_prompt, user_prompt, api_name="/generate")
```

Statut : code prêt, **non déployé** (itération 4 bis). Points à vérifier au premier déploiement :
signature exacte de `Client` (`token=` ou `hf_token=`), décompte du quota sur le compte appelant,
durée réelle de génération pour ajuster `@spaces.GPU(duration=...)`.
