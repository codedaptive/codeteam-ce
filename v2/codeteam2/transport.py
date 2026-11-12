"""How a message reaches a session: one small interface, so the transport can change alone.

Today: PromptTransport types the message into the session's input through herdr (`agent prompt`),
which herdr refuses while the agent is in a dialog. Planned: PushTransport, once a memory MCP
server supports the MCP specification's push message: each message becomes a queue item in the
team's store, and the server pushes it to the
session it is addressed to. The loop's rules (deliver only when ready, one per turn, put back a
prompt that started no turn) stay as they are; only `deliver` changes.
"""
from .herdr import HerdrError


class Refused(Exception):
    """The session could not take the message now (blocked, gone); the loop holds it until something
    changes for the session (its herdr status, or a completed turn), then tries again."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PromptTransport:
    name = "herdr-prompt"

    def __init__(self, herdr):
        self.herdr = herdr

    def deliver(self, agent_name, text):
        try:
            self.herdr.agent_prompt(agent_name, text)
        except HerdrError as e:
            raise Refused(e.code)


class PushTransport:
    """Not built yet: waits on an MCP server with push support. Shape, for whoever builds it: enqueue the message as a queue item addressed to the session's agent, carrying the
    store's id, and let the server push it; mark it delivered when it reports the push accepted."""
    name = "push"

    def __init__(self, *_, **__):
        raise NotImplementedError("push: planned once an MCP server supports push")
