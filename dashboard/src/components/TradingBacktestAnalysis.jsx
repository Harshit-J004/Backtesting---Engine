// src/components/TradingBacktestAnalysis.jsx
import React, { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Upload, DollarSign, TrendingUp, TrendingDown, Clock } from "lucide-react";

function parseCsvText(text) {
  const t = (text || "").replace(/^\uFEFF/, "").trim();
  if (!t) return [];
  const rows = t.split(/\r?\n/).filter((r) => r.trim().length);
  if (rows.length < 2) return [];
  const headers = rows[0].split(",").map((h) => h.trim());
  return rows.slice(1).map((row) => {
    const values = row.split(",");
    const obj = {};
    headers.forEach((h, i) => (obj[h] = (values[i] ?? "").trim()));
    return obj;
  });
}

function compactMoney(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return "-";
  const abs = Math.abs(x);
  if (abs >= 1_000_000_000) return `${(x / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(x / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(x / 1_000).toFixed(2)}K`;
  return x.toFixed(2);
}

function formatDuration(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "-";
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function DataTable({ rows, label }) {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;

  const cols = useMemo(() => Object.keys(rows?.[0] || {}), [rows]);

  const filtered = useMemo(() => {
    const query = (q || "").toLowerCase().trim();
    if (!query) return rows || [];
    return (rows || []).filter((r) =>
      cols.some((c) => String(r[c] ?? "").toLowerCase().includes(query))
    );
  }, [rows, q, cols]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const p = Math.min(page, totalPages);
  const start = (p - 1) * pageSize;
  const pageRows = filtered.slice(start, start + pageSize);

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-gray-600">{filtered.length} rows</div>
        <div className="flex items-center gap-2">
          <input
            className="border rounded-lg px-3 py-2 text-sm w-72"
            placeholder={`Search ${label}...`}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </div>
      </div>

      <div className="mt-3 overflow-auto border rounded-xl">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {cols.slice(0, 14).map((c) => (
                <th
                  key={c}
                  className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r, i) => (
              <tr key={i} className="border-t">
                {cols.slice(0, 14).map((c) => (
                  <td key={c} className="px-3 py-2 whitespace-nowrap">
                    {String(r[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
            {pageRows.length === 0 ? (
              <tr>
                <td colSpan={cols.length || 1} className="px-3 py-6 text-center text-gray-500">
                  No rows to display. (Upload or run a backtest to generate outputs.)
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-3 text-sm text-gray-600">
        <div>
          Page {p} / {totalPages}
        </div>
        <div className="flex gap-2">
          <button
            className="px-3 py-2 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50"
            onClick={() => setPage((x) => Math.max(1, x - 1))}
            disabled={p <= 1}
          >
            Prev
          </button>
          <button
            className="px-3 py-2 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50"
            onClick={() => setPage((x) => Math.min(totalPages, x + 1))}
            disabled={p >= totalPages}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TradingBacktestAnalysis({ preloadedCsv = null }) {
  const [basketData, setBasketData] = useState([]);
  const [tradeData, setTradeData] = useState([]);
  const [equityData, setEquityData] = useState([]);

  const [view, setView] = useState("dashboard"); // dashboard | tables
  const [tab, setTab] = useState("overview");

  const [eqBrush, setEqBrush] = useState({ startIndex: 0, endIndex: 0 });
  const [ddBrush, setDdBrush] = useState({ startIndex: 0, endIndex: 0 });

  useEffect(() => {
    if (!preloadedCsv) return;
    try {
      if (preloadedCsv.basketCsv) setBasketData(parseCsvText(preloadedCsv.basketCsv));
      if (preloadedCsv.tradeCsv) setTradeData(parseCsvText(preloadedCsv.tradeCsv));
      if (preloadedCsv.equityCsv) setEquityData(parseCsvText(preloadedCsv.equityCsv));
    } catch (e) {
      console.error("Failed to preload CSV outputs:", e);
    }
  }, [preloadedCsv]);

  const handleFileUpload = (event, type) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const rows = parseCsvText(e.target.result);
      if (type === "basket") setBasketData(rows);
      if (type === "trade") setTradeData(rows);
      if (type === "equity") setEquityData(rows);
    };
    reader.readAsText(file);
  };

  const stats = useMemo(() => {
    if (!basketData.length) return null;
    const net = basketData.map((b) => Number(b.net_pnl)).filter(Number.isFinite);
    if (!net.length) return null;

    const durations = basketData
      .map((b) => (b.duration_seconds ? Number(b.duration_seconds) : Number(b.duration_minutes || 0) * 60))
      .filter(Number.isFinite);

    const wins = net.filter((p) => p > 0);
    const losses = net.filter((p) => p <= 0);

    const totalPnl = net.reduce((a, b) => a + b, 0);
    const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
    const avgLoss = losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : 0;
    const winRate = (wins.length / net.length) * 100;

    const avgDuration = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : 0;
    const maxDuration = durations.length ? Math.max(...durations) : 0;

    return {
      totalPnl,
      avgWin,
      avgLoss,
      winRate,
      avgDuration,
      maxDuration,
      totalTrades: net.length,
      wins: wins.length,
      losses: losses.length,
    };
  }, [basketData]);

  const equityCurve = useMemo(() => {
    if (!equityData.length) return [];
    let running = Number(equityData[0].capital) || 10000;
    let peak = running;

    const curve = equityData.map((row) => {
      const eq = Number(row.total_equity);
      const equity = Number.isFinite(eq) ? eq : running;
      peak = Math.max(peak, equity);
      const drawdown = ((equity - peak) / peak) * 100;
      running = equity;
      return {
        date: row.date,
        equity,
        peak,
        drawdown,
      };
    });

    return curve;
  }, [equityData]);

  useEffect(() => {
    if (!equityCurve.length) return;
    setEqBrush({ startIndex: 0, endIndex: equityCurve.length - 1 });
    setDdBrush({ startIndex: 0, endIndex: equityCurve.length - 1 });
  }, [equityCurve.length]);

  const pnlDistribution = useMemo(() => {
    if (!basketData.length) return [];
    const binSize = 50;
    const bins = {};
    basketData.forEach((b) => {
      const pnl = Number(b.net_pnl);
      if (!Number.isFinite(pnl)) return;
      const bin = Math.floor(pnl / binSize) * binSize;
      bins[bin] = (bins[bin] || 0) + 1;
    });

    return Object.entries(bins)
      .map(([bin, count]) => ({
        range: `${bin} to ${Number(bin) + binSize}`,
        binStart: Number(bin),
        count,
      }))
      .sort((a, b) => a.binStart - b.binStart);
  }, [basketData]);

  const monthlyReturns = useMemo(() => {
    if (!basketData.length) return [];
    const map = {};
    basketData.forEach((b) => {
      const d = new Date(b.date);
      if (Number.isNaN(d.getTime())) return;
      const key = `${d.getFullYear()}-${d.getMonth()}`;
      if (!map[key]) {
        map[key] = {
          year: d.getFullYear(),
          month: d.getMonth(),
          monthName: d.toLocaleString("default", { month: "short" }),
          pnl: 0,
        };
      }
      map[key].pnl += Number(b.net_pnl) || 0;
    });
    // Sort chronologically
    return Object.values(map).sort((a, b) => {
      if (a.year !== b.year) return a.year - b.year;
      return a.month - b.month;
    });
  }, [basketData]);

  // simple performance metrics from equity curve (approx)
  const perf = useMemo(() => {
    if (!equityCurve.length) return null;
    const eq = equityCurve.map((x) => x.equity).filter(Number.isFinite);
    if (eq.length < 3) return null;

    const rets = [];
    for (let i = 1; i < eq.length; i++) {
      const r = (eq[i] - eq[i - 1]) / Math.max(1e-9, eq[i - 1]);
      if (Number.isFinite(r)) rets.push(r);
    }
    if (!rets.length) return null;

    const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
    const vol = Math.sqrt(rets.reduce((s, r) => s + (r - mean) ** 2, 0) / Math.max(1, rets.length - 1));
    const downside = Math.sqrt(
      rets.filter((r) => r < 0).reduce((s, r) => s + (r - 0) ** 2, 0) / Math.max(1, rets.filter((r) => r < 0).length)
    );

    const sharpe = vol > 0 ? mean / vol : 0;
    const sortino = downside > 0 ? mean / downside : 0;

    const start = eq[0];
    const end = eq[eq.length - 1];
    const cagr = start > 0 ? (end / start) - 1 : 0;

    // max drawdown
    let peak = eq[0];
    let maxDD = 0;
    for (const v of eq) {
      peak = Math.max(peak, v);
      maxDD = Math.min(maxDD, (v - peak) / peak);
    }
    const calmar = maxDD !== 0 ? cagr / Math.abs(maxDD) : 0;

    return {
      sharpe,
      sortino,
      cagr,
      maxDrawdown: maxDD,
      calmar,
    };
  }, [equityCurve]);

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "equity", label: "Equity" },
    { id: "distribution", label: "Distribution" },
    { id: "monthly", label: "Monthly" },
    { id: "costs", label: "Costs" },
    { id: "metrics", label: "Performance Metrics" },
  ];

  return (
    <div className="w-full max-w-7xl mx-auto p-4 bg-gray-50">
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm text-gray-500 font-medium">Backtest Analytics</div>
            <h1 className="text-3xl font-bold text-gray-900 leading-tight">
              Performance Dashboard
            </h1>
            <p className="text-gray-600 mt-2 max-w-xl">
              Equity, drawdown, distribution and execution metrics — presented in an investor-friendly format.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="inline-flex rounded-full border bg-white p-1">
              <button
                className={`px-4 py-2 rounded-full text-sm font-semibold ${view === "dashboard" ? "bg-gray-900 text-white" : "text-gray-700"
                  }`}
                onClick={() => setView("dashboard")}
              >
                Dashboard
              </button>
              <button
                className={`px-4 py-2 rounded-full text-sm font-semibold ${view === "tables" ? "bg-gray-900 text-white" : "text-gray-700"
                  }`}
                onClick={() => setView("tables")}
              >
                Tables
              </button>
            </div>

            <label className="inline-flex items-center gap-2 px-4 py-2 rounded-full border bg-white hover:bg-gray-50 cursor-pointer">
              <Upload className="w-4 h-4 text-gray-600" />
              <span className="text-sm font-semibold text-gray-800">Import/Replace CSVs</span>
              <input type="file" accept=".csv" className="hidden" onChange={() => { }} />
              {/* We keep single import button; uploads happen below in tables view */}
            </label>
          </div>
        </div>

        {view === "tables" ? (
          <div className="mt-6">
            {/* Upload cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <UploadCard
                title="Basket Summary"
                subtitle="Upload basket summary CSV"
                onUpload={(e) => handleFileUpload(e, "basket")}
                loaded={basketData.length}
              />
              <UploadCard
                title="Trade Log"
                subtitle="Upload trade log CSV"
                onUpload={(e) => handleFileUpload(e, "trade")}
                loaded={tradeData.length}
              />
              <UploadCard
                title="Equity Curve"
                subtitle="Upload equity curve CSV"
                onUpload={(e) => handleFileUpload(e, "equity")}
                loaded={equityData.length}
              />
            </div>

            {/* Tables + paging */}
            <div className="mt-6">
              <div className="inline-flex rounded-full border bg-white p-1">
                {["basket_summary", "trade_log", "equity_curve"].map((k) => (
                  <button
                    key={k}
                    className={`px-4 py-2 rounded-full text-sm font-semibold ${tab === k ? "bg-gray-900 text-white" : "text-gray-700"
                      }`}
                    onClick={() => setTab(k)}
                  >
                    {k}
                  </button>
                ))}
              </div>

              {tab === "basket_summary" ? <DataTable rows={basketData} label="basket_summary" /> : null}
              {tab === "trade_log" ? <DataTable rows={tradeData} label="trade_log" /> : null}
              {tab === "equity_curve" ? <DataTable rows={equityData} label="equity_curve" /> : null}
            </div>
          </div>
        ) : (
          <div className="mt-6">
            {/* Dashboard tabs */}
            <div className="flex flex-wrap gap-2">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-4 py-2 rounded-full border text-sm font-semibold ${tab === t.id ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-800 hover:bg-gray-50"
                    }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Overview */}
            {tab === "overview" && stats ? (
              <div className="mt-6">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                  <KpiCard
                    label="Total P&L"
                    icon={<DollarSign className="w-4 h-4" />}
                    value={`${stats.totalPnl < 0 ? "-" : ""}$${compactMoney(Math.abs(stats.totalPnl))}`}
                    sub={`${stats.totalTrades} baskets`}
                    negative={stats.totalPnl < 0}
                  />
                  <KpiCard
                    label="Win Rate"
                    icon={<TrendingUp className="w-4 h-4" />}
                    value={`${stats.winRate.toFixed(1)}%`}
                    sub={`${stats.wins}W / ${stats.losses}L`}
                  />
                  <KpiCard
                    label="Avg Duration"
                    icon={<Clock className="w-4 h-4" />}
                    value={formatDuration(stats.avgDuration)}
                    sub={`Max: ${formatDuration(stats.maxDuration)}`}
                  />
                  <KpiCard
                    label="Avg Win / Loss"
                    icon={<TrendingDown className="w-4 h-4" />}
                    value={
                      <div className="text-sm leading-tight">
                        <div className="text-green-700 font-semibold">+${compactMoney(stats.avgWin)}</div>
                        <div className="text-red-700 font-semibold">-${compactMoney(Math.abs(stats.avgLoss))}</div>
                      </div>
                    }
                    sub=""
                  />
                </div>
              </div>
            ) : null}

            {/* Equity + Drawdown */}
            {tab === "equity" ? (
              <div className="mt-6 space-y-6">
                <ChartCard
                  title="Equity Curve"
                  right={
                    <button
                      className="text-sm font-semibold px-3 py-2 rounded-lg border bg-white hover:bg-gray-50"
                      onClick={() => setEqBrush({ startIndex: 0, endIndex: Math.max(0, equityCurve.length - 1) })}
                    >
                      Reset zoom
                    </button>
                  }
                >
                  <ResponsiveContainer width="100%" height={320}>
                    <AreaChart data={equityCurve} margin={{ left: 18, right: 18, top: 10, bottom: 28 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                      <YAxis
                        tick={{ fontSize: 12 }}
                        tickFormatter={(v) => compactMoney(v)}
                        width={70}
                      />
                      <Tooltip formatter={(v) => `$${Number(v).toFixed(2)}`} />
                      <Legend />
                      <Area type="monotone" dataKey="equity" name="Equity" />
                      <Area type="monotone" dataKey="peak" name="Peak" strokeDasharray="5 5" fill="none" />
                      <Brush
                        dataKey="date"
                        startIndex={eqBrush.startIndex}
                        endIndex={eqBrush.endIndex}
                        onChange={(r) => r && setEqBrush({ startIndex: r.startIndex, endIndex: r.endIndex })}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </ChartCard>

                <ChartCard
                  title="Drawdown Curve"
                  right={
                    <button
                      className="text-sm font-semibold px-3 py-2 rounded-lg border bg-white hover:bg-gray-50"
                      onClick={() => setDdBrush({ startIndex: 0, endIndex: Math.max(0, equityCurve.length - 1) })}
                    >
                      Reset zoom
                    </button>
                  }
                >
                  <ResponsiveContainer width="100%" height={300}>
                    <AreaChart data={equityCurve} margin={{ left: 18, right: 18, top: 10, bottom: 28 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 12 }} width={70} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
                      <Tooltip formatter={(v) => `${Number(v).toFixed(2)}%`} />
                      {/* drawdown in red */}
                      <Area type="monotone" dataKey="drawdown" name="Drawdown %" stroke="#dc2626" fill="#fecaca" />
                      <Brush
                        dataKey="date"
                        startIndex={ddBrush.startIndex}
                        endIndex={ddBrush.endIndex}
                        onChange={(r) => r && setDdBrush({ startIndex: r.startIndex, endIndex: r.endIndex })}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </ChartCard>
              </div>
            ) : null}

            {/* Distribution */}
            {tab === "distribution" ? (
              <div className="mt-6">
                <ChartCard title="P&L Distribution">
                  <ResponsiveContainer width="100%" height={380}>
                    <BarChart data={pnlDistribution} margin={{ left: 18, right: 18, top: 10, bottom: 60 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="range" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={90} />
                      <YAxis tick={{ fontSize: 12 }} width={50} />
                      <Tooltip />
                      {/* Remove the black legend block by not rendering Legend */}
                      <Bar dataKey="count" name="Frequency">
                        {pnlDistribution.map((e, i) => (
                          <Cell key={i} fill={e.binStart >= 0 ? "#10b981" : "#ef4444"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </ChartCard>
              </div>
            ) : null}

            {/* Monthly heatmap (RESTORED) */}
            {tab === "monthly" ? (
              <div className="mt-6">
                <ChartCard title="Monthly Returns">
                  <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))" }}>
                    {monthlyReturns.map((m, i) => (
                      <div
                        key={i}
                        className="p-3 rounded-xl text-center text-white font-semibold"
                        style={{
                          backgroundColor:
                            m.pnl === 0
                              ? "#94a3b8" // slate-400 for zero
                              : m.pnl > 0
                                ? `rgba(16, 185, 129, ${Math.max(0.4, Math.min(Math.abs(m.pnl) / 500, 1))})`
                                : `rgba(239, 68, 68, ${Math.max(0.4, Math.min(Math.abs(m.pnl) / 500, 1))})`,
                        }}
                      >
                        <div className="text-xs opacity-90">{m.monthName} {m.year}</div>
                        <div className="text-sm mt-1">${compactMoney(m.pnl)}</div>
                      </div>
                    ))}
                    {monthlyReturns.length === 0 ? (
                      <div className="text-sm text-gray-500">No monthly data yet.</div>
                    ) : null}
                  </div>
                </ChartCard>
              </div>
            ) : null}

            {/* Costs */}
            {tab === "costs" ? (
              <div className="mt-6">
                <ChartCard title="Commission & Slippage">
                  <p className="text-sm text-gray-700">
                    If your trade CSV includes additional fields (e.g., realized commission, filled prices),
                    this section can compute realized costs and execution quality.
                  </p>
                </ChartCard>
              </div>
            ) : null}

            {/* Performance Metrics tab (ADDED) */}
            {tab === "metrics" ? (
              <div className="mt-6">
                <ChartCard title="Performance Metrics">
                  {!perf ? (
                    <div className="text-sm text-gray-500">Not enough equity data to compute metrics.</div>
                  ) : (
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                      <Metric label="Sharpe (approx)" value={perf.sharpe.toFixed(3)} />
                      <Metric label="Sortino (approx)" value={perf.sortino.toFixed(3)} />
                      <Metric label="CAGR (approx)" value={`${(perf.cagr * 100).toFixed(2)}%`} />
                      <Metric label="Max Drawdown" value={`${(perf.maxDrawdown * 100).toFixed(2)}%`} />
                      <Metric label="Calmar (approx)" value={perf.calmar.toFixed(3)} />
                    </div>
                  )}
                </ChartCard>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function UploadCard({ title, subtitle, onUpload, loaded }) {
  return (
    <div className="border rounded-2xl bg-white p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold text-gray-900">{title}</div>
          <div className="text-sm text-gray-500 mt-1">{subtitle}</div>
          <div className="text-sm text-gray-500 mt-2">{loaded ? `✓ ${loaded} rows loaded` : ""}</div>
        </div>
        <label className="cursor-pointer inline-flex items-center gap-2 px-3 py-2 rounded-xl border hover:bg-gray-50">
          <Upload className="w-4 h-4 text-gray-700" />
          <input type="file" accept=".csv" onChange={onUpload} className="hidden" />
        </label>
      </div>
    </div>
  );
}

function KpiCard({ label, value, sub, icon, negative }) {
  return (
    <div className="border rounded-2xl p-4 bg-white">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-700">{label}</div>
        <div className="text-gray-500">{icon}</div>
      </div>

      <div className={`mt-2 text-2xl font-bold ${negative ? "text-red-700" : "text-gray-900"} break-words`}>
        {value}
      </div>
      {sub ? <div className="text-sm text-gray-500 mt-1">{sub}</div> : null}
    </div>
  );
}

function ChartCard({ title, right, children }) {
  return (
    <div className="border rounded-2xl p-4 bg-white">
      <div className="flex items-center justify-between mb-3">
        <div className="font-semibold text-gray-900">{title}</div>
        {right ? <div>{right}</div> : null}
      </div>
      {children}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="border rounded-xl p-3 bg-gray-50">
      <div className="text-xs font-semibold text-gray-600">{label}</div>
      <div className="text-lg font-bold text-gray-900 mt-1">{value}</div>
    </div>
  );
}
