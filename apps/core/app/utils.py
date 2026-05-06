from __future__ import annotations

import subprocess


def run_cmd(cmd: list[str], error_message: str, error_class: type[Exception] = RuntimeError) -> None:
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        details = process.stderr.strip() or process.stdout.strip()
        raise error_class(f"{error_message}: {details}")
