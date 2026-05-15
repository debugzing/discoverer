#!/usr/bin/env python3
"""Discover KVM/OLVM hosts, VMs, networks, and storage domains for recovery use.

This script is designed to scan one or more nodes and collect:
- host metadata
- virtual machines
- virtual networks
- storage pools and volumes

It is useful when recovering OLVM after an engine/database crash,
so you can rebuild inventory from the cluster itself.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime


def run_command(command, ssh_target=None, timeout=60):
    if ssh_target:
        ssh_command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            ssh_target,
            command,
        ]
        proc = subprocess.run(
            ssh_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            timeout=timeout,
        )
    else:
        proc = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            timeout=timeout,
        )

    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def parse_table(output):
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    header = lines[0]
    # We assume columns are separated by 2+ spaces.
    columns = [col.strip() for col in header.split("  ") if col.strip()]
    rows = []
    for line in lines[2:]:
        values = [value.strip() for value in line.split("  ") if value.strip()]
        if len(values) < len(columns):
            values += [""] * (len(columns) - len(values))
        row = dict(zip(columns, values))
        rows.append(row)
    return rows


def collect_host_info(host, ssh_target=None):
    host_data = {
        "query_time": datetime.utcnow().isoformat() + "Z",
        "host": host,
        "local": ssh_target is None,
        "commands": {},
        "vms": [],
        "networks": [],
        "storage_pools": [],
    }

    def gather(name, command, parser=None):
        rc, out, err = run_command(command, ssh_target=ssh_target)
        host_data["commands"][name] = {
            "returncode": rc,
            "stdout": out,
            "stderr": err,
        }
        if parser and rc == 0:
            return parser(out)
        return None

    gather("hostname", "virsh hostname")
    gather("version", "virsh version")

    vms = gather("list_all_vms", "virsh list --all", parser=parse_table) or []
    for vm in vms:
        vm_name = vm.get("Name") or vm.get("name")
        if not vm_name:
            continue
        vm_record = {"name": vm_name, "raw": vm}
        rc, info_out, info_err = run_command(f"virsh dominfo {shlex.quote(vm_name)}", ssh_target=ssh_target)
        vm_record["dominfo"] = info_out if rc == 0 else None
        rc, xml_out, xml_err = run_command(f"virsh dumpxml {shlex.quote(vm_name)}", ssh_target=ssh_target)
        vm_record["xml"] = xml_out if rc == 0 else None
        host_data["vms"].append(vm_record)

    nets = gather("list_networks", "virsh net-list --all", parser=parse_table) or []
    for net in nets:
        net_name = net.get("Name") or net.get("name")
        if not net_name:
            continue
        net_record = {"name": net_name, "raw": net}
        rc, info_out, info_err = run_command(f"virsh net-info {shlex.quote(net_name)}", ssh_target=ssh_target)
        net_record["net_info"] = info_out if rc == 0 else None
        rc, xml_out, xml_err = run_command(f"virsh net-dumpxml {shlex.quote(net_name)}", ssh_target=ssh_target)
        net_record["xml"] = xml_out if rc == 0 else None
        host_data["networks"].append(net_record)

    pools = gather("list_storage_pools", "virsh pool-list --all", parser=parse_table) or []
    for pool in pools:
        pool_name = pool.get("Name") or pool.get("name")
        if not pool_name:
            continue
        pool_record = {"name": pool_name, "raw": pool}
        rc, info_out, info_err = run_command(f"virsh pool-info {shlex.quote(pool_name)}", ssh_target=ssh_target)
        pool_record["pool_info"] = info_out if rc == 0 else None
        rc, xml_out, xml_err = run_command(f"virsh pool-dumpxml {shlex.quote(pool_name)}", ssh_target=ssh_target)
        pool_record["xml"] = xml_out if rc == 0 else None

        rc, volumes_out, volumes_err = run_command(
            f"virsh vol-list --pool {shlex.quote(pool_name)}", ssh_target=ssh_target
        )
        pool_record["volumes_raw"] = volumes_out if rc == 0 else None
        pool_record["volumes"] = parse_table(volumes_out) if rc == 0 else []
        host_data["storage_pools"].append(pool_record)

    return host_data


def load_hosts(hosts_arg):
    if os.path.isfile(hosts_arg):
        with open(hosts_arg, "r", encoding="utf-8") as fp:
            return [line.strip() for line in fp if line.strip() and not line.startswith("#")]
    return [host.strip() for host in hosts_arg.split(",") if host.strip()]


def build_ssh_target(user, keyfile, port, host):
    if host in ("localhost", "127.0.0.1"):
        return None
    target = []
    if keyfile:
        target += ["-i", keyfile]
    if port:
        target += ["-p", str(port)]
    if user:
        target_host = f"{user}@{host}"
    else:
        target_host = host
    return " ".join(shlex.quote(part) for part in target + [target_host])


def main():
    parser = argparse.ArgumentParser(
        description="Discover OLVM KVM hosts, VMs, networks, and storage domains."
    )
    parser.add_argument(
        "hosts",
        help="Comma-separated host list or file path containing hostnames/IPs. Use localhost for local scan.",
    )
    parser.add_argument("--user", help="SSH user for remote hosts.")
    parser.add_argument("--keyfile", help="SSH private key file path.")
    parser.add_argument("--port", type=int, help="SSH port for remote hosts.")
    parser.add_argument(
        "--output",
        default="olvm-discovery.json",
        help="Output JSON file path. Defaults to olvm-discovery.json.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug messages to stderr.",
    )
    args = parser.parse_args()

    hosts = load_hosts(args.hosts)
    if not hosts:
        parser.error("No hosts were provided.")

    results = []
    for host in hosts:
        ssh_target = build_ssh_target(args.user, args.keyfile, args.port, host)
        if args.debug:
            print(f"Scanning host: {host} ssh_target={ssh_target}", file=sys.stderr)
        try:
            host_data = collect_host_info(host, ssh_target=ssh_target)
            results.append(host_data)
        except subprocess.TimeoutExpired as exc:
            print(f"Timeout while scanning {host}: {exc}", file=sys.stderr)
            results.append({"host": host, "error": "timeout"})
        except Exception as exc:
            print(f"Error scanning {host}: {exc}", file=sys.stderr)
            results.append({"host": host, "error": str(exc)})

    output_data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "host_count": len(results),
        "hosts": results,
    }

    with open(args.output, "w", encoding="utf-8") as out_fp:
        json.dump(output_data, out_fp, indent=2)

    print(f"Discovery completed. Results written to {args.output}")


if __name__ == "__main__":
    main()
