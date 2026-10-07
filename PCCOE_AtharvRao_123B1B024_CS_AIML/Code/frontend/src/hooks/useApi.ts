import { useEffect, useState } from "react";

export function useApi<T>(load: () => Promise<T>, dependencies: unknown[]) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const refresh = () => {
    setLoading(true); setError(undefined);
    void load().then(setData).catch(setError).finally(() => setLoading(false));
  };
  useEffect(refresh, dependencies); // The load closure is deliberately keyed by screen inputs.
  return { data, error, loading, refresh };
}
