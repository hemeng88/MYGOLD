import { useCallback, useEffect, useRef, useState } from "react";

export const FUNDS_CHANGED_EVENT = "mygold:funds-changed";

/** 串行轮询；后台暂停，回到页面或恢复网络时立即同步。 */
export function usePolling<T>(fetchData: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    try {
      const next = await fetchData(controller.signal);
      if (!controller.signal.aborted) {
        setData(next);
        setError(null);
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "读取失败，请稍后重试");
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [fetchData]);

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    let generation = 0;
    const tick = async () => {
      window.clearTimeout(timer);
      const current = ++generation;
      if (disposed || document.visibilityState === "hidden") return;
      if (!navigator.onLine) {
        setLoading(false);
        setError("网络已断开，恢复连接后会自动重试");
        return;
      }
      await reload();
      if (!disposed && current === generation) timer = window.setTimeout(tick, 20000);
    };
    const resume = () => {
      window.clearTimeout(timer);
      active.current?.abort();
      void tick();
    };
    void tick();
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    window.addEventListener("offline", resume);
    window.addEventListener(FUNDS_CHANGED_EVENT, resume);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      active.current?.abort();
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
      window.removeEventListener("offline", resume);
      window.removeEventListener(FUNDS_CHANGED_EVENT, resume);
    };
  }, [reload]);

  return { data, loading, error, reload };
}
