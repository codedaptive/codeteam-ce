"""The page, filled in from its template."""


def page_html(template: str, motion_on: bool, interval: float) -> str:
    """The template with {{motion}} as "on" or "off" and {{interval}} as the refresh interval in seconds."""
    return template.replace("{{motion}}", "on" if motion_on else "off").replace("{{interval}}", repr(interval))
