"""Check that a locally built app can dispatch hooks without opening the UI."""

import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dist" / "AgentBarrage.app"
EXECUTABLE = APP / "Contents" / "MacOS" / "AgentBarrage"


def main():
    with (APP / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["LSUIElement"] is True
    assert info["CFBundleIdentifier"] == "io.github.agentbarrage.AgentBarrage"
    result = subprocess.run(
        [str(EXECUTABLE), "--hook-adapter", "codex"],
        input='{"hook_event_name":"Stop","cwd":"/tmp/AgentBarrage"}',
        text=True, capture_output=True, timeout=10, check=True)
    assert result.stdout == "{}\n", result.stdout
    print("Packaged hook dispatch: OK")


if __name__ == "__main__":
    main()
