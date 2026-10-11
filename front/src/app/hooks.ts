import { useRef, useState } from "react";
import { ApiError } from "../services/api";

export function useTask() {
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function run(task: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (error) {
      setError(error);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return {
    run,
    busy,
    error,
    setError,
    fields: error instanceof ApiError ? error.fields : {},
  };
}
