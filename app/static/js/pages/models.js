import { api } from "../core/api.js";
import { html, raw } from "../core/dom.js";
import { icon } from "../ui/icons.js";
import { fmt } from "../ui/format.js";
import { makeChart, disposeCharts, axis, baseOptions } from "../ui/charts.js";
import { pageHead, skeletonPage, badge, notice, stateEmpty } from "../ui/components.js";

const m = (k, v) => html`<div class="metric"><span>${k}</span><b>${v}</b></div>`;
export default async function render(ctx) {
  const { root } = ctx, charts = [];
  ctx.onCleanup(() => disposeCharts(charts));
  root.innerHTML = skeletonPage(2).toString();
  const { data } = await api("/models", {}, { signal: ctx.signal });
  const card = (c) => {
    const re = c.real_evaluation, se = c.synthetic_evaluation, ts = c.tiny_sample;
    return html`<section class="card mcard"><div class="row between wrap"><h3>${c.name}</h3><div class="row gap-6">${badge(c.trained_on.startsWith("real") ? "real" : "synthetic", `Trained on ${c.trained_on.split(" ")[0]}`)}${c.recalibrated_on_real ? badge("real", "Recalibrated on real data") : ""}${badge("derived", c.status)}</div></div>
      <div class="small t2">${c.type}</div><div class="small t2"><b>Used for:</b> ${c.used_for}</div>
      <div><div class="lbl" style="margin-bottom:4px">Real-world evaluation</div>${re ? (c.id === "pregame" ? html`${m("Test season", `${re.test_season} · ${re.test_games} games`)}${m("Accuracy", fmt.pct(re.accuracy * 100))}${m("Log loss", re.log_loss)}${m("Brier", re.brier)}${m("Baseline: always home", fmt.pct(re.baselines.always_home_accuracy * 100))}` : c.id === "winprob" ? html`${m("Games / snapshots", `${re.games} / ${re.snapshots}`)}${m("Raw log loss → calibrated", `${re.raw.log_loss} → ${re.calibrated.log_loss}`)}${m("Accuracy (held out)", fmt.pct((re.recalibration_applied ? re.calibrated : re.raw).accuracy * 100))}${m("Baseline log loss", re.baseline_constant_home_rate.log_loss)}` : html`${m("Real shots", re.shots)}${m("Log loss: baseline", re.baseline_constant_fg.log_loss)}${m("Synthetic model", re.synthetic_model.log_loss)}${m("Synthetic + recalibration", re.synthetic_model_recalibrated.log_loss)}${m("Real-trained model", re.real_model.log_loss)}${m("AUC (real model)", re.real_model.auc)}`) : html`<div class="small muted">Not yet measured on real data.</div>`}</div>
      ${ts && !re ? html`<div class="notice">${raw(icon("alert"))}<div>Only a tiny hand-extracted sample exists (${ts.games ?? ts.checkpoints ?? "few"} ${ts.games ? "games" : "checkpoints"}${ts.overall_real_fg_pct ? `, ${(ts.buckets || []).reduce((s, b) => s + b.n, 0)} shots` : ""}). ${ts.log_loss ? `Win-prob log loss there was ${ts.log_loss} — worse than a coin flip (0.693).` : ts.correlation_real_fg_vs_predicted_quality != null ? `Correlation with real FG% was ${ts.correlation_real_fg_vs_predicted_quality}.` : ""} Not statistically meaningful.</div></div>` : ""}
      ${se ? html`<div><div class="lbl" style="margin-bottom:4px">Synthetic holdout <span class="muted">(not real-world performance)</span></div>${Object.entries(se).filter(([k]) => k !== "holdout_kind").map(([k, v]) => m(k.replace("_", " "), v))}</div>` : ""}
      <div class="small t2">${c.note || ""}</div></section>`;
  };
  const shot = data.cards.find((c) => c.id === "shot"), dc = shot.real_evaluation?.distance_calibration;
  root.innerHTML = pageHead({ title: "Models & Evaluation", sub: "What every model is, what it was trained on, and how it scored. Synthetic training data is never presented as real performance." }).toString() + html`
    ${notice(raw("<b>How to read this:</b> “Trained on synthetic” means the training labels come from a hand-written generator, so its holdout scores only show it matches that generator. Real-world scores are measured on actual NBA games and shots with <code>scripts/evaluate_real.py</code> and <code>scripts/train_pregame.py</code>."), "info")}
    <div class="grid">${data.cards.map((c) => html`<div class="s6">${card(c)}</div>`)}
    ${dc?.length ? html`<section class="card s12"><div class="card-h"><h3>Shot model vs. real FG% by distance</h3><span class="tiny muted">Held-out recent shots</span></div><div class="card-b"><div class="chart h260"><canvas id="dc"></canvas></div></div></section>` : ""}
    <section class="card s12"><div class="card-h"><h3>Explainability</h3></div><div class="card-b small t2"><ul style="margin:0;padding-left:18px;line-height:1.7"><li><b>Pre-game model:</b> logistic regression, so factor contributions are exact SHAP values in log-odds (shown as win-probability points on the Predictions page).</li><li><b>In-game win probability:</b> exact Shapley values over its six inputs against a neutral reference state.</li><li><b>Shot model:</b> TreeSHAP via XGBoost <code>pred_contribs</code>.</li><li><b>Archetypes:</b> k-means centroids on per-36 and rate stats; similarity is cosine distance. Unsupervised, so there is no accuracy score.</li></ul></div></section></div>`.toString();
  if (dc?.length) makeChart(root.querySelector("#dc"), (c) => ({ type: "bar", data: { labels: dc.map((b) => `${b.label} (n=${b.n})`), datasets: [{ label: "Actual", data: dc.map((b) => b.actual_fg_pct), backgroundColor: c.accent, borderRadius: 4 }, { label: "Synthetic model", data: dc.map((b) => b.synthetic_model_pct), backgroundColor: c.warn, borderRadius: 4 }, { label: "Real-trained model", data: dc.map((b) => b.real_model_pct), backgroundColor: c.pos, borderRadius: 4 }] }, options: baseOptions(c, { plugins: { legend: { display: true, labels: { color: c.text, usePointStyle: true } } }, scales: { x: axis(c, { grid: { display: false } }), y: axis(c, { beginAtZero: true, ticks: { callback: (v) => `${v}%` } }) } }) }), charts);
}
