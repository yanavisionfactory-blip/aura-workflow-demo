import { useState } from "react";
import { useOptionalAuth } from "@/lib/authState.mjs";

export default function WorkspaceIdentity() {
  const auth = useOptionalAuth();
  const [open, setOpen] = useState(false);
  if (!auth) return null;
  const { user, workspace, workspaces, chooseWorkspace, accountControl } = auth;
  const email = user?.primaryEmailAddress?.emailAddress;
  return <div className="relative flex items-center gap-2">
    <button type="button" aria-expanded={open} aria-label="Account and workspace"
      onClick={() => setOpen(!open)} className="rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground">
      Account
    </button>
    {open && <section aria-label="Account and workspace details" className="absolute left-0 top-10 z-50 w-[min(18rem,calc(100vw-2rem))] sm:left-auto sm:right-0 rounded-xl border border-white/10 bg-[#111827] p-4 text-sm shadow-xl">
      <p className="text-xs text-muted-foreground">Signed in as</p>
      <p className="mt-1 break-all">{email || user?.fullName || "Current AURA account"}</p>
      <p className="mt-3 text-xs text-muted-foreground">Workspace</p>
      {workspaces.length > 1 ? <select aria-label="Active workspace" value={workspace?.workspace_id || ""}
        onChange={(event) => { const selected = workspaces.find((item) => item.workspace_id === event.target.value); if (selected) chooseWorkspace(selected); }}
        className="mt-1 w-full rounded-lg border border-white/10 bg-[#0c121e] p-2">
        {workspaces.map((item) => <option key={item.workspace_id} value={item.workspace_id}>{item.name}</option>)}
      </select> : <p className="mt-1">{workspace?.name || "Connecting…"}</p>}
      <div className="mt-4 flex items-center gap-3">{accountControl}<span className="text-xs text-muted-foreground">Manage or switch your account</span></div>
      <p className="mt-3 text-xs text-muted-foreground">Saved workflow links require access to the workspace where they were created.</p>
    </section>}
  </div>;
}
