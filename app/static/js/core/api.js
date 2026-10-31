import { store } from "./store.js";

export class ApiFailure extends Error {
  constructor(message, code = "error", status = 0, meta = {}) { super(message); this.code = code; this.status = status; this.meta = meta; }
}
const cache = new Map();
const inflight = new Map();

export async function api(path, params = {}, { ttl = 15000, signal, force = false } = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();
  const url = `/api/v1${path}${qs ? `?${qs}` : ""}`;
  const hit = cache.get(url);
  if (!force && hit && Date.now() - hit.t < ttl) return hit.body;
  if (!force && inflight.has(url)) return inflight.get(url);
  const p = (async () => {
    let res;
    try { res = await fetch(url, { signal, headers: { Accept: "application/json" } }); }
    catch (e) {
      if (e.name === "AbortError") throw e;
      store.set("dataStatus", { status: "unavailable", text: "Offline" });
      throw new ApiFailure("Can't reach the CourtVision server. Check your connection and try again.", "network", 0);
    }
    let body = null;
    try { body = await res.json(); } catch { /* handled below */ }
    if (!body) throw new ApiFailure("The server returned an unreadable response.", "bad_response", res.status);
    if (!res.ok || !body.ok) throw new ApiFailure(body?.error?.message || res.statusText || "Request failed", body?.error?.code, res.status, body?.meta);
    cache.set(url, { t: Date.now(), body });
    reportStatus(body.meta);
    return body;
  })().finally(() => inflight.delete(url));
  inflight.set(url, p);
  return p;
}

function reportStatus(meta) {
  if (!meta) return;
  const s = meta.status || "fresh";
  const text = s === "stale" ? "Stale data" : s === "cached" ? "Cached" : "Live data";
  store.set("dataStatus", { status: s, text });
}
export const clearApiCache = () => cache.clear();
