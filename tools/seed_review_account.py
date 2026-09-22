"""Seed a representative review account for the Milestone 2 manual gate.

Run from the repository root with the same environment variables used to launch
the server. The script is idempotent: rerunning it refreshes the seeded state.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.app import create_runtime
from server.config import load_config
from server.game.buffs import TIMED, BuffInstance
from server.game.modifiers import Modifier
from server.security import utc_now

from datetime import timedelta

REVIEW_USERNAME = os.environ.get("TR_REVIEW_USERNAME", "reviewer")
REVIEW_PASSWORD = os.environ.get("TR_REVIEW_PASSWORD", "review-password-42")
FRIEND_USERNAME = os.environ.get("TR_REVIEW_FRIEND", "reviewerbuddy")
FRIEND_PASSWORD = os.environ.get("TR_REVIEW_FRIEND_PASSWORD", "review-password-42")
SEED_CARDS = (
    "sturdy",
    "nimble",
    "charming",
    "stylish",
    "spirited",
    "ballet-shoes",
    "juicy-drink",
    "juicy-drink",
    "tasty-toast",
    "tomato-sauce",
    "lucille",
    "seal-plushie",
    "fancy-wallet",
    "hand-light",
    "wave",
    "happy-dance",
    "heart",
    "starlight",
)


def _ensure_account(runtime, username: str, password: str):
    account = runtime.profiles.get_account_by_username(username)
    if account is None:
        result = runtime.accounts.create_account(username, password, runtime.config.new_account_passphrase, "seed")
        account = result.account
    if not account.initial_sticker_complete:
        account = runtime.accounts.confirm_initial_sticker(account.id, "s1.png")
    return account


def _grant_cards(runtime, account) -> None:
    for index, card_id in enumerate(SEED_CARDS):
        runtime.progression.reward_once(account.id, f"seed:{index}:{card_id}", cards=[card_id], kind="seed")


def _slot_sturdy(runtime, account) -> None:
    profile = runtime.profiles.get_user_profile(account.id)
    sturdy = next(
        (stack for stack in runtime.profiles.list_inventory(account.id, runtime.world.id) if stack.card_def_id == "sturdy"),
        None,
    )
    if sturdy is None:
        return
    stored = list(profile.skills)
    while len(stored) < 15:
        stored.append(None)
    stored[0] = sturdy.stack_id
    runtime.profiles.update_profile(account.id, lambda data: data.__setitem__("skills", stored))


def main() -> None:
    config = load_config()
    runtime = create_runtime(config)
    try:
        reviewer = _ensure_account(runtime, REVIEW_USERNAME, REVIEW_PASSWORD)
        friend = _ensure_account(runtime, FRIEND_USERNAME, FRIEND_PASSWORD)
        _grant_cards(runtime, reviewer)
        _grant_cards(runtime, friend)

        with runtime.hub.transaction() as connection:
            runtime.profiles.update_account_progress(
                connection,
                reviewer.id,
                level=3,
                kudos=6,
                bops=120,
                energy=55,
                last_energy_at=utc_now().isoformat(),
                last_daily_claim=None,
            )

        # Representative statuses and counters: half health and low cleanliness.
        runtime.stats.mutate(reviewer.id, health_delta=-25, cleanliness_delta=-100)
        _slot_sturdy(runtime, reviewer)

        # A timed buff so the Self view shows an active buff icon.
        runtime.stats.add_buff(
            reviewer.id,
            BuffInstance(
                id="seed-glow",
                label="Seed Glow",
                kind=TIMED,
                expires_at=utc_now() + timedelta(hours=1),
                modifiers=(Modifier(target="fanciness", flat=1),),
                icon="✨",
            ),
        )

        # Mutual friendship.
        try:
            runtime.friends.send_request(reviewer, friend)
            runtime.friends.accept_request(
                runtime.profiles.get_account_by_id(friend.id), reviewer.id
            )
        except ValueError:
            pass

        print("Seeded review account:")
        print(f"  username: {REVIEW_USERNAME}")
        print(f"  password: {REVIEW_PASSWORD}")
        print(f"  friend:   {FRIEND_USERNAME}")
    finally:
        runtime.hub.close()


if __name__ == "__main__":
    main()
