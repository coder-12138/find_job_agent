import re
import hashlib


def sanitize_agent_name(name: str) -> str:
    ascii_parts = re.findall(r"[a-zA-Z0-9]+", name)
    if ascii_parts:
        sanitized = "_".join(ascii_parts)
    else:
        hash_str = hashlib.md5(name.encode()).hexdigest()[:8]
        sanitized = f"company_{hash_str}"
    if sanitized[0].isdigit():
        sanitized = f"agent_{sanitized}"
    return sanitized
