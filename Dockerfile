# syntax=docker/dockerfile:1

# ---------- Étape 0 : interface web (React + Vite), construite dans app/static/ui ----------
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


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
# Configuration + un seul jeu de poids par modèle : model.safetensors s'il existe, sinon
# pytorch_model.bin (BGE-M3 n'est publié qu'en .bin). Ni ONNX, ni OpenVINO, ni doublons.
RUN <<EOF
python - <<'PY'
import os
from huggingface_hub import HfApi, snapshot_download

for repo in (os.environ["EMBEDDING_MODEL"], os.environ["RERANKER_MODEL"]):
    files = set(HfApi().list_repo_files(repo))
    weights = "model.safetensors" if "model.safetensors" in files else "pytorch_model.bin"
    snapshot_download(repo, allow_patterns=[
        weights, "config.json", "config_sentence_transformers.json", "modules.json",
        "sentence_bert_config.json", "tokenizer*", "special_tokens_map.json",
        "sentencepiece.bpe.model", "1_Pooling/*",
    ])
    print(f"{repo} : {weights}")
PY
EOF

# Modèles de Docling (mise en page, tableaux) et de l'OCR RapidOCR, pour l'ajout de documents
# depuis l'interface : téléchargés ici en convertissant un PDF vierge, rien à l'exécution.
# RapidOCR range ses modèles dans son paquet : l'image finale copie donc /opt/venv de cette étape.
RUN <<EOF
python - <<'PY'
import pypdfium2 as pdfium
from docling.document_converter import DocumentConverter

pdf = pdfium.PdfDocument.new()
pdf.new_page(595, 842)
pdf.save("/tmp/vierge.pdf")
DocumentConverter().convert("/tmp/vierge.pdf")
print("Modèles Docling prêts")
PY
EOF


# ---------- Étape 3 : image finale, légère et sans outils de build ----------
FROM python:3.12-slim AS runtime

ARG EMBEDDING_MODEL=BAAI/bge-m3
ARG RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    MODELS_LOCAL_ONLY=1 \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    RERANKER_MODEL=${RERANKER_MODEL} \
    MLFLOW_TRACKING_ENABLED=true \
    MLFLOW_TRACKING_URI=sqlite:////home/appuser/app/data/mlflow.db

# Utilisateur non root (uid 1000)
RUN useradd --create-home --uid 1000 appuser

COPY --from=models /opt/venv /opt/venv
COPY --from=models --chown=appuser:appuser /opt/hf /opt/hf

WORKDIR /home/appuser/app
# Dossiers écrits à l'exécution : base MLflow (suivi des requêtes), documents ajoutés depuis
# l'interface, cache du parsing. Disque du conteneur : éphémère sur Azure Container Apps.
RUN mkdir -p data/raw data/parsed && chown -R appuser:appuser /home/appuser/app
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser ingestion ./ingestion
# Interface web servie par FastAPI sur /ui (rapport d'évaluation : app/reports/dashboard.json).
COPY --from=frontend --chown=appuser:appuser /build/app/static/ui ./app/static/ui
# Index Chroma construit en amont par `python -m ingestion.ingest`, et documents sources : l'ajout
# depuis l'interface relance l'ingestion incrémentale, qui retirerait de l'index tout document
# absent de data/raw.
COPY --chown=appuser:appuser chroma_db ./chroma_db
COPY --chown=appuser:appuser data/raw ./data/raw

USER appuser

EXPOSE 7860

# Docker vérifie toutes les 30 s que l'API répond (pas de curl dans l'image slim).
# start-period long : chargement des modèles d'embeddings au démarrage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
