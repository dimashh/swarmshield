"""Per-round gateway state. Everything is cleared when the hub's round id changes."""
from dataclasses import dataclass


@dataclass
class RoundState:
    id: int = 0
    shield: bool = False

    def apply_round(self, r: dict) -> bool:
        """Update from GET /api/round. Returns True when a new round started (state was reset)."""
        new_id = int(r.get("id", 0))
        self.shield = bool(r.get("shield", False))
        if new_id == self.id:
            return False
        self.reset(new_id)
        return True

    def reset(self, round_id: int):
        self.id = round_id
