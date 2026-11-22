"""How long a model request may wait for its answer before the loop calls it hung: the one table.

Keys are model-name prefixes, matched case-insensitively. Claude models reach their first response block within
65 s at p99.9 (Opus; Haiku 55 s) on this machine, so 300 s is far past a slow request (30 of 83,014 Opus requests
took longer); GPT models (Sol) think for up to about 11 minutes, so theirs is 720 s (creator #4945, measured over the
last 500 sessions). A manifest overrides entries with `[v2] hang_threshold_s`.
"""

HANG_THRESHOLDS_S = {"claude": 300, "gpt": 720}
