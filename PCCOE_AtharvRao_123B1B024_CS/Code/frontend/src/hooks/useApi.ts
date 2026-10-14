import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Load data when `dependencies` change.
 *
 * Responses that arrive after the inputs changed (or after the component went away) are ignored, so
 * a slow request can never overwrite newer data or update an unmounted screen.
 */
export function useApi<T>(load: () => Promise<T>, dependencies: unknown[]) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;
  const ticket = useRef(0);

  const run = useCallback((silent: boolean) => {
    const mine = ++ticket.current;
    if (!silent) setLoading(true);
    loadRef
      .current()
      .then((value) => {
        if (mine !== ticket.current) return;
        setData(value);
        setError(undefined);
      })
      .catch((reason: unknown) => {
        if (mine === ticket.current) setError(reason instanceof Error ? reason : new Error(String(reason)));
      })
      .finally(() => {
        if (mine === ticket.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    run(false);
    return () => {
      ticket.current += 1; // invalidate anything still in flight
    };
  }, dependencies);

  const refresh = useCallback(() => run(false), [run]);
  /** Reload without flashing the loading state (used for polling). */
  const reload = useCallback(() => run(true), [run]);
  return { data, error, loading, refresh, reload };
}
