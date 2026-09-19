import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { useT } from "../components/LanguageProvider";

export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number | null = 5000) {
  const t = useT();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(() => {
    return fetcherRef
      .current()
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : t("poll.connection_error"));
      })
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => {
    refresh();
    if (!intervalMs) return;
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}
