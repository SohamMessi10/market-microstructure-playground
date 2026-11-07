"""A deliberately simple matching engine, used only to check the real one.

It keeps every resting order in one flat list and, for each fill, searches the whole list
for the best one. That's far too slow for real use, but short enough to check by eye, and it
shares no code with the real engine. If both produce the same trades and the same book on
thousands of random order sequences, a bug would have to exist identically in both.
"""

from microstructure import Side


class ReferenceEngine:
    def __init__(self):
        self.resting = []  # [order_id, side, price, remaining], in arrival order
        self.next_id = 1

    def submit(self, side, price, quantity):
        """Returns (trades, resting quantity); each trade is (price, quantity, buy id, sell id)."""
        order_id = self.next_id
        self.next_id += 1
        left, trades = quantity, []
        while left:
            if side is Side.BUY:
                candidates = [o for o in self.resting if o[1] is Side.SELL and o[2] <= price]
                best = min(candidates, key=lambda o: (o[2], o[0]), default=None)    # lowest ask, oldest
            else:
                candidates = [o for o in self.resting if o[1] is Side.BUY and o[2] >= price]
                best = min(candidates, key=lambda o: (-o[2], o[0]), default=None)   # highest bid, oldest
            if best is None:
                break
            traded = min(left, best[3])
            buyer, seller = (order_id, best[0]) if side is Side.BUY else (best[0], order_id)
            trades.append((best[2], traded, buyer, seller))
            best[3] -= traded
            left -= traded
            if best[3] == 0:
                self.resting.remove(best)
        if left:
            self.resting.append([order_id, side, price, left])
        return trades, left

    def book(self, side):
        """Resting orders on one side as (id, price, remaining), in the order they would trade."""
        orders = [o for o in self.resting if o[1] is side]
        orders.sort(key=(lambda o: (-o[2], o[0])) if side is Side.BUY else (lambda o: (o[2], o[0])))
        return [(o[0], o[2], o[3]) for o in orders]
