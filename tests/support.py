import re


def sections(text: str) -> dict[str, str]:
    parts = re.split(r"(?m)^## ", text.strip())
    found = {}
    for part in parts:
        if not part.strip():
            continue
        heading, _, body = part.partition("\n")
        found[heading.strip()] = body.strip()
    return found


def headings(text: str) -> list[str]:
    return re.findall(r"(?m)^## (.+)$", text)
