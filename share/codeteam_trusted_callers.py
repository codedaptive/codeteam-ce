"""The calling files of one changed declaration that an interface notice may trust, from seed_zones' answer (D600)."""


def trusted_callers(zone_files: dict[str, list[str]], note: dict) -> dict[str, list[str]] | None:
    """zone_files when the callers answer was complete; None when note carries an interface_error, since an incomplete
    answer may miss calling files and an unknown caller list must wake the notice's recipient."""
    if "interface_error" in note:
        return None
    return zone_files
