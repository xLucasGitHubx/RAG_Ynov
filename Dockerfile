# syntax=docker/dockerfile:1

# ---------- Étape 1 : environnement Python (torch CPU, sans les bibliothèques CUDA) ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copier requirements.txt seul d'abord : la couche des dépendances reste en cache
# tant que ce fichier ne change pas, même si le code change.
COPY requirements.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt


# ---------- Étape 2 : modèles d'embeddings et de reranking (aucun téléchargement au démarrage) ----------
FROM builder AS models

ARG EMBEDDING_MODEL=BAAI/bge-m3
ARG RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
ENV HF_HOME=/opt/hf
# Uniquement les poids safetensors et la configuration : pas les doublons .bin / onnx.
RUN python -c "from huggingface_hub import snapshot_download as d; \
pat=['*.json','*.safetensors','*.model','*.txt','sentencepiece*','1_Pooling/*']; \
d('${EMBEDDING_MODEL}', allow_patterns=pat); d('${RERANKER_MODEL}', allow_patterns=pat)"


# ---------- Étape 3 : image finale, légère et sans outils de build ----------
FROM python:3.12-slim AS runtime

ARG EMBEDDING_MODEL=BAAI/bge-m3
ARG RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    RERANKER_MODEL=${RERANKER_MODEL} \
    MLFLOW_TRACKING_ENABLED=false

# Utilisateur non root (uid 1000)
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=models /opt/hf /opt/hf

WORKDIR /home/appuser/app
COPY --chown=appuser:appuser app ./app
# Index Chroma construit en amont par `python -m ingestion.ingest` (corpus fixe) :
# réindexer = reconstruire l'image. Docling n'est donc pas embarqué.
COPY --chown=appuser:appuser chroma_db ./chroma_db
COPY --chown=appuser:appuser data/raw/metadata.json ./data/raw/metadata.json

USER appuser

EXPOSE 7860

# Docker vérifie toutes les 30 s que l'API répond (pas de curl dans l'image slim).
# start-period long : chargement des modèles d'embeddings au démarrage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
