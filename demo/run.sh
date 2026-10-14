#!/bin/zsh
set -euo pipefail
cd "${0:A:h}/.."
exec python3 bin/agent-barrage --demo
