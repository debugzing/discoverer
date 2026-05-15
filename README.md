## OLVM 4.5 Recovery Discovery Script

`discover_olvm.py` is an interactive recovery assistant for Oracle Linux Virtualization Manager 4.5 environments. Run it from the Engine host to discover surviving KVM hosts, VM libvirt XML, VDSM/libvirt state, logical network clues, and storage-domain metadata after an Engine database loss.

The script intentionally does **not** write directly into the Engine PostgreSQL database. The safe recovery path is to restore an `engine-backup` archive when one exists. If the DB is completely lost and no backup exists, deploy a fresh Engine, use the generated manifest to recreate baseline objects, then import existing storage domains and VMs through supported OLVM workflows.

### Interactive usage

```bash
python3 discover_olvm.py -i
```

The interactive flow can:

- Parse Engine logs/configuration for old host candidates.
- Accept extra hosts, host files, or CIDR ranges to probe for SSH.
- Scan hosts over SSH, optionally with passwordless sudo.
- Generate a JSON manifest, Markdown recovery plan, XML artifacts, and an Engine API bootstrap template.

### Non-interactive examples

Scan known hosts:

```bash
python3 discover_olvm.py \
  --hosts "kvm01.example.com,kvm02.example.com" \
  --user root \
  --keyfile ~/.ssh/id_rsa \
  --outdir olvm-recovery-run
```

Probe a management subnet for SSH and scan discovered hosts:

```bash
python3 discover_olvm.py \
  --cidr 192.0.2.0/24 \
  --user root \
  --cidr-limit 256 \
  --outdir olvm-recovery-run
```

Scan a host list with passwordless sudo:

```bash
python3 discover_olvm.py \
  --hosts-file hosts.txt \
  --user olvm-admin \
  --sudo \
  --outdir olvm-recovery-run
```

### Output

Each run writes:

- `olvm-recovery-manifest.json`: full machine-readable inventory.
- `olvm-recovery-plan.md`: practical rebuild sequence and summary tables.
- `hosts/*/vms/*.xml`: VM libvirt XML captured per host.
- `hosts/*/networks/*.xml`: libvirt network XML.
- `hosts/*/storage-pools/*.xml`: libvirt storage pool XML.
- `engine_api_bootstrap_template.py`: review-before-run SDK template for creating baseline data center, cluster, logical networks, and hosts on a fresh Engine.
