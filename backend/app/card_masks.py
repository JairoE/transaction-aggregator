"""Privacy boundary for provider-supplied card-number masks."""

from __future__ import annotations

import re

LAST_FOUR_ASCII_DIGITS = re.compile(r"[0-9]{4}\Z")


def normalize_card_mask(mask: str | None) -> str | None:
    """Keep an exact ASCII last-four mask; discard every other value."""

    return (
        mask
        if mask is not None and LAST_FOUR_ASCII_DIGITS.fullmatch(mask)
        else None
    )


__all__ = ["normalize_card_mask"]
