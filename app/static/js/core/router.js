import { store } from "./store.js";
import { clearApiCache } from "./api.js";

const routes = [];
let current = null;
export function route(pattern, load, nav) { routes.push({ re: new RegExp("^" + pattern.replace(/:(\w+)/g, "(?<$1>[^/]+)") + "$"), load, nav }); }

export function parseHash() {
  const raw = (location.hash || "#/overview").slice(1);
  const [path, qs = ""] = raw.split("?");
  return { path: path || "/overview", query: Object.fromEntries(new URLSearchParams(qs)) };
}
export function navigate(path, query = {}, { replace = false } = {}) {
  const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== "" && v != null)).toString();
  const h = `#${path}${qs ? "?" + qs : ""}`;
  if (replace) history.replaceState(null, "", h); else location.hash = h;
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}
export function setQuery(patch) {
  const { path, query } = parseHash();
  history.replaceState(null, "", `#${path}?${new URLSearchParams(Object.entries({ ...query, ...patch }).filter(([, v]) => v !== "" && v != null))}`);
}

export function startRouter(host, { onRoute }) {
  const run = async () => {
    const { path, query } = parseHash();
    let match = null, params = {};
    for (const r of routes) { const m = r.re.exec(path); if (m) { match = r; params = m.groups || {}; break; } }
    if (!match) { match = routes.find((r) => r.nav === "notfound"); }
    if (current) { current.abort.abort(); current.cleanups.forEach((fn) => { try { fn(); } catch { /* ignore */ } }); }
    const ctx = { params, query, root: host, abort: new AbortController(), cleanups: [], path,
      onCleanup(fn) { this.cleanups.push(fn); }, get signal() { return this.abort.signal; },
      season: store.state.season, reload() { clearApiCache(); run(); } };
    current = ctx;
    onRoute?.(match?.nav, path);
    host.classList.add("page-leave");
    await new Promise((r) => setTimeout(r, 90));
    if (current !== ctx) return;
    host.classList.remove("page-leave");
    host.scrollTop = 0; window.scrollTo({ top: 0 });
    host.innerHTML = ""; host.classList.remove("page-enter"); void host.offsetWidth; host.classList.add("page-enter");
    try {
      const mod = await match.load();
      if (current !== ctx) return;
      await mod.default(ctx);
    } catch (e) {
      if (e?.name === "AbortError" || current !== ctx) return;
      console.error(e);
      const { stateError } = await import("../ui/components.js");
      host.innerHTML = stateError(e, true).toString();
      host.querySelector("[data-retry]")?.addEventListener("click", () => ctx.reload());
    }
  };
  window.addEventListener("hashchange", run);
  store.on("season", run);
  run();
  return run;
}
