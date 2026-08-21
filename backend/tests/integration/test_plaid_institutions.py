"""Guards `SUPPORTED_BANKS` against Plaid's live institution registry.

This is the suite's highest-value test, because it covers the failure that
actually reached production. `exchange_public_token` rejects any Item whose
institution is not in a bank's allowlist, so a stale entry does not degrade
gracefully — it tombstones a correctly-authenticated connection and, in
production, permanently spends a Trial Item slot to do it.

Nothing offline can catch this: the allowlist agrees with itself, and only
Plaid knows that Chase moved to `ins_56` when it migrated to OAuth, or that
Wells Fargo answers to `ins_127991`.
"""

from __future__ import annotations

import pytest

from app.services.plaid_client import PlaidPythonGateway
from app.services.plaid_gateway import SUPPORTED_BANKS
from tests.integration.conftest import (
    lookup_institution_name,
    requires_sandbox_credentials,
)

pytestmark = [pytest.mark.plaid_sandbox, requires_sandbox_credentials]


@pytest.mark.parametrize("slug", sorted(SUPPORTED_BANKS))
def test_each_bank_still_has_a_live_institution_id(
    gateway: PlaidPythonGateway, slug: str
) -> None:
    """At least one configured ID per bank must still resolve to that bank.

    Deliberately not "every ID": the allowlists intentionally retain legacy
    entries (Chase's pre-OAuth `ins_3`, Wells Fargo's `ins_4`) so an older
    Item keeps validating. One of those going dark is harmless. All of them
    going dark is the outage.
    """
    bank = SUPPORTED_BANKS[slug]
    expected = bank.display_name.lower()

    resolved = {
        institution_id: lookup_institution_name(gateway, institution_id)
        for institution_id in sorted(bank.institution_ids)
    }
    matching = {
        institution_id: name
        for institution_id, name in resolved.items()
        if name and expected in name.lower()
    }

    assert matching, (
        f"no configured institution_id for {bank.display_name} resolves to it "
        f"in Plaid's registry — got {resolved}. Plaid has likely migrated the "
        f"institution; add the current ID to SUPPORTED_BANKS."
    )


@pytest.mark.parametrize("slug", sorted(SUPPORTED_BANKS))
def test_no_configured_id_resolves_to_a_different_bank(
    gateway: PlaidPythonGateway, slug: str
) -> None:
    """The inverse risk: an ID that resolves, but to somebody else. That would
    let a connection validate against the wrong institution and file another
    bank's cards under this one.
    """
    bank = SUPPORTED_BANKS[slug]
    expected = bank.display_name.lower()

    for institution_id in sorted(bank.institution_ids):
        name = lookup_institution_name(gateway, institution_id)
        if name is None:
            continue  # retired IDs are covered by the test above
        assert expected in name.lower(), (
            f"{institution_id} is configured as {bank.display_name} but Plaid "
            f"reports it as {name!r}"
        )
