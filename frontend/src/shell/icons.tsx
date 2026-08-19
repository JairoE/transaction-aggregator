/**
 * Small inline icons. Every icon is decorative (`aria-hidden`) — state is
 * always conveyed to assistive technology through adjacent text as well, so
 * these never carry meaning on their own.
 */

export function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M4 10.5l3.5 3.5L16 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function ShieldIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M10 2l6 2.2v4.4c0 4-2.6 7-6 9-3.4-2-6-5-6-9V4.2L10 2z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true" focusable="false">
      <path
        d="M8 4H4v12h12v-4M11 3h6v6M9 11l8-8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function WarningIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M10 3l8 14H2L10 3z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M10 8.5v3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="10" cy="14.5" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function DotIcon() {
  return (
    <svg viewBox="0 0 20 20" width="10" height="10" aria-hidden="true" focusable="false">
      <circle cx="10" cy="10" r="6" fill="currentColor" />
    </svg>
  )
}
