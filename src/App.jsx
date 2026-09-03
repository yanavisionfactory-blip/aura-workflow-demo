import { useState } from "react";
import { CreateOrganization, OrganizationList, Show, SignIn, SignUp } from "@clerk/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter as Router, Route, Routes } from "react-router-dom";

import { Toaster } from "@/components/ui/toaster";
import { AuthProvider, useAuth } from "@/lib/AuthContext";
import PageNotFound from "@/lib/PageNotFound";
import { queryClientInstance } from "@/lib/query-client";
import Demo from "@/pages/Demo";

function AuthLanding() {
  const [mode, setMode] = useState("sign-in");
  return (
    <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center p-6">
      <section className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-xs uppercase tracking-[0.35em] text-violet-300">AURA</p>
          <h1 className="mt-3 text-3xl font-semibold">Automate work across every tool</h1>
          <p className="mt-2 text-sm text-slate-400">Sign in to your secure workspace.</p>
        </div>
        <div className="flex justify-center gap-2 mb-4">
          <button onClick={() => setMode("sign-in")} className="rounded-lg px-3 py-2 text-sm bg-white/10">Sign in</button>
          <button onClick={() => setMode("sign-up")} className="rounded-lg px-3 py-2 text-sm bg-violet-500">Create account</button>
        </div>
        {mode === "sign-in" ? <SignIn routing="hash" /> : <SignUp routing="hash" />}
      </section>
    </main>
  );
}

function OrganizationGate() {
  const [creating, setCreating] = useState(false);
  return (
    <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center p-6">
      <section className="w-full max-w-xl text-center">
        <p className="text-xs uppercase tracking-[0.35em] text-violet-300">AURA workspace</p>
        <h1 className="mt-3 text-2xl font-semibold">Choose or create an organization</h1>
        <p className="mt-2 mb-6 text-sm text-slate-400">Organizations keep each customer’s workflows and connections isolated.</p>
        <button onClick={() => setCreating(!creating)} className="mb-5 rounded-lg bg-violet-500 px-4 py-2 text-sm font-medium">
          {creating ? "Choose an existing organization" : "Create organization"}
        </button>
        <div className="flex justify-center">
          {creating ? <CreateOrganization routing="hash" /> : <OrganizationList hidePersonal />}
        </div>
      </section>
    </main>
  );
}

function LoadingScreen({ label }) {
  return <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center"><p className="text-sm text-slate-400">{label}</p></main>;
}

function ProductRoutes() {
  const { organization, isLoadingAuth, isLoadingWorkspace, workspace, workspaceError } = useAuth();
  if (isLoadingAuth) return <LoadingScreen label="Checking your session…" />;
  if (!organization) return <OrganizationGate />;
  if (isLoadingWorkspace) return <LoadingScreen label="Opening your workspace…" />;
  if (workspaceError) return <LoadingScreen label={workspaceError.message || "Workspace could not be opened."} />;
  if (!workspace) return <LoadingScreen label="Preparing your workspace…" />;
  return (
    <Routes>
      <Route path="/" element={<Demo />} />
      <Route path="*" element={<PageNotFound />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClientInstance}>
      <Router basename={import.meta.env.BASE_URL}>
        <Show when="signed-out"><AuthLanding /></Show>
        <Show when="signed-in"><AuthProvider><ProductRoutes /></AuthProvider></Show>
      </Router>
      <Toaster />
    </QueryClientProvider>
  );
}
