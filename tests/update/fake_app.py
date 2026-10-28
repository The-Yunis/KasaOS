"""Stand-in for KasaOS-app.exe in launcher tests.

Behaviour is controlled by a `behaviour.txt` file in its version folder:
  ready      — write the readiness signal, then idle briefly
  crash      — exit 3 immediately
  hang       — never signal readiness
  wrong      — signal readiness with a wrong version
It also appends a line to ../../launches.log so tests can see what ran.
"""

import json
import os
import sys
import time
from pathlib import Path

here = Path(sys.argv[1])
version = (here / "kasaos-version.txt").read_text(encoding="utf-8").strip()
behaviour = (here / "behaviour.txt").read_text(encoding="utf-8").strip()
root = here.parent.parent
with open(root / "launches.log", "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"version": version, "notice": os.environ.get("KASAOS_UPDATE_NOTICE"),
                         "ready_file": bool(os.environ.get("KASAOS_READY_FILE"))}) + "\n")

if behaviour == "crash":
    sys.exit(3)
ready = os.environ.get("KASAOS_READY_FILE")
if behaviour in ("ready", "wrong") and ready:
    Path(ready).write_text(json.dumps({"version": version if behaviour == "ready" else "0.0.0"}),
                           encoding="utf-8")
time.sleep(30 if behaviour == "hang" else 1)
