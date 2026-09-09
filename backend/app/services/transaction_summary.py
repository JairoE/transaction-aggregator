"""Shared USD transaction-summary SQL and result conversion."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func

from app.models import Transaction


@dataclass(frozen=True)
class TransactionSummary:
    usd_match_count: int
    usd_pending_count: int
    purchases_cents: int
    refunds_cents: int
    net_total_cents: int


def transaction_summary_columns() -> tuple:
    """Return labelled aggregate columns for matching USD transactions."""

    is_usd = Transaction.currency_code == "USD"
    is_purchase = is_usd & (Transaction.amount_cents > 0)
    is_refund = is_usd & (Transaction.amount_cents < 0)
    return (
        func.coalesce(func.sum(case((is_usd, 1), else_=0)), 0).label(
            "usd_match_count"
        ),
        func.coalesce(
            func.sum(case((is_usd & Transaction.pending.is_(True), 1), else_=0)),
            0,
        ).label("usd_pending_count"),
        func.coalesce(
            func.sum(case((is_purchase, Transaction.amount_cents), else_=0)), 0
        ).label("purchases_cents"),
        func.coalesce(
            func.sum(case((is_refund, -Transaction.amount_cents), else_=0)), 0
        ).label("refunds_cents"),
        func.coalesce(
            func.sum(case((is_usd, Transaction.amount_cents), else_=0)), 0
        ).label("net_total_cents"),
    )


def transaction_summary_from_row(row) -> TransactionSummary:
    return TransactionSummary(
        usd_match_count=int(row.usd_match_count),
        usd_pending_count=int(row.usd_pending_count),
        purchases_cents=int(row.purchases_cents),
        refunds_cents=int(row.refunds_cents),
        net_total_cents=int(row.net_total_cents),
    )


__all__ = [
    "TransactionSummary",
    "transaction_summary_columns",
    "transaction_summary_from_row",
]
