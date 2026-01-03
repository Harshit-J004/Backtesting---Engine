import React, { useEffect, useMemo, useRef, useState } from "react";

function badge(level) {
  const base =
    "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold tracking-wide";
  switch (level) {
    case "error":
      return `${base} bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30`;
    case "warn":
      return `${base} bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30`;
    case "success":
      return `${base} bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/30`;
    default:
      return `${base} bg-slate-500/15 text-slate-200 ring-1 ring-slate-500/30`;
  }
}

// If something non-string gets logged, normalize it safely.
function safeText(x) {
  if (x == null) return "";
  if (typeof x === "string") return x;

  // Prevent className garbage / objects from flooding UI
  if (typeof x === "object") {
    // If it looks like a React element, don’t dump it
    if (x.$$typeof) return "[log: non-text payload]";
    try {
      const s = JSON.stringify(x);
      // Avoid huge dumps
      return s.length > 800 ? s.slice(0, 800) + "…[truncated]" : s;
    } catch {
      return String(x);
    }
  }

  return String(x);
}

export default function TerminalPanel({
  title = "Terminal",
  logs = [],
  disabled = false,
  onCommand,
}) {
  const [cmd, setCmd] = useState("");
  const [q, setQ] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const [history, setHistory] = useState([]);
  const [histIdx, setHistIdx] = useState(-1);
  const boxRef = useRef(null);

  const formatted = useMemo(() => {
    const items = logs.map((l) => ({
      ...l,
      t: new Date(l.ts).toLocaleTimeString(),
      msg: safeText(l.msg), // ✅ sanitize displayed text
    }));

    if (!q.trim()) return items;
    const qq = q.toLowerCase();
    return items.filter((l) => `${l.level} ${l.msg}`.toLowerCase().includes(qq));
  }, [logs, q]);

  useEffect(() => {
    if (!autoScroll) return;
    if (!boxRef.current) return;
    boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [formatted.length, autoScroll]);

  const submit = () => {
    const v = cmd.trim();
    if (!v) return;

    onCommand?.(v);

    setHistory((h) => [v, ...h].slice(0, 30));
    setHistIdx(-1);
    setCmd("");
  };

  const quick = (c) => {
    if (disabled) return;
    onCommand?.(c);
    setHistory((h) => [c, ...h].slice(0, 30));
    setHistIdx(-1);
    setCmd("");
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="flex flex-col gap-2 border-b border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-900">{title}</div>
          {/* ✅ Removed the “Commands: …” text you don’t want */}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => quick("help")}
            className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            help
          </button>
          <button
            onClick={() => quick("show")}
            className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            show
          </button>
          <button
            onClick={() => quick("trades")}
            className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            trades
          </button>
          <button
            onClick={() => quick("run")}
            className="rounded-full bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            disabled={disabled}
          >
            run
          </button>

          <div className="ml-0 flex items-center gap-2 sm:ml-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search logs…"
              className="w-40 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs outline-none focus:ring-2 focus:ring-slate-200"
            />
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              Auto-scroll
            </label>
          </div>
        </div>
      </div>

      {/* Log Body */}
      <div
        ref={boxRef}
        className="h-80 overflow-auto bg-gradient-to-b from-slate-950 to-slate-900 p-3 font-mono text-[13px] text-slate-100"
      >
        {formatted.length === 0 ? (
          <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-slate-300">
            No logs yet. Run a backtest to start.
          </div>
        ) : (
          formatted.map((l, idx) => (
            <div
              key={idx}
              className="mb-1.5 grid grid-cols-[92px_72px_1fr] items-start gap-3"
            >
              <span className="text-slate-400">{l.t}</span>
              <span className={badge(l.level)}>{l.level}</span>
              <span className="whitespace-pre-wrap break-words leading-relaxed">
                {l.msg}
              </span>
            </div>
          ))
        )}
      </div>

      {/* Input */}
      <div className="flex gap-2 border-t border-slate-200 bg-white p-3">
        <div className="flex-1">
          <input
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-sm text-slate-900 outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
            placeholder='Type a command (e.g., set sl=5 tp=6 rsi_len=22) and press Enter'
            value={cmd}
            onChange={(e) => setCmd(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();

              if (e.key === "ArrowUp") {
                e.preventDefault();
                if (!history.length) return;
                const nextIdx = Math.min(history.length - 1, histIdx + 1);
                setHistIdx(nextIdx);
                setCmd(history[nextIdx] || "");
              }
              if (e.key === "ArrowDown") {
                e.preventDefault();
                if (!history.length) return;
                const nextIdx = Math.max(-1, histIdx - 1);
                setHistIdx(nextIdx);
                setCmd(nextIdx === -1 ? "" : history[nextIdx] || "");
              }
            }}
            disabled={disabled}
          />

          {history.length ? (
            <div className="mt-1 text-[11px] text-slate-500">
              Tip: Use ↑/↓ to navigate recent commands.
            </div>
          ) : null}
        </div>

        <button
          className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          onClick={submit}
          disabled={disabled}
        >
          Send
        </button>
      </div>
    </div>
  );
}
