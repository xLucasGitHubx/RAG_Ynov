"""Suivi MLflow de chaque requête et des retours utilisateurs (pouce haut / bas).

Chaque question devient un run MLflow (expérience « requests ») : latence par étape, nombre de
chunks, scores, tokens, backend, modèles, version de l'index. Jamais le texte de la question.

L'écriture se fait dans un thread de fond (file d'attente) : la réponse à l'utilisateur n'attend
pas MLflow. Si MLflow est absent ou en panne, l'API continue de fonctionner.
"""

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("rag.monitoring")


@dataclass
class RequestRecord:
    request_id: str
    endpoint: str
    params: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class FeedbackRecord:
    request_id: str
    rating: int
    comment_length: int = 0


def new_request_id() -> str:
    return uuid.uuid4().hex


class Tracker:
    """Interface minimale : `track` et `feedback` ne bloquent jamais."""

    def track(self, record: RequestRecord) -> None: ...

    def feedback(self, record: FeedbackRecord) -> None: ...

    def flush(self, timeout: float = 5) -> None: ...


class NullTracker(Tracker):
    pass


class MLflowTracker(Tracker):
    def __init__(self, tracking_uri: str, experiment: str = "requests") -> None:
        import mlflow  # dépendance optionnelle

        self._mlflow = mlflow
        mlflow.set_tracking_uri(tracking_uri)
        self._client = mlflow.MlflowClient(tracking_uri)
        found = self._client.get_experiment_by_name(experiment)
        self._experiment_id = (found.experiment_id if found
                               else self._client.create_experiment(experiment))
        self._runs: dict[str, str] = {}  # request_id -> run_id (pour le feedback)
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._thread = threading.Thread(target=self._worker, name="mlflow-tracker", daemon=True)
        self._thread.start()

    def track(self, record: RequestRecord) -> None:
        self._put(record)

    def feedback(self, record: FeedbackRecord) -> None:
        self._put(record)

    def flush(self, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)

    def _put(self, item) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            logger.warning("File MLflow pleine : enregistrement ignoré")

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if isinstance(item, RequestRecord):
                    self._write_request(item)
                else:
                    self._write_feedback(item)
            except Exception as exc:  # MLflow ne doit jamais faire tomber l'API
                logger.warning("Écriture MLflow impossible : %s", exc)
            finally:
                self._queue.task_done()

    def _write_request(self, record: RequestRecord) -> None:
        run = self._client.create_run(
            self._experiment_id,
            run_name=f"{record.endpoint}-{record.request_id[:8]}",
            tags={"request_id": record.request_id, "endpoint": record.endpoint, **record.tags},
            start_time=int(record.timestamp * 1000),
        )
        run_id = run.info.run_id
        self._runs[record.request_id] = run_id
        from mlflow.entities import Metric, Param

        ts = int(record.timestamp * 1000)
        self._client.log_batch(
            run_id,
            metrics=[Metric(k, float(v), ts, 0) for k, v in record.metrics.items()],
            params=[Param(k, str(v)[:500]) for k, v in record.params.items()],
        )
        self._client.set_terminated(run_id)

    def _write_feedback(self, record: FeedbackRecord) -> None:
        run_id = self._runs.get(record.request_id)
        if run_id is None:
            runs = self._client.search_runs(
                [self._experiment_id], f"tags.request_id = '{record.request_id}'", max_results=1
            )
            if not runs:
                logger.warning("Feedback pour une requête inconnue : %s", record.request_id[:8])
                return
            run_id = runs[0].info.run_id
        self._client.log_metric(run_id, "feedback", record.rating)
        self._client.set_tag(run_id, "feedback", "positif" if record.rating > 0 else "negatif")
        if record.comment_length:
            self._client.log_metric(run_id, "feedback_comment_length", record.comment_length)


def build_tracker(enabled: bool, tracking_uri: str) -> Tracker:
    if not enabled:
        return NullTracker()
    try:
        return MLflowTracker(tracking_uri)
    except Exception as exc:  # mlflow non installé, base inaccessible...
        logger.warning("Suivi MLflow désactivé : %s", exc)
        return NullTracker()
