import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getJson } from "./api";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | Error | null;
  loading: boolean;
  reload: () => void;
}

/** Charge une ressource JSON de l'API ; garde l'ancienne donnée pendant un rechargement. */
export function useApi<T>(path: string | null, refreshMs?: number): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setLoading(true);
    getJson<T>(path, controller.signal)
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, tick]);

  useEffect(() => {
    if (!refreshMs) return;
    const id = window.setInterval(reload, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, reload]);

  useEffect(() => {
    // Une nouvelle clé d'API saisie relance les requêtes en échec.
    const onKey = () => reload();
    window.addEventListener("nexalis-api-key", onKey);
    return () => window.removeEventListener("nexalis-api-key", onKey);
  }, [reload]);

  return { data, error, loading, reload };
}

export type Theme = "light" | "dark";

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(
    () => (document.documentElement.dataset.theme as Theme) ?? "light",
  );
  const setTheme = useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
      meta.content = next === "dark" ? "#0a0a0a" : "#fafafa";
    }
    try {
      localStorage.setItem("nexalis-theme", next);
    } catch {
      // stockage indisponible : le thème vaut pour la session
    }
    setThemeState(next);
  }, []);
  return [theme, setTheme];
}

/** Vrai quand l'élément entre dans la fenêtre (pour différer un graphique). */
export function useInView<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || visible) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setVisible(true);
      },
      { rootMargin: "120px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible]);
  return [ref, visible];
}
