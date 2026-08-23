import type { TransactionLimitAlertResponse } from '../limitations/api'

interface Props {
  alerts: TransactionLimitAlertResponse[]
}

function windowSummary(alert: TransactionLimitAlertResponse): string {
  if (alert.window.type === 'all_time') {
    return 'All available history'
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
