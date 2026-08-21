import type { ReactNode } from 'react'

/**
 * Case-insensitive literal-substring highlighter for the submitted search
 * term. Deliberately avoids `RegExp` entirely — this is a plain `indexOf`
 * scan — so a term containing regex metacharacters (`a*b`) can never change
 * matching behavior or throw a "nothing to repeat" style error. It also
 * builds an array of React nodes rather than an HTML string, so a
 * term that looks like markup (`<b>`) is rendered as literal text and can
 * never be injected as an element.
 */
export function highlightText(text: string, term: string): ReactNode {
  const needle = term.trim().toLowerCase()
  if (!needle) {
    return text
  }

  const haystack = text.toLowerCase()
  let matchIndex = haystack.indexOf(needle)
  if (matchIndex === -1) {
    return text
  }

  const nodes: ReactNode[] = []
  let cursor = 0
  let key = 0

  while (matchIndex !== -1) {
    if (matchIndex > cursor) {
      nodes.push(text.slice(cursor, matchIndex))
    }
    const matchEnd = matchIndex + needle.length
    nodes.push(
      <mark key={key++} className="tx-highlight">
        {text.slice(matchIndex, matchEnd)}
      </mark>,
    )
    cursor = matchEnd
    matchIndex = haystack.indexOf(needle, cursor)
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor))
  }

  return nodes
}
