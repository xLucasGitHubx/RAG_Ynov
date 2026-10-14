import { ApiError } from "../lib/api";
import { OPEN_KEY_DIALOG } from "./AppShell";
import { Button, EmptyState } from "./ui";

/** Message d'erreur qui dit quoi faire, pas seulement ce qui ne va pas. */
export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 401) {
    return (
      <EmptyState
        title="Clé d'API requise"
        action={
          <Button variant="primary" onClick={() => window.dispatchEvent(new Event(OPEN_KEY_DIALOG))}>
            Saisir une clé d'API
          </Button>
        }
      >
        L'API est protégée par des clés (<code>API_KEYS</code>). Saisissez une clé de rôle employé ou admin.
      </EmptyState>
    );
  }
  const hint =
    status === 0
      ? "L'API ne répond pas : lancez « uvicorn app.main:app --port 7860 » puis réessayez."
      : error.message;
  return (
    <EmptyState
      title={status === 404 ? "Données indisponibles" : "Chargement impossible"}
      action={onRetry && <Button onClick={onRetry}>Réessayer</Button>}
    >
      {hint}
    </EmptyState>
  );
}
