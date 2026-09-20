import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, Loader2, MousePointer2, RefreshCw, X } from "lucide-react";
import {
  closeLiveReviewSession,
  createLiveReviewSession,
  getLiveReviewFrame,
  sendLiveReviewInput,
} from "@/lib/auraApi";

const SPECIAL_KEYS = new Set([
  "Enter",
  "Tab",
  "Backspace",
  "Delete",
  "Escape",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Home",
  "End",
  "PageUp",
  "PageDown",
]);

const imageSource = (frame) => (
  frame?.image_base64
    ? `data:${frame.mime_type || "image/jpeg"};base64,${frame.image_base64}`
    : ""
);

export default function LiveToolReview({ provider, label }) {
  const [sessionId, setSessionId] = useState("");
  const [frame, setFrame] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const viewportRef = useRef(null);
  const sessionRef = useRef("");
  const refreshTimerRef = useRef(null);
  const inputQueueRef = useRef(Promise.resolve());

  const refresh = useCallback(async (id = sessionRef.current) => {
    if (!id) return;
    try {
      const next = await getLiveReviewFrame(id);
      if (sessionRef.current === id) {
        setFrame(next);
        setError("");
      }
    } catch (refreshError) {
      if (sessionRef.current === id) {
        setError(refreshError.message || "The live tool session is unavailable.");
      }
    }
  }, []);

  const close = useCallback(async () => {
    const id = sessionRef.current;
    sessionRef.current = "";
    setSessionId("");
    setFrame(null);
    if (id) {
      try {
        await closeLiveReviewSession(id);
      } catch {
        // Sessions expire automatically; closing is deliberately best-effort.
      }
    }
  }, []);

  useEffect(() => () => {
    window.clearTimeout(refreshTimerRef.current);
    const id = sessionRef.current;
    sessionRef.current = "";
    if (id) closeLiveReviewSession(id).catch(() => {});
  }, []);

  useEffect(() => {
    if (!sessionId) return undefined;
    const poll = window.setInterval(() => refresh(sessionId), 1_500);
    return () => window.clearInterval(poll);
  }, [refresh, sessionId]);

  const start = async () => {
    setStarting(true);
    setError("");
    try {
      const created = await createLiveReviewSession(provider);
      sessionRef.current = created.session_id;
      setSessionId(created.session_id);
      setFrame(created);
      window.setTimeout(() => viewportRef.current?.focus(), 0);
    } catch (startError) {
      setError(startError.message || "The live tool session could not start.");
    } finally {
      setStarting(false);
    }
  };

  const queueRefresh = () => {
    window.clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = window.setTimeout(() => refresh(), 250);
  };

  const sendInput = (input) => {
    const id = sessionRef.current;
    if (!id) return Promise.resolve();
    inputQueueRef.current = inputQueueRef.current.then(async () => {
      await sendLiveReviewInput(id, input);
      queueRefresh();
    }).catch((inputError) => {
      setError(inputError.message || "AURA could not forward that browser input.");
    });
    return inputQueueRef.current;
  };

  const pointerInput = (event, type) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const width = frame?.width || 1280;
    const height = frame?.height || 800;
    sendInput({
      type,
      x: Math.max(0, Math.min(width, ((event.clientX - bounds.left) / bounds.width) * width)),
      y: Math.max(0, Math.min(height, ((event.clientY - bounds.top) / bounds.height) * height)),
    });
    viewportRef.current?.focus();
  };

  const keyboardInput = (event) => {
    if (["Shift", "Control", "Alt", "Meta", "CapsLock"].includes(event.key)) return;
    let input = null;
    if ((event.ctrlKey || event.metaKey) && event.key.length === 1) {
      input = { type: "key", key: `Control+${event.key.toUpperCase()}` };
    } else if (SPECIAL_KEYS.has(event.key)) {
      input = { type: "key", key: event.key };
    } else if (event.key.length === 1 && !event.altKey) {
      input = { type: "text", text: event.key };
    }
    if (input) {
      event.preventDefault();
      sendInput(input);
    }
  };

  if (!sessionId) {
    return (
      <div className="rounded-xl border border-violet-400/20 bg-violet-400/[0.04] p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex min-w-0 flex-1 items-start gap-2.5">
            <MousePointer2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-violet-300" />
            <div>
              <p className="text-xs font-medium">Try the live {label} workspace</p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                A private cloud browser opens the real tool. You can click and type without limiting yourself to AURA fields. The normal approval preview remains available below.
              </p>
              <p className="mt-1 text-[10px] leading-relaxed text-amber-200/70">
                Experimental: live-tool edits are not yet substituted into the approved connector payload.
              </p>
            </div>
          </div>
          <button
            type="button"
            disabled={starting}
            onClick={start}
            className="flex items-center gap-1.5 rounded-lg bg-violet-500 px-3 py-2 text-[11px] font-medium text-white hover:bg-violet-400 disabled:opacity-60"
          >
            {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ExternalLink className="h-3.5 w-3.5" />}
            {starting ? "Opening…" : `Open live ${label}`}
          </button>
        </div>
        {error && <p className="mt-3 text-[11px] text-rose-300">{error} The standard preview still works.</p>}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-violet-400/25 bg-[#111522]">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/8 px-3 py-2">
        <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.12)]" />
        <span className="text-[11px] font-medium">You control this private {label} session</span>
        <span className="max-w-[18rem] truncate text-[10px] text-muted-foreground">{frame?.title || frame?.url}</span>
        <span className="ml-auto text-[10px] text-muted-foreground">Click the page, then type normally</span>
        <button type="button" onClick={() => refresh()} aria-label="Refresh live tool" className="rounded-md p-1.5 text-muted-foreground hover:bg-white/5 hover:text-foreground">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={close} aria-label="Close live tool" className="rounded-md p-1.5 text-muted-foreground hover:bg-white/5 hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div
        ref={viewportRef}
        role="application"
        aria-label={`Interactive ${label} cloud browser`}
        tabIndex={0}
        onKeyDown={keyboardInput}
        onPaste={(event) => {
          const text = event.clipboardData.getData("text");
          if (text) {
            event.preventDefault();
            sendInput({ type: "text", text });
          }
        }}
        onWheel={(event) => sendInput({ type: "scroll", delta_x: event.deltaX, delta_y: event.deltaY })}
        className="relative aspect-[16/10] w-full overflow-hidden bg-[#202432] outline-none ring-inset focus:ring-2 focus:ring-violet-400/70"
      >
        {frame ? (
          <img
            src={imageSource(frame)}
            alt={`Live ${label} browser session`}
            draggable="false"
            onClick={(event) => pointerInput(event, "click")}
            onDoubleClick={(event) => pointerInput(event, "double_click")}
            className="h-full w-full select-none object-contain"
          />
        ) : (
          <div className="flex h-full items-center justify-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading live tool…</div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-white/8 px-3 py-2 text-[10px] text-muted-foreground">
        <span>Isolated session · automatically expires after inactivity</span>
        {error && <span className="ml-auto text-rose-300">{error} The standard preview below remains usable.</span>}
      </div>
    </div>
  );
}
