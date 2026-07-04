// DataContext — loads all datasets from the backend once, after login, and
// exposes them to the pages. The app renders a global loading/error gate so
// pages can assume `data` is present.
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { loadAll } from "./data.js";

const Ctx = createContext(null);

export function DataProvider({ children, onAuthError }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loadAll());
    } catch (err) {
      if (err.isAuthError) {
        onAuthError?.();
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => { reload(); }, [reload]);

  // Shallow-merge fields into the loaded dataset (e.g. after Settings saves the
  // current user), so dependent UI like the sidebar updates without a refetch.
  const patch = useCallback((partial) => {
    setData((d) => (d ? { ...d, ...partial } : d));
  }, []);

  return (
    <Ctx.Provider value={{ data, loading, error, reload, patch }}>
      {children}
    </Ctx.Provider>
  );
}

export function useData() {
  const ctx = useContext(Ctx);
  if (ctx == null) throw new Error("useData must be used within a DataProvider");
  return ctx;
}
