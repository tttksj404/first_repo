#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXTIFY = ROOT / 'scripts' / 'leet_official_textify.py'
SCAN = ROOT / 'scripts' / 'check_leet_textify_regressions.py'


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run full LEET textify audit on official corpus.')
    parser.add_argument('source_root', type=Path, help='Root directory containing official LEET PDF/HWP sources')
    parser.add_argument('--vault-root', type=Path, required=True)
    parser.add_argument('--out-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.expanduser().resolve()
    vault_root = args.vault_root.expanduser().resolve()
    out_root = args.out_root.expanduser().resolve()
    report_path = args.report.expanduser().resolve()

    out_root.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    textify_cmd = [sys.executable, str(TEXTIFY), str(source_root), '--vault-root', str(vault_root), '--official-textified-root', str(out_root)]
    textify_result = run(textify_cmd, ROOT)

    report: dict[str, object] = {
        'source_root': str(source_root),
        'vault_root': str(vault_root),
        'out_root': str(out_root),
        'textify': {
            'returncode': textify_result.returncode,
            'stdout': textify_result.stdout.splitlines(),
            'stderr': textify_result.stderr.splitlines(),
        },
    }

    if textify_result.returncode == 0:
        scan_cmd = [sys.executable, str(SCAN), str(out_root), '--json']
        scan_result = run(scan_cmd, ROOT)
        report['scan'] = {
            'returncode': scan_result.returncode,
            'stdout': scan_result.stdout,
            'stderr': scan_result.stderr.splitlines(),
        }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    if textify_result.returncode != 0:
        print(report_path)
        raise SystemExit(textify_result.returncode)
    if report.get('scan', {}).get('returncode', 0) != 0:
        print(report_path)
        raise SystemExit(report['scan']['returncode'])
    print(report_path)


if __name__ == '__main__':
    main()
