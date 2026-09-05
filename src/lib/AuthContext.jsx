import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth as useClerkAuth, useOrganization, useUser } from "@clerk/react";

import {
  bootstrapWorkspace,
  clearWorkspace,
  createPythonWorkspace,
  listPythonWorkspaces,
  selectWorkspace,
  setAuraTokenProvider,
} from "@/lib/auraApi";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const clerk = useClerkAuth();
  const { user } = useUser();
  const { organization } = useOrganization();
  const [workspace, setWorkspace] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [workspaceError, setWorkspaceError] = useState(null);
  const [isLoadingWorkspace, setIsLoadingWorkspace] = useState(false);

  useEffect(() => {
    setAuraTokenProvider(() => clerk.getToken());
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
    setIsLoadingWorkspace(true);
    setWorkspaceError(null);
    clearWorkspace();
    bootstrapWorkspace(organization?.name || "My AURA Workspace")
      .then(async (active) => {
        if (cancelled) return;
        setWorkspace(active);
        const rows = await listPythonWorkspaces();
        if (!cancelled) setWorkspaces(rows);
      })
      .catch((error) => {
        if (!cancelled) setWorkspaceError(error);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingWorkspace(false);
      });
    return () => {
      cancelled = true;
    };
  }, [clerk.isLoaded, clerk.isSignedIn, clerk.orgId, organization?.name]);

  useEffect(() => {
    const handleExpiredSession = () => clerk.signOut({ redirectUrl: window.location.href });
    window.addEventListener("aura:session-expired", handleExpiredSession);
    return () => window.removeEventListener("aura:session-expired", handleExpiredSession);
  }, [clerk]);

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
    organization,
    workspace,
    workspaces,
    workspaceError,
    isAuthenticated: Boolean(clerk.isSignedIn),
    isLoadingAuth: !clerk.isLoaded,
    isLoadingWorkspace,
    chooseWorkspace,
    createWorkspace,
    refreshWorkspaces,
    logout,
  }), [user, organization, workspace, workspaces, workspaceError, clerk.isSignedIn, clerk.isLoaded, isLoadingWorkspace, chooseWorkspace, createWorkspace, refreshWorkspaces, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
};
