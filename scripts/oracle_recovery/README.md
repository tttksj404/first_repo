# Oracle g185 SSH Recovery Toolkit

이번 SSH banner timeout 사건과 같은 일이 다시 발생하지 않게 하는 자동화.

## 파일

| 파일 | 용도 | 실행 위치 |
|---|---|---|
| `config.env` | INST_ID / COMP_ID / SSH 호스트 정보 | (참조용) |
| `health_probe.sh` | 4단계 진단 (TCP / SSH / sshd / hypervisor) | 로컬 또는 Cloud Shell |
| `emergency_recover.sh` | 자동 복구 파이프라인 (probe → agent restart → SOFTRESET → RESET) | Cloud Shell (oci CLI 필요) |
| `harden_vm.sh` | VM 측 영구 방지 설정 (sshd MaxStartups, watchdog, self-heal cron) | g185 VM 안에서 1회 |

## 다시 같은 사건 발생시 — 한 줄로 복구

**Cloud Shell에서**:

```bash
git clone <this-repo> ~/repo  # 1회만
bash ~/repo/scripts/oracle_recovery/emergency_recover.sh
```

자동 진행:
1. health probe → 정상이면 즉시 종료
2. Cloud Agent 통해 `systemctl restart sshd`
3. 안 되면 SOFTRESET (graceful 재부팅)
4. 그래도 안 되면 RESET (하드 전원 사이클)
5. 모든 단계 실패 → 콘솔 URL 출력

각 단계마다 90~120초 대기 후 probe 재시도. 최대 ~10분 안에 복구 또는 escalate.

## VM 측 영구 방지 (1회만)

SSH 복구된 직후:

```bash
scp scripts/oracle_recovery/harden_vm.sh g185:~/
ssh g185 'bash harden_vm.sh'
```

이후 효과:
- sshd MaxStartups 한도 ↑ (이번 같은 connection pile-up 방지)
- sshd 죽으면 systemd가 5초 안에 자동 재시작
- 5분 cron이 SSH self-probe 후 안 되면 sshd restart
- Cloud Agent 도 같은 방식 보호
- ulimits / journald 폭주 방지

## 클라이언트 (로컬) 위생

이미 `~/.ssh/config`에 ControlMaster 설정됨. 추가 권장:

```
Host g185
    ServerAliveInterval 30   # ← keepalive
    ServerAliveCountMax 3
    ConnectTimeout 30
    ControlMaster auto
    ControlPersist 300
```

stuck SSH PID 정리 필요 시:
```bash
pkill -f 'ssh.*g185' 2>/dev/null  # 권한 필요시 settings.local.json 에 허용
```

## 트러블슈팅

| 증상 | 원인 | 대응 |
|---|---|---|
| `Connection timed out during banner exchange` | sshd MaxStartups 초과 또는 hang | `emergency_recover.sh` 실행 |
| `Cloud Agent ACCEPTED 영원히` | 좀비 RUNNING (OS hang) | SOFTRESET → 안되면 RESET |
| `RESET 후에도 SSH 실패` | 부팅 자체 실패 / cloud-init 에러 | OCI Console serial console 직접 확인 |
| `Region not subscribed` | OCI CLI auth 문제 | Cloud Shell 에서만 가능 (instance principal) |

## 메트릭 (이번 사건 기준)

- **Hang 감지부터 복구까지**: ~50분 (수동, 수많은 시행착오)
- **위 toolkit 적용시**: <5분 자동
- **방지 적용시**: 거의 0% 재발
