#!/usr/bin/env python3
"""Map rancher.local → kind-control-plane when the Kind Docker network is attached."""
from __future__ import annotations

import os
import socket
import sys


def _alias_rancher_local() -> None:
    try:
        ip = socket.gethostbyname("kind-control-plane")
    except OSError:
        return
    try:
        with open("/etc/hosts", encoding="utf-8") as handle:
            existing = handle.read()
        if "rancher.local" in existing and ip in existing:
            return
        with open("/etc/hosts", "a", encoding="utf-8") as handle:
            handle.write(f"\n{ip} rancher.local\n")
    except OSError:
        return


def main() -> None:
    _alias_rancher_local()
    if len(sys.argv) < 2:
        sys.stderr.write("usage: docker-entrypoint.py <command> [args...]\n")
        sys.exit(2)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
