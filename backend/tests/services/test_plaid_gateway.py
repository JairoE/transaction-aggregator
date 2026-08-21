from __future__ import annotations

from app.services.plaid_gateway import SUPPORTED_BANKS, load_supported_banks


def test_chase_accepts_both_the_legacy_and_oauth_institution_ids() -> None:
    """Regression: Chase's real Link traffic resolves to ins_56 (its OAuth-era
    institution) since migrating off ins_3 (its pre-OAuth entry) — Plaid never
    merged the two, so a live exchange can legitimately report either.
    Accepting only ins_3 makes exchange_public_token tombstone a real,
    correctly-authenticated Chase connection as WRONG_INSTITUTION_LINKED.
    """
    assert {"ins_3", "ins_56"} <= SUPPORTED_BANKS["chase"].institution_ids


def test_wells_fargo_accepts_both_the_stale_and_current_institution_ids() -> None:
    """Regression: ins_4 is stale; Plaid's registry currently resolves real
    Wells Fargo connections to ins_127991 in both sandbox and production."""
    assert {"ins_4", "ins_127991"} <= SUPPORTED_BANKS["wells-fargo"].institution_ids


def test_load_supported_banks_overrides_layer_on_top_of_the_defaults() -> None:
    banks = load_supported_banks('{"chase": ["ins_999"]}')

    assert banks["chase"].institution_ids == frozenset({"ins_999"})
    assert banks["wells-fargo"] == SUPPORTED_BANKS["wells-fargo"]
