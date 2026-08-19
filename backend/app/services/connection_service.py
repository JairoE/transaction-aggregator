"""Bank connection lifecycle: Link tokens, exchange, update mode, disconnect.

Every Plaid access token is encrypted before it touches the database and is
decrypted only for the duration of one gateway call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError, NotFoundError
from app.models import (
    BankConnection,
    CardAccount,
    Owner,
    SyncJob,
    Transaction,
    new_id,
    utcnow,
)
from app.services.crypto import EncryptedSecret, TokenCipher
from app.services.plaid_gateway import (
    DAYS_REQUESTED,
    LinkTokenRequest,
    PlaidAccount,
    PlaidGateway,
    SupportedBank,
    load_supported_banks,
)
from app.services.sync_service import enqueue_sync

TRIAL_ITEM_LIMIT = 10
CREDIT_SUBTYPES = frozenset({"credit card", None})


@dataclass(frozen=True)
class LinkTokenResult:
    link_token: str
    bank: str
    mode: str
    consumes_trial_slot: bool
    production_item_count: int
    production_item_limit: int = TRIAL_ITEM_LIMIT


@dataclass(frozen=True)
class BankSummary:
    bank: str
    display_name: str
    connected: bool
    connection_id: str | None
    institution_name: str | None
    card_count: int
    lifecycle_status: str
    last_successful_sync_at: datetime | None
    last_provider_update_at: datetime | None
    consent_expiration_at: datetime | None
    last_error_code: str | None
    refresh_supported: bool


@dataclass(frozen=True)
class ConnectionsSummary:
    banks: list[BankSummary]
    production_item_count: int
    production_item_limit: int
    environment: str


class ConnectionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        gateway: PlaidGateway,
        cipher: TokenCipher,
    ) -> None:
        self._session = session
        self._settings = settings
        self._gateway = gateway
        self._cipher = cipher
        self._banks = load_supported_banks(settings.plaid_institution_overrides)

    @property
    def gateway(self) -> PlaidGateway:
        return self._gateway

    @property
    def cipher(self) -> TokenCipher:
        return self._cipher

    # --- reads ------------------------------------------------------------
    async def list_connections(self, owner: Owner) -> ConnectionsSummary:
        rows = (
            await self._session.execute(
                select(BankConnection)
                .where(BankConnection.owner_id == owner.id)
                .where(BankConnection.lifecycle_status == "active")
            )
        ).scalars().all()
        active_by_slug = {row.bank_slug: row for row in rows}

        card_counts = dict(
            (
                await self._session.execute(
                    select(CardAccount.connection_id, func.count(CardAccount.id))
                    .where(CardAccount.is_active.is_(True))
                    .group_by(CardAccount.connection_id)
                )
            ).all()
        )

        banks: list[BankSummary] = []
        for slug, bank in self._banks.items():
            connection = active_by_slug.get(slug)
            banks.append(
                BankSummary(
                    bank=slug,
                    display_name=bank.display_name,
                    connected=connection is not None,
                    connection_id=connection.id if connection else None,
                    institution_name=(
                        connection.institution_name if connection else None
                    ),
                    card_count=(
                        int(card_counts.get(connection.id, 0)) if connection else 0
                    ),
                    lifecycle_status=(
                        connection.lifecycle_status if connection else "disconnected"
                    ),
                    last_successful_sync_at=(
                        connection.last_successful_sync_at if connection else None
                    ),
                    last_provider_update_at=(
                        connection.last_provider_update_at if connection else None
                    ),
                    consent_expiration_at=(
                        connection.consent_expiration_at if connection else None
                    ),
                    last_error_code=connection.last_error_code if connection else None,
                    refresh_supported=(
                        connection.refresh_supported if connection else True
                    ),
                )
            )

        return ConnectionsSummary(
            banks=banks,
            production_item_count=await self._production_item_count(owner.id),
            production_item_limit=TRIAL_ITEM_LIMIT,
            environment=self._settings.environment,
        )

    # --- link tokens ------------------------------------------------------
    async def create_link_token(
        self, owner: Owner, bank: str, confirm_trial_slot: bool = False
    ) -> LinkTokenResult:
        supported = self._require_bank(bank)
        await self._reject_existing_active_connection(owner.id, supported)

        consumes_slot = self._settings.environment == "production"
        production_count = await self._production_item_count(owner.id)
        if consumes_slot:
            if production_count >= TRIAL_ITEM_LIMIT:
                raise AppError(
                    "TRIAL_LIMIT_REACHED",
                    "All 10 Plaid Trial Item slots have been used. Removing a "
                    "connection does not return a slot.",
                    409,
                )
            if not confirm_trial_slot:
                raise AppError(
                    "TRIAL_SLOT_UNCONFIRMED",
                    "Connecting a real bank permanently consumes one of the 10 "
                    "Plaid Trial Item slots. Confirm to continue.",
                    409,
                )

        plaid_user_id = await self._ensure_plaid_user(owner)
        link_token = self._gateway.create_link_token(
            LinkTokenRequest(
                client_user_id=owner.id,
                plaid_user_id=plaid_user_id,
                redirect_uri=self._settings.oauth_redirect_uri,
                webhook_url=(
                    str(self._settings.plaid_webhook_url)
                    if self._settings.plaid_webhook_url
                    else None
                ),
                institution_id=next(iter(sorted(supported.institution_ids)), None),
                access_token=None,
                days_requested=DAYS_REQUESTED,
            )
        )
        return LinkTokenResult(
            link_token=link_token,
            bank=bank,
            mode="new",
            consumes_trial_slot=consumes_slot,
            production_item_count=production_count,
        )

    async def create_update_link_token(
        self, owner: Owner, connection_id: str
    ) -> LinkTokenResult:
        connection = await self._require_active_connection(owner.id, connection_id)
        access_token = self._decrypt_access_token(connection)
        plaid_user_id = await self._ensure_plaid_user(owner)

        link_token = self._gateway.create_link_token(
            LinkTokenRequest(
                client_user_id=owner.id,
                plaid_user_id=plaid_user_id,
                redirect_uri=self._settings.oauth_redirect_uri,
                webhook_url=(
                    str(self._settings.plaid_webhook_url)
                    if self._settings.plaid_webhook_url
                    else None
                ),
                institution_id=connection.institution_id,
                access_token=access_token,
            )
        )
        return LinkTokenResult(
            link_token=link_token,
            bank=connection.bank_slug,
            mode="update",
            consumes_trial_slot=False,
            production_item_count=await self._production_item_count(owner.id),
        )

    # --- exchange ---------------------------------------------------------
    async def exchange_public_token(
        self,
        owner: Owner,
        bank: str,
        public_token: str,
        institution_id: str,
        institution_name: str,
    ) -> BankConnection:
        supported = self._require_bank(bank)
        await self._reject_existing_active_connection(owner.id, supported)

        exchanged = self._gateway.exchange_public_token(public_token)
        linked_institution = exchanged.institution_id or institution_id

        if linked_institution not in supported.institution_ids:
            self._gateway.remove_item(exchanged.access_token)
            self._session.add(
                BankConnection(
                    owner_id=owner.id,
                    bank_slug=bank,
                    institution_id=linked_institution,
                    institution_name=institution_name,
                    plaid_item_id=exchanged.item_id,
                    plaid_environment=self._settings.environment,
                    lifecycle_status="removed",
                    removed_at=utcnow(),
                    last_error_code="WRONG_INSTITUTION_LINKED",
                    last_error_at=utcnow(),
                )
            )
            await self._session.flush()
            raise AppError(
                "WRONG_INSTITUTION_LINKED",
                f"That sign-in was not {supported.display_name}. The connection was "
                "removed; start again from the correct bank tile.",
                409,
            )

        connection_id = new_id()
        encrypted = self._cipher.encrypt(exchanged.access_token, context=connection_id)
        connection = BankConnection(
            id=connection_id,
            owner_id=owner.id,
            bank_slug=bank,
            institution_id=linked_institution,
            institution_name=institution_name or supported.display_name,
            plaid_item_id=exchanged.item_id,
            plaid_environment=self._settings.environment,
            lifecycle_status="active",
            access_token_ciphertext=encrypted.ciphertext,
            access_token_nonce=encrypted.nonce,
            access_token_key_version=encrypted.key_version,
        )
        self._session.add(connection)
        await self._session.flush()

        accounts = self._gateway.get_accounts(exchanged.access_token)
        self._upsert_cards(connection, accounts)
        await self._session.flush()

        await enqueue_sync(self._session, connection.id, "initial")
        return connection

    async def summarize_connection(self, connection_id: str) -> tuple[int, str | None]:
        """Card count and in-flight job id, read explicitly to avoid lazy loads."""

        card_count = int(
            (
                await self._session.execute(
                    select(func.count(CardAccount.id)).where(
                        CardAccount.connection_id == connection_id
                    )
                )
            ).scalar_one()
        )
        job_id = (
            await self._session.execute(
                select(SyncJob.id)
                .where(SyncJob.connection_id == connection_id)
                .where(SyncJob.state.in_(("queued", "running")))
                .limit(1)
            )
        ).scalars().first()
        return card_count, job_id

    # --- disconnect -------------------------------------------------------
    async def disconnect(self, owner: Owner, connection_id: str) -> None:
        connection = await self._require_active_connection(owner.id, connection_id)
        access_token = self._decrypt_access_token(connection)

        try:
            self._gateway.remove_item(access_token)
        except Exception:
            # Local purge still proceeds; the Trial slot stays consumed either way.
            pass

        card_ids = (
            await self._session.execute(
                select(CardAccount.id).where(
                    CardAccount.connection_id == connection.id
                )
            )
        ).scalars().all()
        if card_ids:
            await self._session.execute(
                delete(Transaction).where(Transaction.card_account_id.in_(card_ids))
            )
            await self._session.execute(
                delete(CardAccount).where(CardAccount.id.in_(card_ids))
            )

        connection.lifecycle_status = "removed"
        connection.removed_at = utcnow()
        connection.access_token_ciphertext = None
        connection.access_token_nonce = None
        connection.access_token_key_version = None
        connection.sync_cursor = None
        connection.last_error_code = None
        await self._session.flush()

    # --- helpers ----------------------------------------------------------
    def _require_bank(self, bank: str) -> SupportedBank:
        supported = self._banks.get(bank)
        if supported is None:
            raise AppError("BANK_UNSUPPORTED", "That bank is not supported.", 400)
        return supported

    async def _reject_existing_active_connection(
        self, owner_id: str, supported: SupportedBank
    ) -> None:
        existing = (
            await self._session.execute(
                select(BankConnection)
                .where(BankConnection.owner_id == owner_id)
                .where(BankConnection.bank_slug == supported.slug)
                .where(BankConnection.lifecycle_status == "active")
                .limit(1)
            )
        ).scalars().first()
        if existing is not None:
            raise AppError(
                "USE_UPDATE_MODE",
                f"{supported.display_name} is already connected. Use Reconnect to "
                "repair the existing connection or change selected cards.",
                409,
            )

    async def _require_active_connection(
        self, owner_id: str, connection_id: str
    ) -> BankConnection:
        connection = (
            await self._session.execute(
                select(BankConnection)
                .where(BankConnection.id == connection_id)
                .where(BankConnection.owner_id == owner_id)
                .where(BankConnection.lifecycle_status == "active")
            )
        ).scalars().first()
        if connection is None:
            raise NotFoundError("That bank connection was not found.")
        return connection

    async def _production_item_count(self, owner_id: str) -> int:
        count = (
            await self._session.execute(
                select(func.count(BankConnection.id))
                .where(BankConnection.owner_id == owner_id)
                .where(BankConnection.plaid_environment == "production")
            )
        ).scalar_one()
        return int(count)

    async def _ensure_plaid_user(self, owner: Owner) -> str | None:
        if owner.plaid_user_id:
            return owner.plaid_user_id
        try:
            plaid_user_id = self._gateway.create_user(owner.id)
        except Exception:
            return None
        owner.plaid_user_id = plaid_user_id
        await self._session.flush()
        return plaid_user_id

    def _decrypt_access_token(self, connection: BankConnection) -> str:
        if (
            connection.access_token_ciphertext is None
            or connection.access_token_nonce is None
            or connection.access_token_key_version is None
        ):
            raise AppError(
                "CONNECTION_TOKEN_MISSING",
                "This connection has no stored credential. Reconnect the bank.",
                409,
            )
        return self._cipher.decrypt(
            EncryptedSecret(
                ciphertext=connection.access_token_ciphertext,
                nonce=connection.access_token_nonce,
                key_version=connection.access_token_key_version,
            ),
            context=connection.id,
        )

    def _upsert_cards(
        self, connection: BankConnection, accounts: list[PlaidAccount]
    ) -> None:
        for account in accounts:
            if account.type != "credit":
                continue
            if account.subtype not in CREDIT_SUBTYPES:
                continue
            self._session.add(
                CardAccount(
                    connection_id=connection.id,
                    plaid_account_id=account.account_id,
                    name=account.name,
                    official_name=account.official_name,
                    mask=account.mask,
                    subtype=account.subtype,
                    is_active=True,
                )
            )


__all__ = [
    "BankSummary",
    "ConnectionService",
    "ConnectionsSummary",
    "LinkTokenResult",
    "TRIAL_ITEM_LIMIT",
]
