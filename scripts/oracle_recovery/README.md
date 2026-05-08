# Oracle g185 Access And Recovery

This folder keeps the Oracle paper-trading VM reachable from any working
machine: current SSAFY PC, home Mac, future replacement PC, or Cloud Shell.

The important rule is: do not rely on a memorized public IP. Use OCI discovery
to find the current instance, then regenerate `Host g185`.

## Files

| File | Purpose |
|---|---|
| `config.env` | Last known instance OCID, public IP, SSH alias, region |
| `ensure_access.py` | Cross-platform bootstrap: discover VM, update SSH config, enroll key when possible, verify SSH |
| `emergency_recover.sh` | Cloud Shell recovery: health probe, sshd restart, START/SOFTRESET/RESET |
| `health_probe.sh` | TCP/SSH/OCI health check |
| `harden_vm.sh` | One-time VM hardening for SSH durability |
| `mac_setup.sh` | Thin wrapper for `ensure_access.py --repair` on macOS |
| `recover_and_deploy_g1165.py` | Local recovery + G1165 deployment runner |

## Normal Setup On Any PC Or Mac

From a cloned repo:

```bash
python scripts/oracle_recovery/ensure_access.py --repair
```

On macOS:

```bash
bash scripts/oracle_recovery/mac_setup.sh
```

What this does:

1. Uses OCI Search, when available, to find `g185-restored` or `g185`.
2. Updates `scripts/oracle_recovery/config.env`.
3. Rewrites `~/.ssh/config` with a managed `Host g185` block.
4. Generates `~/.ssh/id_ed25519` if needed.
5. Verifies `ssh g185`.
6. If TCP is open but key auth fails and OCI is available, registers the local public key through OCI Instance Agent.

If a new laptop has neither SSH access nor OCI credentials, the script prints a
single Cloud Shell command that registers that laptop's public key.

Opening the VM from the home Mac and this Windows PC at the same time should
not break SSH. Repeated failures after switching machines usually mean one of
two things:

- that machine's SSH public key is not in the VM's `authorized_keys`; or
- SSH is reachable at TCP level but `sshd` is not returning a banner.

`ensure_access.py --repair` is the intended fix for both cases when OCI
credentials are present locally: it refreshes the VM IP, rewrites `Host g185`,
tries an OCI Instance Agent `sshd` restart, registers the local public key, and
then retries SSH.

For truly portable operation, set up OCI CLI credentials once on every machine
that should be able to self-recover access. Without OCI credentials, that
machine can still use an already-registered SSH key, but it cannot repair a
stuck `sshd` or register a new key by itself.

## Cloud Shell Recovery

Use this only when local SSH cannot reach the VM:

```bash
cd ~
git clone https://github.com/tttksj404/first_repo.git repo 2>/dev/null || true
cd ~/repo
git pull
python3 scripts/oracle_recovery/ensure_access.py --repair
bash scripts/oracle_recovery/emergency_recover.sh
```

`ensure_access.py` fixes stale instance IDs/IPs first. `emergency_recover.sh`
then tries:

1. Health probe.
2. START if stopped.
3. Restart sshd via OCI Instance Agent.
4. SOFTRESET.
5. RESET.

## After SSH Recovers

Run hardening once:

```bash
scp scripts/oracle_recovery/harden_vm.sh g185:~/
ssh g185 'bash ~/harden_vm.sh'
```

Then verify:

```bash
ssh g185 'hostname; systemctl is-active sshd; systemctl --user is-active g1165-emulator.service'
```

## Current Known VM

- Display name: `g185-restored`
- Region: `ap-chuncheon-1`
- SSH alias: `g185`
- SSH port: `443`

The current public IP and instance OCID live in `config.env`, but they should be
treated as cache, not truth. Run `ensure_access.py --repair` whenever a machine
changes or SSH suddenly fails.
