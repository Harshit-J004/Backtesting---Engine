// src/pages/ResultsPage.jsx
import React, { useMemo, useState } from "react";
import { useRun } from "../state/RunContext";
import TerminalPanel from "../components/TerminalPanel";
import TradingBacktestAnalysis from "../components/TradingBacktestAnalysis";

function DataTable({ title, rows, pageSize = 25 }) {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const cols = useMemo(() => Object.keys(rows?.[0] || {}), [rows]);

  const filtered = useMemo(() => {
    const query = (q || "").toLowerCase().trim();
    if (!query) return rows || [];
    return (rows || []).filter((r) =>
      cols.some((c) => String(r[c] ?? "").toLowerCase().includes(query))
    );
  }, [rows, q, cols]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageClamped = Math.min(page, totalPages);
  const start = (pageClamped - 1) * pageSize;
  const pageRows = filtered.slice(start, start + pageSize);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="text-lg font-semibold text-gray-900">{title}</div>
          <div className="text-sm text-gray-500">{filtered.length} rows</div>
        </div>

        <div className="flex items-center gap-2">
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            className="border rounded-lg px-3 py-2 text-sm w-64"
            placeholder="Search..."
          />
        </div>
      </div>

      <div className="overflow-auto border rounded-xl">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {cols.slice(0, 12).map((c) => (
                <th key={c} className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r, i) => (
              <tr key={i} className="border-t">
                {cols.slice(0, 12).map((c) => (
                  <td key={c} className="px-3 py-2 whitespace-nowrap">
                    {String(r[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
            {pageRows.length === 0 ? (
              <tr>
                <td colSpan={cols.length || 1} className="px-3 py-6 text-center text-gray-500">
                  No rows to display.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-3 text-sm text-gray-600">
        <div>
          Page {pageClamped} / {totalPages}
        </div>
        <div className="flex gap-2">
          <button
            className="px-3 py-2 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={pageClamped <= 1}
          >
            Prev
          </button>
          <button
            className="px-3 py-2 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={pageClamped >= totalPages}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ResultsPage() {
  const { logs, appendLog, outputs, status, error, resetRun, applyTerminalCommand, tables } = useRun();

  const onCommand = (cmd) => {
    appendLog("info", `> ${cmd}`);
    applyTerminalCommand(cmd);
  };

  return (
    <div className="w-full max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Strategy Results</h1>
          <p className="text-gray-600 mt-1">Backtest logs and performance analytics.</p>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => (window.location.hash = "#/")}
            className="px-4 py-2 rounded-lg border bg-white hover:bg-gray-50"
          >
            ← Back
          </button>
          <button
            onClick={resetRun}
            className="px-4 py-2 rounded-lg border bg-white hover:bg-gray-50"
          >
            Reset Run
          </button>
        </div>
      </div>

      {error ? (
        <div className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-4 mb-4">
          {error}
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left */}
        <div className="space-y-6">
          <TerminalPanel
            title="Terminal"
            logs={logs}
            disabled={status === "running"}
            onCommand={onCommand}
            commandHint="Commands: help, show, trades, set key=value, run"
          />

          {/* Trades table (from trade_log.csv) */}
          <DataTable title="Trades" rows={tables.trades || []} pageSize={25} />
        </div>

        {/* Right */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-2">
          <TradingBacktestAnalysis preloadedCsv={outputs || null} />
        </div>
      </div>
    </div>
  );
}
