from typing import Any


class ExchangeError(Exception):
    status_code: int = 400
    code: str = "EXCHANGE_ERROR"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class AuthenticationError(ExchangeError):
    status_code = 401
    code = "AUTHENTICATION_FAILED"


class ForbiddenActionError(ExchangeError):
    status_code = 403
    code = "FORBIDDEN_ACTION"


class ResourceNotFoundError(ExchangeError):
    status_code = 404
    code = "RESOURCE_NOT_FOUND"


class DuplicateAccountError(ExchangeError):
    status_code = 409
    code = "DUPLICATE_ACCOUNT_OR_SEAT"


class InvalidGamePhaseError(ExchangeError):
    status_code = 409
    code = "INVALID_GAME_PHASE"


class StockHaltedError(ExchangeError):
    status_code = 409
    code = "STOCK_TRADING_HALTED"


class InsufficientFundsError(ExchangeError):
    status_code = 422
    code = "INSUFFICIENT_FUNDS"


class InsufficientSharesError(ExchangeError):
    status_code = 422
    code = "INSUFFICIENT_SHARES"


class BorrowPoolExhaustedError(ExchangeError):
    status_code = 422
    code = "BORROW_POOL_EXHAUSTED"


class ShortPositionLimitError(ExchangeError):
    status_code = 422
    code = "SHORT_POSITION_LIMIT_EXCEEDED"


class MarginViolationError(ExchangeError):
    status_code = 422
    code = "MARGIN_REQUIREMENT_NOT_MET"


class OrderValidationError(ExchangeError):
    status_code = 422
    code = "ORDER_VALIDATION_FAILED"


class RateLimitExceededError(ExchangeError):
    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"
