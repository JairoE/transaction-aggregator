export type DashboardView = 'cards' | 'transactions'

export interface DashboardViewToggleProps {
  view: DashboardView
  onChange: (view: DashboardView) => void
}

/** URL-independent control: DashboardPage owns the URL mutation and history. */
export function DashboardViewToggle({ view, onChange }: DashboardViewToggleProps) {
  return (
    <div className="dashboard-view-toggle" role="group" aria-label="Dashboard view">
      <button type="button" aria-pressed={view === 'cards'} onClick={() => onChange('cards')}>
        All cards
      </button>
      <button type="button" aria-pressed={view === 'transactions'} onClick={() => onChange('transactions')}>
        All transactions
      </button>
    </div>
  )
}
