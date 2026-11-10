#!/usr/bin/env python3
"""Double-fork daemonizer: survives sandbox background-process reaping.

Usage: python3 scripts/daemonize.py [--log FILE] <command> [args...]

Forks twice (orphaning the child), detaches from the controlling
terminal (setsid), redirects std streams (to /dev/null, or to FILE when
--log is given), then execvp's the target command so it keeps running
independently of this shell.

Examples:
  python3 scripts/daemonize.py uvicorn app.main:app --host 127.0.0.1 --port 3030
  python3 scripts/daemonize.py --log /tmp/rebuild.log bash scripts/rebuild_stack.sh
"""
import os
import sys


def _fork_and_die() -> None:
    pid = os.fork()
    if pid > 0:
        os._exit(0)


def daemonize(logfile: str | None) -> None:
    _fork_and_die()          # first fork: parent exits immediately
    os.setsid()              # new session, detach from controlling tty
    _fork_and_die()          # second fork: daemon can never re-acquire a tty
    os.umask(0o022)
    if logfile:
        # line-buffered append so `tail -f` stays useful
        fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    else:
        fd = os.open(os.devnull, os.O_RDWR)
    os.dup2(fd, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    if fd > 2:
        os.close(fd)


def main(argv: list[str]) -> int:
    logfile = None
    args = argv
    if args and args[0] == "--log":
        if len(args) < 3:
            sys.stderr.write("usage: daemonize.py [--log FILE] <command> [args...]\n")
            return 2
        logfile = args[1]
        args = args[2:]
    if len(args) < 1:
        sys.stderr.write("usage: daemonize.py [--log FILE] <command> [args...]\n")
        return 2
    daemonize(logfile)
    os.execvp(args[0], args)
    return 0  # pragma: no cover (execvp never returns)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
