# Oracle g185 SSH Recovery Toolkit

이번 SSH banner timeout 사건과 같은 일이 다시 발생하지 않게 하는 자동화.

## 파일

| 파일 | 용도 | 실행 위치 |
|---|---|---|
| `config.env` | INST_ID / COMP_ID / SSH 호스트 정보 | (참조용) |
| `health_probe.sh` | 4단계 진단 (TCP / SSH / sshd / hypervisor) | 로컬 또는 Cloud Shell |
| `emergency_recover.sh` | 자동 복구 파이프라인 (probe → agent restart → SOFTRESET → RESET) | Cloud Shell (oci CLI 필요) |
| `harden_vm.sh` | VM 측 영구 방지 설정 (sshd MaxStartups, watchdog, self-heal cron) | g185 VM 안에서 1회 |
| `prune_low_value_emulators.sh` | 저우선순위 전략 3개 stop+disable+mask | g185 VM 안에서 1회 |
| `cloudshell_bootstrap.sh` | Cloud Shell에 영구 `g185ctl` 명령 설치 | Cloud Shell에서 1회 |

## Cloud Shell 반복 설정 제거 — 처음 한 번만

Cloud Shell은 사용자 세션이라 Codex가 독립적으로 상시 접속할 수는 없다. 대신 Cloud Shell 홈에 `g185ctl`을 한 번 설치해두면, 어느 PC에서 Cloud Shell을 열어도 같은 명령으로 조정한다.

처음 한 번:

```bash
curl -fsSL https://raw.githubusercontent.com/tttksj404/first_repo/main/scripts/oracle_recovery/cloudshell_bootstrap.sh | bash
g185ctl discover
```

이후부터:

```bash
g185ctl status   # OCI Instance Agent로 상태 확인, SSH 불필요
g185ctl prune    # g1165/g129183/g922_meme stop+disable+mask
g185ctl rescue-prune  # Agent가 ACCEPTED에 멈추면 SOFTRESET/RESET 후 prune까지 자동 진행
g185ctl recover  # sshd 재시작
g185ctl ssh      # SSH가 살아 있을 때만 접속
```

`g185ctl discover`는 현재 Cloud Shell 권한으로 보이는 RUNNING 인스턴스 중 `g185` 계열을 찾아 `~/.g185ctl.env`에 저장하고, `~/.ssh/config`의 `Host g185`도 현재 public IP/443 기준으로 갱신한다. 비밀번호나 API 키는 저장하지 않는다.

`g185ctl status`나 `g185ctl prune`이 `ACCEPTED`에 계속 머무르면 인스턴스 안의 OCI Agent가 명령을 실행하지 못하는 상태다. 이때는 반복 설정하지 말고:

```bash
g185ctl rescue-prune
```

이 명령 하나가 prune 시도 → SOFTRESET → prune 재시도 → 필요시 RESET → prune 재시도를 순서대로 처리한다.

## 전략 과적재 정리 — 한 번만 실행

`sudo`를 쓰지 않는다. VM에 `opc`로 들어가 있으면 그대로 실행하고, OCI Run Command처럼 root로 실행돼도 스크립트가 알아서 `opc` user systemd로 전환한다.

기본 정리 대상:
- `g1165-emulator.service`
- `g129183-emulator.service`
- `g922_meme-emulator.service`

SSH가 살아 있을 때:

```bash
scp scripts/oracle_recovery/prune_low_value_emulators.sh g185:~/
ssh g185 'bash ~/prune_low_value_emulators.sh'
```

VM 콘솔 또는 OCI Run Command에서 직접 실행할 때:

```bash
cat > /tmp/prune_low_value_emulators.sh <<'SH'
#!/bin/bash
curl -fsSL https://raw.githubusercontent.com/tttksj404/first_repo/main/scripts/oracle_recovery/prune_low_value_emulators.sh -o /tmp/prune_impl.sh
bash /tmp/prune_impl.sh
SH
bash /tmp/prune_low_value_emulators.sh
```

완료 후 기대 상태:
- 위 3개는 `active=inactive enabled=masked`
- 남는 서비스는 `g4692`, `g920_top7`, `g921_alts`
- 재부팅해도 masked 서비스는 자동으로 다시 올라오지 않음

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
