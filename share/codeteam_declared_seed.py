"""Whether a CodeGraph blast seed is a declaration the interface check follows."""


def declared_seed(seed: dict, kinds, marks) -> bool:
    """seed's kind is in kinds, it is not a whole file, and no test mark is in its path."""
    return (seed.get("kind") in kinds and not seed.get("wholeFile")
            and not any(m in seed["path"] for m in marks))
