from datetime import datetime, timezone


def parse_utc_timestamp(value):
    """Parse Facepunch ISO timestamps and return an aware UTC datetime."""
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    created = datetime.fromisoformat(text)
    if created.tzinfo is None:
        return created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc)
