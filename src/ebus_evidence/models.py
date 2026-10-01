from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Frame:
    timestamp: str
    direction: str
    initiated_by_ebusd: bool
    source: str
    target: str
    pbsb: str
    request: str
    response: str | None = None
