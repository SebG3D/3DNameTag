"""Name validation - same whitelist as the kiosk keyboard."""
import re

NAME_MAX = 12
_NAME_RE = re.compile(r"^[A-Z0-9ÄÖÜß\- ]+$")


def clean_name(raw: str) -> str:
    """Upper-case (keeping ß, str.upper() would make it SS), trim, collapse
    spaces. Raises ValueError if the result is not allowed."""
    name = "".join(c if c in "ßẞ" else c.upper() for c in raw).replace("ẞ", "ß")
    name = " ".join(name.split())
    if not name or len(name) > NAME_MAX or not _NAME_RE.match(name):
        raise ValueError(f"invalid name {raw!r}")
    return name
