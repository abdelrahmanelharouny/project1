"""Pure ordering for disposable test-row cleanup; no DB connection or DDL."""
from __future__ import annotations


def child_first_tables(names: list[str], edges: list[tuple[str, str]]) -> list[str]:
    allowed = set(names)
    children: dict[str, set[str]] = {name: set() for name in names}
    for parent, child in edges:
        if parent in allowed and child in allowed and parent != child:
            children[parent].add(child)
    visited: set[str] = set()
    active: set[str] = set()
    ordered: list[str] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in active:
            raise RuntimeError("Disposable test cleanup has an inter-table FK cycle; explicit handling is required.")
        active.add(name)
        for child in sorted(children[name]):
            visit(child)
        active.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in sorted(names):
        visit(name)
    return ordered
