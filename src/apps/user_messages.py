"""Consistent two-level messages for non-technical application users."""


def user_message(title: str, guidance: str | None = None) -> str:
    """Build a toast-safe title and optional action line."""
    title = title.strip()
    guidance = (guidance or "").strip()
    return f"{title}\n{guidance}" if guidance else title
