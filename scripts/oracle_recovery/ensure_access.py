#!/usr/bin/env python3
"""Keep Oracle g185 access portable across Windows, macOS, Linux, and Cloud Shell.

The old failure mode was a stale instance OCID/IP baked into ~/.ssh/config.
This tool makes the current Oracle instance the source of truth:

- Discover the current VM by OCI Search display name.
- Refresh scripts/oracle_recovery/config.env.
- Rebuild the local SSH alias (`Host g185`) with the current public IP.
- Generate/use a local ed25519 key.
- Optionally register that public key through OCI Instance Agent when SSH auth
  is not yet available.
- Verify SSH connectivity.

Run from any cloned copy of this repo:

    python scripts/oracle_recovery/ensure_access.py --repair

On a new Mac/PC without OCI credentials, the script still updates SSH config
from repo config and prints a one-line Cloud Shell registration command.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import pathlib
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG_PATH = pathlib.Path(__file__).resolve().with_name("config.env")
START_MARK = "# === g185 managed by oracle_recovery/ensure_access.py START ==="
END_MARK = "# === g185 managed by oracle_recovery/ensure_access.py END ==="
DEFAULT_DISPLAY_NAMES = ["g185-restored", "g185"]


@dataclass
class OracleConfig:
    inst_id: str
    comp_id: str
    ssh_host: str
    ssh_user: str
    ssh_ip: str
    ssh_port: str
    region: str


def run(
    cmd: list[str],
    *,
    timeout: int = 60,
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )


def parse_env(path: pathlib.Path = CONFIG_PATH) -> OracleConfig:
    raw: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip()] = value.strip().strip('"').strip("'").strip()
    return OracleConfig(
        inst_id=raw["INST_ID"],
        comp_id=raw["COMP_ID"],
        ssh_host=raw.get("SSH_HOST", "g185"),
        ssh_user=raw.get("SSH_USER", "opc"),
        ssh_ip=raw["SSH_IP"],
        ssh_port=raw.get("SSH_PORT", "443"),
        region=raw.get("REGION", "ap-chuncheon-1"),
    )


def write_env(cfg: OracleConfig, path: pathlib.Path = CONFIG_PATH) -> None:
    text = "\n".join(
        [
            f'INST_ID="{cfg.inst_id}"',
            f'COMP_ID="{cfg.comp_id}"',
            f'SSH_HOST="{cfg.ssh_host}"',
            f'SSH_USER="{cfg.ssh_user}"',
            f'SSH_IP="{cfg.ssh_ip}"',
            f'SSH_PORT="{cfg.ssh_port}"',
            f'REGION="{cfg.region}"',
            "",
        ]
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def oci_json(args: list[str], *, timeout: int = 90) -> tuple[dict[str, Any] | None, str | None]:
    if not command_exists("oci"):
        return None, "oci CLI not found"
    proc = run(["oci", *args, *oci_auth_args(), "--output", "json"], timeout=timeout)
    if proc.returncode != 0:
        return None, (proc.stderr.strip() or proc.stdout.strip() or f"oci rc={proc.returncode}")
    if not proc.stdout.strip():
        return None, "oci returned empty stdout"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"oci returned non-JSON stdout: {exc}: {proc.stdout[:300]}"


def oci_auth_args(profile: str = "DEFAULT") -> list[str]:
    config_path = pathlib.Path.home() / ".oci" / "config"
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if parser.has_option(profile, "security_token_file"):
        return ["--auth", "security_token"]
    return []


def command_exists(name: str) -> bool:
    checker = "where.exe" if os.name == "nt" else "command"
    if checker == "where.exe":
        return run([checker, name], timeout=10).returncode == 0
    return run(["bash", "-lc", f"command -v {shlex.quote(name)}"], timeout=10).returncode == 0


def discover_instance(cfg: OracleConfig, names: list[str]) -> tuple[OracleConfig | None, str | None]:
    query_text = "query instance resources"
    data, err = oci_json(
        [
            "search",
            "resource",
            "structured-search",
            "--region",
            cfg.region,
            "--query-text",
            query_text,
        ],
        timeout=120,
    )
    if err:
        return None, err

    items = data.get("data", {}).get("items", []) if data else []
    candidates = [
        item
        for item in items
        if item.get("resource-type") == "Instance"
        and item.get("display-name") in names
        and item.get("lifecycle-state") != "TERMINATED"
    ]
    if not candidates:
        return None, f"No active instance found by display names: {', '.join(names)}"

    def rank(item: dict[str, Any]) -> tuple[int, int]:
        name_rank = names.index(item.get("display-name")) if item.get("display-name") in names else 99
        running_rank = 0 if item.get("lifecycle-state") == "RUNNING" else 1
        return running_rank, name_rank

    best = sorted(candidates, key=rank)[0]
    inst_id = best["identifier"]
    comp_id = best.get("compartment-id") or cfg.comp_id

    vnic_data, vnic_err = oci_json(
        [
            "compute",
            "instance",
            "list-vnics",
            "--region",
            cfg.region,
            "--instance-id",
            inst_id,
        ],
        timeout=90,
    )
    if vnic_err:
        return None, vnic_err
    vnics = vnic_data.get("data", []) if vnic_data else []
    public_ip = next((v.get("public-ip") for v in vnics if v.get("public-ip")), None)
    if not public_ip:
        return None, f"Instance {best.get('display-name')} has no public IP"

    return (
        OracleConfig(
            inst_id=inst_id,
            comp_id=comp_id,
            ssh_host=cfg.ssh_host,
            ssh_user=cfg.ssh_user,
            ssh_ip=public_ip,
            ssh_port=cfg.ssh_port,
            region=cfg.region,
        ),
        None,
    )


def key_paths(key_path: str | None) -> tuple[pathlib.Path, pathlib.Path]:
    key = pathlib.Path(os.path.expanduser(key_path or "~/.ssh/id_ed25519"))
    return key, pathlib.Path(str(key) + ".pub")


def ensure_key(key_path: pathlib.Path) -> None:
    pub_path = pathlib.Path(str(key_path) + ".pub")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists() and pub_path.exists():
        return
    if not command_exists("ssh-keygen"):
        raise RuntimeError("ssh-keygen not found and SSH key is missing")
    comment = f"g185-paper@{socket.gethostname()}-{time.strftime('%Y%m%d')}"
    proc = run(["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", comment], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())


def tcp_open(host: str, port: str, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def remove_old_g185_blocks(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == START_MARK:
            while i < len(lines) and lines[i].strip() != END_MARK:
                i += 1
            i += 1
            continue
        if re.match(r"^\s*Host\s+g185\s*$", line):
            i += 1
            while i < len(lines) and not re.match(r"^\s*Host\s+", lines[i]):
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out).rstrip() + "\n"


def update_ssh_config(cfg: OracleConfig, key_path: pathlib.Path) -> pathlib.Path:
    ssh_dir = pathlib.Path.home() / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    config_path = ssh_dir / "config"
    existing = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else ""
    existing = remove_old_g185_blocks(existing)
    block = f"""
{START_MARK}
Host {cfg.ssh_host}
    HostName {cfg.ssh_ip}
    Port {cfg.ssh_port}
    User {cfg.ssh_user}
    IdentityFile {key_path}
    StrictHostKeyChecking accept-new
    ControlMaster no
    ControlPath none
    ConnectTimeout 30
    ServerAliveInterval 30
    ServerAliveCountMax 3
{END_MARK}
"""
    config_path.write_text(existing.rstrip() + "\n" + block.lstrip(), encoding="utf-8", newline="\n")
    try:
        os.chmod(config_path, 0o600)
        os.chmod(ssh_dir, 0o700)
    except OSError:
        pass
    return config_path


def ssh_ok(cfg: OracleConfig) -> bool:
    proc = run(
        [
            "ssh",
            "-o",
            "ControlMaster=no",
            "-o",
            "ControlPath=none",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=20",
            cfg.ssh_host,
            "echo OK && hostname && date -u",
        ],
        timeout=40,
    )
    if proc.returncode == 0:
        print(proc.stdout.strip())
        return True
    print((proc.stderr or proc.stdout).strip())
    return False


def run_instance_agent_command(cfg: OracleConfig, *, display_name: str, script: str, timeout_seconds: int = 90) -> bool:
    body = {
        "compartmentId": cfg.comp_id,
        "executionTimeOutInSeconds": timeout_seconds,
        "displayName": display_name,
        "target": {"instanceId": cfg.inst_id},
        "content": {
            "source": {"sourceType": "TEXT", "text": script},
            "output": {"outputType": "TEXT"},
        },
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(body, fh)
        body_path = fh.name
    try:
        data, err = oci_json(
            [
                "instance-agent",
                "command",
                "create",
                "--region",
                cfg.region,
                "--timeout-in-seconds",
                str(timeout_seconds),
                "--from-json",
                f"file://{body_path}",
            ],
            timeout=90,
        )
        if err:
            print(f"OCI instance-agent command failed: {err}")
            return False
        cmd_id = data.get("data", {}).get("id") if data else None
        if not cmd_id:
            print("OCI instance-agent command failed: missing command id")
            return False
        for _ in range(24):
            time.sleep(5)
            status, status_err = oci_json(
                [
                    "instance-agent",
                    "command-execution",
                    "get",
                    "--region",
                    cfg.region,
                    "--instance-id",
                    cfg.inst_id,
                    "--command-id",
                    cmd_id,
                ],
                timeout=60,
            )
            if status_err:
                print(f"OCI instance-agent command status failed: {status_err}")
                return False
            state = status.get("data", {}).get("lifecycle-state") if status else None
            if state == "SUCCEEDED":
                return True
            if state in {"FAILED", "TIMED_OUT", "CANCELED"}:
                print(f"OCI instance-agent command ended: {state}")
                return False
        print("OCI instance-agent command timed out")
        return False
    finally:
        pathlib.Path(body_path).unlink(missing_ok=True)


def restart_sshd_via_oci(cfg: OracleConfig) -> bool:
    script = (
        "set -e; "
        "if command -v systemctl >/dev/null 2>&1; then "
        "sudo systemctl restart sshd || sudo systemctl restart ssh || true; "
        "sudo systemctl is-active sshd || sudo systemctl is-active ssh || true; "
        "else sudo service sshd restart || sudo service ssh restart || true; fi"
    )
    return run_instance_agent_command(
        cfg,
        display_name="codex-restart-g185-sshd",
        script=script,
        timeout_seconds=90,
    )


def register_pubkey_via_oci(cfg: OracleConfig, pubkey: str) -> bool:
    user = shlex.quote(cfg.ssh_user)
    home = f"/home/{cfg.ssh_user}"
    script = (
        f"set -e; install -d -m 700 {home}/.ssh; "
        f"touch {home}/.ssh/authorized_keys; chmod 600 {home}/.ssh/authorized_keys; "
        f"grep -qxF {shlex.quote(pubkey)} {home}/.ssh/authorized_keys || "
        f"echo {shlex.quote(pubkey)} >> {home}/.ssh/authorized_keys; "
        f"chown -R {user}:{user} {home}/.ssh; "
        "if command -v systemctl >/dev/null 2>&1; then "
        "sudo systemctl restart sshd || sudo systemctl restart ssh || true; fi; "
        "echo KEY_OK"
    )
    return run_instance_agent_command(
        cfg,
        display_name="codex-register-g185-key",
        script=script,
        timeout_seconds=90,
    )


def cloud_shell_register_command(pubkey: str) -> str:
    safe_pubkey = pubkey.replace("'", "'\"'\"'")
    return (
        "cd ~/repo && git pull && "
        "python3 scripts/oracle_recovery/ensure_access.py "
        f"--repair --register-pubkey '{safe_pubkey}'"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true", help="Discover VM, rewrite config, and verify SSH")
    parser.add_argument("--no-discover", action="store_true", help="Do not use OCI Search; rely on config.env")
    parser.add_argument("--key-path", default=None, help="SSH private key path. Defaults to ~/.ssh/id_ed25519")
    parser.add_argument("--register-pubkey", default=None, help="Public key string to register on the VM via OCI agent")
    parser.add_argument("--display-name", action="append", default=[], help="Preferred VM display name, repeatable")
    args = parser.parse_args()

    cfg = parse_env()
    names = args.display_name or DEFAULT_DISPLAY_NAMES
    key_path, pub_path = key_paths(args.key_path)
    ensure_key(key_path)
    pubkey = args.register_pubkey or pub_path.read_text(encoding="utf-8").strip()

    discovered = False
    if not args.no_discover:
        new_cfg, err = discover_instance(cfg, names)
        if new_cfg:
            cfg = new_cfg
            discovered = True
            if args.repair:
                write_env(cfg)
        else:
            print(f"OCI discovery skipped/failed: {err}")

    if args.register_pubkey:
        if register_pubkey_via_oci(cfg, pubkey):
            print("Registered public key through OCI Instance Agent.")
        else:
            return 2

    config_path = update_ssh_config(cfg, key_path)
    print(f"SSH config updated: {config_path}")
    print(f"Host {cfg.ssh_host} -> {cfg.ssh_user}@{cfg.ssh_ip}:{cfg.ssh_port}")
    if discovered:
        print(f"Discovered instance: {cfg.inst_id}")

    if not tcp_open(cfg.ssh_ip, cfg.ssh_port):
        print(f"TCP closed: {cfg.ssh_ip}:{cfg.ssh_port}")
        print("If you are in Cloud Shell, run: bash scripts/oracle_recovery/emergency_recover.sh")
        return 3

    if ssh_ok(cfg):
        return 0

    print("\nSSH TCP is open, but authentication failed or command did not run.")
    print("Trying OCI Instance Agent sshd restart when credentials are available...")
    if restart_sshd_via_oci(cfg):
        print("Restarted sshd through OCI. Retrying SSH...")
        if ssh_ok(cfg):
            return 0

    if not args.register_pubkey and register_pubkey_via_oci(cfg, pubkey):
        print("Registered local public key through OCI. Retrying SSH...")
        return 0 if ssh_ok(cfg) else 4

    print("\nNo usable OCI registration path from this environment.")
    print("Run this one-liner in Oracle Cloud Shell to enroll this machine's public key:")
    print(cloud_shell_register_command(pubkey))
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
