"""Build a single self-contained ``index.html`` warehouse explorer.

This is pipeforge's live demo: it runs the pipeline against the bundled data
and emits ONE dependency-free HTML file that mirrors the six Grafana panels
(total revenue / orders / quarantined KPIs, revenue by category, revenue by
country, daily-revenue time series) plus the data-quality check table and a
quarantine-reason breakdown -- all as hand-rolled inline SVG. No JS libraries,
no CDN, no network. A reviewer can open it straight from the repo or a
portfolio site without booting Docker/Postgres/Grafana.

The aggregates are computed here from the same star-schema frames the pipeline
produces, so the charts show real numbers, never mock data.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..checks.core import CheckResult
from ..schema.star import StarSchema

__all__ = ["render_html", "export_html"]


# --------------------------------------------------------------------------
# Aggregation -> a plain dict (also embedded as JSON for the curious)
# --------------------------------------------------------------------------
def _aggregate(star: StarSchema) -> dict:
    fact = star.fact_sales
    product = star.dim_product
    customer = star.dim_customer

    joined = fact.merge(product, on="product_key", how="left")
    # Fact -> current customer version (for country rollup).
    cur_cust = customer[customer["is_current"]] if "is_current" in customer else customer
    joined = joined.merge(
        cur_cust[["customer_key", "country"]], on="customer_key", how="left"
    )

    by_category = (
        joined.groupby("category")["revenue"].sum().round(2).sort_values(ascending=False)
    )
    by_country = (
        joined.groupby("country")["revenue"].sum().round(2).sort_values(ascending=False)
    )

    # Daily revenue: date_key (yyyymmdd) -> revenue.
    daily = fact.copy()
    daily["date"] = pd.to_datetime(daily["date_key"].astype(str), format="%Y%m%d")
    daily_rev = daily.groupby("date")["revenue"].sum().round(2).sort_index()

    quarantine_reasons = (
        star.quarantine["quarantine_reason"].value_counts()
        if len(star.quarantine)
        else pd.Series(dtype=int)
    )

    total_revenue = round(float(fact["revenue"].sum()), 2) if len(fact) else 0.0

    return {
        "total_revenue": total_revenue,
        "orders": int(len(fact)),
        "unique_products": int(product["stock_code"].nunique()),
        "unique_customers": int(customer["customer_id"].nunique()),
        "quarantined": int(len(star.quarantine)),
        "by_category": [
            {"label": k, "value": float(v)} for k, v in by_category.items()
        ],
        "by_country": [
            {"label": k, "value": float(v)} for k, v in by_country.items()
        ],
        "daily_revenue": [
            {"date": d.strftime("%Y-%m-%d"), "value": float(v)}
            for d, v in daily_rev.items()
        ],
        "quarantine_reasons": [
            {"label": k, "value": int(v)} for k, v in quarantine_reasons.items()
        ],
    }


# --------------------------------------------------------------------------
# Tiny inline-SVG chart helpers (no dependencies)
# --------------------------------------------------------------------------
# A "forge" identity: warm ember lead, cooled teal/steel supports. Distinct
# from the default indigo-on-dark AI look, and grounded in the project name.
_ACCENT = "#f0883e"  # ember
_PALETTE = [
    "#f0883e", "#38bdf8", "#34d399", "#fbbf24",
    "#fb7185", "#a78bfa", "#22d3ee", "#c084fc",
]


def _fmt_money(v: float) -> str:
    return f"{v:,.2f}"


def _bar_chart(data: list[dict], *, width: int = 460, bar_h: int = 26, gap: int = 10) -> str:
    if not data:
        return "<p class='empty'>No data.</p>"
    max_v = max(d["value"] for d in data) or 1
    label_w = 120
    chart_w = width - label_w - 90
    height = len(data) * (bar_h + gap) + gap
    rows = []
    for i, d in enumerate(data):
        y = gap + i * (bar_h + gap)
        w = max(2, int(chart_w * d["value"] / max_v))
        color = _PALETTE[i % len(_PALETTE)]
        label = html.escape(str(d["label"]))
        rows.append(
            f'<text x="{label_w - 8}" y="{y + bar_h * 0.68:.0f}" '
            f'text-anchor="end" class="lbl">{label}</text>'
            f'<rect x="{label_w}" y="{y}" width="{w}" height="{bar_h}" '
            f'rx="4" fill="{color}"><title>{label}: {_fmt_money(d["value"])}</title></rect>'
            f'<text x="{label_w + w + 6}" y="{y + bar_h * 0.68:.0f}" '
            f'class="val">{_fmt_money(d["value"])}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'role="img" class="chart">{"".join(rows)}</svg>'
    )


def _endpoint_dot(cx: float, cy: float) -> str:
    """An emphasized marker on the latest point of the time series."""
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{_ACCENT}"/>'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="{_ACCENT}" opacity="0.25"/>'
    )


def _line_chart(data: list[dict], *, width: int = 720, height: int = 240) -> str:
    if len(data) < 2:
        return "<p class='empty'>Not enough data for a time series.</p>"
    pad_l, pad_r, pad_t, pad_b = 56, 16, 16, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    values = [d["value"] for d in data]
    max_v = max(values) or 1
    min_v = min(values)
    span = (max_v - min_v) or 1

    def x(i: int) -> float:
        return pad_l + plot_w * i / (len(data) - 1)

    def y(v: float) -> float:
        return pad_t + plot_h * (1 - (v - min_v) / span)

    pts = " ".join(f"{x(i):.1f},{y(d['value']):.1f}" for i, d in enumerate(data))
    area = (
        f"{pad_l},{pad_t + plot_h} "
        + pts
        + f" {pad_l + plot_w},{pad_t + plot_h}"
    )
    # Y gridlines / labels (min, mid, max).
    grid = []
    for frac in (0.0, 0.5, 1.0):
        gv = min_v + span * frac
        gy = y(gv)
        grid.append(
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + plot_w}" y2="{gy:.1f}" '
            f'class="grid"/>'
            f'<text x="{pad_l - 8}" y="{gy + 4:.1f}" text-anchor="end" '
            f'class="axis">{gv:,.0f}</text>'
        )
    # X labels (first, middle, last dates).
    xlabels = []
    for i in (0, len(data) // 2, len(data) - 1):
        xlabels.append(
            f'<text x="{x(i):.1f}" y="{height - 8}" text-anchor="middle" '
            f'class="axis">{html.escape(data[i]["date"])}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" class="chart">'
        f'{"".join(grid)}'
        f'<polygon points="{area}" fill="url(#areaGrad)" opacity="0.18"/>'
        f'<polyline points="{pts}" fill="none" stroke="{_ACCENT}" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'{_endpoint_dot(x(len(data) - 1), y(values[-1]))}'
        f'{"".join(xlabels)}'
        f'<defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{_ACCENT}"/>'
        f'<stop offset="100%" stop-color="{_ACCENT}" stop-opacity="0"/>'
        f'</linearGradient></defs></svg>'
    )


def _donut(data: list[dict], *, size: int = 200) -> str:
    if not data:
        return "<p class='empty'>No data.</p>"
    import math

    total = sum(d["value"] for d in data) or 1
    cx = cy = size / 2
    r = size / 2 - 8
    inner = r * 0.58
    angle = -math.pi / 2
    segs = []
    legend = []
    for i, d in enumerate(data):
        frac = d["value"] / total
        end = angle + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(end), cy + r * math.sin(end)
        color = _PALETTE[i % len(_PALETTE)]
        segs.append(
            f'<path d="M {cx} {cy} L {x1:.2f} {y1:.2f} '
            f'A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f} Z" fill="{color}">'
            f'<title>{html.escape(str(d["label"]))}: {_fmt_money(d["value"])} '
            f'({frac*100:.0f}%)</title></path>'
        )
        legend.append(
            f'<div class="leg"><span class="sw" style="background:{color}"></span>'
            f'{html.escape(str(d["label"]))} '
            f'<span class="muted">{frac*100:.0f}%</span></div>'
        )
        angle = end
    return (
        f'<div class="donut-wrap"><svg viewBox="0 0 {size} {size}" width="{size}" '
        f'height="{size}" role="img" class="chart">{"".join(segs)}'
        f'<circle cx="{cx}" cy="{cy}" r="{inner}" fill="var(--card)"/></svg>'
        f'<div class="legend">{"".join(legend)}</div></div>'
    )


def _check_table(checks: list[CheckResult]) -> str:
    if not checks:
        return "<p class='empty'>No checks recorded.</p>"
    rows = []
    for c in checks:
        badge = "pass" if c.passed else ("fail" if c.severity.value == "error" else "warn")
        label = {"pass": "PASS", "fail": "FAIL", "warn": "WARN"}[badge]
        detail = html.escape(c.detail) if c.detail and not c.passed else ""
        rows.append(
            f"<tr><td><span class='badge {badge}'>{label}</span></td>"
            f"<td class='mono'>{html.escape(c.name)}</td>"
            f"<td>{html.escape(c.severity.value)}</td>"
            f"<td class='mono'>{c.observed}</td>"
            f"<td class='muted'>{detail}</td></tr>"
        )
    return (
        "<table class='dq'><thead><tr><th>Status</th><th>Check</th>"
        "<th>Severity</th><th>Observed</th><th>Detail</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


# --------------------------------------------------------------------------
# Page assembly
# --------------------------------------------------------------------------
def render_html(
    star: StarSchema,
    checks: list[CheckResult],
    *,
    recon: list[CheckResult] | None = None,
) -> str:
    agg = _aggregate(star)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    embedded = json.dumps(agg, indent=2)
    all_checks = list(checks) + list(recon or [])

    kpis = [
        ("Total revenue", _fmt_money(agg["total_revenue"]), "fact_sales"),
        ("Orders (fact rows)", f"{agg['orders']:,}", "invoice lines"),
        ("Products", str(agg["unique_products"]), "dim_product"),
        ("Customers", str(agg["unique_customers"]), "dim_customer"),
        ("Quarantined", str(agg["quarantined"]), "rejected rows"),
    ]
    kpi_html = "".join(
        f'<div class="kpi{" primary" if i == 0 else ""}">'
        f'<div class="kpi-v">{v}</div>'
        f'<div class="kpi-l">{html.escape(l)}</div>'
        f'<div class="kpi-s muted">{html.escape(s)}</div></div>'
        for i, (l, v, s) in enumerate(kpis)
    )

    return _TEMPLATE.format(
        generated=generated,
        kpis=kpi_html,
        cat_donut=_donut(agg["by_category"]),
        country_bar=_bar_chart(agg["by_country"]),
        daily_line=_line_chart(agg["daily_revenue"]),
        quar_bar=_bar_chart(agg["quarantine_reasons"], width=460),
        check_table=_check_table(all_checks),
        embedded=html.escape(embedded),
    )


def export_html(
    star: StarSchema,
    checks: list[CheckResult],
    out_dir: Path,
    *,
    recon: list[CheckResult] | None = None,
    filename: str = "index.html",
) -> Path:
    """Render the explorer and write it to ``out_dir/filename``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / filename
    target.write_text(render_html(star, checks, recon=recon), encoding="utf-8")
    return target


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>pipeforge — Retail Sales Star Schema</title>
<style>
:root {{
  /* Warm-biased slate ground with an ember accent (the "forge"). */
  --bg:#12100e; --card:#1c1a17; --card2:#242019; --ink:#efe9df; --muted:#a39a8c;
  --line:#332e26; --accent:#f0883e;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:
    radial-gradient(1100px 480px at 78% -8%, rgba(240,136,62,.10), transparent 60%),
    var(--bg);
  color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased; }}
.mono, .val, .axis, .kpi-v, td.mono, th {{ font-variant-numeric:tabular-nums; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:32px 20px 64px; }}
header h1 {{ margin:0; font-size:28px; letter-spacing:-.5px; }}
header p {{ margin:6px 0 0; color:var(--muted); }}
header h1 {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
.pill {{ display:inline-block; font-size:11px; letter-spacing:.8px;
  text-transform:uppercase; padding:4px 11px; border-radius:999px;
  background:rgba(240,136,62,.12); border:1px solid rgba(240,136,62,.35);
  color:var(--accent); font-weight:600; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:14px; margin:26px 0; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:16px 18px; }}
.kpi.primary {{ border-color:rgba(240,136,62,.45);
  background:linear-gradient(160deg, rgba(240,136,62,.10), var(--card) 70%); }}
.kpi.primary .kpi-v {{ color:var(--accent); }}
.kpi-v {{ font-size:26px; font-weight:700; letter-spacing:-.5px; }}
.kpi-l {{ font-size:13px; margin-top:2px; }}
.kpi-s {{ font-size:12px; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
@media (max-width:760px) {{ .grid {{ grid-template-columns:1fr; }} }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:16px;
  padding:18px 20px; overflow-x:auto; }}
.card h2 {{ margin:0 0 14px; font-size:15px; font-weight:600; color:#cdd4ea;
  text-transform:uppercase; letter-spacing:.6px; }}
.full {{ grid-column:1 / -1; }}
.muted {{ color:var(--muted); }}
.mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px; }}
svg.chart line.grid {{ stroke:var(--line); stroke-width:1; }}
svg.chart text.lbl {{ fill:var(--ink); font-size:13px; }}
svg.chart text.val {{ fill:var(--muted); font-size:12px; }}
svg.chart text.axis {{ fill:var(--muted); font-size:11px; }}
.donut-wrap {{ display:flex; gap:20px; align-items:center; flex-wrap:wrap; }}
.legend {{ display:flex; flex-direction:column; gap:6px; }}
.leg {{ font-size:13px; }}
.sw {{ display:inline-block; width:11px; height:11px; border-radius:3px;
  margin-right:7px; vertical-align:middle; }}
table.dq {{ width:100%; border-collapse:collapse; font-size:13px; }}
table.dq th, table.dq td {{ text-align:left; padding:8px 10px;
  border-bottom:1px solid var(--line); }}
table.dq th {{ color:var(--muted); font-weight:600; }}
.badge {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; }}
.badge.pass {{ background:#0f2f22; color:#4ade80; }}
.badge.warn {{ background:#33270a; color:#fbbf24; }}
.badge.fail {{ background:#3a1418; color:#f87171; }}
.empty {{ color:var(--muted); }}
details {{ margin-top:26px; }}
summary {{ cursor:pointer; color:var(--muted); }}
pre {{ background:var(--card2); border:1px solid var(--line); border-radius:12px;
  padding:14px; overflow-x:auto; font-size:12px; }}
footer {{ margin-top:36px; color:var(--muted); font-size:13px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>pipeforge <span class="pill">retail sales · star schema</span></h1>
    <p>Static warehouse explorer — the six Grafana panels, generated straight
       from the ELT output. No Docker, no Postgres, no JavaScript libraries.</p>
    <p class="muted">Generated {generated}</p>
  </header>

  <section class="kpis">{kpis}</section>

  <section class="grid">
    <div class="card"><h2>Revenue by category</h2>{cat_donut}</div>
    <div class="card"><h2>Revenue by country</h2>{country_bar}</div>
    <div class="card full"><h2>Daily revenue</h2>{daily_line}</div>
    <div class="card"><h2>Quarantine reasons</h2>{quar_bar}</div>
    <div class="card"><h2>Data-quality &amp; reconciliation</h2>{check_table}</div>
  </section>

  <details>
    <summary>Embedded aggregates (JSON)</summary>
    <pre>{embedded}</pre>
  </details>

  <footer>
    Built by <a href="https://github.com/xj16/pipeforge">pipeforge</a> —
    a runnable batch ELT pipeline. Regenerate with
    <span class="mono">python -m pipeforge export --html</span>.
  </footer>
</div>
</body>
</html>
"""
