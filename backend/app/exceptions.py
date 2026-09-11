"""Shared application exceptions."""


class JobCancelled(Exception):
    """Raised when a job is cooperatively stopped by the user."""
