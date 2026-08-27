import { BANKS_BY_SLUG, type BankSlug } from '../connections/banks'

interface CreditCardOutlineProps {
  bank: BankSlug
  bankDisplayName: string
  cardName: string
  mask: string | null
}

function ChipOutline() {
  return (
    <svg viewBox="0 0 38 30" aria-hidden="true">
      <rect x="1" y="1" width="36" height="28" rx="6" />
      <path d="M13 2v26M25 2v26M2 11h11M25 11h11M2 19h11M25 19h11" />
    </svg>
  )
}

function ContactlessOutline() {
  return (
    <svg viewBox="0 0 28 28" aria-hidden="true">
      <path d="M8.5 9.5a6.5 6.5 0 0 1 0 9M12.5 6a11 11 0 0 1 0 16M16.5 2.5a15.5 15.5 0 0 1 0 23" />
    </svg>
  )
}

export function CreditCardOutline({
  bank,
  bankDisplayName,
  cardName,
  mask,
}: CreditCardOutlineProps) {
  const lastFour = mask ?? '----'
  const bankMeta = BANKS_BY_SLUG[bank]

  return (
    <div
      className={`credit-card-outline credit-card-outline--${bank}`}
      role="img"
      aria-label={`${cardName}, issued by ${bankDisplayName}, card ending in ${lastFour}`}
    >
      <div className="credit-card-outline__topline">
        <span className="credit-card-outline__issuer">{bankDisplayName}</span>
        <span className="credit-card-outline__monogram" aria-hidden="true">
          {bankMeta.initials}
        </span>
      </div>

      <div className="credit-card-outline__account">
        <span className="credit-card-outline__chip">
          <ChipOutline />
        </span>
        <span className="credit-card-outline__number">•••• {lastFour}</span>
        <span className="credit-card-outline__contactless">
          <ContactlessOutline />
        </span>
      </div>

      <div className="credit-card-outline__footer">
        <span className="credit-card-outline__name">{cardName}</span>
        <span className="credit-card-outline__type">Credit</span>
      </div>
    </div>
  )
}
