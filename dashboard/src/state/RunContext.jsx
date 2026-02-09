// src/state/RunContext.jsx
import React, { createContext, useContext, useMemo, useState } from "react";
import { runBacktest } from "../services/engineAdapter";

const RunContext = createContext(null);

function parseValue(s) {
  if (s === "true") return true;
  if (s === "false") return false;
  const n = Number(s);
  if (!Number.isNaN(n)) return n;
  return s;
}

function safeJson(s, fallback) {
  try { return JSON.parse(s || ""); } catch { return fallback; }
}

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

export function RunProvider({ children, navigate }) {
  const [strategyFile, setStrategyFile] = useState(null);
  const [csvFiles, setCsvFiles] = useState([]);
  const [config, setConfig] = useState({
    market: "FOREX",
    years: 2,
    initialCapital: 10000,
    stopLossPct: 2,
    targetProfitPct: 3,
    thresholdBalance: 0,
    maxTradesPerDay: 999,
    commissionBps: 0,
    slippageBps: 0,
    extraParamsJson: "{}",
  });

  const [status, setStatus] = useState("idle"); // idle | running | done | error
  const [error, setError] = useState("");
  const [logs, setLogs] = useState([]);
  const [outputs, setOutputs] = useState(null);

  // Parsed tables for UI + terminal commands
  const [tables, setTables] = useState({
    basket: [],
    trades: [],
    equity: [],
  });

  const appendLog = (level, msg) => {
    setLogs((prev) => [...prev, { ts: Date.now(), level, msg }]);
  };

  const resetRun = () => {
    setStatus("idle");
    setError("");
    setLogs([]);
    setOutputs(null);
    setTables({ basket: [], trades: [], equity: [] });
  };

  const startRun = async () => {
    setError("");
    setOutputs(null);
    setStatus("running");
    setLogs([]);

    if (navigate) navigate("results");

    try {
      await runBacktest({
        strategyFile,
        csvFiles,
        config,
        onLog: (level, msg) => appendLog(level, msg),
        onOutputs: (out) => {
          setOutputs(out);

          const tradeRows = parseCsvText(out?.tradeCsv || "");
          const basketRows = parseCsvText(out?.basketCsv || "");
          const equityRows = parseCsvText(out?.equityCsv || "");

          setTables({
            trades: tradeRows,
            basket: basketRows,
            equity: equityRows,
          });

          appendLog("success", `Outputs loaded. Trades parsed: ${tradeRows.length}`);
        },
      });

      setStatus("done");
      appendLog("success", "Backtest finished.");
    } catch (e) {
      const msg = e?.message || String(e);
      setError(msg);
      setStatus("error");
      appendLog("error", msg);
    }
  };

  const applyTerminalCommand = (cmdRaw) => {
    const cmd = (cmdRaw || "").trim();
    if (!cmd) return;

    if (cmd === "help") {
      appendLog("info", "Commands:");
      appendLog("info", "  help");
      appendLog("info", "  show");
      appendLog("info", "  trades   (prints last 10 trade_log rows)");
      appendLog("info", "  set key=value key2=value2 ...   (auto reruns)");
      appendLog("info", "Aliases: sl, stoploss, tp, target, rsi_len, commission_bps, slippage_bps");
      return;
    }

    if (cmd === "show") {
      appendLog("info", `initialCapital=${config.initialCapital}`);
      appendLog("info", `stopLossPct=${config.stopLossPct}`);
      appendLog("info", `targetProfitPct=${config.targetProfitPct}`);
      appendLog("info", `commissionBps=${config.commissionBps}`);
      appendLog("info", `slippageBps=${config.slippageBps}`);
      appendLog("info", `extraParamsJson=${config.extraParamsJson}`);
      return;
    }

    if (cmd === "trades") {
      const rows = tables.trades || [];
      if (!rows.length) {
        appendLog("warn", "No trades available yet.");
        return;
      }

      const sample = rows[0] || {};
      const keys = Object.keys(sample);

      // Prefer a “nice” subset if available, otherwise show first 6 cols
      const preferred = [
        "date", "time", "basket_id", "trade_num",
        "side", "qty", "size", "lot_size",
        "entry_price", "exit_price", "net_pnl", "pnl",
        "slippage_pips",
      ].filter((k) => keys.includes(k));

      const showKeys = preferred.length ? preferred : keys.slice(0, 6);

      appendLog("info", `Showing last 10 trades (columns: ${showKeys.join(", ")}):`);
      const last = rows.slice(-10);
      last.forEach((r, i) => {
        const line = showKeys.map((k) => `${k}=${r[k] ?? "-"}`).join(" | ");
        appendLog("info", `${i + 1}) ${line}`);
      });
      return;
    }

    // run
    if (cmd === "run") {
      startRun();
      return;
    }

    // set key=value ...
    if (cmd.startsWith("set ")) {
      const args = cmd.slice(4).trim();
      const parts = args.split(/[ ,]+/).filter(Boolean);

      let paramsObj = safeJson(config.extraParamsJson || "{}", {});
      const patchConfig = {};
      const patchParams = {};

      for (const p of parts) {
        const [kRaw, vRaw] = p.split("=");
        if (!kRaw || vRaw == null) continue;
        const k = kRaw.trim().toLowerCase();
        const v = parseValue(vRaw.trim());

        // top-level config aliases
        if (["initial_capital", "capital", "deposit"].includes(k)) patchConfig.initialCapital = Number(v);

        else if (["sl", "stoploss", "stop_loss", "stop_loss_pct", "stoplosspct"].includes(k))
          patchConfig.stopLossPct = Number(v);

        else if (["tp", "target", "target_profit", "target_profit_pct", "targetprofitpct"].includes(k))
          patchConfig.targetProfitPct = Number(v);

        else if (["commission_bps", "commission"].includes(k)) patchConfig.commissionBps = Number(v);
        else if (["slippage_bps", "slippage"].includes(k)) patchConfig.slippageBps = Number(v);

        else if (k === "years") patchConfig.years = Number(v);
        else if (k === "market") patchConfig.market = String(v).toUpperCase();

        // everything else goes into strategy params
        else patchParams[k] = v;
      }

      const nextParams = { ...(paramsObj || {}), ...patchParams };
      patchConfig.extraParamsJson = JSON.stringify(nextParams);

      setConfig((c) => ({ ...c, ...patchConfig }));
      appendLog("success", `Applied: ${Object.keys(patchConfig).join(", ") || "params"}`);

      // REQUIRED: rerun automatically after changing params
      if (status !== "running") {
        appendLog("info", "Re-running with updated parameters...");
        startRun();
      }
      return;
    }

    appendLog("warn", "Unknown command. Type: help");
  };

  const value = useMemo(
    () => ({
      strategyFile,
      setStrategyFile,
      csvFiles,
      setCsvFiles,
      config,
      setConfig,
      status,
      error,
      logs,
      outputs,
      tables,
      appendLog,
      resetRun,
      startRun,
      applyTerminalCommand,
    }),
    [strategyFile, csvFiles, config, status, error, logs, outputs, tables]
  );

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>;
}

export function useRun() {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error("useRun must be used within RunProvider");
  return ctx;
}
