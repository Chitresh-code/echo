#!/usr/bin/env python3
"""Stands in for nsjail in unit tests: honors --cwd, ignores every other option and runs what
follows `--`. Like nsjail, which kills the jail's whole pid namespace, a SIGTERM stops the
command's whole process group, so a child it forked does not outlive it."""
import os
import signal
import subprocess
import sys

argv = sys.argv[1:]
if "--cwd" in argv:
    os.chdir(argv[argv.index("--cwd") + 1])
command = argv[argv.index("--") + 1 :]
child = subprocess.Popen(command, start_new_session=True)
signal.signal(signal.SIGTERM, lambda *_: os.killpg(child.pid, signal.SIGTERM))
code = child.wait()
sys.exit(code if code >= 0 else 128 - code)
