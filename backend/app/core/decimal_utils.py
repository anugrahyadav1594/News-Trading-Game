from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

FOUR_DP = Decimal("0.0001")
TWO_DP = Decimal("0.01")
ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")
HUNDRED = Decimal("100.0000")
INITIAL_NET_WORTH_DEFAULT = Decimal("1000000.0000")


def to_dec(value: Decimal | int | str) -> Decimal:
    """Convert numeric input to 4-decimal fixed-point Decimal without float contamination."""
    if isinstance(value, float):
        raise TypeError("IEEE-754 float is prohibited in financial calculations; pass Decimal, int, or str.")
    if isinstance(value, Decimal):
        return value.quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def round_to_tick(price: Decimal, tick_size: Decimal) -> Decimal:
    """Round a positive price to the nearest valid tick increment."""
    tick = to_dec(tick_size)
    if tick <= ZERO:
        raise ValueError("tick_size must be positive")
    steps = (Decimal(price) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    result = (steps * tick).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    return max(tick, result)


def is_valid_tick(price: Decimal, tick_size: Decimal) -> bool:
    """Check whether price is strictly positive and an exact integer multiple of tick_size."""
    p = to_dec(price)
    t = to_dec(tick_size)
    if p <= ZERO or t <= ZERO:
        return False
    remainder = p % t
    return remainder == ZERO
