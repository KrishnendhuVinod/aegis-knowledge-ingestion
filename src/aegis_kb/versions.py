"""Software-revision scopes. The reason this module exists: '180 bar' and '200 bar' are only a
conflict if their scopes overlap. Scopes are first-class so coexistence is computed, not guessed.

A scope is either KNOWN (a [min, max) interval of software revisions, either end may be open) or
UNKNOWN (the source does not say which revisions it describes, e.g. an undated field note).
"""
from __future__ import annotations

from dataclasses import dataclass

Ver = tuple


def parse_ver(s: str) -> Ver:
    return tuple(int(p) for p in str(s).strip().strip(".").split("."))


def fmt(v: Ver | None) -> str | None:
    return None if v is None else ".".join(map(str, v))


@dataclass(frozen=True)
class SwScope:
    known: bool = False
    min: Ver | None = None      # inclusive
    max: Ver | None = None      # exclusive

    # --- constructors
    @staticmethod
    def unknown() -> "SwScope":
        return SwScope(known=False)

    @staticmethod
    def all() -> "SwScope":
        return SwScope(known=True)

    @staticmethod
    def since(v: str) -> "SwScope":
        return SwScope(True, parse_ver(v), None)

    @staticmethod
    def before(v: str, floor: str | None = None) -> "SwScope":
        return SwScope(True, parse_ver(floor) if floor else None, parse_ver(v))

    @staticmethod
    def from_dict(d: dict) -> "SwScope":
        return SwScope(d["known"], parse_ver(d["sw_min"]) if d.get("sw_min") else None,
                       parse_ver(d["sw_max_exclusive"]) if d.get("sw_max_exclusive") else None)

    # --- queries
    def contains(self, ver: str) -> bool | None:
        if not self.known:
            return None
        v = parse_ver(ver)
        return (self.min is None or v >= self.min) and (self.max is None or v < self.max)

    def relation(self, other: "SwScope") -> str:
        """'unknown' | 'overlap' | 'disjoint'"""
        if not (self.known and other.known):
            return "unknown"
        lo = max([x for x in (self.min, other.min) if x is not None], default=None)
        hi = min([x for x in (self.max, other.max) if x is not None], default=None)
        if lo is None or hi is None or lo < hi:
            return "overlap"
        return "disjoint"

    def to_dict(self) -> dict:
        return {"known": self.known, "sw_min": fmt(self.min), "sw_max_exclusive": fmt(self.max)}

    def label(self) -> str:
        if not self.known:
            return "unspecified software revision"
        if self.min is None and self.max is None:
            return "all revisions"
        if self.max is None:
            return f"software >= {fmt(self.min)}"
        if self.min is None:
            return f"software < {fmt(self.max)}"
        return f"software {fmt(self.min)} to < {fmt(self.max)}"
