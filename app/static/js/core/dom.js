// Tiny safe-by-default templating: interpolations are HTML-escaped unless wrapped with raw().
const MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => MAP[c]);
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s ?? ""));
const flat = (v) => {
  if (v == null || v === false) return "";
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(flat).join("");
  return esc(v);
};
export function html(strings, ...vals) {
  let out = strings[0];
  for (let i = 0; i < vals.length; i++) out += flat(vals[i]) + strings[i + 1];
  return new Raw(out);
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
export function mount(el, content) { el.innerHTML = content instanceof Raw ? content.s : esc(content); return el; }
export function delegate(root, type, selector, handler) {
  const fn = (e) => { const t = e.target.closest(selector); if (t && root.contains(t)) handler(e, t); };
  root.addEventListener(type, fn);
  return () => root.removeEventListener(type, fn);
}
export const debounce = (fn, ms = 200) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
