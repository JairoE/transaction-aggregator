"""The concrete `plaid-python` implementation of `PlaidGateway`.

Everything Plaid-shaped stops here. Callers receive plain dataclasses, and
provider failures become `PlaidGatewayError` carrying only an error code, a
request ID, and a retry classification — never a raw body or an access token.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal

from plaid.api import plaid_api
from plaid.api_client import ApiClient
from plaid.configuration import Configuration, Environment
from plaid.exceptions import ApiException
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.credit_filter import CreditFilter
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_account_filters import LinkTokenAccountFilters
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.link_token_transactions import LinkTokenTransactions
from plaid.model.products import Products
from plaid.model.transactions_refresh_request import TransactionsRefreshRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.webhook_verification_key_get_request import (
    WebhookVerificationKeyGetRequest,
)

from app.config import Settings
from app.services.plaid_gateway import (
    DAYS_REQUESTED,
    ExchangedItem,
    ItemStatus,
    LinkTokenRequest,
    PlaidAccount,
    PlaidGatewayError,
    PlaidTransaction,
    PlaidUser,
    RefreshUnsupported,
    SyncMutationDuringPagination,
    SyncPage,
    classify_error_code,
)

logger = logging.getLogger(__name__)

MUTATION_CODE = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"
REFRESH_UNSUPPORTED_CODES = frozenset(
    {"PRODUCTS_NOT_SUPPORTED", "TRANSACTIONS_REFRESH_NOT_SUPPORTED"}
)


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value if value is not None else "0"))


def _to_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:  # pragma: no cover - provider format drift
        return None


class PlaidPythonGateway:
    """Implements every `PlaidGateway` method against the official SDK."""

    def __init__(self, settings: Settings) -> None:
        host = (
            Environment.Production
            if settings.plaid_host_environment == "production"
            else Environment.Sandbox
        )
        configuration = Configuration(
            host=host,
            api_key={
                "clientId": settings.plaid_client_id.get_secret_value(),
                "secret": settings.plaid_secret.get_secret_value(),
            },
        )
        self._client = plaid_api.PlaidApi(ApiClient(configuration))
        self._settings = settings

    # --- users ------------------------------------------------------------
    def create_user(self, client_user_id: str) -> PlaidUser:
        from plaid.model.user_create_request import UserCreateRequest

        response = self._call(
            lambda: self._client.user_create(
                UserCreateRequest(client_user_id=client_user_id)
            )
        )
        return _build_plaid_user(response)

    # --- link -------------------------------------------------------------
    def create_link_token(self, request: LinkTokenRequest) -> str:
        kwargs: dict[str, object] = {
            "client_name": "Transaction Aggregator",
            "language": "en",
            "country_codes": [CountryCode("US")],
            "user": LinkTokenCreateRequestUser(client_user_id=request.client_user_id),
            "redirect_uri": request.redirect_uri,
        }
        if request.webhook_url:
            kwargs["webhook"] = request.webhook_url

        if request.access_token:
            # Update mode repairs an existing Item and must not send products.
            kwargs["access_token"] = request.access_token
        else:
            kwargs["products"] = [Products("transactions")]
            kwargs["transactions"] = LinkTokenTransactions(
                days_requested=request.days_requested or DAYS_REQUESTED
            )
            kwargs["account_filters"] = LinkTokenAccountFilters(
                credit=CreditFilter(account_subtypes=_credit_card_subtypes())
            )
            if request.user_token:
                kwargs["user_token"] = request.user_token

        response = self._call(
            lambda: self._client.link_token_create(LinkTokenCreateRequest(**kwargs))
        )
        return str(response["link_token"])

    def exchange_public_token(self, public_token: str) -> ExchangedItem:
        response = self._call(
            lambda: self._client.item_public_token_exchange(
                ItemPublicTokenExchangeRequest(public_token=public_token)
            )
        )
        access_token = str(response["access_token"])
        item = self.get_item_status(access_token)
        return ExchangedItem(
            access_token=access_token,
            item_id=str(response["item_id"]),
            institution_id=item.institution_id,
        )

    # --- accounts and item ------------------------------------------------
    def get_accounts(self, access_token: str) -> list[PlaidAccount]:
        response = self._call(
            lambda: self._client.accounts_get(
                AccountsGetRequest(access_token=access_token)
            )
        )
        accounts: list[PlaidAccount] = []
        for account in response["accounts"]:
            accounts.append(
                PlaidAccount(
                    account_id=str(account["account_id"]),
                    name=str(account["name"]),
                    official_name=(
                        str(account["official_name"])
                        if account.get("official_name")
                        else None
                    ),
                    mask=str(account["mask"]) if account.get("mask") else None,
                    type=str(account["type"]),
                    subtype=str(account["subtype"]) if account.get("subtype") else None,
                )
            )
        return accounts

    def get_item_status(self, access_token: str) -> ItemStatus:
        response = self._call(
            lambda: self._client.item_get(ItemGetRequest(access_token=access_token))
        )
        item = response["item"]
        error = item.get("error")
        status = response.get("status") or {}
        transactions_status = (status or {}).get("transactions") or {}
        return ItemStatus(
            item_id=str(item["item_id"]),
            institution_id=(
                str(item["institution_id"]) if item.get("institution_id") else None
            ),
            error_code=str(error["error_code"]) if error else None,
            consent_expiration_time=(
                str(item["consent_expiration_time"])
                if item.get("consent_expiration_time")
                else None
            ),
            last_successful_update=(
                str(transactions_status["last_successful_update"])
                if transactions_status.get("last_successful_update")
                else None
            ),
        )

    # --- transactions -----------------------------------------------------
    def transactions_sync(self, access_token: str, cursor: str) -> SyncPage:
        kwargs: dict[str, object] = {"access_token": access_token, "count": 500}
        if cursor:
            kwargs["cursor"] = cursor
        response = self._call(
            lambda: self._client.transactions_sync(TransactionsSyncRequest(**kwargs))
        )
        return SyncPage(
            added=[_transaction(row) for row in response["added"]],
            modified=[_transaction(row) for row in response["modified"]],
            removed_ids=[str(row["transaction_id"]) for row in response["removed"]],
            next_cursor=str(response["next_cursor"]),
            has_more=bool(response["has_more"]),
            request_id=str(response.get("request_id") or "") or None,
        )

    def transactions_refresh(self, access_token: str) -> None:
        try:
            self._call(
                lambda: self._client.transactions_refresh(
                    TransactionsRefreshRequest(access_token=access_token)
                )
            )
        except PlaidGatewayError as error:
            if error.error_code in REFRESH_UNSUPPORTED_CODES:
                raise RefreshUnsupported() from error
            raise

    def remove_item(self, access_token: str) -> None:
        self._call(
            lambda: self._client.item_remove(
                ItemRemoveRequest(access_token=access_token)
            )
        )

    # --- webhooks ---------------------------------------------------------
    def verify_webhook(self, body: bytes, verification_header: str | None) -> bool:
        """Verify the `Plaid-Verification` JWT against Plaid's signing key."""

        if not verification_header:
            return False
        try:
            import jwt
        except ImportError:  # pragma: no cover - dependency guard
            logger.error("pyjwt is required to verify Plaid webhooks")
            return False

        try:
            header = jwt.get_unverified_header(verification_header)
            if header.get("alg") != "ES256":
                return False
            key_id = header.get("kid")
            if not key_id:
                return False
            response = self._call(
                lambda: self._client.webhook_verification_key_get(
                    WebhookVerificationKeyGetRequest(key_id=key_id)
                )
            )
            jwk = response["key"]
            # plaid-python models are not Mappings; dict() raises on them.
            public_key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(jwk.to_dict()))
            claims = jwt.decode(
                verification_header,
                public_key,
                algorithms=["ES256"],
                options={"require": ["iat"]},
            )
        except Exception:
            logger.warning("plaid webhook verification failed")
            return False

        import hashlib
        import hmac as hmac_module

        expected = claims.get("request_body_sha256")
        if not expected:
            return False
        actual = hashlib.sha256(body).hexdigest()
        return hmac_module.compare_digest(str(expected), actual)

    # --- error translation ------------------------------------------------
    def _call(self, operation):  # type: ignore[no-untyped-def]
        try:
            return operation()
        except ApiException as error:
            code, request_id = _extract_error(error)
            if code == MUTATION_CODE:
                raise SyncMutationDuringPagination() from None
            logger.warning(
                "plaid_api_error",
                extra={"plaid_error_code": code, "plaid_request_id": request_id},
            )
            raise PlaidGatewayError(
                error_code=code or "PLAID_UNAVAILABLE",
                retry_class=classify_error_code(code),
                request_id=request_id,
            ) from None
        except (SyncMutationDuringPagination, PlaidGatewayError):
            raise
        except Exception as error:  # network-level failures
            logger.warning("plaid_transport_error", extra={"error_type": type(error).__name__})
            raise PlaidGatewayError(
                error_code="PLAID_UNREACHABLE", retry_class="transient"
            ) from None


def _extract_error(error: ApiException) -> tuple[str | None, str | None]:
    try:
        body = json.loads(error.body or "{}")
    except (ValueError, TypeError):
        return None, None
    return body.get("error_code"), body.get("request_id")


def _build_plaid_user(response: object) -> PlaidUser:
    """A pure mapping, kept separate from `_call` so it is unit-testable
    without a network call: construct a `UserCreateResponse` and pass it in.
    """

    return PlaidUser(
        user_id=str(response["user_id"]), user_token=str(response["user_token"])
    )


def _transaction(row: object) -> PlaidTransaction:
    data = row  # plaid models behave like mappings
    categories = data.get("personal_finance_category") or {}
    return PlaidTransaction(
        transaction_id=str(data["transaction_id"]),
        account_id=str(data["account_id"]),
        name=str(data["name"]),
        merchant_name=(
            str(data["merchant_name"]) if data.get("merchant_name") else None
        ),
        original_description=(
            str(data["original_description"])
            if data.get("original_description")
            else None
        ),
        amount=_to_decimal(data.get("amount")),
        iso_currency_code=(
            str(data["iso_currency_code"]) if data.get("iso_currency_code") else None
        ),
        date=_to_date(data.get("date")),
        authorized_date=_to_date(data.get("authorized_date")),
        pending=bool(data.get("pending")),
        category=(
            str(categories.get("primary")).replace("_", " ").title()
            if categories.get("primary")
            else None
        ),
    )


def _credit_card_subtypes() -> object:
    """CreditFilter requires the CreditAccountSubtypes wrapper, not a plain list."""

    from plaid.model.credit_account_subtype import CreditAccountSubtype
    from plaid.model.credit_account_subtypes import CreditAccountSubtypes

    return CreditAccountSubtypes([CreditAccountSubtype("credit card")])


__all__ = ["PlaidPythonGateway"]
