/**
 * Fixed, typed table of the four v1 supported banks. The UI always renders
 * from this constant (never from provider-supplied markup), and it is the
 * single source of truth for display initials and the demo/sandbox
 * institution identifiers used when approving the simulated bank-hosted
 * dialog.
 */

export type BankSlug = 'capital-one' | 'chase' | 'citi' | 'wells-fargo'

export interface BankMeta {
  slug: BankSlug
  displayName: string
  initials: string
  /** Sandbox/demo Plaid institution id, used by the simulated demo dialog. */
  demoInstitutionId: string
}

export const SUPPORTED_BANKS: readonly BankMeta[] = [
  {
    slug: 'capital-one',
    displayName: 'Capital One',
    initials: 'CO',
    demoInstitutionId: 'ins_128026',
  },
  {
    slug: 'chase',
    displayName: 'Chase',
    initials: 'CH',
    demoInstitutionId: 'ins_3',
  },
  {
    slug: 'citi',
    displayName: 'Citi',
    initials: 'CI',
    demoInstitutionId: 'ins_5',
  },
  {
    slug: 'wells-fargo',
    displayName: 'Wells Fargo',
    initials: 'WF',
    demoInstitutionId: 'ins_4',
  },
]

export const BANKS_BY_SLUG: Readonly<Record<BankSlug, BankMeta>> = {
  'capital-one': SUPPORTED_BANKS[0],
  chase: SUPPORTED_BANKS[1],
  citi: SUPPORTED_BANKS[2],
  'wells-fargo': SUPPORTED_BANKS[3],
}
