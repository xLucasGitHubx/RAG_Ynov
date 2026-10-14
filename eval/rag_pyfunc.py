"""Modèle MLflow « from code » : le pipeline RAG complet (voir eval/register_config.py).

Entrée : une liste de questions (ou un DataFrame avec une colonne « question »).
Sortie : pour chaque question, la réponse et les documents cités.

Le chargement reconstruit l'assistant à partir de la configuration de l'environnement (index
Chroma, modèles, LLM) : le registre versionne la configuration et ses scores, pas les poids
(BGE-M3 et le LLM restent sur le Hub Hugging Face).
"""

import mlflow
from mlflow.pyfunc import PythonModel


class RagAssistantModel(PythonModel):
    def load_context(self, context):
        from app.config import get_settings
        from app.llm import build_llm_client
        from app.rag.factory import build_retriever
        from app.services.assistant import Assistant

        settings = get_settings()
        self.assistant = Assistant(build_llm_client(settings), build_retriever(settings))

    def predict(self, context, model_input, params=None):
        questions = (model_input["question"].tolist() if hasattr(model_input, "columns")
                     else list(model_input))
        outputs = []
        for question in questions:
            result = self.assistant.answer(question)
            outputs.append({"answer": result.response.answer,
                            "sources": [s.document for s in result.response.sources]})
        return outputs


mlflow.models.set_model(RagAssistantModel())
