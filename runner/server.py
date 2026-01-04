# runner/server.py
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
import traceback
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import importlib.util

try:
    import matplotlib.pyplot as plt
    plt.switch_backend('Agg') # Force non-interactive backend
except:
    pass

# Force initialization of C-extensions
_dummy_df = pd.DataFrame({"a": [1, 2, 3]})
_dummy_np = np.array([1, 2, 3])
print(f"[SERVER] Pre-loaded Pandas {_dummy_df.shape} and Numpy {_dummy_np.shape}", flush=True)

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

# =========================
# Paths
# =========================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runner" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Setup explicit logging (Print ONLY to avoid file lock hangs)
DEBUG_FILE = Path("DEBUG_TRACE.txt")

def log_debug(msg):
    # Print to console (uvicorn captures this usually)
    print(f"[DEBUG] {msg}", flush=True)

def log_error(msg):
    print(f"[ERROR] {msg}", flush=True)




# Ensure project imports work everywhere (important)
def ensure_sys_path(extra: Optional[Path] = None) -> None:
    # Put project root first
    pr = str(PROJECT_ROOT)
    py = str(PROJECT_ROOT / "python")
    if pr not in sys.path:
        sys.path.insert(0, pr)
    if py not in sys.path:
        sys.path.insert(0, py)

    if extra is not None:
        ex = str(extra)
        if ex not in sys.path:
            sys.path.insert(0, ex)

ensure_sys_path()

# =========================
# AssetSpec compatibility
# =========================

try:
    from scripts.prototype import AssetSpec as ProjectAssetSpec  # type: ignore
except Exception:
    @dataclass(frozen=True)
    class ProjectAssetSpec:
        name: str = "EURUSD"
        symbol_id: int = 1
        tick_size: float = 0.00001
        lot_size: float = 1.0
        commission_bps: float = 0.0
        slippage_bps: float = 0.0
        spread: float = 0.0


# =========================
# FastAPI app
# =========================
app = FastAPI(title="Felix Local Runner")

# If you use Vite proxy, CORS is not required, but okay for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# In-memory state
# =========================
RUN_STATE: Dict[str, Dict[str, Any]] = {}
RUN_LOGS: Dict[str, Queue] = {}


def emit(run_id: str, event: str, payload: dict) -> None:
    q = RUN_LOGS.get(run_id)
    if q:
        q.put({"event": event, "payload": payload})


def log(run_id: str, level: str, msg: str) -> None:
    emit(run_id, "log", {"ts": time.time(), "level": level, "msg": msg})



def _load_strategy_module(strategy_path: Path, run_id: str):
    """
    Load uploaded strategy by file path.
    Critical: sys.path must include PROJECT_ROOT + PROJECT_ROOT/python + strategy folder.
    """
    ensure_sys_path(strategy_path.parent)

    mod_name = f"ui_strategy_{run_id}"
    # Clear any cached module with same name (safety)
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    spec = importlib.util.spec_from_file_location(mod_name, str(strategy_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to create import spec for strategy file")

    mod = importlib.util.module_from_spec(spec)
    # Register early to help relative imports within strategy
    sys.modules[mod_name] = mod
    
    log_debug(f"[DEBUG] Executing module {mod_name}...")
    try:
        spec.loader.exec_module(mod)
        log_debug(f"[DEBUG] Executing module finished.")
    except Exception as e:
        log_error(f"[ERROR] Module exec failed: {e}")
        raise
    return mod


def _validate_strategy(mod) -> None:
    # Required by your prototype contract + runner pipeline
    if not hasattr(mod, "STRATEGY_META"):
        raise RuntimeError("Strategy invalid: missing STRATEGY_META")

    if not hasattr(mod, "StrategyImpl"):
        raise RuntimeError("Strategy invalid: missing StrategyImpl (prototype format)")

    if not hasattr(mod, "run_pipeline"):
        raise RuntimeError("Strategy invalid: missing run_pipeline(csv_paths, run_config, asset, out_dir, log)")


# Global safe logger
SAFE_LOG_FILE = Path("server_global.log")

def safe_log(msg):
    try:
        with open(SAFE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.ctime()}] {msg}\n")
    except:
        pass

def _worker(run_id: str, workdir: Path, payload: Dict[str, Any]) -> None:
    safe_log(f"Worker START for {run_id}")
    print(f"[DEBUG] _worker executing for run_id={run_id}")
    try:
        RUN_STATE[run_id]["status"] = "running"
        print("[DEBUG] Status set to running")

        strategy_path: Path = payload["strategy_path"]
        csv_paths: List[Path] = payload["csv_paths"]
        run_config: Dict[str, Any] = payload["run_config"]
        asset: ProjectAssetSpec = payload["asset_spec"]
        
        safe_log(f"Validating strategy {strategy_path}")
        print(f"[DEBUG] Validating strategy {strategy_path}")

        log(run_id, "info", f"Strategy: {strategy_path.name}")
        log(run_id, "info", f"CSV files: {', '.join([p.name for p in csv_paths])}")
        log(run_id, "info", "Importing strategy module ...")
        
        log_debug(f"[DEBUG] sys.path before import: {sys.path}")
        try:
            mod = _load_strategy_module(strategy_path, run_id)
            log_debug(f"[DEBUG] Strategy module loaded: {mod}")
            _validate_strategy(mod)
            log_debug("[DEBUG] Strategy validated")
            safe_log("Strategy validated")
        except Exception as e:
            msg = f"Strategy load failed: {e}"
            safe_log(msg)
            log_error(f"[ERROR] {msg}")
            log(run_id, "error", msg)
            traceback.print_exc()
            raise

        out_dir = workdir / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)

        # log callback to stream into UI terminal
        def log_cb(msg: str):
            m = str(msg).rstrip("\n")
            lvl = "info"
            ml = m.lower()

            if ml.startswith("[warn]") or "warn" in ml:
                lvl = "warn"
            if ml.startswith("[error]") or "error" in ml or "traceback" in ml:
                lvl = "error"
            if "backtest finished" in ml or ml.startswith("[success]"):
                lvl = "success"

            log(run_id, lvl, m)

        log(run_id, "info", "Running run_pipeline(...) ...")
        safe_log("Calling run_pipeline")

        outputs = mod.run_pipeline(
            csv_paths=[str(p) for p in csv_paths],
            run_config=run_config,
            asset=asset,
            out_dir=str(out_dir),
            log=log_cb,
        )
        safe_log("run_pipeline returned")

        # Robustly find CSV paths (handle differences in out_dir vs workdir)
        def find_file(key, filename):
            candidates = [
                Path(outputs.get(key, "")),
                out_dir / filename,
                workdir / "outputs" / filename,
                workdir / filename
            ]
            for c in candidates:
                if c and c.name and c.exists():
                    return c
            return Path("")

        basket_path = find_file("basket_summary", "basket_summary.csv")
        trade_path = find_file("trade_log", "trade_log.csv")
        equity_path = find_file("equity_curve", "equity_curve.csv")
        
        safe_log(f"Resolved Paths:\n  Basket: {basket_path} (Exists: {basket_path.exists()})\n  Trade: {trade_path}\n  Equity: {equity_path}")
        print(f"[DEBUG] Resolved Paths:\n  Basket: {basket_path} (Exists: {basket_path.exists()})\n  Trade: {trade_path}\n  Equity: {equity_path}", flush=True)

        basket_csv = basket_path.read_text(errors="ignore") if basket_path.exists() else ""
        trade_csv = trade_path.read_text(errors="ignore") if trade_path.exists() else ""
        equity_csv = equity_path.read_text(errors="ignore") if equity_path.exists() else ""
        
        safe_log(f"CSV Sizes -> Basket: {len(basket_csv)}, Trade: {len(trade_csv)}, Equity: {len(equity_csv)}")
        print(f"[DEBUG] CSV Sizes -> Basket: {len(basket_csv)}, Trade: {len(trade_csv)}, Equity: {len(equity_csv)}", flush=True)

        RUN_STATE[run_id]["status"] = "done"
        RUN_STATE[run_id]["result"] = {
            "basketCsv": basket_csv,
            "tradeCsv": trade_csv,
            "equityCsv": equity_csv,
            "meta": {
                "outputs_dir": str(out_dir),
                "files": {
                    "basket_summary": str(basket_path),
                    "trade_log": str(trade_path),
                    "equity_curve": str(equity_path),
                },
            },
        }
        log(run_id, "success", "Backtest finished.")
        safe_log("Worker FINISHED SUCCESS")

    except Exception as e:
        RUN_STATE[run_id]["status"] = "error"
        RUN_STATE[run_id]["error"] = str(e)
        
        safe_log(f"WORKER EXCEPTION: {e}")
        tb = traceback.format_exc()
        safe_log(tb)

        # Stream both summary + full traceback
        log_error(f"[ERROR] RUNNER CRASH: {e}")
        log_error(tb)
        log(run_id, "error", str(e))
        log(run_id, "error", tb)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/run/start")
async def start_run(
    run_config_json: str = Form(...),
    strategy: UploadFile = File(...),
    csv_files: List[UploadFile] = File(...),
):
    run_id = uuid.uuid4().hex
    workdir = RUNS_DIR / run_id
    workdir.mkdir(parents=True, exist_ok=True)

    RUN_LOGS[run_id] = Queue()
    RUN_STATE[run_id] = {"status": "queued", "error": "", "result": None}

    # Save uploaded strategy
    strategy_content = await strategy.read()
    
    # [AUTO-FIX] Sanitize incompatible imports for Windows/Threads
    try:
        text = strategy_content.decode("utf-8")
        if "from felix.strategy.base import Strategy" in text:
            log_debug("[WARN] Auto-fixing strategy: Disabling felix import")
            text = text.replace("from felix.strategy.base import Strategy", "# [SERVER-FIX] from felix.strategy.base import Strategy")
            # Also ensure we define the fallback class if not present (heuristic)
            if "class Strategy:" not in text and "class Strategy" not in text:
                 # This is a bit risky if they didn't have the fallback, but the prototype usually does.
                 pass 
        strategy_path = workdir / strategy.filename
        strategy_path.write_text(text, encoding="utf-8")
    except Exception as e:
        log_error(f"Failed to sanitize strategy: {e}")
        # Fallback to raw write
        strategy_path = workdir / strategy.filename
        strategy_path.write_bytes(strategy_content)


    # Save uploaded CSVs
    csv_paths: List[Path] = []
    for f in csv_files:
        p = workdir / f.filename
        p.write_bytes(await f.read())
        csv_paths.append(p)

    # Parse config
    try:
        run_config = json.loads(run_config_json)
    except Exception as e:
        RUN_STATE[run_id]["status"] = "error"
        RUN_STATE[run_id]["error"] = f"Invalid run_config_json: {e}"
        return JSONResponse({"run_id": run_id, "error": RUN_STATE[run_id]["error"]}, status_code=400)

    # Build asset spec (you can expand later from backtest_config.json)
    asset = ProjectAssetSpec(
        name=str(run_config.get("asset", "EURUSD")),
        symbol_id=int(run_config.get("symbol_id", 1)),
        tick_size=float(run_config.get("tick_size", 0.00001)),
        lot_size=float(run_config.get("lot_size", 1.0)),
        commission_bps=float(run_config.get("commission_bps", 0.0)),
        slippage_bps=float(run_config.get("slippage_bps", 0.0)),
        spread=float(run_config.get("spread", 0.0)),
    )

    payload = {
        "strategy_path": strategy_path,
        "csv_paths": csv_paths,
        "run_config": run_config,
        "asset_spec": asset,
    }

    t = threading.Thread(target=_worker, args=(run_id, workdir, payload), daemon=True)
    t.start()

    return {"run_id": run_id}


@app.get("/api/run/status")
def run_status(run_id: str):
    st = RUN_STATE.get(run_id)
    if not st:
        return JSONResponse({"error": "unknown run_id"}, status_code=404)
    return {"status": st["status"], "error": st.get("error", "")}


@app.get("/api/run/result")
def run_result(run_id: str):
    st = RUN_STATE.get(run_id)
    if not st:
        return JSONResponse({"error": "unknown run_id"}, status_code=404)
    if st["status"] != "done":
        return JSONResponse({"error": f"run not done (status={st['status']})"}, status_code=400)
    return st["result"]


@app.get("/api/run/stream")
def run_stream(run_id: str):
    q = RUN_LOGS.get(run_id)
    if not q:
        return JSONResponse({"error": "unknown run_id"}, status_code=404)

    def event_gen():
        while True:
            try:
                item = q.get(timeout=0.5)
                yield f"data: {json.dumps(item)}\n\n"
            except Empty:
                st = RUN_STATE.get(run_id, {})
                if st.get("status") in ("done", "error"):
                    break
                continue

    return StreamingResponse(event_gen(), media_type="text/event-stream")
