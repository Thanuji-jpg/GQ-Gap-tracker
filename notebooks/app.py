"""
Lightweight BQ Gap Tracker — single custom page, not a dashboard scaffold.

  python tracker/app.py
  → http://127.0.0.1:5055
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis import run_analysis, write_payload  # noqa: E402
from src.strava_sync import sync  # noqa: E402

app = Flask(__name__)

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>BQ Gap Tracker</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet" />
<style>
  :root {
    --ink: #1a1f1c;
    --muted: #5a645c;
    --paper: #eef2ec;
    --band: #d5e0d4;
    --line: #2f5d50;
    --safe: #1f6b4a;
    --std: #8a3b12;
    --fit: #1c3d5a;
    --dot: #e85d04;
    --warn: #7a2e2e;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    color: var(--ink);
    font-family: "Source Sans 3", sans-serif;
    background:
      radial-gradient(1200px 600px at 10% -10%, #f7faf5 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #dfe8dc 0%, transparent 50%),
      linear-gradient(180deg, #e8eee6 0%, var(--paper) 40%, #e3e9e0 100%);
    min-height: 100vh;
  }
  main {
    max-width: 920px;
    margin: 0 auto;
    padding: 2.5rem 1.25rem 4rem;
  }
  .brand {
    font-family: Fraunces, Georgia, serif;
    font-size: clamp(2.2rem, 5vw, 3.2rem);
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1.05;
    margin: 0 0 0.4rem;
  }
  .question {
    font-size: 1.05rem;
    color: var(--muted);
    max-width: 38rem;
    margin: 0 0 1.75rem;
  }
  .actions {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-bottom: 1.75rem;
  }
  button {
    font: inherit;
    font-weight: 600;
    border: 1.5px solid var(--ink);
    background: var(--ink);
    color: #f4f7f2;
    padding: 0.55rem 1rem;
    cursor: pointer;
  }
  button.secondary {
    background: transparent;
    color: var(--ink);
  }
  button:disabled { opacity: 0.5; cursor: wait; }
  .status { color: var(--muted); font-size: 0.9rem; align-self: center; }
  .verdict-card {
    background: rgba(255,255,255,0.72);
    border: 1px solid #c5d0c3;
    padding: 1.25rem 1.35rem 1.35rem;
    margin-bottom: 1.75rem;
  }
  .verdict-card.bad { border-left: 5px solid var(--warn); }
  .verdict-card.ok { border-left: 5px solid var(--safe); }
  .verdict-card.warn { border-left: 5px solid var(--std); }
  .verdict-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    font-weight: 600;
    margin: 0 0 0.35rem;
  }
  .verdict-headline {
    font-family: Fraunces, Georgia, serif;
    font-size: clamp(1.55rem, 3.5vw, 2rem);
    font-weight: 700;
    line-height: 1.15;
    margin: 0 0 0.55rem;
  }
  .verdict-card.bad .verdict-headline { color: var(--warn); }
  .verdict-card.ok .verdict-headline { color: var(--safe); }
  .verdict-summary {
    color: var(--muted);
    margin: 0 0 1.1rem;
    max-width: 40rem;
    line-height: 1.45;
  }
  .verdict-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 0.85rem 1rem;
  }
  .verdict-grid .item {
    background: rgba(238, 242, 236, 0.85);
    padding: 0.7rem 0.8rem;
  }
  .verdict-grid .item span {
    display: block;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    font-weight: 600;
    margin-bottom: 0.2rem;
  }
  .verdict-grid .item strong {
    font-size: 1.15rem;
    font-weight: 600;
  }
  .verdict-note {
    margin: 1rem 0 0;
    font-size: 0.92rem;
    color: var(--ink);
    line-height: 1.4;
  }
  #chart {
    width: 100%;
    height: auto;
    background: rgba(255,255,255,0.4);
    border: 1px solid #c5d0c3;
  }
  .legend {
    display: flex; gap: 1.25rem; flex-wrap: wrap;
    font-size: 0.85rem; margin: 0.6rem 0 1.5rem; color: var(--muted);
  }
  .legend span::before {
    content: ""; display: inline-block; width: 1.1rem; height: 3px;
    margin-right: 0.4rem; vertical-align: middle;
  }
  .legend .fit::before { background: var(--fit); }
  .legend .dot::before {
    width: 0.55rem; height: 0.55rem; border-radius: 50%;
    background: var(--dot); vertical-align: middle;
  }
  .legend .std::before { background: var(--std); }
  .legend .safe::before { background: var(--safe); }
  .legend .trend::before { background: #666; border-top: 2px dashed #666; height: 0; }
  details {
    margin-top: 1rem;
    background: rgba(255,255,255,0.35);
    padding: 0.75rem 1rem;
  }
  summary { cursor: pointer; font-weight: 600; }
  pre { white-space: pre-wrap; font-size: 0.85rem; color: var(--muted); }
  footer { margin-top: 2rem; font-size: 0.8rem; color: var(--muted); }
</style>
</head>
<body>
<main>
  <h1 class="brand">BQ Gap Tracker</h1>
  <p class="question">Based on your Strava runs: are you on track to hit a Boston Qualifying time — and if so, by when?</p>

  <div class="actions">
    <button id="syncBtn" type="button">Sync new runs from Strava</button>
    <button id="recomputeBtn" class="secondary" type="button">Recompute</button>
    <span class="status" id="status"></span>
  </div>

  <section id="verdict" class="verdict-card" aria-live="polite"></section>

  <svg id="chart" viewBox="0 0 900 420" role="img" aria-label="Predicted marathon fitness vs BQ targets"></svg>
  <div class="legend">
    <span class="fit">Fitness trend</span>
    <span class="dot">Weekly estimate</span>
    <span class="std">BQ standard</span>
    <span class="safe">Safe target (−6:00)</span>
    <span class="trend">Recent trend</span>
  </div>

  <details>
    <summary>Data quality &amp; diagnostics</summary>
    <pre id="quality"></pre>
    <pre id="diagnostics"></pre>
  </details>

  <footer>Age group &amp; targets come from <code>src/config.py</code> + BAA 2027 standards. Update your age there if the placeholder is wrong.</footer>
</main>
<script>
async function load() {
  const res = await fetch("/api/analysis");
  const data = await res.json();
  render(data);
}

function parseVerdict(text) {
  const t = text || "";
  let status = "Checking…";
  let tone = "warn";
  if (/NOT ON TRACK/i.test(t)) { status = "Not on track"; tone = "bad"; }
  else if (/ON TRACK/i.test(t) || /Already at/i.test(t)) { status = "On track"; tone = "ok"; }
  else if (/POSSIBLE BUT AGGRESSIVE|LATE/i.test(t)) { status = "Possible, but aggressive"; tone = "warn"; }

  const grab = (re) => {
    const m = t.match(re);
    return m ? m[1].trim() : null;
  };
  return {
    status,
    tone,
    current: grab(/Current predicted marathon fitness:\s*([0-9:]+)/i),
    gapStd: grab(/Gap to BQ standard \(([^)]+)\):\s*([0-9:]+)/i),
    std: grab(/Gap to BQ standard \(([0-9:]+)\)/i),
    gapSafe: grab(/Gap to safe target \(([^)]+)\):\s*([0-9:]+)/i),
    safe: grab(/Gap to safe target \(([0-9:]+)\)/i),
    weeks: grab(/Time remaining until [^:]+:\s*([0-9.]+ weeks)/i),
    need: grab(/need ~([0-9:]+) improvement per week/i),
    trend: grab(/Recent trend:\s*([^\n.]+)/i),
  };
}

function render(data) {
  const parsed = parseVerdict(data.verdict);
  const gapToStd = (data.latest_prediction_seconds != null)
    ? fmtHms(data.latest_prediction_seconds - data.target.standard_seconds)
    : (parsed.gapStd || "—");
  const summary = parsed.tone === "ok"
    ? "Your recent runs project a marathon time at or under the Boston target."
    : "Your recent Strava runs project a marathon much slower than the Boston cutoff, and the trend is not closing the gap fast enough.";

  const v = document.getElementById("verdict");
  v.className = "verdict-card " + parsed.tone;
  v.innerHTML = `
    <p class="verdict-label">Verdict for Boston ${data.athlete.horizon?.slice(0,4) || "2027"}</p>
    <h2 class="verdict-headline">${parsed.status}</h2>
    <p class="verdict-summary">${summary}</p>
    <div class="verdict-grid">
      <div class="item"><span>Your fitness now</span><strong>${data.latest_prediction || "—"}</strong></div>
      <div class="item"><span>BQ standard needed</span><strong>${data.target.standard}</strong></div>
      <div class="item"><span>Gap to close</span><strong>${gapToStd}</strong></div>
      <div class="item"><span>Safe target</span><strong>${data.target.safe_target}</strong></div>
      <div class="item"><span>Trend</span><strong>${data.projection.trend_direction}</strong></div>
      <div class="item"><span>Time left</span><strong>${parsed.weeks || "—"}</strong></div>
      <div class="item"><span>Age group</span><strong>${data.target.age_group} · ${data.athlete.gender}</strong></div>
      <div class="item"><span>Need / week</span><strong>${parsed.need || "—"}</strong></div>
    </div>
    <p class="verdict-note">${escapeHtml(oneLineNote(data))}</p>
  `;
  document.getElementById("quality").textContent = data.quality;
  document.getElementById("diagnostics").textContent =
    data.diagnostics_narrative + "\\n\\n" + data.projection.message;
  drawChart(data);
}

function fmtHms(seconds) {
  const s = Math.round(Math.abs(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const sign = seconds < 0 ? "-" : "";
  return `${sign}${h}:${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function oneLineNote(data) {
  const p = data.projection || {};
  if (p.trend_direction === "flat") {
    return "Recent weeks are basically flat — no reliable date when you would hit Boston pace.";
  }
  if (p.trend_direction === "worsening") {
    return "Fitness is trending the wrong way, so no hopeful crossing date is projected.";
  }
  if (p.crosses_safe_on) return `At the current rate, the safe target is projected around ${p.crosses_safe_on}.`;
  if (p.crosses_standard_on) return `At the current rate, the bare BQ standard is projected around ${p.crosses_standard_on}.`;
  return p.message || "";
}

function drawChart(data) {
  const svg = document.getElementById("chart");
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const series = data.fitness_series || [];
  if (!series.length) {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", 40); t.setAttribute("y", 40);
    t.textContent = "Not enough fitness points yet.";
    svg.appendChild(t);
    return;
  }

  const W = 900, H = 420, pad = {l:70, r:30, t:30, b:50};
  const xs = series.map(d => new Date(d.week_start + "T00:00:00"));
  const ys = series.map(d => d.pred_marathon_s);
  const std = data.target.standard_seconds;
  const safe = data.target.safe_target_seconds;
  const yMin = Math.min(...ys, safe) - 600;
  const yMax = Math.max(...ys, std) + 600;
  const xMin = xs[0].getTime(), xMax = xs[xs.length-1].getTime() || xMin+1;

  const xScale = t => pad.l + (t - xMin) / (xMax - xMin || 1) * (W - pad.l - pad.r);
  const yScale = s => pad.t + (1 - (s - yMin) / (yMax - yMin || 1)) * (H - pad.t - pad.b);

  function line(x1,y1,x2,y2, color, dash) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", "line");
    el.setAttribute("x1", x1); el.setAttribute("y1", y1);
    el.setAttribute("x2", x2); el.setAttribute("y2", y2);
    el.setAttribute("stroke", color); el.setAttribute("stroke-width", 2);
    if (dash) el.setAttribute("stroke-dasharray", dash);
    svg.appendChild(el);
  }
  // target lines
  line(pad.l, yScale(std), W-pad.r, yScale(std), "#8a3b12", "6 4");
  line(pad.l, yScale(safe), W-pad.r, yScale(safe), "#1f6b4a", "6 4");

  // fitness path
  let d = "";
  series.forEach((pt, i) => {
    const x = xScale(xs[i].getTime()), y = yScale(pt.pred_marathon_s);
    d += (i ? "L" : "M") + x + " " + y + " ";
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 5);
    c.setAttribute("fill", "#e85d04");
    c.setAttribute("stroke", "#fff7ed");
    c.setAttribute("stroke-width", "1.5");
    svg.appendChild(c);
  });
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "#1c3d5a");
  path.setAttribute("stroke-width", 2.5);
  svg.insertBefore(path, svg.firstChild);

  // trend overlay from last N points
  const n = Math.min(14, series.length);
  if (n >= 3) {
    const pts = series.slice(-n);
    const t0 = new Date(pts[0].week_start + "T00:00:00").getTime();
    const X = pts.map(p => (new Date(p.week_start + "T00:00:00").getTime() - t0) / (7*86400000));
    const Y = pts.map(p => p.pred_marathon_s);
    const xm = X.reduce((a,b)=>a+b,0)/X.length, ym = Y.reduce((a,b)=>a+b,0)/Y.length;
    let num=0, den=0;
    for (let i=0;i<X.length;i++){ num += (X[i]-xm)*(Y[i]-ym); den += (X[i]-xm)**2; }
    const slope = den ? num/den : 0, intercept = ym - slope*xm;
    const x1 = xScale(new Date(pts[0].week_start + "T00:00:00").getTime());
    const x2 = xScale(new Date(pts[pts.length-1].week_start + "T00:00:00").getTime());
    const y1 = yScale(intercept);
    const y2 = yScale(intercept + slope * X[X.length-1]);
    line(x1,y1,x2,y2, "#666", "2 6");
  }

  // y labels
  [std, safe, ys[ys.length-1]].forEach((val, i) => {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", 8);
    t.setAttribute("y", yScale(val) + 4);
    t.setAttribute("font-size", 11);
    t.setAttribute("fill", "#5a645c");
    const h = Math.floor(val/3600), m = Math.floor((val%3600)/60);
    t.textContent = `${h}:${String(m).padStart(2,"0")}`;
    svg.appendChild(t);
  });
  // x end labels
  [xs[0], xs[xs.length-1]].forEach((dt, i) => {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", xScale(dt.getTime()));
    t.setAttribute("y", H - 18);
    t.setAttribute("font-size", 11);
    t.setAttribute("fill", "#5a645c");
    t.setAttribute("text-anchor", i ? "end" : "start");
    t.textContent = dt.toISOString().slice(0,10);
    svg.appendChild(t);
  });
}

document.getElementById("syncBtn").onclick = async () => {
  const btn = document.getElementById("syncBtn");
  const st = document.getElementById("status");
  btn.disabled = true; st.textContent = "Syncing…";
  try {
    const res = await fetch("/api/sync", {method:"POST"});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "sync failed");
    st.textContent = `+${data.sync.fetched_new} new · ${data.sync.total_runs} runs`;
    render(data.analysis);
  } catch (e) {
    st.textContent = String(e.message || e);
  } finally {
    btn.disabled = false;
  }
};

document.getElementById("recomputeBtn").onclick = () => load();
load();
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/api/analysis")
def api_analysis():
    return jsonify(run_analysis())


@app.post("/api/sync")
def api_sync():
    try:
        summary = sync(full=False)
        payload = run_analysis()
        write_payload()
        return jsonify({"sync": summary, "analysis": payload})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    write_payload()
    print("BQ Gap Tracker → http://127.0.0.1:5055")
    app.run(host="127.0.0.1", port=5055, debug=False)
