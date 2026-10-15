"""Parse page ranges typed by users, e.g. "1-3, 5, 8-"."""

from __future__ import annotations


class RangeError(ValueError):
    pass


def parse_ranges(text: str, count: int) -> list[list[int]]:
    """Return groups of 0-based page indices, one group per comma part."""
    groups: list[list[int]] = []
    for part in text.replace(";", ",").split(","):
        part = part.strip().replace(" ", "")
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                start = int(a) if a else 1
                end = int(b) if b else count
            else:
                start = end = int(part)
        except ValueError:
            raise RangeError(f"« {part} » n'est pas une plage valide") from None
        if not (1 <= start <= count and 1 <= end <= count):
            raise RangeError(f"« {part} » dépasse le nombre de pages ({count})")
        step = 1 if end >= start else -1
        groups.append(list(range(start - 1, end - 1 + step, step)))
    if not groups:
        raise RangeError("Aucune page indiquée")
    return groups


def flat_pages(text: str, count: int) -> list[int]:
    seen: list[int] = []
    for g in parse_ranges(text, count):
        for i in g:
            if i not in seen:
                seen.append(i)
    return seen


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} Ko"
    return f"{n / 1024 / 1024:.1f} Mo".replace(".", ",")
