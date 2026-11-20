"""List-compatible search results with per-search completion status."""


class SearchResults(list):
    def __init__(self, rows=(), complete=True):
        super().__init__(rows)
        self.complete = complete
