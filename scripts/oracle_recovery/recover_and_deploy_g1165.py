#!/usr/bin/env python3
"""Recover the Oracle g185 VM when possible, then deploy G1165.

This runner is designed for the local Codex workspace. It avoids asking for
manual server uploads:
1. Try the normal G1165 SSH deployment.
2. If SSH/TCP is down and OCI CLI credentials are available locally, recover
   the instance by START -> agent sshd restart -> SOFTRESET -> RESET.
3. Retry the G1165 deployment after each recovery step.

If local OCI credentials are absent, the script exits with a precise blocker.
"""

from __future__ import annotations

import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG_PATH = pathlib.Path(__file__).resolve().with_name("config.env")
ENSURE_ACCESS = pathlib.Path(__file__).resolve().with_name("ensure_access.py")
DEPLOY_SCRIPT = REPO_ROOT / "quant_binance" / "strategies" / "_scripts" / "deploy_g1165_to_oracle.py"


def run(
    cmd: list[str],
    *,
    timeout: int = 60,
    check: bool = False,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
    )


def parse_config() -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip().strip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'").strip()
    return data


def tcp_open(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def deploy() -> bool:
    proc = run([sys.executable, str(DEPLOY_SCRIPT)], timeout=90)
    print(proc.stdout, end="")
    print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode == 0


def oci_config_usable() -> tuple[bool, str]:
    config = pathlib.Path.home() / ".oci" / "config"
    if not config.exists():
        return False, f"missing {config}"
    text = config.read_text(encoding="utf-8", errors="ignore")
    required = ["tenancy=", "user=", "fingerprint=", "key_file="]
    missing = [key[:-1] for key in required if key not in text]
    if missing:
        return False, f"{config} missing: {', '.join(missing)}"
    return True, "ok"


def oci(args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return run(["oci", *args], timeout=timeout)


def instance_state(instance_id: str, region: str) -> str:
    proc = oci(
        [
            "compute",
            "instance",
            "get",
            "--instance-id",
            instance_id,
            "--region",
            region,
            "--query",
            'data."lifecycle-state"',
            "--raw-output",
        ],
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def instance_action(instance_id: str, region: str, action: str, wait_seconds: int) -> bool:
    proc = oci(
        [
            "compute",
            "instance",
            "action",
            "--action",
            action,
            "--instance-id",
            instance_id,
            "--region",
            region,
            "--wait-for-state",
            "RUNNING",
            "--max-wait-seconds",
            str(wait_seconds),
        ],
        timeout=wait_seconds + 90,
    )
    if proc.returncode != 0:
        print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
        return False
    return True


def restart_sshd_via_agent(instance_id: str, compartment_id: str, region: str) -> bool:
    body: dict[str, Any] = {
        "compartmentId": compartment_id,
        "executionTimeOutInSeconds": 60,
        "displayName": "codex-auto-sshd-restart",
        "target": {"instanceId": instance_id},
        "content": {
            "source": {
                "sourceType": "TEXT",
                "text": "sudo systemctl restart sshd; systemctl is-active sshd",
            },
            "output": {"outputType": "TEXT"},
        },
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(body, fh)
        body_path = fh.name
    try:
        create = oci(
            [
                "instance-agent",
                "command",
                "create",
                "--region",
                region,
                "--from-json",
                f"file://{body_path}",
                "--query",
                "data.id",
                "--raw-output",
            ],
            timeout=90,
        )
        if create.returncode != 0:
            print(create.stderr.strip() or create.stdout.strip(), file=sys.stderr)
            return False
        command_id = create.stdout.strip()
        if not command_id:
            return False
        for _ in range(18):
            time.sleep(5)
            status = oci(
                [
                    "instance-agent",
                    "command-execution",
                    "get",
                    "--region",
                    region,
                    "--instance-id",
                    instance_id,
                    "--command-id",
                    command_id,
                    "--query",
                    'data."lifecycle-state"',
                    "--raw-output",
                ],
                timeout=60,
            )
            state = status.stdout.strip()
            if state == "SUCCEEDED":
                return True
            if state in {"FAILED", "TIMED_OUT", "CANCELED"}:
                print(f"agent command ended: {state}", file=sys.stderr)
                return False
        return False
    finally:
        pathlib.Path(body_path).unlink(missing_ok=True)


def wait_for_tcp(host: str, port: int, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if tcp_open(host, port):
            return True
        time.sleep(10)
    return False


def main() -> int:
    if ENSURE_ACCESS.exists():
        # Refresh stale OCID/IP before trying SSH or OCI recovery. Non-zero is
        # acceptable here because SSH may still be down before recovery.
        run([sys.executable, str(ENSURE_ACCESS), "--repair"], timeout=140)

    cfg = parse_config()
    host = cfg["SSH_IP"]
    port = int(cfg["SSH_PORT"])
    instance_id = cfg["INST_ID"]
    compartment_id = cfg["COMP_ID"]
    region = cfg["REGION"]

    print(f"[0] deploy attempt via SSH {host}:{port}")
    if deploy():
        return 0

    print(f"[1] TCP check {host}:{port}: {'open' if tcp_open(host, port) else 'closed'}")
    ok, reason = oci_config_usable()
    if not ok:
        print(f"BLOCKED: local OCI credentials unavailable: {reason}", file=sys.stderr)
        print("The retry automation will keep trying SSH; recovery will run automatically once OCI config is present.", file=sys.stderr)
        return 20

    try:
        state = instance_state(instance_id, region)
    except Exception as exc:
        print(f"BLOCKED: OCI instance state query failed: {exc}", file=sys.stderr)
        return 21

    print(f"[2] OCI lifecycle state: {state}")
    if state == "STOPPED":
        print("[2a] START")
        instance_action(instance_id, region, "START", 600)
        wait_for_tcp(host, port, 90)
        if deploy():
            return 0

    if state in {"TERMINATED", "TERMINATING"}:
        print(f"BLOCKED: instance state is {state}; cannot recover this instance", file=sys.stderr)
        return 22

    print("[3] agent sshd restart")
    restart_sshd_via_agent(instance_id, compartment_id, region)
    wait_for_tcp(host, port, 60)
    if deploy():
        return 0

    print("[4] SOFTRESET")
    instance_action(instance_id, region, "SOFTRESET", 300)
    wait_for_tcp(host, port, 120)
    if deploy():
        return 0

    print("[5] RESET")
    instance_action(instance_id, region, "RESET", 300)
    wait_for_tcp(host, port, 150)
    if deploy():
        return 0

    print("FAILED: recovery actions completed but SSH/deploy still failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
