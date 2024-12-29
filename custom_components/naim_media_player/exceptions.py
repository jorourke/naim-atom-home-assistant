class NaimPlayerError(Exception):
    """Base exception for Naim Player."""


class NaimConnectionError(NaimPlayerError):
    """Connection error occurred."""


class NaimCommandError(NaimPlayerError):
    """Error executing command."""
