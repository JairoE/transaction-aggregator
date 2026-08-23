import type { TransactionLimitAlertResponse } from '../limitations/api'
import { formatDateWithYear, formatShortDate } from './format'

interface Props {
  alerts: TransactionLimitAlertResponse[]
}

function windowSummary(alert: TransactionLimitAlertResponse): string {
  if (alert.window.type === 'all_time') {
    return 'All available history'
  }
  if (alert.window.type === 'rolling') {
    return `Last ${alert.window.days} days (${formatShortDate(alert.window.effective_start_date)}–${formatShortDate(alert.window.effective_end_date)})`
  }
  if (alert.window.type === 'fixed') {
    return `${formatShortDate(alert.window.effective_start_date)}–${formatDateWithYear(alert.window.effective_end_date)}`
  }
  return 'Selected date window'
}

export function TransactionLimitAlerts({ alerts }: Props) {
  if (alerts.length === 0) {
    return null
  }

  return (
    <div className="transaction-limit-alerts">
      {alerts.map((alert) => (
        <div className="transaction-limit-alert" role="alert" key={alert.rule_id}>
          <strong>{alert.match_count} transactions match “{alert.keyword}”</strong>
          <span>
            Threshold: {alert.threshold} · {alert.pending_count} pending · {windowSummary(alert)}
          </span>
          <span className="transaction-limit-alert__notice">Informational only — transactions are not blocked.</span>
        </div>
      ))}
    </div>
  )
}
