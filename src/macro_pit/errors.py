class MacroPITError(Exception):
    """Base exception for expected Macro PIT failures."""


class DataContractError(MacroPITError):
    """Raised when normalized observations violate the PIT contract."""


class NetworkDisabledError(MacroPITError):
    """Raised when a command requires network access without explicit opt-in."""


class CrawlSafetyError(MacroPITError):
    """Raised when a crawler safety circuit breaker is triggered."""


class ParserRowCountError(MacroPITError):
    """Raised when a parser returns suspiciously few rows."""

