"""Oracle Server Manager v2 — g185 서버 원클릭 관리 GUI.

PC가 바뀌어도 이 프로그램 하나면 OK:
  1. 원클릭 셋업 (SSH 키 + config 자동 생성)
  2. 대시보드에서 서버 상태 한눈에 확인
  3. 서비스 시작/중지/로그 확인
  4. 원격 명령 실행

실행:
  Windows: python scripts/oracle_manager.pyw  (또는 .bat 더블클릭)
  macOS:   python3 scripts/oracle_manager.pyw

외부 패키지 필요 없음 (Python 기본 라이브러리만 사용)
"""

from __future__ import annotations

import configparser
import json
import os
import pathlib
import platform
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from dataclasses import dataclass
from typing import Any

# ─── Paths ───

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "oracle_recovery" / "config.env"

START_MARK = "# === g185 managed by oracle_recovery/ensure_access.py START ==="
END_MARK = "# === g185 managed by oracle_recovery/ensure_access.py END ==="

IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"


# ─── Cross-platform helpers ───

def _mono_font() -> str:
    if IS_MAC:
        return "Menlo"
    if IS_WIN:
        return "Consolas"
    return "monospace"


def _ui_font() -> str:
    if IS_MAC:
        return "SF Pro"
    if IS_WIN:
        return "Segoe UI"
    return "sans-serif"


def _startupinfo():
    if IS_WIN:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    return None


def run_local(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=timeout, startupinfo=_startupinfo(),
    )


def command_exists(name: str) -> bool:
    try:
        if IS_WIN:
            return run_local(["where.exe", name], timeout=10).returncode == 0
        return run_local(["which", name], timeout=10).returncode == 0
    except Exception:
        return False


def tcp_open(host: str, port: str, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


# ─── Config ───

@dataclass
class ServerConfig:
    inst_id: str = ""
    comp_id: str = ""
    ssh_host: str = "g185"
    ssh_user: str = "opc"
    ssh_ip: str = ""
    ssh_port: str = "443"
    region: str = "ap-chuncheon-1"


def load_config() -> ServerConfig:
    if not CONFIG_PATH.exists():
        return ServerConfig()
    raw: dict[str, str] = {}
    for line in CONFIG_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip()] = value.strip().strip('"').strip("'").strip()
    return ServerConfig(
        inst_id=raw.get("INST_ID", ""),
        comp_id=raw.get("COMP_ID", ""),
        ssh_host=raw.get("SSH_HOST", "g185"),
        ssh_user=raw.get("SSH_USER", "opc"),
        ssh_ip=raw.get("SSH_IP", ""),
        ssh_port=raw.get("SSH_PORT", "443"),
        region=raw.get("REGION", "ap-chuncheon-1"),
    )


def save_config(cfg: ServerConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join([
        f'INST_ID="{cfg.inst_id}"',
        f'COMP_ID="{cfg.comp_id}"',
        f'SSH_HOST="{cfg.ssh_host}"',
        f'SSH_USER="{cfg.ssh_user}"',
        f'SSH_IP="{cfg.ssh_ip}"',
        f'SSH_PORT="{cfg.ssh_port}"',
        f'REGION="{cfg.region}"',
        "",
    ])
    CONFIG_PATH.write_text(text, encoding="utf-8", newline="\n")


# ─── SSH ───

def _ssh_key_path() -> pathlib.Path:
    return pathlib.Path.home() / ".ssh" / "id_ed25519"


def _ssh_pub_path() -> pathlib.Path:
    return pathlib.Path(str(_ssh_key_path()) + ".pub")


def ssh_args(cfg: ServerConfig) -> list[str]:
    """Build SSH command that works without SSH config (direct IP connection)."""
    args = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ControlMaster=no",
        "-o", "ControlPath=none",
        "-o", "ServerAliveInterval=15",
        "-p", cfg.ssh_port,
    ]
    key = _ssh_key_path()
    if key.exists():
        args += ["-i", str(key)]
    args.append(f"{cfg.ssh_user}@{cfg.ssh_ip}")
    return args


def ssh_exec(cfg: ServerConfig, remote_cmd: str, timeout: int = 30) -> tuple[str, bool]:
    if not cfg.ssh_ip:
        return "[SSH IP가 설정되지 않았습니다. 설정 탭에서 IP를 입력하세요.]", False
    try:
        proc = run_local(ssh_args(cfg) + [remote_cmd], timeout=timeout)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if proc.returncode == 0:
            return stdout, True
        if "Permission denied" in stderr:
            return "[SSH 인증 실패] 공개키가 서버에 등록되지 않았습니다. Setup 탭에서 원클릭 셋업을 실행하세요.", False
        if "Connection refused" in stderr or "Connection timed out" in stderr:
            return "[연결 실패] 서버가 꺼져있거나 방화벽에 막혀있습니다.", False
        if "Host key verification failed" in stderr:
            return "[호스트 키 변경됨] ~/.ssh/known_hosts에서 서버 항목을 삭제 후 재시도하세요.", False
        combined = (stdout + "\n" + stderr).strip()
        return combined or f"[명령 실패 (exit code {proc.returncode})]", False
    except subprocess.TimeoutExpired:
        return f"[타임아웃] {timeout}초 내에 응답이 없습니다. 서버 상태를 확인하세요.", False
    except FileNotFoundError:
        return "[SSH 미설치] ssh 명령을 찾을 수 없습니다. OpenSSH를 설치하세요.", False
    except Exception as e:
        return f"[오류] {e}", False


def scp_upload(cfg: ServerConfig, local_path: str, remote_path: str,
               timeout: int = 120) -> tuple[str, bool]:
    args = [
        "scp",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new",
        "-P", cfg.ssh_port,
    ]
    key = _ssh_key_path()
    if key.exists():
        args += ["-i", str(key)]
    args += [local_path, f"{cfg.ssh_user}@{cfg.ssh_ip}:{remote_path}"]
    try:
        proc = run_local(args, timeout=timeout)
        output = (proc.stdout + proc.stderr).strip()
        return output or "업로드 완료", proc.returncode == 0
    except subprocess.TimeoutExpired:
        return f"[타임아웃] {timeout}초 초과", False
    except Exception as e:
        return f"[오류] {e}", False


def open_ssh_terminal(cfg: ServerConfig):
    """Open an interactive SSH session in a new terminal window."""
    if IS_WIN:
        subprocess.Popen(
            ["cmd", "/c", "start", "cmd", "/k", "ssh", cfg.ssh_host],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    elif IS_MAC:
        script = f'tell application "Terminal" to do script "ssh {cfg.ssh_host}"'
        subprocess.Popen(["osascript", "-e", script])
    else:
        for terminal in ["gnome-terminal", "konsole", "xfce4-terminal", "xterm"]:
            if command_exists(terminal):
                if terminal == "gnome-terminal":
                    subprocess.Popen([terminal, "--", "ssh", cfg.ssh_host])
                else:
                    subprocess.Popen([terminal, "-e", f"ssh {cfg.ssh_host}"])
                return
        subprocess.Popen(["xterm", "-e", f"ssh {cfg.ssh_host}"])


# ─── OCI helpers ───

def oci_auth_args() -> list[str]:
    config_path = pathlib.Path.home() / ".oci" / "config"
    if not config_path.exists():
        return []
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except Exception:
        return []
    if parser.has_option("DEFAULT", "security_token_file"):
        return ["--auth", "security_token"]
    return []


def register_key_via_oci(cfg: ServerConfig, pubkey: str) -> tuple[bool, str]:
    home = f"/home/{cfg.ssh_user}"
    user = shlex.quote(cfg.ssh_user)
    script = (
        f"set -e; install -d -m 700 {home}/.ssh; "
        f"touch {home}/.ssh/authorized_keys; chmod 600 {home}/.ssh/authorized_keys; "
        f"grep -qxF {shlex.quote(pubkey)} {home}/.ssh/authorized_keys || "
        f"echo {shlex.quote(pubkey)} >> {home}/.ssh/authorized_keys; "
        f"chown -R {user}:{user} {home}/.ssh; "
        "sudo systemctl restart sshd || true; echo KEY_OK"
    )
    body = {
        "compartmentId": cfg.comp_id,
        "executionTimeOutInSeconds": 90,
        "displayName": "manager-register-key",
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
        auth = oci_auth_args()
        proc = run_local(
            ["oci", "instance-agent", "command", "create",
             "--region", cfg.region, "--timeout-in-seconds", "90",
             "--from-json", f"file://{body_path}",
             *auth, "--output", "json"],
            timeout=90,
        )
        if proc.returncode != 0:
            return False, proc.stderr.strip()[:200]
        data = json.loads(proc.stdout)
        cmd_id = data.get("data", {}).get("id")
        if not cmd_id:
            return False, "command id 없음"
        for _ in range(18):
            time.sleep(5)
            sp = run_local(
                ["oci", "instance-agent", "command-execution", "get",
                 "--region", cfg.region, "--instance-id", cfg.inst_id,
                 "--command-id", cmd_id, *auth, "--output", "json"],
                timeout=60,
            )
            if sp.returncode != 0:
                continue
            state = json.loads(sp.stdout).get("data", {}).get("lifecycle-state", "")
            if state == "SUCCEEDED":
                return True, "키 등록 성공"
            if state in {"FAILED", "TIMED_OUT", "CANCELED"}:
                return False, f"OCI command: {state}"
        return False, "타임아웃"
    except Exception as e:
        return False, str(e)
    finally:
        pathlib.Path(body_path).unlink(missing_ok=True)


# ─── SSH Config management ───

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


def write_ssh_config(cfg: ServerConfig, key_path: pathlib.Path) -> pathlib.Path:
    ssh_dir = pathlib.Path.home() / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    config_path = ssh_dir / "config"
    existing = ""
    if config_path.exists():
        existing = config_path.read_text(encoding="utf-8", errors="replace")
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
    config_path.write_text(
        existing.rstrip() + "\n" + block.lstrip(),
        encoding="utf-8", newline="\n",
    )
    try:
        os.chmod(config_path, 0o600)
        os.chmod(ssh_dir, 0o700)
    except OSError:
        pass
    return config_path


# ─── Async worker ───

class AsyncWorker:
    def __init__(self, root: tk.Tk):
        self.root = root

    def run(self, fn, callback):
        def _go():
            try:
                result = fn()
                self.root.after(0, callback, result, None)
            except Exception as e:
                self.root.after(0, callback, None, e)
        threading.Thread(target=_go, daemon=True).start()


# ─── Tooltip ───

class Tooltip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip_window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT, relief=tk.SOLID, borderwidth=1,
            background="#ffffdd", font=(_ui_font(), 9), wraplength=350, padx=6, pady=4,
        )
        label.pack()

    def _hide(self, _event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ─── Smart Connect Dialog ───

class SmartConnectDialog:
    """만능 연결 — 상황을 자동 진단하고 단계별로 문제를 해결합니다."""

    STEP_ICONS = {"wait": "[ . ]", "run": "[>>>]", "ok": "[ O ]", "fail": "[ X ]", "skip": "[ - ]", "warn": "[ ! ]"}

    def __init__(self, parent: tk.Tk, cfg: ServerConfig, on_done=None):
        self.cfg = cfg
        self.on_done = on_done
        self.success = False

        self.win = tk.Toplevel(parent)
        self.win.title("만능 연결")
        self.win.geometry("660x520")
        self.win.resizable(True, True)
        self.win.transient(parent)
        self.win.grab_set()

        ttk.Label(self.win, text="자동 진단 & 연결", font=(_ui_font(), 13, "bold")).pack(
            anchor=tk.W, padx=12, pady=(10, 2))
        ttk.Label(self.win, text=(
            "현재 상태를 자동으로 파악하고, 문제가 있으면 스스로 고칩니다."
        ), font=(_ui_font(), 9), foreground="#757575").pack(anchor=tk.W, padx=12, pady=(0, 8))

        # Steps display
        self.steps_frame = ttk.Frame(self.win, padding=(12, 0))
        self.steps_frame.pack(fill=tk.X)

        self.step_labels: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        step_defs = [
            ("env",        "환경 점검",       "SSH 설치, config.env 파일 확인"),
            ("key",        "SSH 키",          "키 파일 확인, 없으면 자동 생성"),
            ("config",     "SSH Config",      "SSH 설정 확인, 필요하면 자동 갱신"),
            ("tcp",        "네트워크 연결",    "서버에 TCP 연결 시도"),
            ("oci_discover", "OCI 인스턴스 탐색", "IP 변경 시 OCI에서 최신 IP 조회"),
            ("hostkey",    "호스트 키 확인",   "known_hosts 충돌 시 자동 수정"),
            ("ssh_auth",   "SSH 인증",        "키 기반 로그인 시도"),
            ("key_register", "키 등록",       "인증 실패 시 OCI로 공개키 자동 등록"),
            ("sshd_restart", "sshd 재시작",   "서버 sshd 데몬 문제 시 원격 재시작"),
            ("final",      "최종 확인",       "연결 성공 여부 최종 판정"),
        ]
        for i, (key, title, desc) in enumerate(step_defs):
            icon_lbl = ttk.Label(self.steps_frame, text=self.STEP_ICONS["wait"],
                                 font=(_mono_font(), 9), width=6)
            icon_lbl.grid(row=i, column=0, sticky=tk.W, pady=1)
            text_lbl = ttk.Label(self.steps_frame, text=f"{title}  —  {desc}",
                                 font=(_ui_font(), 9), foreground="#757575")
            text_lbl.grid(row=i, column=1, sticky=tk.W, padx=(4, 0), pady=1)
            self.step_labels[key] = (icon_lbl, text_lbl)

        # Detail log
        ttk.Label(self.win, text="상세 로그:", font=(_ui_font(), 9)).pack(
            anchor=tk.W, padx=12, pady=(10, 2))
        self.log_text = scrolledtext.ScrolledText(
            self.win, height=10, font=(_mono_font(), 9), wrap=tk.WORD,
            bg="#1e1e1e", fg="#cccccc", state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 5))
        self.log_text.tag_configure("ok", foreground="#4ec9b0")
        self.log_text.tag_configure("fail", foreground="#f44747")
        self.log_text.tag_configure("info", foreground="#569cd6")
        self.log_text.tag_configure("step", foreground="#dcdcaa")

        # Bottom buttons
        btn_frame = ttk.Frame(self.win, padding=(12, 5))
        btn_frame.pack(fill=tk.X)
        self.btn_close = ttk.Button(btn_frame, text="닫기", command=self._close, width=10)
        self.btn_close.pack(side=tk.RIGHT)
        self.btn_terminal = ttk.Button(btn_frame, text="SSH 터미널 열기",
                                       command=lambda: open_ssh_terminal(self.cfg),
                                       width=15, state=tk.DISABLED)
        self.btn_terminal.pack(side=tk.RIGHT, padx=(0, 8))

        # Start
        threading.Thread(target=self._run, daemon=True).start()

    def _close(self):
        self.win.destroy()
        if self.on_done:
            self.on_done(self.success)

    def _log(self, msg: str, tag: str = ""):
        def _do():
            self.log_text.configure(state=tk.NORMAL)
            if tag:
                self.log_text.insert(tk.END, msg + "\n", tag)
            else:
                self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        self.win.after(0, _do)

    def _set_step(self, key: str, state: str, detail: str = ""):
        def _do():
            if key not in self.step_labels:
                return
            icon_lbl, text_lbl = self.step_labels[key]
            icon_lbl.configure(text=self.STEP_ICONS.get(state, "[ ? ]"))
            colors = {"ok": "#2e7d32", "fail": "#c62828", "run": "#1565c0",
                      "skip": "#9e9e9e", "warn": "#e65100", "wait": "#9e9e9e"}
            icon_lbl.configure(foreground=colors.get(state, "#757575"))
            if detail:
                base = text_lbl.cget("text").split("  —  ")[0]
                text_lbl.configure(text=f"{base}  —  {detail}",
                                   foreground=colors.get(state, "#757575"))
        self.win.after(0, _do)

    def _run(self):
        """Main smart-connect logic — runs in background thread."""
        self._log("=== 만능 연결 시작 ===", "step")
        self._log("")

        # ── Step 1: Environment check ──
        self._set_step("env", "run", "확인중...")
        self._log("[환경 점검]", "info")

        if not command_exists("ssh"):
            self._set_step("env", "fail", "SSH 미설치!")
            self._log("ssh 명령을 찾을 수 없습니다.", "fail")
            if IS_WIN:
                self._log("설정 > 앱 > 선택적 기능 > OpenSSH 클라이언트 를 설치하세요.", "fail")
            else:
                self._log("brew install openssh 또는 apt install openssh-client", "fail")
            self._finish(False)
            return

        if not CONFIG_PATH.exists():
            self._set_step("env", "fail", "config.env 없음")
            self._log(f"설정 파일을 찾을 수 없습니다: {CONFIG_PATH}", "fail")
            self._log("레포지토리를 올바르게 clone했는지 확인하세요.", "fail")
            self._finish(False)
            return

        self.cfg = load_config()
        if not self.cfg.ssh_ip:
            self._set_step("env", "fail", "서버 IP 미설정")
            self._log("config.env에 SSH_IP가 비어있습니다. 설정 탭에서 입력하세요.", "fail")
            self._finish(False)
            return

        self._set_step("env", "ok", "정상")
        self._log(f"  SSH: 설치됨  |  서버: {self.cfg.ssh_ip}:{self.cfg.ssh_port}", "ok")

        # ── Step 2: SSH Key ──
        self._set_step("key", "run", "확인중...")
        self._log("\n[SSH 키]", "info")
        key_path = _ssh_key_path()
        pub_path = _ssh_pub_path()

        if key_path.exists() and pub_path.exists():
            self._set_step("key", "ok", "이미 존재")
            self._log(f"  키 존재: {key_path}", "ok")
        else:
            self._log("  키가 없습니다. 새로 생성합니다...")
            key_path.parent.mkdir(parents=True, exist_ok=True)
            comment = f"g185@{socket.gethostname()}-{time.strftime('%Y%m%d')}"
            proc = run_local(
                ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", comment],
                timeout=30,
            )
            if proc.returncode != 0:
                self._set_step("key", "fail", "생성 실패")
                self._log(f"  키 생성 실패: {proc.stderr.strip()}", "fail")
                self._finish(False)
                return
            self._set_step("key", "ok", "새로 생성됨")
            self._log("  SSH 키 생성 완료", "ok")

        # ── Step 3: SSH Config ──
        self._set_step("config", "run", "갱신중...")
        self._log("\n[SSH Config]", "info")
        config_path = write_ssh_config(self.cfg, key_path)
        self._set_step("config", "ok", "갱신 완료")
        self._log(f"  SSH Config 갱신: {config_path}", "ok")
        self._log(f"  'ssh {self.cfg.ssh_host}' 으로 접속 가능하도록 설정됨", "ok")

        # ── Step 4: TCP check ──
        self._set_step("tcp", "run", f"{self.cfg.ssh_ip}:{self.cfg.ssh_port} 연결중...")
        self._log(f"\n[네트워크 연결] {self.cfg.ssh_ip}:{self.cfg.ssh_port}", "info")

        tcp_ok = tcp_open(self.cfg.ssh_ip, self.cfg.ssh_port)

        if not tcp_ok:
            self._set_step("tcp", "fail", "연결 실패")
            self._log("  TCP 연결 실패", "fail")

            # ── Step 4a: OCI Discovery ──
            if command_exists("oci"):
                self._set_step("oci_discover", "run", "IP 조회중...")
                self._log("\n[OCI 인스턴스 탐색] IP가 바뀌었을 수 있어 OCI에서 조회합니다...", "info")
                new_ip = self._oci_discover_ip()
                if new_ip and new_ip != self.cfg.ssh_ip:
                    self._log(f"  IP 변경 감지: {self.cfg.ssh_ip} -> {new_ip}", "ok")
                    self.cfg.ssh_ip = new_ip
                    save_config(self.cfg)
                    write_ssh_config(self.cfg, key_path)
                    self._set_step("oci_discover", "ok", f"IP 갱신: {new_ip}")
                    tcp_ok = tcp_open(new_ip, self.cfg.ssh_port)
                    if tcp_ok:
                        self._set_step("tcp", "ok", "새 IP로 연결 성공")
                        self._log(f"  새 IP로 TCP 연결 성공!", "ok")
                    else:
                        self._set_step("tcp", "fail", "새 IP도 연결 실패")
                        self._log("  새 IP로도 연결 불가", "fail")
                elif new_ip:
                    self._set_step("oci_discover", "ok", "IP 동일, 변경 없음")
                    self._log("  IP가 동일합니다. 서버 자체가 꺼져있을 수 있습니다.", "fail")
                else:
                    self._set_step("oci_discover", "fail", "조회 실패")
                    self._log("  OCI 인스턴스 조회 실패", "fail")
            else:
                self._set_step("oci_discover", "skip", "OCI CLI 없음")
                self._log("  OCI CLI가 없어 자동 IP 조회를 건너뜁니다.", "fail")

            if not tcp_ok:
                self._log("\n서버에 접근할 수 없습니다.", "fail")
                self._log("가능한 원인:", "fail")
                self._log("  1. 서버가 꺼져 있음 -> Oracle Cloud Console에서 확인", "fail")
                self._log("  2. 네트워크/방화벽 차단 -> 보안 그룹에서 포트 443 확인", "fail")
                self._log("  3. 인터넷 연결 문제 -> 다른 사이트 접속 확인", "fail")
                for key in ["hostkey", "ssh_auth", "key_register", "sshd_restart", "final"]:
                    self._set_step(key, "skip", "TCP 실패로 건너뜀")
                self._finish(False)
                return
        else:
            self._set_step("tcp", "ok", "연결됨")
            self._log("  TCP 연결 성공", "ok")
            self._set_step("oci_discover", "skip", "TCP 정상 — 불필요")

        # ── Step 5: Host key check ──
        self._set_step("hostkey", "run", "확인중...")
        self._log("\n[호스트 키 확인]", "info")

        test_out, test_ok = ssh_exec(self.cfg, "echo ALIVE", timeout=15)

        if "Host key verification failed" in test_out or "REMOTE HOST IDENTIFICATION HAS CHANGED" in test_out:
            self._log("  호스트 키 충돌 감지 — 자동 수정중...", "info")
            self._remove_known_host(self.cfg.ssh_ip)
            self._set_step("hostkey", "ok", "충돌 수정됨")
            self._log("  known_hosts에서 이전 항목 제거 완료", "ok")
            test_out, test_ok = ssh_exec(self.cfg, "echo ALIVE", timeout=15)
        elif test_ok:
            self._set_step("hostkey", "ok", "정상")
            self._log("  호스트 키 정상", "ok")
        else:
            self._set_step("hostkey", "ok", "해당 없음")

        # ── Step 6: SSH Auth ──
        self._set_step("ssh_auth", "run", "인증 시도중...")
        self._log("\n[SSH 인증]", "info")

        if test_ok and "ALIVE" in test_out:
            self._set_step("ssh_auth", "ok", "인증 성공!")
            self._log("  SSH 인증 성공!", "ok")
            for key in ["key_register", "sshd_restart"]:
                self._set_step(key, "skip", "인증 성공 — 불필요")
            self._do_final_check()
            return

        # Auth failed — diagnose
        self._log(f"  인증 실패: {test_out[:120]}", "fail")

        is_permission_denied = "Permission denied" in test_out
        is_timeout = "timed out" in test_out.lower() or "Timeout" in test_out
        is_conn_reset = "Connection reset" in test_out or "Connection closed" in test_out

        # ── Step 7: Key registration ──
        if is_permission_denied:
            self._set_step("ssh_auth", "fail", "인증 실패 (키 미등록)")
            if command_exists("oci") and self.cfg.inst_id:
                self._set_step("key_register", "run", "OCI로 키 등록중...")
                self._log("\n[키 등록] OCI Instance Agent로 공개키 등록 시도...", "info")
                pubkey = pub_path.read_text(encoding="utf-8").strip()
                ok_reg, msg = register_key_via_oci(self.cfg, pubkey)
                if ok_reg:
                    self._set_step("key_register", "ok", "등록 성공!")
                    self._log(f"  키 등록 성공: {msg}", "ok")
                    self._log("  3초 후 재시도...", "info")
                    time.sleep(3)
                    retry_out, retry_ok = ssh_exec(self.cfg, "echo ALIVE", timeout=15)
                    if retry_ok:
                        self._set_step("ssh_auth", "ok", "재시도 성공!")
                        self._log("  SSH 인증 성공!", "ok")
                        self._set_step("sshd_restart", "skip", "불필요")
                        self._do_final_check()
                        return
                    else:
                        self._log(f"  키 등록 후에도 인증 실패: {retry_out[:80]}", "fail")
                else:
                    self._set_step("key_register", "fail", f"등록 실패: {msg[:40]}")
                    self._log(f"  OCI 키 등록 실패: {msg}", "fail")
            else:
                self._set_step("key_register", "warn", "수동 등록 필요")
                self._log("\n[키 등록] OCI CLI 없음 — 수동 등록이 필요합니다.", "fail")
                pubkey = pub_path.read_text(encoding="utf-8").strip()
                self._log("", "")
                self._log("=== 수동 키 등록 방법 ===", "step")
                self._log(f"공개키: {pubkey}", "info")
                self._log("", "")
                self._log("방법 1) Oracle Cloud Shell에서:", "info")
                self._log(f"  cd ~/repo && git pull && python3 scripts/oracle_recovery/ensure_access.py --repair --register-pubkey '{pubkey}'", "")
                self._log("", "")
                self._log("방법 2) 이미 접속 가능한 다른 PC에서:", "info")
                safe = pubkey.replace("'", "'\\''")
                self._log(f"  ssh g185 \"echo '{safe}' >> ~/.ssh/authorized_keys\"", "")

        # ── Step 8: sshd restart ──
        if is_timeout or is_conn_reset:
            self._set_step("ssh_auth", "fail", "타임아웃/연결 끊김")
            self._set_step("key_register", "skip", "해당 없음")
            if command_exists("oci") and self.cfg.inst_id:
                self._set_step("sshd_restart", "run", "sshd 재시작 중...")
                self._log("\n[sshd 재시작] 서버 SSH 데몬을 원격으로 재시작합니다...", "info")
                ok_restart = self._oci_restart_sshd()
                if ok_restart:
                    self._set_step("sshd_restart", "ok", "재시작 성공")
                    self._log("  sshd 재시작 완료. 5초 후 재시도...", "ok")
                    time.sleep(5)
                    retry_out, retry_ok = ssh_exec(self.cfg, "echo ALIVE", timeout=15)
                    if retry_ok:
                        self._set_step("ssh_auth", "ok", "재시도 성공!")
                        self._log("  SSH 인증 성공!", "ok")
                        self._do_final_check()
                        return
                    else:
                        self._log(f"  sshd 재시작 후에도 실패: {retry_out[:80]}", "fail")
                else:
                    self._set_step("sshd_restart", "fail", "재시작 실패")
                    self._log("  OCI sshd 재시작 실패", "fail")
            else:
                self._set_step("sshd_restart", "skip", "OCI CLI 없음")

        if not is_permission_denied and not is_timeout and not is_conn_reset:
            self._set_step("ssh_auth", "fail", "알 수 없는 오류")
            self._set_step("key_register", "skip", "")
            self._set_step("sshd_restart", "skip", "")

        self._finish(False)

    def _do_final_check(self):
        self._set_step("final", "run", "최종 확인중...")
        self._log("\n[최종 확인]", "info")
        out, ok = ssh_exec(self.cfg, "echo OK && hostname && uptime -p 2>/dev/null", timeout=15)
        if ok:
            self._set_step("final", "ok", "연결 성공!")
            self._log(f"  서버 응답: {out}", "ok")
            self._finish(True)
        else:
            self._set_step("final", "fail", "연결 실패")
            self._log(f"  최종 확인 실패: {out}", "fail")
            self._finish(False)

    def _finish(self, success: bool):
        self.success = success
        self._log("")
        if success:
            self._log("=== 연결 성공! ===", "ok")
            self._log("'SSH 터미널 열기' 버튼을 눌러 접속하거나, 터미널에서 'ssh g185'를 입력하세요.", "ok")
        else:
            self._log("=== 자동 연결 실패 ===", "fail")
            self._log("위의 실패 항목과 안내를 확인해주세요.", "fail")

        def _enable_btns():
            if success:
                self.btn_terminal.configure(state=tk.NORMAL)
        self.win.after(0, _enable_btns)

    def _remove_known_host(self, ip: str):
        known_hosts = pathlib.Path.home() / ".ssh" / "known_hosts"
        if not known_hosts.exists():
            return
        try:
            lines = known_hosts.read_text(encoding="utf-8", errors="replace").splitlines()
            filtered = [line for line in lines if ip not in line]
            if len(filtered) != len(lines):
                known_hosts.write_text("\n".join(filtered) + "\n", encoding="utf-8", newline="\n")
                self._log(f"  known_hosts에서 {ip} 관련 {len(lines) - len(filtered)}줄 제거", "ok")
        except Exception as e:
            self._log(f"  known_hosts 수정 실패: {e}", "fail")

    def _oci_discover_ip(self) -> str | None:
        try:
            auth = oci_auth_args()
            proc = run_local(
                ["oci", "search", "resource", "structured-search",
                 "--region", self.cfg.region,
                 "--query-text", "query instance resources",
                 *auth, "--output", "json"],
                timeout=120,
            )
            if proc.returncode != 0:
                self._log(f"  OCI Search 실패: {proc.stderr.strip()[:100]}", "fail")
                return None
            data = json.loads(proc.stdout)
            items = data.get("data", {}).get("items", [])
            names = ["g185-restored", "g185"]
            candidates = [
                item for item in items
                if item.get("resource-type") == "Instance"
                and item.get("display-name") in names
                and item.get("lifecycle-state") != "TERMINATED"
            ]
            if not candidates:
                self._log("  OCI에서 인스턴스를 찾을 수 없습니다.", "fail")
                return None

            best = sorted(candidates, key=lambda x: (
                0 if x.get("lifecycle-state") == "RUNNING" else 1,
                names.index(x.get("display-name", "")) if x.get("display-name") in names else 99,
            ))[0]

            inst_id = best["identifier"]
            vnic_proc = run_local(
                ["oci", "compute", "instance", "list-vnics",
                 "--region", self.cfg.region, "--instance-id", inst_id,
                 *auth, "--output", "json"],
                timeout=90,
            )
            if vnic_proc.returncode != 0:
                return None
            vnics = json.loads(vnic_proc.stdout).get("data", [])
            public_ip = next((v.get("public-ip") for v in vnics if v.get("public-ip")), None)
            if public_ip:
                self.cfg.inst_id = inst_id
                self.cfg.comp_id = best.get("compartment-id", self.cfg.comp_id)
            return public_ip
        except Exception as e:
            self._log(f"  OCI 탐색 오류: {e}", "fail")
            return None

    def _oci_restart_sshd(self) -> bool:
        script = (
            "set -e; "
            "if command -v systemctl >/dev/null 2>&1; then "
            "sudo systemctl restart sshd || sudo systemctl restart ssh || true; "
            "else sudo service sshd restart || sudo service ssh restart || true; fi"
        )
        body = {
            "compartmentId": self.cfg.comp_id,
            "executionTimeOutInSeconds": 90,
            "displayName": "smart-connect-restart-sshd",
            "target": {"instanceId": self.cfg.inst_id},
            "content": {
                "source": {"sourceType": "TEXT", "text": script},
                "output": {"outputType": "TEXT"},
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(body, fh)
            body_path = fh.name
        try:
            auth = oci_auth_args()
            proc = run_local(
                ["oci", "instance-agent", "command", "create",
                 "--region", self.cfg.region, "--timeout-in-seconds", "90",
                 "--from-json", f"file://{body_path}",
                 *auth, "--output", "json"],
                timeout=90,
            )
            if proc.returncode != 0:
                return False
            cmd_id = json.loads(proc.stdout).get("data", {}).get("id")
            if not cmd_id:
                return False
            for _ in range(12):
                time.sleep(5)
                sp = run_local(
                    ["oci", "instance-agent", "command-execution", "get",
                     "--region", self.cfg.region, "--instance-id", self.cfg.inst_id,
                     "--command-id", cmd_id, *auth, "--output", "json"],
                    timeout=60,
                )
                if sp.returncode != 0:
                    continue
                state = json.loads(sp.stdout).get("data", {}).get("lifecycle-state", "")
                if state == "SUCCEEDED":
                    return True
                if state in {"FAILED", "TIMED_OUT", "CANCELED"}:
                    return False
            return False
        except Exception:
            return False
        finally:
            pathlib.Path(body_path).unlink(missing_ok=True)


# ─── Main App ───

class OracleManagerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Oracle Server Manager")
        self.root.geometry("850x680")
        self.root.minsize(750, 600)
        self.cfg = load_config()
        self.worker = AsyncWorker(root)
        self._connected = False

        self._setup_styles()
        self._build_ui()
        self.root.after(300, self._auto_refresh_dashboard)

    def _setup_styles(self):
        style = ttk.Style()
        mono = _mono_font()
        ui = _ui_font()
        style.configure("Mono.TLabel", font=(mono, 10))
        style.configure("Title.TLabel", font=(ui, 12, "bold"))
        style.configure("Subtitle.TLabel", font=(ui, 10))
        style.configure("Green.TLabel", foreground="#2e7d32", font=(ui, 10, "bold"))
        style.configure("Red.TLabel", foreground="#c62828", font=(ui, 10, "bold"))
        style.configure("Orange.TLabel", foreground="#e65100", font=(ui, 10))
        style.configure("Gray.TLabel", foreground="#757575", font=(ui, 9))
        style.configure("Big.TButton", font=(ui, 11), padding=8)
        style.configure("StatusOK.TLabel", foreground="#2e7d32", font=(ui, 10))
        style.configure("StatusFail.TLabel", foreground="#c62828", font=(ui, 10))

    def _build_ui(self):
        # Status bar (bottom)
        status_frame = ttk.Frame(self.root, padding=(8, 4))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.statusbar = ttk.Label(status_frame, text="", style="Gray.TLabel")
        self.statusbar.pack(side=tk.LEFT)
        self.conn_indicator = ttk.Label(status_frame, text="", style="Gray.TLabel")
        self.conn_indicator.pack(side=tk.RIGHT)

        # Notebook
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self._build_dashboard_tab(nb)
        self._build_setup_tab(nb)
        self._build_deploy_tab(nb)
        self._build_services_tab(nb)
        self._build_remote_tab(nb)
        self._build_settings_tab(nb)

    def _set_status(self, msg: str):
        self.statusbar.configure(text=msg)

    def _set_connected(self, connected: bool):
        self._connected = connected
        if connected:
            self.conn_indicator.configure(
                text=f"[{self.cfg.ssh_ip}:{self.cfg.ssh_port}] 연결됨",
                style="StatusOK.TLabel",
            )
        else:
            self.conn_indicator.configure(
                text=f"[{self.cfg.ssh_ip}:{self.cfg.ssh_port}] 연결 안됨",
                style="StatusFail.TLabel",
            )

    # ═══════════════════════════════════════
    # Dashboard Tab
    # ═══════════════════════════════════════
    def _build_dashboard_tab(self, nb: ttk.Notebook):
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="  대시보드  ")

        # Top bar
        top = ttk.Frame(frame)
        top.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(top, text="서버 대시보드", style="Title.TLabel").pack(side=tk.LEFT)
        btn = ttk.Button(top, text="새로고침", command=self._refresh_dashboard, width=10)
        btn.pack(side=tk.RIGHT)
        Tooltip(btn, "서버에 접속해서 최신 상태를 가져옵니다")

        # Connection status
        conn_frame = ttk.LabelFrame(frame, text="연결 상태", padding=8)
        conn_frame.pack(fill=tk.X, pady=(0, 8))

        self.dash_conn = ttk.Label(conn_frame, text="확인중...", style="Gray.TLabel")
        self.dash_conn.pack(anchor=tk.W)

        # Quick actions
        actions = ttk.Frame(conn_frame)
        actions.pack(fill=tk.X, pady=(6, 0))

        btn_smart = ttk.Button(actions, text="만능 연결", style="Big.TButton",
                               command=self._smart_connect)
        btn_smart.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn_smart, (
            "현재 상황을 자동으로 진단하고 문제를 해결합니다.\n\n"
            "처리하는 상황:\n"
            "  - 새 PC (SSH 키/설정 없음) -> 자동 생성\n"
            "  - 서버 IP 변경 -> OCI에서 최신 IP 조회\n"
            "  - 호스트 키 충돌 -> known_hosts 자동 수정\n"
            "  - 키 미등록 -> OCI로 자동 등록\n"
            "  - sshd 장애 -> 원격 재시작\n\n"
            "어떤 상황인지 몰라도 이 버튼 하나면 됩니다!"
        ))

        btn1 = ttk.Button(actions, text="SSH 터미널 열기", style="Big.TButton",
                          command=lambda: open_ssh_terminal(self.cfg))
        btn1.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn1, "새 터미널 창에서 서버에 SSH 접속합니다.\n접속 후 직접 명령어를 입력할 수 있습니다.")

        # System info
        info_frame = ttk.LabelFrame(frame, text="시스템 정보 (CPU / 메모리 / 디스크)", padding=8)
        info_frame.pack(fill=tk.X, pady=(0, 8))
        self.dash_sysinfo = tk.Text(info_frame, height=5, font=(_mono_font(), 9),
                                    state=tk.DISABLED, wrap=tk.WORD, bg="#f5f5f5",
                                    relief=tk.FLAT)
        self.dash_sysinfo.pack(fill=tk.X)

        # Running strategies
        strat_frame = ttk.LabelFrame(
            frame, text="실행중인 전략 서비스 (emulator)", padding=8)
        strat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.dash_strategies = tk.Text(strat_frame, height=8, font=(_mono_font(), 9),
                                       state=tk.DISABLED, wrap=tk.WORD, bg="#f5f5f5",
                                       relief=tk.FLAT)
        self.dash_strategies.pack(fill=tk.BOTH, expand=True)

        # Running processes
        proc_frame = ttk.LabelFrame(frame, text="주요 프로세스 (메모리 상위)", padding=8)
        proc_frame.pack(fill=tk.BOTH, expand=True)
        self.dash_procs = tk.Text(proc_frame, height=6, font=(_mono_font(), 9),
                                   state=tk.DISABLED, wrap=tk.WORD, bg="#f5f5f5",
                                   relief=tk.FLAT)
        self.dash_procs.pack(fill=tk.BOTH, expand=True)

    def _smart_connect(self):
        def on_done(success):
            if success:
                self._set_connected(True)
                self._refresh_dashboard()
            else:
                self._set_connected(False)
        SmartConnectDialog(self.root, self.cfg, on_done=on_done)

    def _auto_refresh_dashboard(self):
        self._refresh_dashboard()

    def _refresh_dashboard(self):
        self._set_status("대시보드 새로고침 중...")
        self.dash_conn.configure(text="서버에 접속 중...", style="Orange.TLabel")
        self.worker.run(self._fetch_dashboard, self._on_dashboard)

    def _fetch_dashboard(self) -> dict[str, Any]:
        result: dict[str, Any] = {}

        if not tcp_open(self.cfg.ssh_ip, self.cfg.ssh_port):
            result["connected"] = False
            result["error"] = "TCP 연결 실패 — 서버가 꺼져있거나 네트워크 문제"
            return result

        out, ok = ssh_exec(self.cfg, "echo OK", timeout=15)
        if not ok:
            result["connected"] = False
            result["error"] = out
            return result

        result["connected"] = True

        sysinfo, _ = ssh_exec(self.cfg, (
            "echo \"호스트: $(hostname)  |  업타임: $(uptime -p 2>/dev/null || uptime -s)\"; "
            "echo; "
            "echo '--- CPU ---'; "
            "grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs echo 'CPU:'; "
            "echo \"로드: $(cat /proc/loadavg | cut -d' ' -f1-3)\"; "
            "echo; echo '--- 메모리 ---'; free -h | head -2; "
            "echo; echo '--- 디스크 ---'; df -h / 2>/dev/null | tail -1"
        ), timeout=15)
        result["sysinfo"] = sysinfo

        strats, _ = ssh_exec(self.cfg, (
            "systemctl --user list-units --type=service --state=running "
            "--no-legend --no-pager 2>/dev/null | "
            "grep -E 'emulator|paper|live' || echo '(실행중인 전략 서비스 없음)'; "
            "echo; echo '--- 전략 폴더 ---'; "
            "ls -d ~/g*/runtime 2>/dev/null | head -15 || echo '(전략 폴더 없음)'"
        ), timeout=15)
        result["strategies"] = strats

        procs, _ = ssh_exec(self.cfg, (
            "ps aux --sort=-%mem 2>/dev/null | head -10 || "
            "ps aux | head -10"
        ), timeout=15)
        result["procs"] = procs

        return result

    def _on_dashboard(self, result, err):
        if err:
            self._set_status(f"오류: {err}")
            self.dash_conn.configure(text=f"오류: {err}", style="Red.TLabel")
            self._set_connected(False)
            return

        if not result.get("connected"):
            error_msg = result.get("error", "알 수 없는 오류")
            self.dash_conn.configure(text=f"연결 실패: {error_msg}", style="Red.TLabel")
            self._set_connected(False)
            self._set_status("서버 연결 실패")
            self._set_text(self.dash_sysinfo, "(연결 안됨)")
            self._set_text(self.dash_strategies, "(연결 안됨)")
            self._set_text(self.dash_procs, "(연결 안됨)")
            return

        self._set_connected(True)
        self.dash_conn.configure(
            text=f"연결 성공  |  {self.cfg.ssh_user}@{self.cfg.ssh_ip}:{self.cfg.ssh_port}",
            style="Green.TLabel",
        )
        self._set_text(self.dash_sysinfo, result.get("sysinfo", ""))
        self._set_text(self.dash_strategies, result.get("strategies", ""))
        self._set_text(self.dash_procs, result.get("procs", ""))
        self._set_status(f"대시보드 갱신 완료 ({time.strftime('%H:%M:%S')})")

    def _set_text(self, widget: tk.Text, text: str):
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.DISABLED)

    # ═══════════════════════════════════════
    # Setup Tab
    # ═══════════════════════════════════════
    def _build_setup_tab(self, nb: ttk.Notebook):
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="  Setup  ")

        ttk.Label(frame, text="새 PC 셋업", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=(
            "새 PC에서 처음 사용할 때 아래 절차를 따르세요.\n"
            "'원클릭 셋업' 버튼 하나로 1~3단계가 자동 진행됩니다."
        ), style="Gray.TLabel", wraplength=700, justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 10))

        # Steps
        steps_frame = ttk.LabelFrame(frame, text="셋업 단계", padding=10)
        steps_frame.pack(fill=tk.X, pady=(0, 8))

        self.setup_checks: dict[str, ttk.Label] = {}
        steps = [
            ("ssh_key",    "1. SSH 키 생성",    "서버 인증에 필요한 키 파일을 만듭니다 (~/.ssh/id_ed25519)"),
            ("ssh_config", "2. SSH 설정 등록",   "'ssh g185'로 접속 가능하도록 SSH Config에 서버 정보를 등록합니다"),
            ("tcp",        "3. 서버 연결 확인",  f"서버({self.cfg.ssh_ip})에 네트워크 연결이 되는지 확인합니다"),
            ("ssh_auth",   "4. SSH 인증 확인",   "SSH 키로 서버에 로그인할 수 있는지 확인합니다"),
            ("oci_cli",    "5. OCI CLI (선택)",  "Oracle Cloud CLI 설치 여부. 없어도 수동으로 키 등록 가능합니다"),
        ]
        for i, (key, label, desc) in enumerate(steps):
            ttk.Label(steps_frame, text=label, font=(_ui_font(), 10)).grid(
                row=i, column=0, sticky=tk.W, pady=3, padx=(0, 15))
            status_lbl = ttk.Label(steps_frame, text="...", style="Gray.TLabel", width=12)
            status_lbl.grid(row=i, column=1, sticky=tk.W, pady=3, padx=(0, 10))
            self.setup_checks[key] = status_lbl
            desc_lbl = ttk.Label(steps_frame, text=desc, style="Gray.TLabel", wraplength=400)
            desc_lbl.grid(row=i, column=2, sticky=tk.W, pady=3)

        # Buttons
        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=8)

        btn_smart = ttk.Button(btns, text="만능 연결", style="Big.TButton",
                               command=self._smart_connect, width=14)
        btn_smart.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn_smart, "상황을 자동 진단하고 문제를 해결합니다.\n새 PC든, 서버 장애든 이 버튼 하나면 됩니다!")

        btn_setup = ttk.Button(btns, text="원클릭 셋업",
                               command=self._do_full_setup, width=12)
        btn_setup.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn_setup, "SSH 키/설정만 생성합니다. (만능 연결에 포함된 기능)")

        btn_check = ttk.Button(btns, text="상태 확인", command=self._refresh_setup_status, width=10)
        btn_check.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn_check, "현재 설정 상태만 확인합니다. 아무것도 변경하지 않습니다.")

        btn_term = ttk.Button(btns, text="SSH 터미널", command=lambda: open_ssh_terminal(self.cfg), width=10)
        btn_term.pack(side=tk.LEFT)
        Tooltip(btn_term, "새 터미널 창에서 서버에 접속합니다.")

        # Log
        ttk.Label(frame, text="실행 로그:", style="Subtitle.TLabel").pack(anchor=tk.W, pady=(8, 2))
        self.setup_log = scrolledtext.ScrolledText(
            frame, height=10, font=(_mono_font(), 9),
            state=tk.DISABLED, wrap=tk.WORD, bg="#fafafa",
        )
        self.setup_log.pack(fill=tk.BOTH, expand=True)

    def _log(self, msg: str):
        self.setup_log.configure(state=tk.NORMAL)
        self.setup_log.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.setup_log.see(tk.END)
        self.setup_log.configure(state=tk.DISABLED)

    def _set_check(self, key: str, ok: bool | None, text: str = ""):
        lbl = self.setup_checks.get(key)
        if not lbl:
            return
        if ok is True:
            lbl.configure(text=text or "OK", style="Green.TLabel")
        elif ok is False:
            lbl.configure(text=text or "실패", style="Red.TLabel")
        else:
            lbl.configure(text=text or "...", style="Gray.TLabel")

    def _refresh_setup_status(self):
        for key in self.setup_checks:
            self._set_check(key, None, "확인중...")
        self._set_status("셋업 상태 확인중...")
        self.worker.run(self._check_all_status, self._on_status_checked)

    def _check_all_status(self) -> dict[str, tuple[bool, str]]:
        results: dict[str, tuple[bool, str]] = {}

        has_key = _ssh_key_path().exists() and _ssh_pub_path().exists()
        results["ssh_key"] = (has_key, "있음" if has_key else "없음")

        ssh_config = pathlib.Path.home() / ".ssh" / "config"
        has_config = False
        if ssh_config.exists():
            content = ssh_config.read_text(encoding="utf-8", errors="replace")
            has_config = bool(re.search(r"Host\s+g185\b", content))
        results["ssh_config"] = (has_config, "설정됨" if has_config else "없음")

        if self.cfg.ssh_ip:
            tcp_ok = tcp_open(self.cfg.ssh_ip, self.cfg.ssh_port)
            results["tcp"] = (tcp_ok, "연결됨" if tcp_ok else "실패")
        else:
            results["tcp"] = (False, "IP 미설정")

        if has_key and self.cfg.ssh_ip:
            _, ok = ssh_exec(self.cfg, "echo OK", timeout=20)
            results["ssh_auth"] = (ok, "성공" if ok else "실패")
        else:
            results["ssh_auth"] = (False, "확인불가")

        has_oci = command_exists("oci")
        results["oci_cli"] = (has_oci, "설치됨" if has_oci else "없음 (선택)")

        return results

    def _on_status_checked(self, results, err):
        if err:
            self._log(f"상태 확인 오류: {err}")
            return
        for key, (ok, text) in results.items():
            self._set_check(key, ok, text)
        all_ok = all(results[k][0] for k in ["ssh_key", "ssh_config", "tcp", "ssh_auth"])
        self._set_connected(all_ok)
        self._set_status("셋업 상태 확인 완료")

    def _do_full_setup(self):
        self._log("=== 원클릭 셋업 시작 ===")
        self._set_status("셋업 진행중...")
        self.worker.run(self._full_setup_work, self._on_setup_done)

    def _full_setup_work(self) -> list[str]:
        logs: list[str] = []
        key_path = _ssh_key_path()
        pub_path = _ssh_pub_path()

        # Step 1: SSH Key
        if not key_path.exists() or not pub_path.exists():
            logs.append("[1/4] SSH 키 생성중...")
            key_path.parent.mkdir(parents=True, exist_ok=True)
            comment = f"g185@{socket.gethostname()}-{time.strftime('%Y%m%d')}"
            proc = run_local(
                ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", comment],
                timeout=30,
            )
            if proc.returncode != 0:
                logs.append(f"  실패: {proc.stderr.strip()}")
                return logs
            logs.append("  SSH 키 생성 완료")
        else:
            logs.append("[1/4] SSH 키 이미 존재 (건너뜀)")

        # Step 2: SSH Config
        logs.append("[2/4] SSH Config 업데이트중...")
        config_path = write_ssh_config(self.cfg, key_path)
        logs.append(f"  완료: {config_path}")

        # Step 3: TCP check
        logs.append(f"[3/4] TCP 연결 확인: {self.cfg.ssh_ip}:{self.cfg.ssh_port}")
        if not tcp_open(self.cfg.ssh_ip, self.cfg.ssh_port):
            logs.append("  실패 — 서버가 꺼져있거나 네트워크 문제")
            logs.append("")
            logs.append("해결 방법:")
            logs.append("  1. 인터넷 연결을 확인하세요")
            logs.append("  2. Oracle Cloud Console에서 서버가 RUNNING 상태인지 확인하세요")
            logs.append("  3. 방화벽(보안 그룹)에서 포트 443이 열려있는지 확인하세요")
            return logs
        logs.append("  TCP 연결 성공")

        # Step 4: SSH Auth
        logs.append("[4/4] SSH 인증 시도...")
        output, ok = ssh_exec(self.cfg, "echo OK && hostname && date -u", timeout=20)
        if ok:
            logs.append(f"  SSH 접속 성공! ({output.splitlines()[0] if output else ''})")
            logs.append("")
            logs.append("셋업 완료! 이제 'SSH 터미널 열기'로 접속하거나")
            logs.append("터미널에서 'ssh g185' 명령으로 접속할 수 있습니다.")
            return logs

        logs.append(f"  SSH 인증 실패: {output[:100]}")

        # Try OCI key registration
        pubkey = pub_path.read_text(encoding="utf-8").strip()

        if command_exists("oci"):
            logs.append("")
            logs.append("OCI CLI로 공개키 자동 등록 시도...")
            ok_reg, msg = register_key_via_oci(self.cfg, pubkey)
            if ok_reg:
                logs.append(f"  키 등록 성공: {msg}")
                logs.append("  3초 후 SSH 재시도...")
                time.sleep(3)
                output2, ok2 = ssh_exec(self.cfg, "echo OK && hostname", timeout=20)
                if ok2:
                    logs.append(f"  SSH 접속 성공!")
                else:
                    logs.append(f"  SSH 여전히 실패: {output2[:100]}")
            else:
                logs.append(f"  OCI 키 등록 실패: {msg}")
        else:
            logs.append("")
            logs.append("=== 수동 키 등록이 필요합니다 ===")
            logs.append("")
            logs.append("이 PC의 공개키를 서버에 등록해야 합니다.")
            logs.append("아래 방법 중 하나를 선택하세요:")
            logs.append("")
            logs.append("[방법 1] Oracle Cloud Shell에서 실행:")
            logs.append(f"  cd ~/repo && git pull && python3 scripts/oracle_recovery/ensure_access.py --repair --register-pubkey '{pubkey}'")
            logs.append("")
            logs.append("[방법 2] 이미 접속 가능한 다른 PC에서 실행:")
            safe = pubkey.replace("'", "'\\''")
            logs.append(f"  ssh g185 \"echo '{safe}' >> ~/.ssh/authorized_keys\"")
            logs.append("")
            logs.append("공개키 (위 명령에 이미 포함됨):")
            logs.append(f"  {pubkey}")

        return logs

    def _on_setup_done(self, logs, err):
        if err:
            self._log(f"셋업 오류: {err}")
        elif logs:
            for line in logs:
                self._log(line)
        self._log("=== 셋업 완료 ===")
        self._set_status("셋업 완료")
        self._refresh_setup_status()

    # ═══════════════════════════════════════
    # Deploy Tab
    # ═══════════════════════════════════════
    def _build_deploy_tab(self, nb: ttk.Notebook):
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="  프로그램 배포  ")

        ttk.Label(frame, text="프로그램 배포 & 실행", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=(
            "로컬 파일을 서버에 업로드하고, 바로 실행하거나 서비스로 등록할 수 있습니다."
        ), style="Gray.TLabel", wraplength=700, justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 10))

        # ── File selection ──
        file_frame = ttk.LabelFrame(frame, text="1. 파일 선택", padding=8)
        file_frame.pack(fill=tk.X, pady=(0, 6))

        row1 = ttk.Frame(file_frame)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="로컬 파일:").pack(side=tk.LEFT)
        self.deploy_file_var = tk.StringVar()
        self.deploy_file_entry = ttk.Entry(row1, textvariable=self.deploy_file_var,
                                            font=(_mono_font(), 9))
        self.deploy_file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        btn_browse = ttk.Button(row1, text="찾아보기...", command=self._browse_file, width=10)
        btn_browse.pack(side=tk.RIGHT)
        Tooltip(btn_browse, "업로드할 파일을 선택합니다.\n.py, .sh, .js 등 어떤 파일이든 가능합니다.")

        row2 = ttk.Frame(file_frame)
        row2.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(row2, text="프로그램 이름:").pack(side=tk.LEFT)
        self.deploy_name_var = tk.StringVar()
        name_entry = ttk.Entry(row2, textvariable=self.deploy_name_var, width=25)
        name_entry.pack(side=tk.LEFT, padx=6)
        Tooltip(name_entry, "서버에서 사용할 이름입니다.\n영문, 숫자, 하이픈(-) 사용.\n예: my-bot, data-collector, web-api")
        ttk.Label(row2, text="(영문+숫자+하이픈, 예: my-bot)", style="Gray.TLabel").pack(side=tk.LEFT)

        # ── Upload options ──
        opt_frame = ttk.LabelFrame(frame, text="2. 실행 방식 선택", padding=8)
        opt_frame.pack(fill=tk.X, pady=(0, 6))

        self.deploy_mode = tk.StringVar(value="upload_run")
        modes = [
            ("upload_only", "업로드만",
             "파일을 서버에 업로드만 합니다. 실행은 직접 SSH로 접속해서 하세요."),
            ("upload_run", "업로드 + 즉시 실행",
             "파일을 업로드한 뒤 바로 실행하고, 결과를 보여줍니다.\n서버를 닫으면 종료됩니다. (일회성 작업용)"),
            ("upload_service", "업로드 + 서비스 등록 (백그라운드 상시 실행)",
             "파일을 업로드하고 systemd 서비스로 등록합니다.\n서버가 재시작되어도 자동으로 다시 실행됩니다.\n(봇, 서버, 크롤러 등 계속 돌아가야 하는 프로그램용)"),
        ]
        for val, label, tip in modes:
            rb = ttk.Radiobutton(opt_frame, text=label, variable=self.deploy_mode, value=val)
            rb.pack(anchor=tk.W, pady=2)
            Tooltip(rb, tip)

        # ── Service options (shown when service mode) ──
        svc_opts = ttk.LabelFrame(frame, text="3. 서비스 옵션 (서비스 등록 시에만 해당)", padding=8)
        svc_opts.pack(fill=tk.X, pady=(0, 6))

        row_cmd = ttk.Frame(svc_opts)
        row_cmd.pack(fill=tk.X, pady=2)
        ttk.Label(row_cmd, text="실행 명령:").pack(side=tk.LEFT)
        self.deploy_cmd_var = tk.StringVar(value="python3")
        cmd_entry = ttk.Entry(row_cmd, textvariable=self.deploy_cmd_var, width=40,
                              font=(_mono_font(), 9))
        cmd_entry.pack(side=tk.LEFT, padx=6)
        Tooltip(cmd_entry, (
            "파일을 실행할 명령어입니다.\n"
            "  Python: python3\n"
            "  Node.js: node\n"
            "  Shell: bash\n"
            "  직접 실행: ./  (chmod +x 자동 적용)"
        ))
        ttk.Label(row_cmd, text="+ 파일명 (자동 추가됨)", style="Gray.TLabel").pack(side=tk.LEFT)

        row_restart = ttk.Frame(svc_opts)
        row_restart.pack(fill=tk.X, pady=2)
        self.deploy_restart_var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(row_restart, text="오류 시 자동 재시작 (10초 후)",
                             variable=self.deploy_restart_var)
        cb.pack(side=tk.LEFT)
        Tooltip(cb, "프로그램이 크래시하면 10초 후 자동으로 다시 시작합니다.\n봇이나 서버처럼 항상 돌아가야 하는 프로그램에 권장합니다.")

        row_env = ttk.Frame(svc_opts)
        row_env.pack(fill=tk.X, pady=2)
        ttk.Label(row_env, text="환경변수:").pack(side=tk.LEFT)
        self.deploy_env_var = tk.StringVar()
        env_entry = ttk.Entry(row_env, textvariable=self.deploy_env_var, width=50,
                              font=(_mono_font(), 9))
        env_entry.pack(side=tk.LEFT, padx=6)
        Tooltip(env_entry, "환경변수를 설정합니다. (선택사항)\n형식: KEY1=value1 KEY2=value2\n예: API_KEY=abc123 DEBUG=true")

        # ── Action buttons ──
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=6)

        btn_deploy = ttk.Button(btn_frame, text="배포 실행", style="Big.TButton",
                                command=self._do_deploy, width=14)
        btn_deploy.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn_deploy, "위에서 선택한 방식으로 파일을 배포합니다.")

        btn_list = ttk.Button(btn_frame, text="배포된 프로그램 목록",
                              command=self._list_deployed, width=18)
        btn_list.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn_list, "서버에 서비스로 등록된 프로그램 목록을 보여줍니다.")

        btn_remove = ttk.Button(btn_frame, text="서비스 제거",
                                command=self._remove_deployed, width=12)
        btn_remove.pack(side=tk.LEFT)
        Tooltip(btn_remove, "프로그램 이름을 입력하고 이 버튼을 누르면\n해당 서비스를 중지하고 제거합니다.")

        # ── Output ──
        self.deploy_output = scrolledtext.ScrolledText(
            frame, font=(_mono_font(), 9), state=tk.DISABLED,
            wrap=tk.WORD, bg="#1e1e1e", fg="#cccccc",
        )
        self.deploy_output.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.deploy_output.tag_configure("ok", foreground="#4ec9b0")
        self.deploy_output.tag_configure("fail", foreground="#f44747")
        self.deploy_output.tag_configure("info", foreground="#569cd6")
        self.deploy_output.tag_configure("cmd", foreground="#dcdcaa")

    def _deploy_log(self, msg: str, tag: str = ""):
        self.deploy_output.configure(state=tk.NORMAL)
        if tag:
            self.deploy_output.insert(tk.END, msg + "\n", tag)
        else:
            self.deploy_output.insert(tk.END, msg + "\n")
        self.deploy_output.see(tk.END)
        self.deploy_output.configure(state=tk.DISABLED)

    def _browse_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="서버에 업로드할 파일 선택",
            filetypes=[
                ("Python", "*.py"),
                ("Shell Script", "*.sh"),
                ("JavaScript/Node", "*.js *.ts"),
                ("모든 파일", "*.*"),
            ],
        )
        if path:
            self.deploy_file_var.set(path)
            name = self.deploy_name_var.get()
            if not name:
                stem = pathlib.Path(path).stem
                safe = re.sub(r"[^a-zA-Z0-9_-]", "-", stem).strip("-").lower()
                self.deploy_name_var.set(safe or "my-program")

            ext = pathlib.Path(path).suffix.lower()
            cmd_map = {
                ".py": "python3",
                ".sh": "bash",
                ".js": "node",
                ".ts": "npx ts-node",
                ".rb": "ruby",
                ".go": "go run",
            }
            if ext in cmd_map:
                self.deploy_cmd_var.set(cmd_map[ext])

    def _validate_deploy(self) -> tuple[str, str] | None:
        local_file = self.deploy_file_var.get().strip()
        name = self.deploy_name_var.get().strip()
        if not local_file:
            messagebox.showwarning("파일 선택", "배포할 파일을 선택하세요.")
            return None
        if not pathlib.Path(local_file).exists():
            messagebox.showerror("파일 없음", f"파일을 찾을 수 없습니다:\n{local_file}")
            return None
        if not name:
            messagebox.showwarning("이름 입력", "프로그램 이름을 입력하세요.\n영문+숫자+하이픈 (예: my-bot)")
            return None
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name):
            messagebox.showwarning("이름 형식", "이름은 영문+숫자+하이픈만 사용 가능합니다.\n예: my-bot, data-collector")
            return None
        return local_file, name

    def _do_deploy(self):
        result = self._validate_deploy()
        if not result:
            return
        local_file, name = result
        mode = self.deploy_mode.get()

        self.deploy_output.configure(state=tk.NORMAL)
        self.deploy_output.delete("1.0", tk.END)
        self.deploy_output.configure(state=tk.DISABLED)

        self._deploy_log(f"=== 배포 시작: {name} ({mode}) ===", "cmd")
        self._set_status(f"배포중: {name}")

        self.worker.run(
            lambda: self._deploy_work(local_file, name, mode),
            self._on_deploy_done,
        )

    def _deploy_work(self, local_file: str, name: str, mode: str) -> list[tuple[str, str]]:
        logs: list[tuple[str, str]] = []
        filename = pathlib.Path(local_file).name
        remote_dir = f"/home/{self.cfg.ssh_user}/{name}"
        remote_path = f"{remote_dir}/{filename}"

        # Step 1: Create directory
        logs.append(("[1] 서버에 디렉토리 생성...", "info"))
        out, ok = ssh_exec(self.cfg, f"mkdir -p {remote_dir}", timeout=15)
        if not ok:
            logs.append((f"  디렉토리 생성 실패: {out}", "fail"))
            return logs
        logs.append((f"  {remote_dir} 생성됨", "ok"))

        # Step 2: Upload file
        logs.append(("\n[2] 파일 업로드...", "info"))
        logs.append((f"  {local_file} -> {remote_path}", ""))
        out, ok = scp_upload(self.cfg, local_file, remote_path, timeout=120)
        if not ok:
            logs.append((f"  업로드 실패: {out}", "fail"))
            return logs
        logs.append(("  업로드 완료", "ok"))

        # Make executable
        ssh_exec(self.cfg, f"chmod +x {remote_path}", timeout=10)

        if mode == "upload_only":
            logs.append(("\n업로드 완료!", "ok"))
            logs.append((f"서버에서 직접 실행하려면: ssh {self.cfg.ssh_host}", "info"))
            logs.append((f"  cd {remote_dir} && {self.deploy_cmd_var.get()} {filename}", ""))
            return logs

        if mode == "upload_run":
            # Step 3: Run immediately
            run_cmd = self.deploy_cmd_var.get().strip()
            full_cmd = f"cd {remote_dir} && {run_cmd} {filename} 2>&1"
            logs.append((f"\n[3] 실행: {full_cmd}", "info"))
            out, ok = ssh_exec(self.cfg, full_cmd, timeout=60)
            logs.append((out, "ok" if ok else "fail"))
            if ok:
                logs.append(("\n실행 완료!", "ok"))
            else:
                logs.append(("\n실행 실패", "fail"))
            return logs

        if mode == "upload_service":
            # Step 3: Create systemd service
            run_cmd = self.deploy_cmd_var.get().strip()
            restart = "on-failure" if self.deploy_restart_var.get() else "no"
            env_str = self.deploy_env_var.get().strip()

            env_lines = ""
            if env_str:
                for pair in env_str.split():
                    if "=" in pair:
                        env_lines += f"Environment={pair}\n"

            service_unit = (
                f"[Unit]\n"
                f"Description={name} (Oracle Manager 배포)\n"
                f"After=network-online.target\n"
                f"Wants=network-online.target\n"
                f"\n"
                f"[Service]\n"
                f"Type=simple\n"
                f"WorkingDirectory={remote_dir}\n"
                f"ExecStart=/usr/bin/env {run_cmd} {remote_path}\n"
                f"Restart={restart}\n"
                f"RestartSec=10\n"
                f"StandardOutput=journal\n"
                f"StandardError=journal\n"
                f"{env_lines}"
                f"\n"
                f"[Install]\n"
                f"WantedBy=default.target\n"
            )

            service_name = f"{name}.service"
            service_path = f"/home/{self.cfg.ssh_user}/.config/systemd/user/{service_name}"

            logs.append((f"\n[3] 서비스 등록: {service_name}", "info"))

            # Write service file
            safe_unit = service_unit.replace("'", "'\\''")
            create_cmd = (
                f"mkdir -p ~/.config/systemd/user && "
                f"cat > {service_path} << 'UNIT_EOF'\n{service_unit}UNIT_EOF"
            )
            out, ok = ssh_exec(self.cfg, create_cmd, timeout=15)
            if not ok:
                logs.append((f"  서비스 파일 생성 실패: {out}", "fail"))
                return logs
            logs.append(("  서비스 파일 생성됨", "ok"))

            # Reload and enable
            logs.append(("\n[4] 서비스 활성화...", "info"))
            out, ok = ssh_exec(self.cfg,
                f"systemctl --user daemon-reload && "
                f"systemctl --user enable {service_name} && "
                f"systemctl --user start {service_name}",
                timeout=20)
            if not ok:
                logs.append((f"  서비스 시작 실패: {out}", "fail"))
                return logs
            logs.append(("  서비스 활성화 + 시작 완료", "ok"))

            # Check status
            time.sleep(1)
            status_out, _ = ssh_exec(self.cfg,
                f"systemctl --user status {service_name} --no-pager 2>/dev/null | head -10",
                timeout=10)
            logs.append((f"\n[상태]\n{status_out}", ""))

            logs.append(("\n서비스 등록 완료!", "ok"))
            logs.append(("", ""))
            logs.append(("관리 명령어:", "info"))
            logs.append((f"  상태 확인: ssh {self.cfg.ssh_host} systemctl --user status {service_name}", ""))
            logs.append((f"  로그 보기: ssh {self.cfg.ssh_host} journalctl --user -u {service_name} -f", ""))
            logs.append((f"  중지:     ssh {self.cfg.ssh_host} systemctl --user stop {service_name}", ""))
            logs.append((f"  재시작:   ssh {self.cfg.ssh_host} systemctl --user restart {service_name}", ""))
            logs.append(("", ""))
            logs.append(("또는 '서비스 관리' 탭에서 GUI로 제어할 수 있습니다.", "info"))
            return logs

        return logs

    def _on_deploy_done(self, logs, err):
        if err:
            self._deploy_log(f"오류: {err}", "fail")
        elif logs:
            for msg, tag in logs:
                self._deploy_log(msg, tag)
        self._set_status("배포 완료")

    def _list_deployed(self):
        self.deploy_output.configure(state=tk.NORMAL)
        self.deploy_output.delete("1.0", tk.END)
        self.deploy_output.configure(state=tk.DISABLED)
        self._deploy_log("배포된 프로그램 조회중...", "info")
        self.worker.run(
            lambda: ssh_exec(self.cfg, (
                "echo '=== 서비스로 등록된 프로그램 ==='; "
                "systemctl --user list-unit-files --type=service --no-legend --no-pager 2>/dev/null | "
                "grep -v '@' || echo '(서비스 없음)'; "
                "echo; echo '=== 현재 실행중 ==='; "
                "systemctl --user list-units --type=service --state=running "
                "--no-legend --no-pager 2>/dev/null || echo '(없음)'; "
                "echo; echo '=== 프로그램 폴더 (~/에 배포된 것들) ==='; "
                "for d in /home/opc/*/; do "
                "  name=$(basename $d); "
                "  files=$(ls $d 2>/dev/null | head -3 | tr '\\n' ', '); "
                "  svc_state=$(systemctl --user is-active ${name}.service 2>/dev/null || echo '-'); "
                "  printf '  %-20s  서비스: %-10s  파일: %s\\n' \"$name\" \"$svc_state\" \"$files\"; "
                "done 2>/dev/null || echo '(폴더 없음)'"
            ), timeout=20),
            lambda result, err: self._on_list_deployed(result, err),
        )

    def _on_list_deployed(self, result, err):
        if err:
            self._deploy_log(f"조회 오류: {err}", "fail")
        elif result:
            output, ok = result
            self._deploy_log(output, "" if ok else "fail")

    def _remove_deployed(self):
        name = self.deploy_name_var.get().strip()
        if not name:
            messagebox.showinfo("이름 입력", "제거할 프로그램의 이름을 '프로그램 이름' 칸에 입력하세요.")
            return
        if not messagebox.askyesno("서비스 제거",
                f"'{name}' 서비스를 중지하고 제거하시겠습니까?\n\n"
                f"  - 서비스 중지 + 비활성화\n"
                f"  - 서비스 파일 삭제\n"
                f"  - 프로그램 폴더(~/{name}/)는 유지됩니다"):
            return
        self._deploy_log(f"\n=== {name} 서비스 제거 ===", "cmd")
        service_name = f"{name}.service"
        self.worker.run(
            lambda: ssh_exec(self.cfg, (
                f"systemctl --user stop {service_name} 2>/dev/null; "
                f"systemctl --user disable {service_name} 2>/dev/null; "
                f"rm -f ~/.config/systemd/user/{service_name}; "
                f"systemctl --user daemon-reload; "
                f"echo '서비스 제거 완료: {service_name}'; "
                f"echo '프로그램 폴더 ~/{ name }/ 는 유지됩니다. 삭제하려면:'; "
                f"echo '  ssh {self.cfg.ssh_host} rm -rf ~/{name}/'"
            ), timeout=15),
            lambda result, err: self._on_remove_done(result, err),
        )

    def _on_remove_done(self, result, err):
        if err:
            self._deploy_log(f"제거 오류: {err}", "fail")
        elif result:
            output, ok = result
            self._deploy_log(output, "ok" if ok else "fail")

    # ═══════════════════════════════════════
    # Services Tab
    # ═══════════════════════════════════════
    def _build_services_tab(self, nb: ttk.Notebook):
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="  서비스 관리  ")

        ttk.Label(frame, text="서버 서비스 관리", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=(
            "서버에서 실행중인 서비스(전략 emulator 등)를 조회하고 제어합니다.\n"
            "서비스를 선택한 후 오른쪽 버튼으로 시작/중지/재시작/로그 확인이 가능합니다."
        ), style="Gray.TLabel", wraplength=700, justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 10))

        # Content area
        content = ttk.Frame(frame)
        content.pack(fill=tk.BOTH, expand=True)

        # Service list (left)
        list_frame = ttk.Frame(content)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        top_btns = ttk.Frame(list_frame)
        top_btns.pack(fill=tk.X, pady=(0, 5))
        btn_refresh = ttk.Button(top_btns, text="서비스 목록 가져오기", command=self._refresh_services, width=20)
        btn_refresh.pack(side=tk.LEFT)
        Tooltip(btn_refresh, "서버에 접속해서 현재 등록된 모든 서비스 목록을 가져옵니다")

        self.svc_filter_var = tk.StringVar(value="emulator")
        filter_frame = ttk.Frame(top_btns)
        filter_frame.pack(side=tk.RIGHT)
        ttk.Label(filter_frame, text="필터:").pack(side=tk.LEFT, padx=(0, 4))
        for text, val in [("전략만", "emulator"), ("전체", "")]:
            ttk.Radiobutton(filter_frame, text=text, variable=self.svc_filter_var,
                           value=val, command=self._apply_svc_filter).pack(side=tk.LEFT, padx=2)

        cols = ("name", "sub_state", "active_state", "description")
        self.svc_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=16)
        self.svc_tree.heading("name", text="서비스명")
        self.svc_tree.heading("sub_state", text="상태")
        self.svc_tree.heading("active_state", text="Active")
        self.svc_tree.heading("description", text="설명")
        self.svc_tree.column("name", width=220)
        self.svc_tree.column("sub_state", width=80)
        self.svc_tree.column("active_state", width=70)
        self.svc_tree.column("description", width=180)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.svc_tree.yview)
        self.svc_tree.configure(yscrollcommand=sb.set)
        self.svc_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)

        self._all_services: list[tuple[str, str, str, str]] = []

        # Buttons (right)
        btn_panel = ttk.LabelFrame(content, text="제어", padding=10)
        btn_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        buttons = [
            ("Start",   self._svc_start,   "선택한 서비스를 시작합니다"),
            ("Stop",    self._svc_stop,    "선택한 서비스를 중지합니다"),
            ("Restart", self._svc_restart, "선택한 서비스를 재시작합니다"),
            ("로그 보기", self._svc_logs,   "선택한 서비스의 최근 로그를 봅니다"),
        ]
        for text, cmd, tip in buttons:
            btn = ttk.Button(btn_panel, text=text, command=cmd, width=12)
            btn.pack(pady=4)
            Tooltip(btn, tip)

        ttk.Separator(btn_panel).pack(fill=tk.X, pady=8)

        btn_all_status = ttk.Button(btn_panel, text="전체 상태", command=self._svc_show_all_status, width=12)
        btn_all_status.pack(pady=4)
        Tooltip(btn_all_status, "모든 전략 서비스의 실행 상태를 한눈에 보여줍니다")

    def _refresh_services(self):
        self._set_status("서비스 목록 조회중...")
        self.worker.run(self._fetch_services, self._on_services_fetched)

    def _fetch_services(self) -> list[tuple[str, str, str, str]]:
        output, ok = ssh_exec(
            self.cfg,
            "systemctl --user list-units --type=service --all "
            "--no-legend --no-pager --plain 2>/dev/null",
            timeout=20,
        )
        if not ok:
            return [("(SSH 연결 실패)", "", "", output[:80])]
        services = []
        for line in output.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 3:
                name = parts[0].replace(".service", "")
                active = parts[2] if len(parts) > 2 else ""
                sub = parts[3] if len(parts) > 3 else ""
                desc = parts[4] if len(parts) > 4 else ""
                services.append((name, sub, active, desc))
        return services or [("(서비스 없음)", "", "", "")]

    def _on_services_fetched(self, services, err):
        if err:
            self._set_status(f"서비스 조회 오류: {err}")
            return
        self._all_services = services
        self._apply_svc_filter()
        self._set_status(f"서비스 {len(services)}개 조회됨")

    def _apply_svc_filter(self):
        self.svc_tree.delete(*self.svc_tree.get_children())
        filt = self.svc_filter_var.get()
        for name, sub, active, desc in self._all_services:
            if filt and filt not in name.lower():
                continue
            tags = ()
            if sub == "running":
                tags = ("running",)
            elif sub in ("dead", "failed"):
                tags = ("stopped",)
            self.svc_tree.insert("", tk.END, values=(name, sub, active, desc), tags=tags)
        self.svc_tree.tag_configure("running", foreground="#2e7d32")
        self.svc_tree.tag_configure("stopped", foreground="#757575")

    def _selected_service(self) -> str | None:
        sel = self.svc_tree.selection()
        if not sel:
            messagebox.showinfo("서비스 선택", "먼저 목록에서 서비스를 클릭해서 선택하세요.")
            return None
        name = self.svc_tree.item(sel[0])["values"][0]
        if name.startswith("("):
            return None
        return name

    def _svc_action(self, action: str):
        svc = self._selected_service()
        if not svc:
            return
        svc_unit = svc if svc.endswith(".service") else f"{svc}.service"
        self._set_status(f"서비스 {action}: {svc}")
        self.worker.run(
            lambda: ssh_exec(self.cfg, f"systemctl --user {action} {svc_unit}", timeout=20),
            lambda result, err: self._on_svc_action(action, svc, result, err),
        )

    def _on_svc_action(self, action, svc, result, err):
        if err:
            messagebox.showerror("오류", f"{action} 실패: {err}")
        elif result:
            output, ok = result
            if ok:
                self._set_status(f"{svc} {action} 성공")
            else:
                messagebox.showwarning(f"{action} 실패", output[:300])
        self._refresh_services()

    def _svc_start(self):
        self._svc_action("start")

    def _svc_stop(self):
        svc = self._selected_service()
        if not svc:
            return
        if messagebox.askyesno("서비스 중지", f"'{svc}' 서비스를 중지하시겠습니까?"):
            self._svc_action("stop")

    def _svc_restart(self):
        self._svc_action("restart")

    def _svc_logs(self):
        svc = self._selected_service()
        if not svc:
            return
        svc_unit = svc if svc.endswith(".service") else f"{svc}.service"
        self._set_status(f"로그 조회: {svc}")
        self.worker.run(
            lambda: ssh_exec(self.cfg, (
                f"journalctl --user -u {svc_unit} -n 80 --no-pager 2>/dev/null || "
                f"echo '(journalctl 사용 불가)'; "
                f"echo; echo '--- 파일 로그 ---'; "
                f"ls -la ~/{svc.split('-')[0]}/runtime/*.log 2>/dev/null | tail -5; "
                f"echo; tail -30 ~/{svc.split('-')[0]}/runtime/*.log 2>/dev/null || "
                f"echo '(파일 로그 없음)'"
            ), timeout=20),
            lambda result, err: self._show_log_window(svc, result, err),
        )

    def _show_log_window(self, svc, result, err):
        win = tk.Toplevel(self.root)
        win.title(f"로그: {svc}")
        win.geometry("800x500")
        text = scrolledtext.ScrolledText(win, font=(_mono_font(), 9), wrap=tk.WORD, bg="#1e1e1e", fg="#d4d4d4")
        text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        if err:
            text.insert(tk.END, f"오류: {err}")
        elif result:
            output, _ = result
            text.insert(tk.END, output)
        text.configure(state=tk.DISABLED)

    def _svc_show_all_status(self):
        self._set_status("전체 전략 상태 조회중...")
        self.worker.run(
            lambda: ssh_exec(self.cfg, (
                "echo '=== 실행중인 전략 서비스 ==='; "
                "systemctl --user list-units --type=service --state=running "
                "--no-legend --no-pager 2>/dev/null | grep -i emulator || "
                "echo '(없음)'; "
                "echo; echo '=== 중지된 전략 서비스 ==='; "
                "systemctl --user list-units --type=service --state=dead "
                "--no-legend --no-pager 2>/dev/null | grep -i emulator || "
                "echo '(없음)'; "
                "echo; echo '=== 전략 폴더 & 최근 활동 ==='; "
                "for d in ~/g*/runtime; do "
                "  name=$(basename $(dirname $d)); "
                "  latest=$(ls -t $d/*.json 2>/dev/null | head -1); "
                "  if [ -n \"$latest\" ]; then "
                "    mod=$(stat -c '%y' \"$latest\" 2>/dev/null | cut -d. -f1); "
                "    echo \"  $name  최근: $mod  ($latest)\"; "
                "  else echo \"  $name  (데이터 없음)\"; fi; "
                "done 2>/dev/null || echo '(전략 폴더 없음)'"
            ), timeout=25),
            lambda result, err: self._show_log_window("전체 전략 상태", result, err),
        )

    # ═══════════════════════════════════════
    # Remote Execute Tab
    # ═══════════════════════════════════════
    def _build_remote_tab(self, nb: ttk.Notebook):
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="  원격 실행  ")

        ttk.Label(frame, text="원격 명령 실행", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=(
            "서버에서 명령어를 실행하고 결과를 확인합니다.\n"
            "자주 쓰는 명령은 아래 버튼을 클릭하세요. 직접 입력도 가능합니다."
        ), style="Gray.TLabel", wraplength=700, justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 10))

        # Preset buttons with descriptions
        presets_frame = ttk.LabelFrame(frame, text="자주 쓰는 명령", padding=8)
        presets_frame.pack(fill=tk.X, pady=(0, 8))

        preset_cmds = [
            ("메모리 확인",     "free -h",
             "서버의 RAM 사용량을 확인합니다"),
            ("디스크 확인",     "df -h / /home 2>/dev/null",
             "디스크 용량과 사용률을 확인합니다"),
            ("CPU / 부하",     "uptime && echo && cat /proc/loadavg",
             "서버 부하(load average)를 확인합니다"),
            ("프로세스 목록",   "ps aux --sort=-%mem | head -15",
             "메모리를 많이 쓰는 상위 프로세스를 보여줍니다"),
            ("서비스 목록",     "systemctl --user list-units --type=service --no-pager",
             "등록된 사용자 서비스 전체 목록을 보여줍니다"),
            ("네트워크 포트",   "ss -tlnp 2>/dev/null | head -20 || netstat -tlnp 2>/dev/null | head -20",
             "현재 열려있는 네트워크 포트를 보여줍니다"),
            ("최근 로그인",     "last -10 2>/dev/null || echo '(last 명령 없음)'",
             "최근 10건의 SSH 로그인 기록을 보여줍니다"),
            ("전략 폴더",       "ls -la ~/g*/runtime/ 2>/dev/null | head -30 || echo '(전략 폴더 없음)'",
             "서버에 배포된 전략 폴더 목록을 보여줍니다"),
            ("cron 작업",       "crontab -l 2>/dev/null || echo '(cron 없음)'",
             "등록된 cron 자동실행 작업을 보여줍니다"),
        ]

        for i, (label, cmd, tip) in enumerate(preset_cmds):
            btn = ttk.Button(presets_frame, text=label, width=14,
                             command=lambda c=cmd: self._run_remote_cmd(c))
            btn.grid(row=i // 3, column=i % 3, padx=4, pady=3, sticky=tk.EW)
            Tooltip(btn, tip)

        for col in range(3):
            presets_frame.columnconfigure(col, weight=1)

        # Custom command input
        input_frame = ttk.LabelFrame(frame, text="직접 입력", padding=6)
        input_frame.pack(fill=tk.X, pady=(0, 5))

        self.cmd_entry = ttk.Entry(input_frame, font=(_mono_font(), 10))
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.cmd_entry.insert(0, "")
        self.cmd_entry.bind("<Return>", lambda e: self._run_remote_cmd(self.cmd_entry.get()))

        btn_run = ttk.Button(input_frame, text="실행", width=8,
                             command=lambda: self._run_remote_cmd(self.cmd_entry.get()))
        btn_run.pack(side=tk.RIGHT, padx=(0, 5))
        Tooltip(btn_run, "입력한 명령어를 서버에서 실행합니다 (Enter 키로도 실행)")

        btn_clear = ttk.Button(input_frame, text="지우기", width=6, command=self._clear_remote_output)
        btn_clear.pack(side=tk.RIGHT)
        Tooltip(btn_clear, "출력 화면을 지웁니다")

        # Output
        self.remote_output = scrolledtext.ScrolledText(
            frame, font=(_mono_font(), 9), state=tk.DISABLED,
            wrap=tk.WORD, bg="#1e1e1e", fg="#d4d4d4",
        )
        self.remote_output.pack(fill=tk.BOTH, expand=True)
        self.remote_output.tag_configure("cmd", foreground="#569cd6")
        self.remote_output.tag_configure("error", foreground="#f44747")
        self.remote_output.tag_configure("info", foreground="#6a9955")

    def _run_remote_cmd(self, cmd: str):
        cmd = cmd.strip()
        if not cmd:
            return
        self.remote_output.configure(state=tk.NORMAL)
        self.remote_output.insert(tk.END, f"\n$ {cmd}\n", "cmd")
        self.remote_output.configure(state=tk.DISABLED)
        self._set_status(f"명령 실행중: {cmd[:40]}...")
        self.worker.run(
            lambda: ssh_exec(self.cfg, cmd, timeout=30),
            self._on_remote_cmd_done,
        )

    def _on_remote_cmd_done(self, result, err):
        self.remote_output.configure(state=tk.NORMAL)
        if err:
            self.remote_output.insert(tk.END, f"오류: {err}\n", "error")
        elif result:
            output, ok = result
            if ok:
                self.remote_output.insert(tk.END, output + "\n")
            else:
                self.remote_output.insert(tk.END, output + "\n", "error")
        self.remote_output.see(tk.END)
        self.remote_output.configure(state=tk.DISABLED)
        self._set_status("명령 실행 완료")

    def _clear_remote_output(self):
        self.remote_output.configure(state=tk.NORMAL)
        self.remote_output.delete("1.0", tk.END)
        self.remote_output.configure(state=tk.DISABLED)

    # ═══════════════════════════════════════
    # Settings Tab
    # ═══════════════════════════════════════
    def _build_settings_tab(self, nb: ttk.Notebook):
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="  설정  ")

        ttk.Label(frame, text="서버 설정", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=(
            "서버 접속에 필요한 정보를 관리합니다.\n"
            "보통은 수정할 필요가 없지만, 서버 IP가 바뀌었을 때 여기서 업데이트하세요."
        ), style="Gray.TLabel", wraplength=700, justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 10))

        form = ttk.LabelFrame(frame, text="서버 접속 정보 (config.env)", padding=10)
        form.pack(fill=tk.X)

        self.settings_vars: dict[str, tk.StringVar] = {}
        fields = [
            ("SSH 별칭",         "ssh_host", self.cfg.ssh_host,
             "SSH 접속 시 사용할 이름 (ssh g185)"),
            ("SSH 사용자",       "ssh_user", self.cfg.ssh_user,
             "서버 로그인 계정 (보통 opc)"),
            ("서버 IP",          "ssh_ip", self.cfg.ssh_ip,
             "Oracle Cloud 인스턴스의 공개 IP"),
            ("SSH 포트",         "ssh_port", self.cfg.ssh_port,
             "SSH 연결 포트 (보통 443 또는 22)"),
            ("리전",             "region", self.cfg.region,
             "Oracle Cloud 리전 (예: ap-chuncheon-1)"),
            ("Instance OCID",   "inst_id", self.cfg.inst_id,
             "Oracle Cloud 인스턴스 고유 ID (OCI 키 등록 시 필요)"),
            ("Compartment OCID", "comp_id", self.cfg.comp_id,
             "Oracle Cloud 컴파트먼트 ID (OCI 키 등록 시 필요)"),
        ]
        for i, (label, key, default, desc) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky=tk.W, pady=3)
            var = tk.StringVar(value=default)
            self.settings_vars[key] = var
            width = 55 if "ocid" in key.lower() or "inst" in key else 25
            entry = ttk.Entry(form, textvariable=var, width=width)
            entry.grid(row=i, column=1, sticky=tk.W, padx=(10, 10), pady=3)
            ttk.Label(form, text=desc, style="Gray.TLabel").grid(
                row=i, column=2, sticky=tk.W, pady=3)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=10)

        btn_save = ttk.Button(btn_frame, text="저장", command=self._save_settings, width=10)
        btn_save.pack(side=tk.LEFT, padx=(0, 8))
        Tooltip(btn_save, "변경사항을 config.env 파일에 저장합니다")

        btn_reload = ttk.Button(btn_frame, text="다시 불러오기", command=self._reload_settings, width=12)
        btn_reload.pack(side=tk.LEFT)
        Tooltip(btn_reload, "config.env 파일에서 설정을 다시 읽어옵니다")

        # SSH Key info
        key_frame = ttk.LabelFrame(frame, text="SSH 키 정보", padding=10)
        key_frame.pack(fill=tk.X, pady=(10, 0))

        key_path = _ssh_key_path()
        pub_path = _ssh_pub_path()

        ttk.Label(key_frame, text=f"비밀키 경로: {key_path}").pack(anchor=tk.W)
        ttk.Label(key_frame, text=f"공개키 경로: {pub_path}").pack(anchor=tk.W)

        if pub_path.exists():
            pubkey = pub_path.read_text(encoding="utf-8").strip()
            ttk.Label(key_frame, text=(
                "\n공개키 내용 (서버에 수동 등록할 때 아래 내용을 복사하세요):"
            ), style="Gray.TLabel").pack(anchor=tk.W)
            pub_entry = ttk.Entry(key_frame, width=85, font=(_mono_font(), 8))
            pub_entry.insert(0, pubkey)
            pub_entry.configure(state="readonly")
            pub_entry.pack(anchor=tk.W, pady=(2, 0))

            btn_copy = ttk.Button(key_frame, text="공개키 복사",
                                  command=lambda: self._copy_to_clipboard(pubkey), width=12)
            btn_copy.pack(anchor=tk.W, pady=(4, 0))
            Tooltip(btn_copy, "공개키를 클립보드에 복사합니다")
        else:
            ttk.Label(key_frame, text=(
                "SSH 키가 아직 없습니다. Setup 탭에서 '원클릭 셋업'을 실행하세요."
            ), style="Orange.TLabel").pack(anchor=tk.W, pady=5)

        # Quick reference
        ref_frame = ttk.LabelFrame(frame, text="자주 쓰는 명령어 (터미널에서 직접 사용)", padding=10)
        ref_frame.pack(fill=tk.X, pady=(10, 0))

        commands = [
            ("서버 접속",    f"ssh {self.cfg.ssh_host}"),
            ("파일 업로드",  f"scp -P {self.cfg.ssh_port} 파일.txt {self.cfg.ssh_host}:~/"),
            ("파일 다운로드", f"scp -P {self.cfg.ssh_port} {self.cfg.ssh_host}:~/파일.txt ./"),
            ("포트 포워딩",  f"ssh -L 8080:localhost:8080 {self.cfg.ssh_host}"),
        ]
        for i, (desc, cmd) in enumerate(commands):
            ttk.Label(ref_frame, text=desc, width=12).grid(row=i, column=0, sticky=tk.W, pady=1)
            entry = ttk.Entry(ref_frame, width=60, font=(_mono_font(), 9))
            entry.insert(0, cmd)
            entry.configure(state="readonly")
            entry.grid(row=i, column=1, sticky=tk.W, padx=(8, 0), pady=1)

    def _copy_to_clipboard(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status("클립보드에 복사되었습니다")

    def _save_settings(self):
        self.cfg = ServerConfig(
            inst_id=self.settings_vars["inst_id"].get(),
            comp_id=self.settings_vars["comp_id"].get(),
            ssh_host=self.settings_vars["ssh_host"].get(),
            ssh_user=self.settings_vars["ssh_user"].get(),
            ssh_ip=self.settings_vars["ssh_ip"].get(),
            ssh_port=self.settings_vars["ssh_port"].get(),
            region=self.settings_vars["region"].get(),
        )
        save_config(self.cfg)
        self._set_status("설정 저장 완료")
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.\nSSH Config도 업데이트하려면 Setup 탭에서 원클릭 셋업을 다시 실행하세요.")

    def _reload_settings(self):
        self.cfg = load_config()
        for key, var in self.settings_vars.items():
            var.set(getattr(self.cfg, key, ""))
        self._set_status("설정 다시 불러옴")


def main():
    root = tk.Tk()
    if IS_WIN:
        try:
            root.iconbitmap(default="")
        except Exception:
            pass
    if IS_MAC:
        try:
            root.tk.call("::tk::unsupported::MacWindowStyle", "style",
                         root._w, "document", "closeBox collapseBox resizable")
        except Exception:
            pass
    OracleManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
