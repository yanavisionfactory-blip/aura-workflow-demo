export const CONNECTION_REQUEST_TIMEOUT_MS = 20_000;
export const CONNECTION_CANCELLED = "Connection cancelled. Your plan is unchanged.";

// Bound the whole operation, including token lookup and response decoding.
// Aborting fetch alone cannot release a UI waiting on a stalled token provider.
export function connectionTask(operation, { signal, timeoutMs = 0,
  timeoutMessage = "The connection service took too long to respond. Please try again. Your plan is unchanged." } = {}) {
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    let settled = false;
    let timer;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
      callback(value);
    };
    const cancel = () => {
      const error = signal?.reason instanceof Error ? signal.reason : new Error(CONNECTION_CANCELLED);
      controller.abort(error);
      finish(reject, error);
    };
    if (signal?.aborted) { cancel(); return; }
    signal?.addEventListener("abort", cancel, { once: true });
    if (timeoutMs > 0) timer = setTimeout(() => {
      const error = new Error(timeoutMessage);
      controller.abort(error);
      finish(reject, error);
    }, timeoutMs);
    try {
      // Invoke synchronously so popup reservation keeps the original click gesture.
      Promise.resolve(operation(controller.signal)).then(
        (value) => finish(resolve, value), (error) => finish(reject, error),
      );
    } catch (error) { finish(reject, error); }
  });
}

export function connectionPollDelay(signal, delayMs) {
  return new Promise((resolve, reject) => {
    let timer;
    const cleanup = () => {
      window.clearTimeout?.(timer);
      signal?.removeEventListener("abort", cancel);
    };
    const cancel = () => { cleanup(); reject(signal.reason || new Error(CONNECTION_CANCELLED)); };
    if (signal?.aborted) { cancel(); return; }
    signal?.addEventListener("abort", cancel, { once: true });
    timer = window.setTimeout(() => { cleanup(); resolve(); }, delayMs);
  });
}
