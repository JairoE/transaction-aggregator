import { CardPanel } from './CardPanel'
import type { CardTransactionGroup } from './api'

/**
 * The raw API shape plus a client-only flag for whether *this* card's next
 * page is currently being fetched. Adding a field here (rather than a new
 * prop) keeps the pinned `CardGrid({ groups, onLoadMore })` /
 * `CardPanel({ group, onLoadMore })` signatures intact.
 */
export interface DashboardCardGroup extends CardTransactionGroup {
  isLoadingMore: boolean
}

export interface CardGridProps {
  groups: DashboardCardGroup[]
  onLoadMore: (cardId: string) => void
}

export function CardGrid({ groups, onLoadMore }: CardGridProps) {
  return (
    <div className="card-grid">
      {groups.map((group) => (
        <div className="card-grid__item" key={group.card.id}>
          <CardPanel group={group} onLoadMore={() => onLoadMore(group.card.id)} />
        </div>
      ))}
    </div>
  )
}
