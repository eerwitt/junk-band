"""Load local server configuration without executing or interpolating its contents."""

import os
import re
from pathlib import Path


def load_environment(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*?)\s*", line)
        if not match:
            raise ValueError(f"Invalid environment assignment on line {number}")
        name, value = match.groups()
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (
                value[end + 1 :].strip() and not value[end + 1 :].lstrip().startswith("#")
            ):
                raise ValueError(f"Invalid quoted environment value for {name} on line {number}")
            value = value[1:end]
        else:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(name, value)
