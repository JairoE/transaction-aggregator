import { useState } from 'react'
import { CardPanel } from './CardPanel'
import type { CardTransactionGroup } from './api'
import type { TransactionLimitAlertResponse } from '../limitations/api'
import type { SavedTransactionAggregateResponse } from '../aggregates/api'

/**
 * The raw API shape plus a client-only flag for whether *this* card's next
 * page is currently being fetched. Adding a field here (rather than a new
 * prop) keeps the pinned `CardGrid({ groups, onLoadMore })` /
 * `CardPanel({ group, onLoadMore })` signatures intact.
 */
export interface DashboardCardGroup extends CardTransactionGroup {
  isLoadingMore: boolean
  limitationAlerts: TransactionLimitAlertResponse[]
  savedAggregates: SavedTransactionAggregateResponse[]
}

export interface CardGridProps {
  groups: DashboardCardGroup[]
  onLoadMore: (cardId: string) => void
}

interface BankCardGroup {
  bank: DashboardCardGroup['card']['bank']
  bankDisplayName: string
  groups: DashboardCardGroup[]
}

function groupCardsByBank(groups: DashboardCardGroup[]): BankCardGroup[] {
  const banks = new Map<DashboardCardGroup['card']['bank'], BankCardGroup>()

  for (const group of groups) {
    const existing = banks.get(group.card.bank)
    if (existing) {
      existing.groups.push(group)
      continue
    }

    banks.set(group.card.bank, {
      bank: group.card.bank,
      bankDisplayName: group.card.bank_display_name,
      groups: [group],
    })
  }

  return [...banks.values()]
}

interface BankCardSectionProps {
  bankGroup: BankCardGroup
  onLoadMore: (cardId: string) => void
}

function BankCardSection({ bankGroup, onLoadMore }: BankCardSectionProps) {
  const [isExpanded, setIsExpanded] = useState(true)
  const contentId = `bank-card-group-${bankGroup.bank}`
  const action = isExpanded ? 'Collapse' : 'Expand'

  return (
    <section className="bank-card-group" aria-label={`${bankGroup.bankDisplayName} cards`}>
      <h2 className="bank-card-group__heading">
        <button
          type="button"
          className="bank-card-group__toggle"
          aria-expanded={isExpanded}
          aria-controls={contentId}
          aria-label={`${action} ${bankGroup.bankDisplayName} cards`}
          onClick={() => setIsExpanded((expanded) => !expanded)}
        >
          <span>{bankGroup.bankDisplayName}</span>
          <span className="disclosure-indicator" aria-hidden="true">
            {isExpanded ? '−' : '+'}
          </span>
        </button>
      </h2>
      <div className="card-grid" id={contentId} hidden={!isExpanded}>
        {bankGroup.groups.map((group) => (
          <div className="card-grid__item" key={group.card.id}>
            <CardPanel group={group} onLoadMore={() => onLoadMore(group.card.id)} />
          </div>
        ))}
      </div>
    </section>
  )
}

export function CardGrid({ groups, onLoadMore }: CardGridProps) {
  return (
    <div className="bank-card-groups">
      {groupCardsByBank(groups).map((bankGroup) => (
        <BankCardSection key={bankGroup.bank} bankGroup={bankGroup} onLoadMore={onLoadMore} />
      ))}
    </div>
  )
}
