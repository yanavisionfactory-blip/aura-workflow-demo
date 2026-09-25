import { useEffect, useState } from "react";
import { Show, SignIn, SignUp } from "@clerk/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter as Router, Route, Routes } from "react-router-dom";

import { Toaster } from "@/components/ui/toaster";
import { AuthProvider, useAuth } from "@/lib/AuthContext";
import PageNotFound from "@/lib/PageNotFound";
import { queryClientInstance } from "@/lib/query-client";
import Demo from "@/pages/Demo";

function UpdateNotice() {
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    const build = import.meta.env.VITE_AURA_BUILD_SHA;
    if (!build) return undefined;
    let mounted = true;
    const check = async () => {
      try {
        const response = await fetch(`${import.meta.env.BASE_URL}version.txt?at=${Date.now()}`, {
          cache: "no-store",
        });
        if (!response.ok) return;
        const published = (await response.text()).trim();
        if (mounted && published && published !== build) setAvailable(true);
      } catch {
        // A temporary network failure must not interrupt the active workflow.
      }
    };
    const onVisible = () => { if (document.visibilityState === "visible") void check(); };
    void check();
    const timer = window.setInterval(check, 30_000);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mounted = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  if (!available) return null;
  return (
    <div role="status" className="fixed left-1/2 top-4 z-[110] flex w-[min(92vw,34rem)] -translate-x-1/2 items-center justify-between gap-4 rounded-xl border border-violet-300/30 bg-[#111827] px-4 py-3 text-sm text-white shadow-2xl">
      <span>AURA has an update. Refresh to use the latest workflow fixes.</span>
      <button type="button" onClick={() => window.location.reload()} className="shrink-0 rounded-lg bg-violet-500 px-3 py-1.5 font-medium">Refresh</button>
    </div>
  );
}

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

function ProductRoutes() {
  const { workspaceError, reconnectWorkspace } = useAuth();

  return (
    <>
      <Routes>
        <Route path="/" element={<Demo />} />
        <Route path="*" element={<PageNotFound />} />
      </Routes>
      {workspaceError && (
        <div role="alert" className="fixed bottom-4 left-1/2 z-[100] flex -translate-x-1/2 items-center gap-3 rounded-xl border border-amber-300/20 bg-[#111827]/95 px-4 py-3 text-sm text-slate-200 shadow-2xl backdrop-blur">
          <span>AURA is reconnecting your workspace. The demo remains available.</span>
          <button type="button" onClick={reconnectWorkspace} className="rounded-lg bg-violet-500 px-3 py-1.5 text-xs font-medium text-white">Retry now</button>
        </div>
      )}
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClientInstance}>
      <Router basename={import.meta.env.BASE_URL}>
        <Show when="signed-out"><AuthLanding /></Show>
        <Show when="signed-in"><AuthProvider><ProductRoutes /></AuthProvider></Show>
      </Router>
      <UpdateNotice />
      <Toaster />
    </QueryClientProvider>
  );
}
