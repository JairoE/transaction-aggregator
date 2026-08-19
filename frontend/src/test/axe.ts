import { act } from '@testing-library/react'
import axe, { type AxeResults } from 'axe-core'

/**
 * Runs an axe-core smoke check against a rendered container. Color-contrast
 * is disabled because jsdom has no real layout/paint engine, so contrast
 * results there are meaningless noise rather than a signal. Wrapped in
 * `act` because any in-flight query (e.g. the session fetch) can settle
 * while axe walks the DOM.
 */
export async function runAxeSmokeTest(container: Element): Promise<void> {
  let results: AxeResults | undefined
  await act(async () => {
    results = await axe.run(container, {
      rules: {
        'color-contrast': { enabled: false },
      },
    })
  })
  if (!results) {
    throw new Error('axe-core did not return results')
  }
  if (results.violations.length > 0) {
    const details = results.violations
      .map((violation) => `${violation.id}: ${violation.description}`)
      .join('\n')
    throw new Error(`axe-core found accessibility violations:\n${details}`)
  }
}
