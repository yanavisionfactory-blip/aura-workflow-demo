import React, { useCallback, useContext, useLayoutEffect, useMemo, useState } from "react";
import { UserButton, useAuth as useClerkAuth, useUser } from "@clerk/react";
import { AuthContext } from "@/lib/authState.mjs";

import {
  bootstrapWorkspace,
  clearWorkspace,
  createPythonWorkspace,
  listPythonWorkspaces,
  rememberedWorkspaceId,
  selectWorkspace,
  setAuraTokenProvider,
} from "@/lib/auraApi";

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

  useLayoutEffect(() => {
    setAuraTokenProvider((options) => clerk.getToken(options));
    return () => setAuraTokenProvider(null);
  }, [clerk.getToken]);

  const refreshWorkspaces = useCallback(async () => {
    if (!clerk.isSignedIn || !clerk.isLoaded) return [];
    const rows = await listPythonWorkspaces();
    setWorkspaces(rows);
    return rows;
  }, [clerk.isLoaded, clerk.isSignedIn]);

  useLayoutEffect(() => {
    if (!clerk.isLoaded) return;
    if (!clerk.isSignedIn) {
      clearWorkspace();
      setWorkspace(null);
      setWorkspaces([]);
      return;
    }

    let cancelled = false;

    async function openWorkspace() {
      setIsLoadingWorkspace(true);
      setWorkspaceError(null);
      setWorkspace(null);
      const previousWorkspaceId = rememberedWorkspaceId();
      clearWorkspace();

      let lastError = null;
      for (const delay of RECOVERY_DELAYS_MS) {
        if (cancelled) return;
        if (delay) await wait(delay);
        try {
          const active = await bootstrapWorkspace("My AURA Workspace");
          if (cancelled) return;
          const rows = await listPythonWorkspaces();
          if (cancelled) return;
          const selected = rows.find((row) => row.workspace_id === previousWorkspaceId)
            || rows.find((row) => row.workspace_id === active.workspace_id) || rows[0];
          if (!selected) throw new Error("No workspace is available for this account");
          selectWorkspace(selected.workspace_id);
          setWorkspace(selected);
          setWorkspaces(rows);
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
  }, [clerk.isLoaded, clerk.isSignedIn, clerk.userId, clerk.orgId, reconnectSequence]);

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
    accountControl: <UserButton />,
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
