"""ATLAS local dev-stack manager (no Docker / no admin rights required).

Starts project-local infrastructure as detached background processes:

* PostgreSQL 16 + pgvector  -> bundled binaries from the ``pgserver`` wheel
* Temporal dev server       -> ``temporal`` CLI binary (downloaded to .data/bin)

Usage::

    python scripts/devstack.py up        # start postgres + temporal
    python scripts/devstack.py down      # stop them
    python scripts/devstack.py status

In environments with Docker available, ``infra/docker-compose.yml`` is the
equivalent containerised stack.
"""

from __future__ import annotations

import io
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data"
PGDATA = DATA / "postgres"
BIN = DATA / "bin"
PG_PORT = int(os.environ.get("ATLAS_PG_PORT", "5433"))
TEMPORAL_PORT = int(os.environ.get("ATLAS_TEMPORAL_PORT", "7233"))
TEMPORAL_UI_PORT = int(os.environ.get("ATLAS_TEMPORAL_UI_PORT", "8233"))
TEMPORAL_VERSION = "1.9.1"
IS_WIN = platform.system() == "Windows"
EXE = ".exe" if IS_WIN else ""


def pg_bin(name: str) -> Path:
    import pgserver  # noqa: PLC0415

    return Path(pgserver.__file__).parent / "pginstall" / "bin" / f"{name}{EXE}"


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def detached(cmd: list[str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": open(log, "ab"), "stderr": subprocess.STDOUT}
    if IS_WIN:
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # own hidden console: immune to our console's Ctrl+C/close
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, cwd=ROOT, **kwargs)


def wait_port(port: int, label: str, timeout: float = 60) -> None:
    start = time.time()
    while time.time() - start < timeout:
        if port_open(port):
            print(f"[ok] {label} listening on 127.0.0.1:{port}")
            return
        time.sleep(0.5)
    raise SystemExit(f"[fail] {label} did not open port {port} within {timeout}s")


def postgres_up() -> None:
    if port_open(PG_PORT):
        print(f"[ok] postgres already on :{PG_PORT}")
        wait_pg_ready()
        ensure_databases()
        return
    if not (PGDATA / "PG_VERSION").exists():
        PGDATA.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(pg_bin("initdb")), "-D", str(PGDATA), "-U", "atlas", "--auth=trust", "-E", "UTF8", "--locale=C"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    # Run the postmaster directly (not pg_ctl) so it is fully detached from this console.
    detached(
        [str(pg_bin("postgres")), "-D", str(PGDATA), "-p", str(PG_PORT), "-h", "127.0.0.1"],
        DATA / "postgres.log",
    )
    wait_port(PG_PORT, "postgres")
    wait_pg_ready()
    ensure_databases()


def wait_pg_ready(timeout: float = 60) -> None:
    """Port open != ready (recovery may still be running). Poll pg_isready."""
    start = time.time()
    while time.time() - start < timeout:
        ok = subprocess.run([str(pg_bin("pg_isready")), "-h", "127.0.0.1", "-p", str(PG_PORT), "-U", "atlas", "-d", "postgres"], capture_output=True)
        if ok.returncode == 0:
            return
        time.sleep(0.5)
    raise SystemExit("[fail] postgres did not become ready")


def ensure_databases() -> None:
    for db in ("atlas", "atlas_test"):
        exists = subprocess.run(
            [str(pg_bin("psql")), "-h", "127.0.0.1", "-p", str(PG_PORT), "-U", "atlas", "-d", "postgres",
             "-tAc", f"select 1 from pg_database where datname='{db}'"],
            capture_output=True, text=True,
        ).stdout.strip()
        if exists != "1":
            subprocess.run(
                [str(pg_bin("createdb")), "-h", "127.0.0.1", "-p", str(PG_PORT), "-U", "atlas", db], check=True
            )
            print(f"[ok] created database {db}")


def temporal_binary() -> Path:
    found = shutil.which("temporal")
    if found:
        return Path(found)
    target = BIN / f"temporal{EXE}"
    if target.exists():
        return target
    system = {"Windows": "windows", "Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"
    ext = "zip" if IS_WIN else "tar.gz"
    url = (
        f"https://github.com/temporalio/cli/releases/download/v{TEMPORAL_VERSION}/"
        f"temporal_cli_{TEMPORAL_VERSION}_{system}_{arch}.{ext}"
    )
    print(f"[..] downloading Temporal CLI {TEMPORAL_VERSION} from {url}")
    BIN.mkdir(parents=True, exist_ok=True)
    payload = urllib.request.urlopen(url, timeout=120).read()  # noqa: S310 - fixed https URL
    if ext == "zip":
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            zf.extract(f"temporal{EXE}", BIN)
    else:
        import tarfile  # noqa: PLC0415

        with tarfile.open(fileobj=io.BytesIO(payload)) as tf:
            tf.extract("temporal", BIN, filter="data")
        target.chmod(0o755)
    return target


def temporal_up() -> None:
    if port_open(TEMPORAL_PORT):
        print(f"[ok] temporal already on :{TEMPORAL_PORT}")
        return
    binary = temporal_binary()
    detached(
        [str(binary), "server", "start-dev", "--ip", "127.0.0.1", "--port", str(TEMPORAL_PORT),
         "--ui-port", str(TEMPORAL_UI_PORT), "--db-filename", str(DATA / "temporal.db"), "--log-level", "warn"],
        DATA / "temporal.log",
    )
    wait_port(TEMPORAL_PORT, "temporal")
    print(f"[ok] Temporal UI: http://127.0.0.1:{TEMPORAL_UI_PORT}")


def down() -> None:
    if (PGDATA / "postmaster.pid").exists():
        subprocess.run([str(pg_bin("pg_ctl")), "-D", str(PGDATA), "stop", "-m", "fast"], check=False)
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/IM", "temporal.exe"], check=False, capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "temporal server start-dev"], check=False)
    print("[ok] stopped")


def status() -> None:
    print(f"postgres :{PG_PORT}  {'UP' if port_open(PG_PORT) else 'DOWN'}")
    print(f"temporal :{TEMPORAL_PORT}  {'UP' if port_open(TEMPORAL_PORT) else 'DOWN'}")
    print(f"temporal-ui :{TEMPORAL_UI_PORT}  {'UP' if port_open(TEMPORAL_UI_PORT) else 'DOWN'}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "up":
        postgres_up()
        if "--no-temporal" not in sys.argv:
            temporal_up()
    elif action == "down":
        down()
    else:
        status()
