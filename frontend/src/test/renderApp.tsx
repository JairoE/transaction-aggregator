import { render } from '@testing-library/react'
import { App } from '../app'

/** Renders the full app at a given path, driving the real BrowserRouter. */
export function renderAppAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<App />)
}
