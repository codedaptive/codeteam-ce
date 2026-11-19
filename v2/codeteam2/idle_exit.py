"""The default for a manifest's [v2] idle_exit_h: hours a session may sit idle before the loop ends it."""

# Idle sessions held disk and processes for hours. A session idle 1 hour with nothing
# waiting is ended and starts again on its next mail. 0 in a manifest's [v2] idle_exit_h means never.
IDLE_EXIT_H = 1
