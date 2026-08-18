# Transaction Aggregator Project Requirements Document

- **Status:** Approved for implementation planning
- **Version:** 1.0
- **Date:** August 18, 2026
- **Audience:** Product owner, designers, implementers, and reviewers

## 1. Executive Summary

Transaction Aggregator is a private, single-owner, local-first web application for searching credit-card transactions across Capital One, Chase, Citi, and Wells Fargo. The owner connects each institution through Plaid, authorizes multiple credit cards under each bank login, and searches cached transaction history from one dashboard.

The defining experience is a single search field above a responsive grid. Each grid panel represents one credit card and contains its own transaction list. A search for `Paze`, for example, returns every matching transaction while preserving the card-by-card grouping.

Plaid is the only financial-data provider in v1. The application never collects or stores bank usernames, passwords, or MFA responses. Bank authentication and consent happen in Plaid- and bank-hosted interfaces.

## 2. Problem and Goal

### Problem

The owner has multiple credit cards at four banks. Finding a transaction requires signing into several bank applications, searching each card independently, and mentally combining the results. Bank portals also vary in search behavior, history depth, and transaction descriptions.

### Goal

Provide one secure, fast, locally cached search experience that:

1. Connects the owner's Capital One, Chase, Citi, and Wells Fargo accounts.
2. Discovers every authorized credit card under each connection.
3. Retrieves and incrementally maintains up to 730 days of available transactions.
4. Searches merchant and statement text across all cards.
5. Displays results in independently readable card panels on one page.

## 3. Product Principles

- **Credentials stay with the bank.** The application uses OAuth-capable Plaid Link and never renders bank credential fields.
- **Local data serves the interface.** Searches and card views read from SQLite, not directly from Plaid.
- **One connection, many cards.** Plaid synchronization occurs once per Item and results are grouped by its credit-card accounts.
- **Freshness is explicit.** Every card and bank connection shows its last successful synchronization time and health state.
- **Partial failure is normal.** One unavailable institution does not block cached search or synchronization of other institutions.
- **Trial capacity is scarce.** Production Item creation is deliberate because the Plaid Trial limit is cumulative and deleted Items do not restore capacity.

## 4. User and Operating Model

### Primary User

The only v1 user is the application owner. Public signup, invitations, shared households, and tenant administration are not supported.

### Deployment Model

- The application runs on the owner's computer and binds its application server to localhost.
- A stable HTTPS URL forwards OAuth callbacks and optional webhooks to the local application while it is running.
- The frontend and API use one origin in the production-like local deployment.
- Cached transactions remain searchable when the internet, Plaid, or an institution is unavailable.
- Full-disk encryption is an operating prerequisite for the local device.

## 5. Research and Provider Decision

### Selected Provider: Plaid

Plaid is selected because it provides:

- OAuth access to Capital One, Chase, Citi, and Wells Fargo on the Trial plan.
- Transactions for credit-card accounts.
- Up to 730 days of requested transaction history.
- Incremental added, modified, and removed updates through `/transactions/sync`.
- React bindings through `react-plaid-link` and an official Python client through `plaid-python`.
- Unlimited API calls against existing Trial Items.

The Trial plan allows at most 10 production Items. An Item represents one end-user connection to one financial institution. Calling `/item/remove` does not free a Trial slot. The app therefore targets one Item for each of the four banks and reserves the other six slots for exceptional additional logins or recovery.

### Rejected Alternatives

| Alternative | Reason not selected for v1 |
| --- | --- |
| Direct bank APIs | Requires separate partnerships, onboarding, consent flows, schemas, testing, and operational support for four institutions. Chase's own account-data demo is intended for existing partners. |
| MX | Provides a capable Connect widget and aggregation API, but adds another enterprise provider relationship without a material v1 advantage for this personal use case. |
| Stripe Financial Connections | Supports connected financial accounts and transactions but exposes up to 180 days of history, which is less than Plaid's maximum. |
| Credential automation or screen scraping | Would expose bank credentials, conflict with the security model, and create fragile behavior around MFA, bot detection, and portal changes. |

## 6. Scope

### In Scope

- Single-owner application login and session management.
- Plaid Sandbox and Trial environments.
- Capital One, Chase, Citi, and Wells Fargo connections.
- Multiple credit cards per bank connection.
- Credit-card transaction history requested up to 730 days.
- Pending transactions when the institution supplies them.
- Incremental synchronization, startup recovery, manual synchronization, and optional webhook triggers.
- Keyword search across all cached credit-card transactions.
- Card-by-card responsive result grid with separate list pagination and scrolling.
- Connection health, synchronization freshness, consent renewal, and disconnect flows.
- Local-first operation and a documented stable HTTPS callback/tunnel setup.

### Out of Scope

- Payments, transfers, card servicing, balance payments, or money movement.
- Checking, savings, investment, mortgage, or loan dashboards.
- Budgets, spending analysis, categories, rewards, statements, or credit scores.
- CSV import or export.
- Public signup, multiple users, invitations, or household sharing.
- Native iOS or Android applications.
- Provider abstraction or a second aggregation provider.
- Direct bank APIs, browser automation, credential capture, or screen scraping.

## 7. Core User Journey

1. The owner opens the local application and signs in.
2. The owner sees four bank connection cards.
3. Selecting a bank starts Plaid Link with Transactions and credit accounts enabled.
4. The owner authenticates on the bank-hosted OAuth screen and selects all desired credit cards.
5. The application exchanges the returned public token server-side, encrypts the access token, records the Item, discovers credit-card accounts, and begins the initial synchronization.
6. The connection card shows initial and historical loading progress without blocking other banks.
7. After all desired banks are connected, the dashboard displays one panel per credit card.
8. With no query, each panel shows recent cached transactions sorted newest first.
9. The owner types `Paze` and submits with the button or Enter.
10. Every card remains visible, displays its match count, and lists only matching transactions. Cards with no matches show an explicit zero-result state.

## 8. Functional Requirements

### 8.1 Owner Authentication

- **FR-AUTH-001:** The application shall support exactly one owner account created through a local CLI command.
- **FR-AUTH-002:** The login screen shall require the owner's email address and password.
- **FR-AUTH-003:** Successful login shall create an opaque server-side session and set an HttpOnly cookie.
- **FR-AUTH-004:** Every bank, synchronization, search, and management endpoint shall require an authenticated owner session.
- **FR-AUTH-005:** Mutating requests shall require a CSRF token and an allowed same-origin `Origin` header.
- **FR-AUTH-006:** Logout shall invalidate the server-side session before clearing the browser cookie.

### 8.2 Bank Connections

- **FR-CONN-001:** The connection page shall list Capital One, Chase, Citi, and Wells Fargo with connected, loading, healthy, attention, or disconnected status.
- **FR-CONN-002:** A new Link token shall initialize only the Transactions product, request 730 days, use US country coverage, filter for credit accounts, include the stable OAuth redirect, and identify the Plaid user created for the owner.
- **FR-CONN-003:** The application shall use Plaid's current User API for a new integration and persist the owner's Plaid `user_id`.
- **FR-CONN-004:** The browser shall pass the temporary public token and Link institution metadata to the backend. Plaid secrets and access tokens shall never reach frontend storage.
- **FR-CONN-005:** The backend shall exchange the public token, encrypt the access token, store the Item ID, and fetch account metadata.
- **FR-CONN-006:** Only `credit` accounts shall appear as cards. Non-credit accounts returned by an institution shall be ignored by the dashboard.
- **FR-CONN-007:** The owner shall be instructed to select the bank represented by the initiating bank tile and every desired credit card during Link.
- **FR-CONN-008:** The backend shall reject a second active connection for the same owner and institution and direct the owner to update mode instead.
- **FR-CONN-009:** Production Link creation shall be blocked when the local cumulative production Item count is 10.
- **FR-CONN-010:** Before every production Link launch, the interface shall show the current cumulative Item count and require explicit confirmation that a new permanent Trial slot will be consumed.
- **FR-CONN-011:** Removed connections shall remain as token-free tombstone records so the cumulative Trial Item count remains accurate.
- **FR-CONN-012:** Update mode shall be used for expired consent, `ITEM_LOGIN_REQUIRED`, and account-selection changes whenever Plaid permits it.

### 8.3 Transaction Synchronization and Cache

- **FR-SYNC-001:** Search and dashboard requests shall read only from the local database.
- **FR-SYNC-002:** Synchronization shall run once per bank Item and process transactions for all accounts returned by that Item.
- **FR-SYNC-003:** A new connection shall begin with an empty `/transactions/sync` cursor and paginate until `has_more` is false.
- **FR-SYNC-004:** Added transactions shall be inserted, modified transactions shall be updated, and removed transactions shall be removed from active search results in one database transaction with the new cursor.
- **FR-SYNC-005:** If Plaid reports a mutation-during-pagination error, the page loop shall restart from the cursor that began that synchronization attempt.
- **FR-SYNC-006:** Repeated pages, jobs, and webhooks shall be idempotent and shall never create duplicate Plaid transaction IDs.
- **FR-SYNC-007:** Startup shall enqueue any active connection that has not synchronized successfully in the previous 60 minutes.
- **FR-SYNC-008:** While the app is running, a scheduler shall enqueue stale active connections every 60 minutes.
- **FR-SYNC-009:** A verified `SYNC_UPDATES_AVAILABLE` webhook shall enqueue, not directly execute, a synchronization job and return within 10 seconds.
- **FR-SYNC-010:** Missing webhooks shall not affect correctness; the next startup or scheduled synchronization shall consume all cursor updates.
- **FR-SYNC-011:** A manual Sync action shall deduplicate against an already queued or running job for the same Item.
- **FR-SYNC-012:** Manual provider refresh shall be best-effort, rate-limited per Item, and disabled after Plaid reports that the capability is unsupported.
- **FR-SYNC-013:** The UI shall distinguish local sync completion from Plaid's last successful provider update.
- **FR-SYNC-014:** Initial history loading shall show recent data as it becomes available and continue historical backfill without blanking the dashboard.

### 8.4 Search

- **FR-SRCH-001:** The dashboard shall provide one visible search input and one visible Search button above the card grid.
- **FR-SRCH-002:** Search shall run only on explicit submit or Enter; typing alone shall not issue API requests.
- **FR-SRCH-003:** Leading and trailing whitespace shall be removed and case shall be ignored.
- **FR-SRCH-004:** The entire submitted query shall match as a substring of merchant name, Plaid transaction name, or original statement description.
- **FR-SRCH-005:** A blank query shall return recent transactions for every active card.
- **FR-SRCH-006:** Results shall be grouped by card and sorted by transaction date descending, then provider transaction ID for deterministic ties.
- **FR-SRCH-007:** The response shall include total matches, per-card match counts, the first page for every card, and an independent continuation cursor per card.
- **FR-SRCH-008:** Additional rows shall be fetched only for the card whose list reaches its continuation threshold.
- **FR-SRCH-009:** The submitted term shall be highlighted in visible merchant and statement text without changing the stored data.
- **FR-SRCH-010:** Search shall be parameterized and shall treat punctuation as text rather than query syntax.

### 8.5 Card Grid

- **FR-GRID-001:** Each active credit card shall have one panel containing bank name, card name, last four digits, match count, connection health, and last synchronization time.
- **FR-GRID-002:** A transaction row shall show date, merchant or normalized name, original statement description when different, amount, and pending status when available.
- **FR-GRID-003:** Every card shall remain in the grid after a search, including cards with zero matches.
- **FR-GRID-004:** Each panel shall maintain its own list position and continuation state.
- **FR-GRID-005:** The desktop layout shall use four columns at 1200 px and wider, two columns from 768–1199 px, and one column below 768 px.
- **FR-GRID-006:** Lists with more than 50 rendered rows shall be virtualized.
- **FR-GRID-007:** Loading shall use stable skeleton regions so bank and transaction updates do not shift surrounding panels.

### 8.6 Connection Management

- **FR-MGMT-001:** The owner shall be able to inspect Item health, provider freshness, local sync time, consent expiration, selected card count, and the last actionable error.
- **FR-MGMT-002:** Recoverable errors shall provide a Retry or Reconnect action specific to the affected bank.
- **FR-MGMT-003:** Disconnect shall require confirmation, call `/item/remove`, delete decrypted token material, purge that connection's cached cards and transactions, and retain only the non-sensitive Trial-slot tombstone.
- **FR-MGMT-004:** Disconnect copy shall warn that the Plaid Trial Item slot is not restored.

## 9. Conceptual Data Model

| Entity | Purpose | Required identifying fields |
| --- | --- | --- |
| Owner | Single local application user | ID, email, password hash, Plaid user ID |
| Owner Session | Revocable browser session | Token hash, CSRF secret, expiry, owner ID |
| Bank Connection | Active Item or removed Trial-slot tombstone | Institution, Plaid Item ID, encrypted access token fields, lifecycle status, sync cursor, consent/freshness timestamps |
| Card Account | One authorized Plaid credit account | Connection ID, Plaid account ID, names, mask, active state |
| Transaction | Locally searchable transaction | Plaid transaction ID, card ID, dates, descriptions, amount, currency, pending state, normalized search text |
| Sync Job | Durable request to synchronize an Item | Connection ID, trigger, state, attempts, run time, error |
| Sync Run | Audit record for one attempt | Starting/ending cursors, counts, timestamps, outcome |
| Webhook Receipt | Deduplication and audit record | Payload hash, webhook type/code, received time |

Plaid transaction IDs and account IDs are external identifiers, not display-safe secrets. Access tokens are secrets and shall only be available as decrypted values inside the backend Plaid client call boundary.

## 10. Recommended Technical Stack

### Frontend

- React with TypeScript and Vite.
- React Router for the signed-out, connection, OAuth return, dashboard, and management routes.
- TanStack Query for authenticated API state and invalidation after sync.
- TanStack Virtual for long per-card transaction lists.
- `react-plaid-link` for the Link lifecycle.
- Testing Library, Vitest, MSW, and Playwright for tests.

### Backend

- Python 3.12 with FastAPI and Pydantic.
- SQLAlchemy 2 with Alembic and SQLite in WAL mode.
- SQLite FTS5 using the trigram tokenizer for cached substring search, with a parameterized fallback for queries shorter than three characters.
- Official `plaid-python` client.
- `cryptography` AES-GCM for Plaid access-token encryption.
- Argon2id password hashing and opaque database-backed sessions.
- Pytest, HTTPX, and freezegun for tests.

### Background Work

The v1 application shall use a durable SQLite job table and one in-process worker started through FastAPI lifespan. Redis, Celery, RabbitMQ, and PostgreSQL are intentionally excluded. The job table provides recovery after process restarts; only one synchronization job may be queued or running for a connection.

## 11. Security and Privacy Requirements

- **SEC-001:** Bank credentials and MFA responses shall only be entered into bank- or Plaid-hosted interfaces.
- **SEC-002:** Plaid client ID and secret shall be backend environment secrets and shall never enter the frontend bundle.
- **SEC-003:** Access tokens shall be encrypted with AES-256-GCM using a versioned 32-byte key supplied outside the database.
- **SEC-004:** The token encryption key shall be stored in the operating-system keychain or injected into the process; it shall not be committed or stored beside the database.
- **SEC-005:** Passwords shall be hashed with Argon2id and shall never be logged.
- **SEC-006:** Session tokens shall contain at least 256 bits of randomness and only their SHA-256 hashes shall be stored.
- **SEC-007:** Session cookies shall be HttpOnly, SameSite=Strict, scoped to the application, and Secure whenever accessed through HTTPS.
- **SEC-008:** Mutations shall require CSRF validation and an expected Origin.
- **SEC-009:** Plaid webhooks shall be verified using the `Plaid-Verification` signature before persistence or job creation.
- **SEC-010:** Logs shall exclude access tokens, public tokens, bank credentials, session tokens, full transaction descriptions, and raw webhook bodies.
- **SEC-011:** The SQLite database and secret files shall be owner-readable only and reside on encrypted storage.
- **SEC-012:** API errors returned to the browser shall use stable application codes and shall not expose stack traces or provider secrets.

## 12. Performance, Reliability, and Accessibility

### Performance

- A cached search over 50,000 transactions shall return its first grouped page within 250 ms at p95 on the owner's development-class laptop.
- The first dashboard response shall not make Plaid API calls.
- The frontend shall avoid request waterfalls by loading connection/card summaries and grouped first pages through aggregate endpoints.
- Per-card continuation requests shall return no more than 50 transactions.

### Reliability

- A failed synchronization shall preserve the previous cache and cursor.
- Database writes and cursor advancement shall commit atomically.
- The worker shall retry transient provider and network failures with capped exponential backoff and shall stop automatic retries for owner-action errors.
- One connection's failure shall not cancel or roll back another connection's work.
- Webhooks may be duplicated, delayed, or lost without corrupting local state.

### Accessibility

- The interface shall meet WCAG 2.2 AA color contrast and keyboard-operability expectations.
- Inputs shall have visible labels and errors shall identify both cause and recovery action.
- Connection and synchronization state shall include text and icons rather than color alone.
- Dynamic result counts and connection outcomes shall use polite live-region announcements.
- Touch targets shall be at least 44 by 44 CSS pixels.
- Motion shall respect `prefers-reduced-motion`.

## 13. Institution and Trial Constraints

- Capital One credit-only Items do not provide pending transactions.
- Capital One credit-only Items do not support `/transactions/refresh`; the app shall continue cursor synchronization and show the last provider update instead.
- Capital One may provide only 90 days of transaction history even when the app requests 730 days; the interface shall report available provider history without implying that every bank supplied the full request window.
- Capital One does not allow past-due credit cards to be linked.
- Capital One and Citi require periodic consent refresh; the app shall treat Plaid's consent expiration metadata and pending-disconnect signals as authoritative.
- Chase account permission changes may need to be completed in the Chase Security Center.
- Institution availability and OAuth approval remain external dependencies even when the provider generally lists support.
- Trial eligibility requires a developer in the United States or Canada without an existing Plaid Production or Limited Production account.
- Production Item creation must use real accounts sparingly; Sandbox shall be used for repeated development and automated testing.

## 14. Success Measures

- The owner can connect one login at each target bank and see every selected credit card as a separate panel.
- Searching `Paze` once returns all matching cached transactions across every card without visiting a bank portal.
- No search request calls Plaid or waits for a bank.
- Added, modified, and removed transactions reconcile without duplicates.
- Cached searches remain usable while offline.
- A bank error is visible and actionable without hiding other banks' data.
- Four normal bank connections consume four, not one Item per card, Trial slots.

## 15. Acceptance Scenarios

1. **Owner login:** Valid credentials create a session; invalid credentials do not reveal whether the email exists.
2. **Four-bank connection:** Each target institution completes Link, returns two sample credit cards, and consumes one Item.
3. **Duplicate prevention:** Attempting to create another active Item for an already connected institution is blocked before Link is launched.
4. **Trial cap:** A cumulative production count of 10 prevents an eleventh Link launch while Sandbox remains usable.
5. **Initial history:** The UI shows recent transactions first and later incorporates historical pages without duplicate rows.
6. **Paze search:** In the approved eight-card acceptance fixture, a case-insensitive `Paze` query returns 10 matches across eight grouped cards using merchant, name, and original-description occurrences.
7. **Zero-match card:** A card without a match remains visible with `0 matches` and a clear empty message.
8. **Independent continuation:** Scrolling one card loads only that card's next page and preserves other card positions.
9. **Incremental reconciliation:** Added, modified, and removed fixtures update the local cache and cursor in one commit.
10. **Pagination mutation:** A simulated mutation-during-pagination response restarts from the attempt's original cursor.
11. **Duplicate webhook:** Replaying the same signed webhook creates at most one pending sync job.
12. **Offline search:** Disabling network access leaves cached dashboard and search behavior functional with stale status.
13. **Capital One refresh:** An unsupported refresh response disables that capability without marking cached transactions unavailable.
14. **Consent renewal:** A pending-disconnect or login-required state offers update mode and retains cached data.
15. **Disconnect:** Confirmed removal revokes the Item, purges financial data, and retains a non-sensitive consumed-slot tombstone.
16. **Security:** Browser bundles, API responses, logs, and repository history contain no Plaid secret or access token.
17. **Responsive layout:** Eight cards render in four, two, and one columns at the specified breakpoints without horizontal page overflow.

## 16. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Trial Item slots are permanently consumed | Default to Sandbox, display the cumulative count, require confirmation, block duplicates, and retain tombstones. |
| Local app misses webhooks while stopped | Treat webhooks as accelerators; reconcile from the stored cursor on startup and schedule. |
| Provider data is delayed or incomplete | Show provider freshness separately from local sync, preserve cache, and document institution limitations. |
| Stable HTTPS callback is unavailable | Make the callback/tunnel a production-link prerequisite and keep Sandbox localhost support for development. |
| Token key is lost | Document secure key backup; fail closed rather than storing or logging decrypted access tokens. |
| Device compromise exposes transaction data | Require full-disk encryption, owner-only permissions, application login, and a minimal local attack surface. |
| Large result sets degrade the dashboard | Use local FTS, grouped first pages, independent cursor pagination, and list virtualization. |

## 17. Release Readiness Gates

- Plaid Trial account approved and OAuth enabled for all four institutions.
- Stable HTTPS redirect registered in the Plaid dashboard.
- Sandbox Link, update mode, sync, refresh, and webhook fixtures pass.
- Production Item counter is zero or reconciled before the first real connection.
- Owner account and encryption key are created through documented local commands.
- Database directory permissions and encrypted-volume prerequisite are verified.
- All acceptance scenarios pass with mock/Sandbox data.
- A controlled live test connects each bank only once and confirms the expected card inventory.

## 18. Sources

- [Plaid Trial plan](https://support.plaid.com/hc/en-us/articles/39994173227159-What-is-the-Plaid-Trial-plan)
- [Plaid Link OAuth guide](https://plaid.com/docs/link/oauth/)
- [Plaid Link API](https://plaid.com/docs/api/link/)
- [Plaid User API](https://plaid.com/docs/api/users/)
- [Plaid Transactions](https://plaid.com/docs/transactions/)
- [Plaid Transactions API](https://plaid.com/docs/api/products/transactions/)
- [Plaid Transactions troubleshooting](https://plaid.com/docs/transactions/troubleshooting/)
- [Plaid webhook behavior](https://plaid.com/docs/api/webhooks/)
- [Plaid webhook verification](https://plaid.com/docs/api/webhooks/webhook-verification/)
- [`react-plaid-link`](https://github.com/plaid/react-plaid-link)
- [`plaid-python`](https://github.com/plaid/plaid-python)
- [Vite getting started](https://vite.dev/guide/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [MX accounts documentation](https://docs.mx.com/api-reference/platform-api/v20111101/reference/accounts)
- [Stripe Financial Connections transactions](https://docs.stripe.com/financial-connections/transactions)
- [Chase Account Data Sharing demo](https://apidemo.chase.com/)
