#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_ROOT"

python3 packaging/macos/make_icon.py
pyinstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller \
  packaging/macos/AgentMarquee.spec

printf 'Built %s\n' "$PROJECT_ROOT/dist/AgentMarquee.app"
