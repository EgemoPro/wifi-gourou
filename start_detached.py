#!/usr/bin/env python3
"""Lance main.py en arrière-plan, totalement détaché du terminal."""
import subprocess
import sys
import os

log = open("/tmp/agent_test.log", "a", buffering=1)
p = subprocess.Popen(
    [sys.executable, "main.py"],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    stdout=log,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    # Nouveau groupe de processus, pas de session terminal
    start_new_session=True,
)
print(f"Agent lancé : PID {p.pid}")
# NE PAS attendre — le parent sort immédiatement
# L'enfant est adopté par init (PID 1)

