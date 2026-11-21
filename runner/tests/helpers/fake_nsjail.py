#!/usr/bin/env python3
"""Stands in for nsjail in unit tests: honors --cwd, ignores every other option and runs what
follows `--`."""
import os
import sys

argv = sys.argv[1:]
if "--cwd" in argv:
    os.chdir(argv[argv.index("--cwd") + 1])
command = argv[argv.index("--") + 1 :]
os.execvp(command[0], command)
