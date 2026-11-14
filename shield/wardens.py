"""Warden realities (step 3). Stub: flagged sessions never reach the target and get a believable 404."""
from common.schema import page


async def handle(state, session: str, method: str, path: str, headers: dict, body: bytes):
    """Returns (status, page_dict)."""
    return 404, page("Not found", "not found", error="not found")
