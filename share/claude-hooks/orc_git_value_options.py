"""The options of the orc's git restore or checkout whose next word is a value (D587)."""

# restore's and checkout's options whose next word is a value, not a pathspec (stash has
# STASH_VALUE_OPTIONS in orc_stash_words.py).
ORC_GIT_VALUE_OPTIONS = {"-s", "--source", "--pathspec-from-file", "-b", "-B", "--orphan"}
