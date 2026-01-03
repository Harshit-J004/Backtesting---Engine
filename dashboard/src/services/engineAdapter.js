// src/services/engineAdapter.js

export async function runBacktest({ strategyFile, csvFiles, config, onLog, onOutputs }) {
  if (!strategyFile) throw new Error("Please upload a strategy .py file.");
  if (!csvFiles || csvFiles.length === 0) throw new Error("Please upload at least one CSV data file.");

  // extra params from JSON
  const paramsFromJson = safeJson(config.extraParamsJson, {});

  // IMPORTANT: map UI SL/TP into what rsi_eurusd_prototype.py actually uses:
  // - tp_rr
  // - trailing_stop
  const slPct = numberOr(config.stopLossPct, null);
  const tpPct = numberOr(config.targetProfitPct, null);

  const derivedParams = {};
  if (slPct != null && tpPct != null && slPct > 0) {
    derivedParams.tp_rr = tpPct / slPct; // RR multiple
  }
  if (slPct != null && slPct > 0) {
    derivedParams.trailing_stop = Math.min(0.2, slPct / 100); // fraction, capped to strategy schema
  }

  const mergedParams = {
    ...paramsFromJson,
    ...derivedParams,
  };

  // Commission/slippage in UI are in bps => convert to rate
  const commissionRate = numberOr(config.commissionBps, 0) / 10000;
  const slippageBps = numberOr(config.slippageBps, 0); // keep as bps if your runner expects bps

  const runConfig = {
    market: config.market || "FOREX",
    years: numberOr(config.years, 2),

    initial_capital: numberOr(config.initialCapital, 10000),

    // If your runner uses commission_rate as fraction:
    commission_rate: commissionRate,

    // If your runner uses execution_overrides:
    execution_overrides: {
      slippage_bps: slippageBps,
      commission_bps: numberOr(config.commissionBps, 0),
    },

    // strategy params
    params: mergedParams,
  };

  const fd = new FormData();
  fd.append("run_config_json", JSON.stringify(runConfig));
  fd.append("strategy", strategyFile);
  csvFiles.forEach((f) => fd.append("csv_files", f));

  onLog?.("info", "Submitting run...");
  const res = await fetch("/api/run/start", { method: "POST", body: fd });
  if (!res.ok) throw new Error(`Runner start failed: ${res.status}`);
  const { run_id } = await res.json();

  onLog?.("info", `Run ID: ${run_id}`);
  onLog?.("info", "Streaming logs...");

  // SSE logs
  const es = new EventSource(`/api/run/stream?run_id=${encodeURIComponent(run_id)}`);
  es.onmessage = (ev) => {
    try {
      const j = JSON.parse(ev.data);
      onLog?.(j.level || "info", j.msg || "");
    } catch {}
  };

  // poll status until done
  while (true) {
    await sleep(400);
    const stRes = await fetch(`/api/run/status?run_id=${encodeURIComponent(run_id)}`);
    const st = await stRes.json();

    if (st.status === "done") {
      es.close();
      onLog?.("success", "Runner completed. Fetching results...");

      const rRes = await fetch(`/api/run/result?run_id=${encodeURIComponent(run_id)}`);
      const result = await rRes.json();

      onOutputs?.({
        basketCsv: result.basketCsv || "",
        tradeCsv: result.tradeCsv || "",
        equityCsv: result.equityCsv || "",
      });

      onLog?.("success", "Outputs loaded.");
      return;
    }

    if (st.status === "error") {
      es.close();
      throw new Error(st.error || "Runner failed");
    }
  }
}

function safeJson(s, fallback) {
  try {
    return JSON.parse(s || "");
  } catch {
    return fallback;
  }
}

function numberOr(v, fallback) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
