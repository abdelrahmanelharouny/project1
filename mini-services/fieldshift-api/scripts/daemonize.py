#!/usr/bin/env python3
"""Double-fork daemonizer: survives sandbox background-process reaping.

Usage: python3 scripts/daemonize.py <command> [args...]

Forks twice (orphaning the child), detaches from the controlling
terminal (setsid), redirects std streams to /dev/null, then execvp's
the target command so it keeps running independently of this shell.
"""
import os
import sys


def _fork_and_die() -> None:
    pid = os.fork()
    if pid > 0:
        os._exit(0)


def daemonize() -> None:
    _fork_and_die()          # first fork: parent exits immediately
    os.setsid()              # new session, detach from controlling tty
    _fork_and_die()          # second fork: daemon can never re-acquire a tty
    os.umask(0o022)
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    if devnull > 2:
        os.close(devnull)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: daemonize.py <command> [args...]\n")
        sys.exit(2)
    daemonize()
    os.execvp(sys.argv[1], sys.argv[1:])
