from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .legacy import select_shell


def stop_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def execute(
    command: str | list[str],
    root: Path,
    timeout: int,
    shell: str = "auto",
    max_output: int = 12000,
) -> dict:
    argv = [*select_shell(shell)[1], command] if isinstance(command, str) else command
    started = time.monotonic()
    # A disk-backed spool avoids unbounded RAM usage and pipe deadlocks.
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                argv,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0,
            )
            timed_out = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_process(process)
            except BaseException:
                stop_process(process)
                raise
            output.seek(0)
            data = output.read(max_output + 1)
            return {
                "ok": process.returncode == 0 and not timed_out,
                "exit_code": process.returncode,
                "timed_out": timed_out,
                "seconds": round(time.monotonic() - started, 2),
                "output": data[:max_output].decode("utf-8", errors="replace")
                + ("\n[output truncated]" if len(data) > max_output else ""),
            }
        except OSError as exc:
            return {"ok": False, "exit_code": None, "output": str(exc)}


def start(
    command: str | list[str],
    root: Path,
    shell: str = "auto",
    log_path: Path | None = None,
) -> dict:
    """Launch a noninteractive background process and return durable evidence."""
    argv = [*select_shell(shell)[1], command] if isinstance(command, str) else command
    if log_path is None:
        log_path = root / ".agent" / "processes" / "process.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("ab") as output:
            process = subprocess.Popen(
                argv,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0,
            )
        return {
            "ok": True,
            "pid": process.pid,
            "cwd": str(root),
            "log": str(log_path),
        }
    except OSError as exc:
        return {"ok": False, "pid": None, "output": str(exc)}
