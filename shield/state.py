"""Per-round gateway state. Everything is cleared when the hub's round id changes."""
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class RoundState:
    id: int = 0
    shield: bool = False
    issued: dict = field(default_factory=dict)      # canary token -> (owner session, kind)
    parent: dict = field(default_factory=dict)      # union-find over linked sessions
    links: set = field(default_factory=set)         # (owner, reuser, token) already emitted
    flagged: set = field(default_factory=set)
    n404: Counter = field(default_factory=Counter)
    legit: set = field(default_factory=set)         # sessions seen with a valid Bearer token
    wardens: dict = field(default_factory=dict)     # session -> Warden
    defender_usd: float = 0.0
    cost_sent_at: float = 0.0

    def apply_round(self, r: dict) -> bool:
        """Update from GET /api/round. Returns True when a new round started (state was reset)."""
        new_id = int(r.get("id", 0))
        self.shield = bool(r.get("shield", False))
        if new_id == self.id:
            return False
        self.reset(new_id)
        return True

    def reset(self, round_id: int):
        shield = self.shield
        self.__init__(id=round_id, shield=shield)

    def find(self, s: str) -> str:
        self.parent.setdefault(s, s)
        while self.parent[s] != s:
            self.parent[s] = self.parent[self.parent[s]]
            s = self.parent[s]
        return s

    def union(self, a: str, b: str):
        self.parent[self.find(a)] = self.find(b)

    def cluster(self, s: str) -> list:
        root = self.find(s)
        return sorted(x for x in list(self.parent) if self.find(x) == root)
