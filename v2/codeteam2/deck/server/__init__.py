"""The deck's web server (`codeteam2 deck --web`): one collector thread runs the terminal deck's refresh, and a
loopback HTTP server hands its latest snapshot and the page in web/ to browser tabs. serve.serve is the entry."""
