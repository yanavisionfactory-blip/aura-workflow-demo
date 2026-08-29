import { INTERFACE_TOOLS } from "@/lib/demoData";

// One shared, in-memory connection store. It reflects what AURA is REALLY
// connected to — seeded empty and populated from the backend (live OAuth
// connectors + persisted user-approved / interface / mcp connections) on app
// load via hydrateConnections(). The demo no longer pre-marks tools connected,
// so the in-plan connection gate actually surfaces tools the user hasn't
// connected yet.
const state = { "AURA Intelligence": true };
const listeners = new Set();

export function getConnection(name) {
  return !!state[name];
}

export function getAllConnections() {
  return { ...state };
}

export function setConnection(name, value = true) {
  state[name] = value;
  listeners.forEach((l) => l(getAllConnections()));
}

// Replace the whole map in one shot (used by hydrateConnections so the store
// mirrors the backend's authoritative state rather than accumulating on top
// of stale demo defaults).
export function replaceConnections(map) {
  for (const k of Object.keys(state)) delete state[k];
  state["AURA Intelligence"] = true;
  if (map && typeof map === "object") {
    Object.entries(map).forEach(([k, v]) => {
      if (v) state[k] = true;
    });
  }
  listeners.forEach((l) => l(getAllConnections()));
}

export function subscribeConnections(listener) {
  listeners.add(listener);
  listener(getAllConnections());
  return () => listeners.delete(listener);
}

export { INTERFACE_TOOLS };