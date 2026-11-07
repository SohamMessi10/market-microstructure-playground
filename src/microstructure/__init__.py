"""Market Microstructure Playground: a limit order book with price-time priority matching."""

from microstructure.book import Book, BookError, InvariantError, LevelView, check_invariants, find_problems
from microstructure.engine import MatchingEngine, Status, SubmitResult
from microstructure.models import Order, OrderError, Side, Trade

__all__ = [
    "Book", "BookError", "InvariantError", "LevelView", "MatchingEngine", "Order", "OrderError", "Side",
    "Status", "SubmitResult", "Trade",
    "check_invariants", "find_problems",
]
__version__ = "0.1.0"
