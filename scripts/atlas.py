"""One-command launcher for the full ATLAS stack (no Docker required).

    python scripts/atlas.py up        # postgres + temporal + migrations + API + worker + web
    python scripts/atlas.py down      # stop everything started by `up`
    python scripts/atlas.py status
    python scripts/atlas.py demo      # reset + run simulated Day 1-3 through the running API

Logs: logs/*.log    PIDs: .data/pids.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devstack  # noqa: E402

ROOT = devstack.ROOT
LOGS = ROOT / "logs"
PIDS = devstack.DATA / "pids.json"
PY = sys.executable
WEB = ROOT / "apps" / "web"
API_URL = "http://127.0.0.1:8000"
WEB_URL = "http://127.0.0.1:3000"


def _spawn(name: str, cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> int:
    LOGS.mkdir(exist_ok=True)
    kwargs: dict = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": open(LOGS / f"{name}.log", "ab"),
                    "stderr": subprocess.STDOUT, "env": {**os.environ, "PYTHONUTF8": "1", **(env or {})}}
    if devstack.IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # own hidden console: immune to our console's Ctrl+C/close
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs).pid


def _wait_http(url: str, label: str, timeout: float = 120) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 - local URL
                if r.status < 500:
                    print(f"[ok] {label}: {url}")
                    return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise SystemExit(f"[fail] {label} not reachable at {url} - see logs/")


def _npx() -> str:
    return "npx.cmd" if devstack.IS_WIN else "npx"


def up() -> None:
    devstack.postgres_up()
    devstack.temporal_up()
    print("[..] applying migrations")
    subprocess.run([PY, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    pids: dict[str, int] = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    if not devstack.port_open(8000):
        pids["api"] = _spawn("api", [PY, "-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8000"], ROOT)
    _wait_http(f"{API_URL}/health", "API")
    pids["worker"] = pids.get("worker") or _spawn("worker", [PY, "-m", "workers.worker"], ROOT)
    if not devstack.port_open(3000):
        if not (WEB / ".next" / "BUILD_ID").exists():
            print("[..] building web app (first run)")
            subprocess.run([_npx(), "next", "build"], cwd=WEB, check=True, env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1"})
        pids["web"] = _spawn("web", [_npx(), "next", "start", "-p", "3000", "-H", "127.0.0.1"], WEB, {"NEXT_TELEMETRY_DISABLED": "1"})
    PIDS.write_text(json.dumps(pids))
    _wait_http(WEB_URL, "Web")
    time.sleep(2)
    print(f"\nATLAS is running:\n  Web         {WEB_URL}\n  API         {API_URL}\n  API docs    {API_URL}/docs\n"
          f"  Temporal UI http://127.0.0.1:{devstack.TEMPORAL_UI_PORT}\n")


def down() -> None:
    pids = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    for name, pid in pids.items():
        if devstack.IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            try:
                os.killpg(pid, 15)
            except OSError:
                pass
        print(f"[ok] stopped {name} ({pid})")
    PIDS.unlink(missing_ok=True)
    devstack.down()


def status() -> None:
    devstack.status()
    for name, port in (("api", 8000), ("web", 3000)):
        print(f"{name} :{port}  {'UP' if devstack.port_open(port) else 'DOWN'}")


def demo() -> None:
    def call(path: str, method: str = "POST") -> dict:
        req = urllib.request.Request(f"{API_URL}{path}", method=method)
        with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310 - local URL
            return json.loads(r.read())

    print(call("/api/v1/demo/reset"))
    for day in (1, 2, 3):
        res = call(f"/api/v1/demo/run-day/{day}?wait=true")
        print(f"day {day}: {res}")
    d = call("/api/v1/dashboard", "GET")
    print(json.dumps({"counts": d["counts"], "compliance": d["compliance"], "languages": d["articles_by_language"]}, indent=2))


if __name__ == "__main__":
    {"up": up, "down": down, "status": status, "demo": demo}.get(sys.argv[1] if len(sys.argv) > 1 else "status", status)()
