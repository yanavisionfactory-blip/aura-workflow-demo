import { useEffect, useRef, useState } from "react";
import { readSupportDiagnostics } from "@/lib/auraApi";

export default function RunSupport() {
  const token = useRef(new URLSearchParams(window.location.hash.slice(1)).get("access_token"));
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    window.history.replaceState(null, "", window.location.pathname);
    let live = true;
    readSupportDiagnostics(token.current).then((result) => { if (live) setData(result); }).catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, []);
  return <main className="mx-auto max-w-3xl p-8"><h1 className="text-xl font-semibold">AURA run diagnostics</h1><p className="my-4 text-sm text-muted-foreground">Temporary, read-only access to redacted diagnostics. The customer keeps control of their account and run.</p>{error ? <p role="alert">{error}</p> : data ? <pre className="overflow-auto rounded-xl border p-4 text-xs">{JSON.stringify(data, null, 2)}</pre> : <p>Checking support access…</p>}</main>;
}
