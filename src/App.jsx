import { useState } from "react";
import { Show, SignIn, SignUp } from "@clerk/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter as Router, Route, Routes } from "react-router-dom";

import { Toaster } from "@/components/ui/toaster";
import { AuthProvider, useAuth } from "@/lib/AuthContext";
import PageNotFound from "@/lib/PageNotFound";
import { queryClientInstance } from "@/lib/query-client";
import Demo from "@/pages/Demo";

function AuthLanding() {
  const [mode, setMode] = useState("sign-in");
  const productUrl = `${window.location.origin}${import.meta.env.BASE_URL}`;

  return (
    <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center p-6">
      <section className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-xs uppercase tracking-[0.35em] text-violet-300">AURA</p>
          <h1 className="mt-3 text-3xl font-semibold">Automate work across every tool</h1>
          <p className="mt-2 text-sm text-slate-400">Sign in to your secure workspace.</p>
        </div>
        <div className="mb-4 flex justify-center gap-2">
          <button type="button" onClick={() => setMode("sign-in")} className="rounded-lg bg-white/10 px-3 py-2 text-sm">Sign in</button>
          <button type="button" onClick={() => setMode("sign-up")} className="rounded-lg bg-violet-500 px-3 py-2 text-sm">Create account</button>
        </div>
        {mode === "sign-in" ? (
          <SignIn routing="hash" fallbackRedirectUrl={productUrl} />
        ) : (
          <SignUp routing="hash" fallbackRedirectUrl={productUrl} />
        )}
      </section>
    </main>
  );
}

function LoadingScreen({ label }) {
  return (
    <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center">
      <div className="text-center">
        <div className="mx-auto mb-4 h-7 w-7 animate-spin rounded-full border-2 border-slate-700 border-t-violet-400" />
        <p className="text-sm text-slate-400">{label}</p>
      </div>
    </main>
  );
}

function ProductRoutes() {
  const { isLoadingAuth, isLoadingWorkspace, workspace, workspaceError, reconnectWorkspace } = useAuth();

  if (isLoadingAuth) return <LoadingScreen label="Checking your session…" />;
  if (isLoadingWorkspace) return <LoadingScreen label="Opening your workspace…" />;
  if (workspaceError) {
    return (
      <main className="min-h-screen bg-[#080d1b] text-white grid place-items-center p-6">
        <section className="w-full max-w-md rounded-2xl border border-white/10 bg-white/5 p-8 text-center">
          <h1 className="text-xl font-semibold">AURA couldn’t open your workspace</h1>
          <p className="mt-3 text-sm text-slate-400">Your session is safe. AURA tried to reconnect automatically.</p>
          <button type="button" onClick={reconnectWorkspace} className="mt-6 rounded-lg bg-violet-500 px-4 py-2 text-sm font-medium">Try again</button>
        </section>
      </main>
    );
  }
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
