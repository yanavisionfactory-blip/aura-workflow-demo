import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth as useClerkAuth, useUser } from "@clerk/react";

import {
  bootstrapWorkspace,
  clearWorkspace,
  createPythonWorkspace,
  listPythonWorkspaces,
  selectWorkspace,
  setAuraTokenProvider,
} from "@/lib/auraApi";

const AuthContext = createContext(null);
const RECOVERY_DELAYS_MS = [0, 350, 900];

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export const AuthProvider = ({ children }) => {
  const clerk = useClerkAuth();
  const { user } = useUser();
  const [workspace, setWorkspace] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [workspaceError, setWorkspaceError] = useState(null);
  const [isLoadingWorkspace, setIsLoadingWorkspace] = useState(false);
  const [reconnectSequence, setReconnectSequence] = useState(0);

  useEffect(() => {
    setAuraTokenProvider((options) => clerk.getToken(options));
    return () => setAuraTokenProvider(null);
  }, [clerk.getToken]);

  const refreshWorkspaces = useCallback(async () => {
    if (!clerk.isSignedIn || !clerk.isLoaded) return [];
    const rows = await listPythonWorkspaces();
    setWorkspaces(rows);
    return rows;
  }, [clerk.isLoaded, clerk.isSignedIn]);

  useEffect(() => {
    if (!clerk.isLoaded || !clerk.isSignedIn) {
      clearWorkspace();
      setWorkspace(null);
      setWorkspaces([]);
      return;
    }

    let cancelled = false;

    async function openWorkspace() {
      setIsLoadingWorkspace(true);
      setWorkspaceError(null);
      clearWorkspace();

      let lastError = null;
      for (const delay of RECOVERY_DELAYS_MS) {
        if (cancelled) return;
        if (delay) await wait(delay);
        try {
          const active = await bootstrapWorkspace("My AURA Workspace");
          if (cancelled) return;
          setWorkspace(active);
          const rows = await listPythonWorkspaces();
          if (!cancelled) setWorkspaces(rows);
          return;
        } catch (error) {
          lastError = error;
          clearWorkspace();
        }
      }

      if (!cancelled) setWorkspaceError(lastError || new Error("Workspace unavailable"));
    }

    openWorkspace().finally(() => {
      if (!cancelled) setIsLoadingWorkspace(false);
    });

    return () => {
      cancelled = true;
    };
  }, [clerk.isLoaded, clerk.isSignedIn, reconnectSequence]);

  const reconnectWorkspace = useCallback(() => {
    setReconnectSequence((value) => value + 1);
  }, []);

  const chooseWorkspace = useCallback((next) => {
    selectWorkspace(next.workspace_id);
    setWorkspace(next);
  }, []);

  const createWorkspace = useCallback(async (name) => {
    const created = await createPythonWorkspace(name);
    selectWorkspace(created.workspace_id);
    setWorkspace(created);
    await refreshWorkspaces();
    return created;
  }, [refreshWorkspaces]);

  const logout = useCallback(async () => {
    clearWorkspace();
    await clerk.signOut({ redirectUrl: window.location.href });
  }, [clerk]);

  const value = useMemo(() => ({
    user,
    workspace,
    workspaces,
    workspaceError,
    isAuthenticated: Boolean(clerk.isSignedIn),
    isLoadingAuth: !clerk.isLoaded,
    isLoadingWorkspace,
    chooseWorkspace,
    createWorkspace,
    refreshWorkspaces,
    reconnectWorkspace,
    logout,
  }), [user, workspace, workspaces, workspaceError, clerk.isSignedIn, clerk.isLoaded, isLoadingWorkspace, chooseWorkspace, createWorkspace, refreshWorkspaces, reconnectWorkspace, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
};
