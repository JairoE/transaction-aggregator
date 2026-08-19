import { render, screen } from '@testing-library/react'
import { App } from './app'

it('renders the product heading', () => {
  render(<App />)
  expect(
    screen.getByRole('heading', { name: 'Transaction Aggregator' }),
  ).toBeInTheDocument()
})
