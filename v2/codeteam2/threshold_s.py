"""A model's hang threshold in seconds, from the one table and a manifest's overrides.

The longest matching prefix wins, so a manifest can single out one model ("gpt-6.1") without changing its family.
A model the table does not know gets the Claude value: most sessions run Claude, and a wrong guess only moves when
the watchdog acts, never whether.
"""
from .hang_thresholds import HANG_THRESHOLDS_S


def threshold_s(model: str, overrides=None) -> float:
    table = {k.lower(): v for k, v in {**HANG_THRESHOLDS_S, **(overrides or {})}.items()}
    hits = [k for k in table if model.lower().startswith(k)]
    return float(table[max(hits, key=len)] if hits else table["claude"])
