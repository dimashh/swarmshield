# Changelog

One line per commit, newest first. Everyone commits to `main`: run `git pull --rebase origin main` before you start and before every push.

- 2026-11-14 `shield`: pass-through gateway `shield/proxy.py` (forwards to target, emits `request`, shopper `forward_legit`, polls `/api/round`); `emit` logs hub-down once instead of every batch (Senior)
- 2026-11-14 `common`: URLs can be set by env var, `flag_hint`/`next_hint` give decimal `seed-NN`, new `common/hub.py` client (`get_round`, board/blue helpers, non-blocking `emit`), `tests/` + `requirements-dev.txt` (Senior)
