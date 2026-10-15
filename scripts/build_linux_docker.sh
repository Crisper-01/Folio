#!/usr/bin/env bash
# Build the Linux bundle from any OS with Docker. AlmaLinux 8 (glibc 2.28)
# keeps the result compatible with Ubuntu 20.04+, Debian 10+, Fedora 29+, RHEL 8+...
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MSYS_NO_PATHCONV=1 docker run --rm -v "$ROOT:/src" -e PYTHON=python3.12 \
  almalinux:8 bash /src/scripts/build_linux.sh /src
