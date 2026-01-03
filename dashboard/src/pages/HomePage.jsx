import React, { useMemo } from "react";
import { useRun } from "../state/RunContext";

function numberOr(v, fallback) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export default function HomePage() {
  const {
    strategyFile,
    setStrategyFile,
    csvFiles,
    setCsvFiles,
    config,
    setConfig,
    startRun,
    status,
    error,
  } = useRun();

  const canRun = useMemo(() => {
    return !!strategyFile && csvFiles.length > 0 && status !== "running";
  }, [strategyFile, csvFiles.length, status]);

  const set = (patch) => setConfig((c) => ({ ...c, ...patch }));

  return (
    <div className="w-full">
      {/* Hero */}
      <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-xs font-medium text-slate-500">Strategy Backtesting</div>
            <h1 className="mt-1 text-2xl sm:text-3xl font-semibold tracking-tight text-slate-900">
              Felix Strategy Workspace
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-600">
              Upload a strategy and market data, configure risk and execution assumptions, then run a full backtest with exportable analytics.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div className={`rounded-full px-3 py-1 text-xs font-medium ${
              status === "running" ? "bg-amber-50 text-amber-800 border border-amber-200"
              : status === "done" ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
              : status === "error" ? "bg-rose-50 text-rose-800 border border-rose-200"
              : "bg-slate-50 text-slate-700 border border-slate-200"
            }`}>
              {status === "running" ? "Running" : status === "done" ? "Ready" : status === "error" ? "Error" : "Idle"}
            </div>
          </div>
        </div>
      </div>

      {error ? (
        <div className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-rose-800">
          {error}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Inputs */}
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 text-sm font-semibold text-slate-900">Inputs</div>

          <label className="block mb-4">
            <div className="text-sm font-medium text-slate-700 mb-2">Strategy File (.py)</div>
            <input
              type="file"
              accept=".py"
              onChange={(e) => setStrategyFile(e.target.files?.[0] || null)}
              className="block w-full text-sm"
            />
            <div className="text-xs text-slate-500 mt-1">
              Strategy must follow the <span className="font-mono">prototype.py</span> contract.
            </div>
            {strategyFile ? (
              <div className="text-xs mt-2 text-emerald-700">✓ {strategyFile.name}</div>
            ) : null}
          </label>

          <label className="block mb-4">
            <div className="text-sm font-medium text-slate-700 mb-2">Market Type</div>
            <select
              value={config.market}
              onChange={(e) => set({ market: e.target.value })}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-slate-200"
            >
              <option value="FOREX">Forex</option>
              <option value="CRYPTO">Crypto</option>
              <option value="EQUITY">Equity</option>
            </select>
          </label>

          <label className="block mb-4">
            <div className="text-sm font-medium text-slate-700 mb-2">Data Horizon (years)</div>
            <input
              type="number"
              min={1}
              max={50}
              value={config.years}
              onChange={(e) => set({ years: numberOr(e.target.value, 2) })}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="block">
            <div className="text-sm font-medium text-slate-700 mb-2">Market Data CSV</div>
            <input
              type="file"
              accept=".csv"
              multiple
              onChange={(e) => setCsvFiles(Array.from(e.target.files || []))}
              className="block w-full text-sm"
            />
            <div className="text-xs text-slate-500 mt-1">
              Large files are supported; conversion and parsing occurs inside the runner.
            </div>
            {csvFiles.length ? (
              <div className="text-xs mt-2 text-emerald-700">✓ {csvFiles.length} file(s) selected</div>
            ) : null}
          </label>
        </div>

        {/* Parameters */}
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 text-sm font-semibold text-slate-900">Parameters</div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Investment Capital" type="number" value={config.initialCapital}
              onChange={(v) => set({ initialCapital: numberOr(v, 10000) })} />
            <Field label="Max Trades / Day" type="number" value={config.maxTradesPerDay}
              onChange={(v) => set({ maxTradesPerDay: numberOr(v, 999) })} />
            <Field label="Stop Loss (%)" type="number" value={config.stopLossPct}
              onChange={(v) => set({ stopLossPct: numberOr(v, 2) })} />
            <Field label="Target Profit (%)" type="number" value={config.targetProfitPct}
              onChange={(v) => set({ targetProfitPct: numberOr(v, 3) })} />
            <Field label="Threshold Balance" type="number" value={config.thresholdBalance}
              onChange={(v) => set({ thresholdBalance: numberOr(v, 0) })} />
            <Field label="Commission (%)" type="number" value={config.commissionBps}
              onChange={(v) => set({ commissionBps: numberOr(v, 0) })} />
            <Field label="Slippage (bps)" type="number" value={config.slippageBps}
              onChange={(v) => set({ slippageBps: numberOr(v, 0) })} />
          </div>

          <div className="mt-4">
            <div className="text-sm font-medium text-slate-700 mb-2">Strategy Params (JSON)</div>
            <textarea
              value={config.extraParamsJson}
              onChange={(e) => set({ extraParamsJson: e.target.value })}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 font-mono text-sm h-28 focus:ring-2 focus:ring-slate-200"
              placeholder='{"rsi_len": 22}'
            />
            <div className="text-xs text-slate-500 mt-1">
              Passed into <span className="font-mono">run_config.params</span>.
            </div>
          </div>

          <div className="mt-6 flex items-center justify-between gap-3">
            <div className="text-xs text-slate-500">
              Run will open Results with live logs and auto-loaded outputs.
            </div>
            <button
              onClick={startRun}
              disabled={!canRun}
              className="rounded-xl bg-slate-900 px-5 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {status === "running" ? "Running…" : "Run Backtest"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, type, value, onChange }) {
  return (
    <label className="block">
      <div className="text-sm font-medium text-slate-700 mb-2">{label}</div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:ring-2 focus:ring-slate-200"
      />
    </label>
  );
}
