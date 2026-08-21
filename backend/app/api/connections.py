"""Bank connection routes. Every mutation requires the owner session and CSRF."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import CsrfDep, OwnerDep, connection_service_dep
from app.schemas import (
    BankConnectionResponse,
    ConnectionsResponse,
    CreateLinkTokenRequest,
    ExchangePublicTokenRequest,
    ExchangeResponse,
    LinkTokenResponse,
)
from app.services.connection_service import ConnectionService

router = APIRouter(prefix="/api/connections", tags=["connections"])

ServiceDep = Depends(connection_service_dep)


@router.get("", response_model=ConnectionsResponse)
async def list_connections(
    owner: OwnerDep, service: ConnectionService = ServiceDep
) -> ConnectionsResponse:
    summary = await service.list_connections(owner)
    return ConnectionsResponse(
        banks=[
            BankConnectionResponse(
                bank=bank.bank,  # type: ignore[arg-type]
                display_name=bank.display_name,
                connected=bank.connected,
                connection_id=bank.connection_id,
                institution_name=bank.institution_name,
                card_count=bank.card_count,
                lifecycle_status=bank.lifecycle_status,
                state=bank.state,
                action=bank.action,
                message=bank.message,
                cache_as_of=bank.cache_as_of,
                last_successful_sync_at=bank.last_successful_sync_at,
                last_provider_update_at=bank.last_provider_update_at,
                consent_expiration_at=bank.consent_expiration_at,
                last_error_code=bank.last_error_code,
                refresh_supported=bank.refresh_supported,
            )
            for bank in summary.banks
        ],
        production_item_count=summary.production_item_count,
        production_item_limit=summary.production_item_limit,
        environment=summary.environment,
        uses_demo_bank=summary.environment in {"demo", "test"},
    )


@router.post("/link-token", response_model=LinkTokenResponse, dependencies=[CsrfDep])
async def create_link_token(
    payload: CreateLinkTokenRequest,
    owner: OwnerDep,
    service: ConnectionService = ServiceDep,
) -> LinkTokenResponse:
    result = await service.create_link_token(
        owner, payload.bank, confirm_trial_slot=payload.confirm_trial_slot
    )
    return LinkTokenResponse(
        link_token=result.link_token,
        bank=result.bank,
        mode=result.mode,  # type: ignore[arg-type]
        consumes_trial_slot=result.consumes_trial_slot,
        production_item_count=result.production_item_count,
        production_item_limit=result.production_item_limit,
    )


@router.post("/exchange", response_model=ExchangeResponse, dependencies=[CsrfDep])
async def exchange_public_token(
    payload: ExchangePublicTokenRequest,
    owner: OwnerDep,
    service: ConnectionService = ServiceDep,
) -> ExchangeResponse:
    connection = await service.exchange_public_token(
        owner,
        payload.bank,
        payload.public_token,
        payload.institution_id,
        payload.institution_name,
    )
    card_count, sync_job_id = await service.summarize_connection(connection.id)
    return ExchangeResponse(
        connection_id=connection.id,
        bank=payload.bank,
        institution_name=connection.institution_name,
        card_count=card_count,
        sync_job_id=sync_job_id,
    )


@router.post(
    "/{connection_id}/update-token",
    response_model=LinkTokenResponse,
    dependencies=[CsrfDep],
)
async def create_update_link_token(
    connection_id: str, owner: OwnerDep, service: ConnectionService = ServiceDep
) -> LinkTokenResponse:
    result = await service.create_update_link_token(owner, connection_id)
    return LinkTokenResponse(
        link_token=result.link_token,
        bank=result.bank,
        mode=result.mode,  # type: ignore[arg-type]
        consumes_trial_slot=result.consumes_trial_slot,
        production_item_count=result.production_item_count,
        production_item_limit=result.production_item_limit,
    )


@router.delete("/{connection_id}", status_code=204, dependencies=[CsrfDep])
async def disconnect(
    connection_id: str, owner: OwnerDep, service: ConnectionService = ServiceDep
) -> None:
    await service.disconnect(owner, connection_id)


__all__ = ["router"]
