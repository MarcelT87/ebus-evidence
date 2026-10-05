from __future__ import annotations

from typing import Any


MAX_STRUCTURE_DEPTH = 64
MAX_STRUCTURE_NODES = 1_000_000


class StructureLimitError(ValueError):
    pass


def validate_structure_limits(value: Any, *, label: str) -> None:
    """Reject pathologically deep, large, or cyclic JSON/YAML-style structures."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    seen_containers: set[int] = set()
    nodes = 0

    while stack:
        current, depth = stack.pop()
        nodes += 1

        if nodes > MAX_STRUCTURE_NODES:
            raise StructureLimitError(
                f"{label} exceeds maximum structure size of "
                f"{MAX_STRUCTURE_NODES} nodes"
            )
        if depth > MAX_STRUCTURE_DEPTH:
            raise StructureLimitError(
                f"{label} exceeds maximum nesting depth of "
                f"{MAX_STRUCTURE_DEPTH}"
            )

        if isinstance(current, (dict, list)):
            identity = id(current)
            if identity in seen_containers:
                raise StructureLimitError(
                    f"{label} contains repeated or cyclic container references"
                )
            seen_containers.add(identity)

        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
