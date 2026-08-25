# Transaction Limitations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add owner-managed, per-card transaction-count rules with all-time, rolling-day, and fixed-date windows, then show qualifying informational alerts on the dashboard with total and pending counts.

**Architecture:** Persist owner-scoped rule definitions and selected-card associations in SQLite. A dedicated limitation service owns CRUD, shared literal matching, and query-time grouped evaluation; REST endpoints expose rule management and derived active alerts. React manages rules on `/transaction-limitations`, fetches alerts independently from search, and joins them into existing card panels by card ID.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, SQLite/FTS5, React 19, TypeScript 5.7, TanStack Query 5, Vitest/Testing Library/MSW, pytest, Playwright, axe-core.

**Spec:** `docs/features/transaction-limitations/PRD.md`

## Global Constraints

- Limits are informational only; no copy or API may imply transaction blocking.
- Alert activation is `match_count >= threshold`.
- All-card rules evaluate each active card independently and dynamically include cards connected later.
- Pending transactions count toward the threshold; every alert returns and displays `pending_count`, including zero.
- Matching must reuse the current case-insensitive literal-substring behavior in `app.services.search_service.normalize_query`; punctuation remains literal.
- Effective date is `posted_date` when present, otherwise `authorized_date`.
- All-time, rolling, and fixed window capabilities must land successively, and no commit may add behavior for more than one window type.
- Rolling windows are inclusive, use the host calendar date, accept 1–730 days, and inject `as_of_date` in tests.
- Fixed windows have inclusive ISO date boundaries and require `start_date <= end_date`.
- Alert evaluation reads SQLite only and never calls Plaid.
- JSON follows the repository's existing `snake_case` convention and generated OpenAPI types.
- No new runtime dependencies.
- Mutations retain authenticated owner, CSRF, and Origin protections.
- Rule keywords, matching transaction text, card names/masks, and request bodies must not be logged.
- The feature must not change existing transaction-search response behavior.
- Keep the task checklist in this plan; do not create `tasks/todo.md`, because the requested deliverable is exactly the PRD and this implementation plan.

---

## 1. Worktree and Baseline Gate

This plan was written in the linked worktree:

```text
/Users/jairoespinosa/.codex/worktrees/30756518-8414-4b50-b761-3e5e044d2c8f/transaction-aggregator
```

At planning time it was an externally managed detached HEAD at `cce3784` (`origin/main`). Do not create a nested worktree. Before implementation, use the Codex app's **Create branch** control and name the branch `feature/transaction-limitations`, or execute the plan in another linked worktree already attached to that branch.

Fresh baseline evidence on August 22, 2026:

```text
make check
backend: 201 passed, 1 failed, 4 skipped, 17 deselected
failure: tests/test_static_app.py::test_api_routes_never_fall_through_to_the_spa
reason: 404 response has no expected top-level "code" field
```

That failure predates this plan and is outside the transaction-limitations scope. Before Task 1, the owner must either merge its fix or explicitly accept it as a known baseline exception. Every focused feature suite still has to pass; no new failure may be masked by the exception.

- [ ] Confirm `git rev-parse --show-toplevel` points to the intended linked worktree.
- [ ] Confirm `git branch --show-current` returns `feature/transaction-limitations` before the first commit.
- [ ] Run `git status --short` and preserve any unrelated owner changes.
- [ ] Run `make check` and record whether the known static-app failure is fixed or explicitly waived.

## 2. Dependency Graph and Vertical Slices

```text
all-time persistence
  └── all-time CRUD/evaluation API
        └── all-time management + dashboard alerts
              └── rolling schema/evaluation API
                    └── rolling form and alert copy
                          └── fixed schema/evaluation API
                                └── fixed form and alert copy
                                      └── E2E + scale verification
```

Window commits are monotonic: all-time comes first, rolling extends it without fixed behavior, and fixed extends both. Migration history follows the same sequence (`0003`, `0004`, `0005`) so each capability can be reviewed and reverted independently.

## 3. File Responsibility Map

### Backend

| File | Responsibility |
| --- | --- |
| `backend/alembic/versions/0003_transaction_limitations_all_time.py` | Initial rule/card tables supporting `all_time` only. |
| `backend/alembic/versions/0004_transaction_limitations_rolling.py` | Add rolling-day storage and constraints. |
| `backend/alembic/versions/0005_transaction_limitations_fixed.py` | Add fixed-date storage and constraints. |
| `backend/app/models.py` | ORM models and relationships for rules and selected cards. |
| `backend/app/schemas.py` | Discriminated window inputs/outputs plus rule and alert wire contracts. |
| `backend/app/services/limitation_service.py` | Owner-scoped CRUD, invariant validation, and grouped query-time evaluation. |
| `backend/app/api/limitations.py` | Protected CRUD and active-alert endpoints. |
| `backend/app/main.py` | Router registration only. |
| `backend/tests/migrations/test_transaction_limitations.py` | Upgrade/downgrade, checks, FK, and cascade tests for all three revisions. |
| `backend/tests/services/test_limitation_service.py` | Rule behavior, matching, grouping, windows, pending counts, and ownership. |
| `backend/tests/api/test_limitations.py` | Authenticated REST contract and validation tests. |
| `backend/tests/conftest.py` | Reusable multi-card/transaction feature fixtures only when sharing reduces duplication. |

### Frontend

| File | Responsibility |
| --- | --- |
| `frontend/src/limitations/api.ts` | Generated-type aliases, query keys, and CRUD/alert fetch helpers. |
| `frontend/src/limitations/TransactionLimitationsPage.tsx` | Page-level queries, mutation invalidation, loading/error/empty composition. |
| `frontend/src/limitations/TransactionLimitationForm.tsx` | Accessible create/edit form and window-specific fields. |
| `frontend/src/limitations/TransactionLimitationList.tsx` | Saved rule summary, enable/disable, edit, and confirmed delete controls. |
| `frontend/src/limitations/transaction-limitations.test.tsx` | MSW-backed management behavior and axe checks. |
| `frontend/src/dashboard/TransactionLimitAlerts.tsx` | Accessible per-card active-alert list and human-readable window copy. |
| `frontend/src/dashboard/transaction-limit-alerts.test.tsx` | Dashboard alert rendering, independence from search, error isolation, and axe. |
| `frontend/src/dashboard/CardGrid.tsx` | Client-only merge shape carrying alerts with each card group. |
| `frontend/src/dashboard/CardPanel.tsx` | Render alert list only for the represented card. |
| `frontend/src/dashboard/DashboardPage.tsx` | Independent alert query and merge by card ID. |
| `frontend/src/app.tsx` | Protected `/transaction-limitations` route. |
| `frontend/src/shell/AppShell.tsx` | Navigation entry without renumbering the existing owner journey semantics incorrectly. |
| `frontend/src/styles.css` | Responsive management and alert styles using existing tokens. |
| `frontend/src/test/limitationFixtures.ts` | Typed rule/alert fixtures and MSW handlers shared by feature tests. |
| `frontend/src/api/openapi.json` | Generated OpenAPI artifact. |
| `frontend/src/api/generated.ts` | Generated TypeScript contract. |
| `frontend/e2e/transaction-limitations.spec.ts` | Create → dashboard alert → disable → alert removed flow. |

## 4. Stable Interfaces

Later tasks must consume these names exactly unless the PRD is amended first.

### Backend Domain Types

```python
WindowType = Literal["all_time", "rolling", "fixed"]
CardScope = Literal["all_cards", "selected_cards"]


@dataclass(frozen=True)
class EvaluatedWindow:
    type: WindowType
    days: int | None
    start_date: date | None
    end_date: date | None
    effective_start_date: date | None
    effective_end_date: date | None


@dataclass(frozen=True)
class ActiveTransactionLimitAlert:
    rule_id: str
    keyword: str
    threshold: int
    card: CardRow
    match_count: int
    pending_count: int
    window: EvaluatedWindow
```

### Service API

```python
class LimitationService:
    async def list_rules(self, owner_id: str) -> TransactionLimitationListResult: ...
    async def create_rule(
        self, owner_id: str, payload: CreateTransactionLimitationRequest
    ) -> TransactionLimitation: ...
    async def update_rule(
        self,
        owner_id: str,
        rule_id: str,
        payload: UpdateTransactionLimitationRequest,
    ) -> TransactionLimitation: ...
    async def delete_rule(self, owner_id: str, rule_id: str) -> None: ...
    async def evaluate_active_alerts(
        self, owner_id: str, *, as_of_date: date | None = None
    ) -> TransactionLimitAlertResult: ...
```

### HTTP API

```text
GET    /api/transaction-limitations
POST   /api/transaction-limitations
PATCH  /api/transaction-limitations/{rule_id}
DELETE /api/transaction-limitations/{rule_id}
GET    /api/transaction-limit-alerts
```

### Frontend API

```ts
export const TRANSACTION_LIMITATIONS_QUERY_KEY = ['transaction-limitations'] as const
export const TRANSACTION_LIMIT_ALERTS_QUERY_KEY = ['transaction-limit-alerts'] as const

export function fetchTransactionLimitations(): Promise<TransactionLimitationListResponse>
export function createTransactionLimitation(
  input: CreateTransactionLimitationRequest,
): Promise<TransactionLimitationResponse>
export function updateTransactionLimitation(
  ruleId: string,
  input: UpdateTransactionLimitationRequest,
): Promise<TransactionLimitationResponse>
export function deleteTransactionLimitation(ruleId: string): Promise<void>
export function fetchTransactionLimitAlerts(): Promise<TransactionLimitAlertListResponse>
```

---

### Task 1: Add All-Time Rule Persistence

**Commit group:** all-time only (1 of 3 window groups)

**Files:**

- Create: `backend/alembic/versions/0003_transaction_limitations_all_time.py`
- Create: `backend/tests/migrations/test_transaction_limitations.py`
- Modify: `backend/app/models.py`

**Interfaces:**

- Consumes: existing `Owner`, `CardAccount`, `TimestampMixin`, `new_id`, and SQLite foreign-key enforcement.
- Produces: ORM `TransactionLimitation` and `TransactionLimitationCard`; tables that accept only `window_type = 'all_time'` in this revision.

- [ ] **Step 1: Write the failing migration tests**

Add tests that upgrade to `0003`, assert both new tables/indexes/checks exist, insert a valid all-time rule, reject threshold `0`, reject `card_scope = 'unknown'`, reject `window_type = 'rolling'`, reject duplicate rule/card pairs, cascade rule cards when a rule or card is deleted, and downgrade back to `0002` cleanly.

```python
def test_0003_accepts_only_valid_all_time_rules(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "0003")
    connection = sqlite3.connect(database_path(alembic_config))
    connection.execute("PRAGMA foreign_keys = ON")
    insert_owner_and_card(connection)
    connection.execute(
        "INSERT INTO transaction_limitations "
        "(id, owner_id, keyword, normalized_keyword, threshold, card_scope, "
        "window_type, is_enabled, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rule-1", "owner-1", "Paze", "paze", 10, "all_cards",
            "all_time", 1, NOW, NOW,
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE transaction_limitations SET window_type = 'rolling' "
            "WHERE id = 'rule-1'"
        )
```

- [ ] **Step 2: Run the migration test and verify red**

Run:

```bash
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py -q
```

Expected: failure because revision `0003` and its tables do not exist.

- [ ] **Step 3: Implement revision `0003`**

Create `transaction_limitations` with owner index, threshold/card-scope/window checks, and timestamps. Create `transaction_limitation_cards` with a composite primary key and cascading foreign keys. Do not add rolling or fixed columns in this revision.

```python
revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "transaction_limitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("keyword", sa.String(100), nullable=False),
        sa.Column("normalized_keyword", sa.String(100), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("card_scope", sa.String(24), nullable=False),
        sa.Column("window_type", sa.String(16), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint("threshold BETWEEN 1 AND 10000", name="ck_limitation_threshold"),
        sa.CheckConstraint(
            "card_scope IN ('all_cards', 'selected_cards')",
            name="ck_limitation_card_scope",
        ),
        sa.CheckConstraint("window_type = 'all_time'", name="ck_limitation_window_type"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
    )
```

- [ ] **Step 4: Add ORM models and relationships**

Add `Owner.transaction_limitations`, `CardAccount.transaction_limitations`, and these exported models. Use association objects rather than a raw secondary table so cascade behavior remains explicit.

```python
class TransactionLimitation(TimestampMixin, Base):
    __tablename__ = "transaction_limitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    card_scope: Mapped[str] = mapped_column(String(24), nullable=False)
    window_type: Mapped[str] = mapped_column(String(16), nullable=False, default="all_time")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

- [ ] **Step 5: Run migration and core-schema regression tests**

Run:

```bash
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py tests/migrations/test_core_schema.py tests/migrations/test_transaction_search.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the all-time persistence foundation**

```bash
git add backend/alembic/versions/0003_transaction_limitations_all_time.py backend/app/models.py backend/tests/migrations/test_transaction_limitations.py
git diff --staged --check
git commit -m "feat: add all-time transaction limitation persistence"
```

### Task 2: Add All-Time Rule CRUD and Evaluation API

**Commit group:** all-time only (1 of 3 window groups)

**Files:**

- Create: `backend/app/services/limitation_service.py`
- Create: `backend/app/api/limitations.py`
- Create: `backend/tests/services/test_limitation_service.py`
- Create: `backend/tests/api/test_limitations.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/search_service.py`

**Interfaces:**

- Consumes: Task 1 models, `normalize_query`, existing `CardRow` mapping, `ErrorResponse`, authenticated `OwnerDep`, `SessionDep`, `SettingsDep`.
- Produces: all-time-only Pydantic contracts, `LimitationService`, protected CRUD routes, and derived all-time alert route.

- [ ] **Step 1: Extract a reusable literal-match filter with regression tests**

Move only the shared SQL predicate construction out of `SearchService` while preserving `normalize_query` and every existing search test. The helper accepts a normalized query and returns the indexed FTS or escaped short-query predicate used by both services.

```python
def transaction_match_filter(normalized: NormalizedQuery) -> ColumnElement[bool]:
    if normalized.is_blank:
        return true()
    if normalized.uses_index:
        matching_rowids = (
            select(literal_column("rowid"))
            .select_from(text("transactions_fts"))
            .where(text("transactions_fts MATCH :fts_query"))
            .params(fts_query=normalized.fts_expression)
        )
        return literal_column("transactions.rowid").in_(matching_rowids)
    return Transaction.search_text.like(
        normalized.like_pattern or "", escape="\\"
    )
```

Add a regression test that `Paze`, `dunkin’ donuts`, `a*b`, `%`, and a two-character term return the same IDs through search and limitation matching.

- [ ] **Step 2: Run shared-match tests and verify red**

```bash
uv run --directory backend pytest tests/services/test_search_service.py tests/services/test_limitation_service.py -q
```

Expected: the new limitation test fails because `LimitationService` does not exist; existing search tests remain green.

- [ ] **Step 3: Define all-time request/response contracts**

The first API revision exposes only `AllTimeWindow`; rolling and fixed types are absent until their own tasks.

```python
class AllTimeWindow(BaseModel):
    type: Literal["all_time"]


class CreateTransactionLimitationRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    threshold: int = Field(ge=1, le=10_000)
    card_scope: Literal["all_cards", "selected_cards"]
    card_ids: list[str] = Field(default_factory=list, max_length=100)
    window: AllTimeWindow
    is_enabled: bool = True


class UpdateTransactionLimitationRequest(BaseModel):
    keyword: str | None = Field(default=None, min_length=1, max_length=100)
    threshold: int | None = Field(default=None, ge=1, le=10_000)
    card_scope: Literal["all_cards", "selected_cards"] | None = None
    card_ids: list[str] | None = Field(default=None, max_length=100)
    window: AllTimeWindow | None = None
    is_enabled: bool | None = None
```

Responses include the saved card IDs, timestamps, active-card metadata for the picker, and alert evaluation metadata from the PRD.

- [ ] **Step 4: Write CRUD and all-time evaluation service tests**

Cover trimmed/display keyword, normalized keyword, all-card dynamic fan-out, selected cards, card ownership, deduplication, selected scope requiring cards, all-card scope rejecting cards, disabled rules, threshold equality, per-card independence, pending count, null-date all-time matching, modified/removed transaction correctness, deterministic ordering, and no provider call.

```python
async def test_all_time_alerts_are_per_card_and_include_pending(
    limitation_service: LimitationService,
    owner: Owner,
    two_cards_with_transactions: tuple[CardAccount, CardAccount],
) -> None:
    await limitation_service.create_rule(
        owner.id,
        CreateTransactionLimitationRequest(
            keyword="Paze",
            threshold=2,
            card_scope="all_cards",
            card_ids=[],
            window=AllTimeWindow(type="all_time"),
        ),
    )
    result = await limitation_service.evaluate_active_alerts(owner.id)
    assert [(alert.card.id, alert.match_count, alert.pending_count) for alert in result.alerts] == [
        (two_cards_with_transactions[0].id, 2, 1)
    ]
```

- [ ] **Step 5: Implement owner-scoped CRUD and all-time grouped evaluation**

Validate rule invariants in one function used after create parsing and PATCH merging. Evaluate one grouped query per enabled rule, not one per card. Filter active owner cards through active connections.

```python
def validate_rule_state(state: RuleState, owned_active_card_ids: set[str]) -> None:
    unique_card_ids = set(state.card_ids)
    if state.card_scope == "all_cards" and unique_card_ids:
        raise AppError("REQUEST_INVALID", "All-card rules cannot select cards.", 422)
    if state.card_scope == "selected_cards" and not unique_card_ids:
        raise AppError("REQUEST_INVALID", "Select at least one active card.", 422)
    if not unique_card_ids <= owned_active_card_ids:
        raise AppError(
            "REQUEST_INVALID", "One or more selected cards are unavailable.", 422
        )
```

Use `func.count(Transaction.id)` and `func.sum(case((Transaction.pending.is_(True), 1), else_=0))`, grouped by card ID. All-time has no effective-date predicate.

- [ ] **Step 6: Write API tests before routes**

Test unauthenticated reads, CSRF/Origin write protection, `GET`, `POST 201`, partial `PATCH`, `DELETE 204`, unknown/non-owned `404 TRANSACTION_LIMITATION_NOT_FOUND`, malformed/invalid `422 REQUEST_INVALID`, and `GET /api/transaction-limit-alerts` response fields.

```python
async def test_create_all_time_rule_and_read_active_alerts(
    authenticated_client: AsyncClient,
    csrf_token: str,
) -> None:
    created = await authenticated_client.post(
        "/api/transaction-limitations",
        headers={"X-CSRF-Token": csrf_token, "Origin": "http://127.0.0.1:8000"},
        json={
            "keyword": "Paze",
            "threshold": 10,
            "card_scope": "all_cards",
            "card_ids": [],
            "window": {"type": "all_time"},
            "is_enabled": True,
        },
    )
    assert created.status_code == 201
    alerts = await authenticated_client.get("/api/transaction-limit-alerts")
    assert alerts.status_code == 200
```

- [ ] **Step 7: Register routes and verify the backend slice**

Register explicit `/api/transaction-limit-alerts` and `/api/transaction-limitations` paths on the feature router. Use existing dependencies and response models; let the established request-scoped session dependency commit exactly once after a successful route.

Run:

```bash
uv run --directory backend pytest tests/services/test_search_service.py tests/services/test_limitation_service.py tests/api/test_search.py tests/api/test_limitations.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit the all-time backend slice**

```bash
git add backend/app/services/search_service.py backend/app/services/limitation_service.py backend/app/api/limitations.py backend/app/schemas.py backend/app/main.py backend/tests/services/test_search_service.py backend/tests/services/test_limitation_service.py backend/tests/api/test_limitations.py
git diff --staged --check
git commit -m "feat: evaluate all-time transaction limitation alerts"
```

### Task 3: Deliver the All-Time Management and Dashboard Experience

**Commit group:** all-time only (1 of 3 window groups)

**Files:**

- Create: `frontend/src/limitations/api.ts`
- Create: `frontend/src/limitations/TransactionLimitationsPage.tsx`
- Create: `frontend/src/limitations/TransactionLimitationForm.tsx`
- Create: `frontend/src/limitations/TransactionLimitationList.tsx`
- Create: `frontend/src/limitations/transaction-limitations.test.tsx`
- Create: `frontend/src/dashboard/TransactionLimitAlerts.tsx`
- Create: `frontend/src/dashboard/transaction-limit-alerts.test.tsx`
- Create: `frontend/src/test/limitationFixtures.ts`
- Modify: `frontend/src/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/dashboard/CardGrid.tsx`
- Modify: `frontend/src/dashboard/CardPanel.tsx`
- Modify: `frontend/src/app.tsx`
- Modify: `frontend/src/shell/AppShell.tsx`
- Modify: `frontend/src/styles.css`
- Regenerate: `frontend/src/api/openapi.json`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: Task 2 REST contract and generated schemas; existing `apiClient`, `AppShell`, `DashboardCardGroup`, and test helpers.
- Produces: protected all-time CRUD page and per-card all-time alerts independent of dashboard search.

- [ ] **Step 1: Generate and inspect API types**

```bash
pnpm --dir frontend generate:api
rg -n "TransactionLimitation|TransactionLimitAlert|AllTimeWindow" frontend/src/api/generated.ts
```

Expected: generated request/response types exist and contain no rolling/fixed variants.

- [ ] **Step 2: Write management-page tests and verify red**

Add MSW fixtures for cards, empty/populated rule lists, create, patch, and delete. Test informational copy, all-card/selected-card validation, create pending state, successful list invalidation, edit, enable/disable, named delete confirmation, no-card state, scoped API error, navigation, and axe.

```tsx
it('creates an informational all-time rule for every card', async () => {
  const user = userEvent.setup()
  renderAppAt('/transaction-limitations')

  await user.type(await screen.findByLabelText(/keyword or phrase/i), 'Paze')
  await user.clear(screen.getByLabelText(/transaction threshold/i))
  await user.type(screen.getByLabelText(/transaction threshold/i), '10')
  await user.click(screen.getByRole('radio', { name: /all cards/i }))
  await user.click(screen.getByRole('button', { name: /save rule/i }))

  expect(await screen.findByText(/Paze/i)).toBeInTheDocument()
  expect(screen.getByText(/informational.*cannot block/i)).toBeInTheDocument()
})
```

Run:

```bash
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx
```

Expected: failure because the route and page do not exist.

- [ ] **Step 3: Implement typed API helpers and query invalidation**

All mutation success handlers invalidate both rule and alert keys. DELETE consumes the existing client's no-content behavior; do not parse JSON from a 204.

```ts
export const TRANSACTION_LIMITATIONS_QUERY_KEY = ['transaction-limitations'] as const
export const TRANSACTION_LIMIT_ALERTS_QUERY_KEY = ['transaction-limit-alerts'] as const

function invalidateLimitationQueries(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: TRANSACTION_LIMITATIONS_QUERY_KEY }),
    queryClient.invalidateQueries({ queryKey: TRANSACTION_LIMIT_ALERTS_QUERY_KEY }),
  ])
}
```

- [ ] **Step 4: Implement all-time management UI**

Use controlled inputs and native radio/checkbox/date semantics. In this slice the window summary is fixed to “All available history”; do not render disabled rolling/fixed choices because they are not implemented yet. Keep server validation authoritative and mirror obvious field validation for immediate feedback.

```tsx
<fieldset>
  <legend>Cards</legend>
  <label>
    <input type="radio" name="card-scope" value="all_cards" checked={scope === 'all_cards'} />
    All cards, including cards connected later
  </label>
  <label>
    <input type="radio" name="card-scope" value="selected_cards" checked={scope === 'selected_cards'} />
    Selected cards
  </label>
</fieldset>
```

- [ ] **Step 5: Write dashboard alert tests and verify red**

Test per-card placement, two rules on one card, threshold/pending/window copy, explicit zero pending, no empty region, no coupling to submitted search, error isolation with cards still present, 60-second refetch option, and axe.

```tsx
it('places an active alert only in its qualifying card panel', async () => {
  renderAppAt('/dashboard')
  const card = await screen.findByRole('region', { name: /ending in 4812/i })
  expect(within(card).getByText(/Paze.*10 matches.*0 pending/i)).toBeInTheDocument()
  const other = screen.getByRole('region', { name: /ending in 9921/i })
  expect(within(other).queryByText(/Paze/i)).not.toBeInTheDocument()
})
```

- [ ] **Step 6: Implement independent alert fetch and card merge**

Add `limitAlerts` to the client-only `DashboardCardGroup`; do not add it to the search API schema. Build a `Map<string, TransactionLimitAlertResponse[]>` and merge by `group.card.id`.

```ts
const alertsQuery = useQuery({
  queryKey: TRANSACTION_LIMIT_ALERTS_QUERY_KEY,
  queryFn: fetchTransactionLimitAlerts,
  refetchInterval: 60_000,
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: true,
})

const alertsByCard = new Map<string, TransactionLimitAlertResponse[]>()
for (const alert of alertsQuery.data?.alerts ?? []) {
  alertsByCard.set(alert.card.id, [...(alertsByCard.get(alert.card.id) ?? []), alert])
}
```

Render a scoped retry message outside the card grid if only the alert request fails. Keep the search query and cached result rendering unchanged.

- [ ] **Step 7: Add route, navigation, and responsive styles**

Add the protected route and a navigation destination. Preserve existing journey meaning by presenting Transaction limits as a utility link rather than renumbering Sign in → Connect banks → View cards → Search history.

```tsx
<Route path="/transaction-limitations" element={<TransactionLimitationsPage />} />
```

- [ ] **Step 8: Run the all-time frontend slice**

```bash
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx src/dashboard/transaction-limit-alerts.test.tsx src/dashboard/dashboard.test.tsx src/connections/connections.test.tsx
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

Expected: all selected tests pass, typecheck succeeds, and production build exits zero.

- [ ] **Step 9: Commit the all-time frontend slice**

```bash
git add frontend/src/limitations frontend/src/dashboard/TransactionLimitAlerts.tsx frontend/src/dashboard/transaction-limit-alerts.test.tsx frontend/src/dashboard/DashboardPage.tsx frontend/src/dashboard/CardGrid.tsx frontend/src/dashboard/CardPanel.tsx frontend/src/app.tsx frontend/src/shell/AppShell.tsx frontend/src/styles.css frontend/src/test/limitationFixtures.ts frontend/src/api/openapi.json frontend/src/api/generated.ts
git diff --staged --check
git commit -m "feat: manage and display all-time transaction limits"
```

## Checkpoint A: All-Time Vertical Slice

- [ ] Create `Paze >= 10` for all cards through the UI.
- [ ] Confirm equality activates an alert and different cards are independent.
- [ ] Confirm pending matches count and `0 pending`/nonzero pending copy is visible.
- [ ] Confirm alert API failure leaves dashboard search usable.
- [ ] Run all focused backend and frontend tests from Tasks 1–3.
- [ ] Inspect `git log --oneline -3`; no rolling or fixed behavior exists yet.
- [ ] Review with the owner before the rolling extension.

### Task 4: Extend Persistence and Backend Evaluation for Rolling Windows

**Commit group:** rolling only (2 of 3 window groups); must follow all-time commits and must not include fixed behavior.

**Files:**

- Create: `backend/alembic/versions/0004_transaction_limitations_rolling.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/limitation_service.py`
- Modify: `backend/tests/migrations/test_transaction_limitations.py`
- Modify: `backend/tests/services/test_limitation_service.py`
- Modify: `backend/tests/api/test_limitations.py`

**Interfaces:**

- Consumes: complete all-time slice.
- Produces: `RollingWindow`, nullable `rolling_days`, inclusive rolling evaluation, effective start/end output.

- [ ] **Step 1: Write failing rolling migration and boundary tests**

Add cases for valid days 1 and 730, invalid 0 and 731, missing days, all-time with non-null days, inclusive five-day boundary, day-before exclusion, posted-date precedence, authorized-date fallback, null-date exclusion, and injected `as_of_date`.

```python
async def test_rolling_five_days_is_inclusive(
    limitation_service: LimitationService,
    owner: Owner,
) -> None:
    result = await limitation_service.evaluate_active_alerts(
        owner.id,
        as_of_date=date(2026, 8, 22),
    )
    alert = result.alerts[0]
    assert alert.match_count == 5
    assert alert.window.effective_start_date == date(2026, 8, 18)
    assert alert.window.effective_end_date == date(2026, 8, 22)
```

- [ ] **Step 2: Run focused backend tests and verify red**

```bash
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py tests/services/test_limitation_service.py tests/api/test_limitations.py -q
```

Expected: rolling cases fail because `0004`, `RollingWindow`, and rolling predicates are absent.

- [ ] **Step 3: Add revision `0004` and ORM field**

Use Alembic SQLite batch mode to add `rolling_days` and replace the window check without weakening all-time invariants.

```sql
(
  window_type = 'all_time' AND rolling_days IS NULL
) OR (
  window_type = 'rolling' AND rolling_days BETWEEN 1 AND 730
)
```

Downgrade must refuse silent data loss. Before batch-rebuilding the table, query for `window_type = 'rolling'`; if any exist, raise `RuntimeError("Convert or delete rolling transaction limitations before downgrading to 0003.")`. Test that the guard fires with a rolling row, then convert the fixture to all-time and prove downgrade returns the schema to all-time-only.

- [ ] **Step 4: Extend the discriminated API union and evaluation predicate**

```python
class RollingWindow(BaseModel):
    type: Literal["rolling"]
    days: int = Field(ge=1, le=730)


TransactionWindow = Annotated[
    AllTimeWindow | RollingWindow,
    Field(discriminator="type"),
]
```

Calculate `start = as_of - timedelta(days=days - 1)`. Filter with `func.coalesce(Transaction.posted_date, Transaction.authorized_date).between(start, as_of)`.

- [ ] **Step 5: Verify and commit rolling backend support**

```bash
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py tests/services/test_limitation_service.py tests/api/test_limitations.py tests/api/test_search.py -q
git add backend/alembic/versions/0004_transaction_limitations_rolling.py backend/app/models.py backend/app/schemas.py backend/app/services/limitation_service.py backend/tests/migrations/test_transaction_limitations.py backend/tests/services/test_limitation_service.py backend/tests/api/test_limitations.py
git diff --staged --check
git commit -m "feat: add rolling transaction limitation windows"
```

### Task 5: Add Rolling Window Management and Alert Copy

**Commit group:** rolling only (2 of 3 window groups); no fixed-date fields or copy.

**Files:**

- Modify: `frontend/src/limitations/TransactionLimitationForm.tsx`
- Modify: `frontend/src/limitations/TransactionLimitationList.tsx`
- Modify: `frontend/src/limitations/transaction-limitations.test.tsx`
- Modify: `frontend/src/dashboard/TransactionLimitAlerts.tsx`
- Modify: `frontend/src/dashboard/transaction-limit-alerts.test.tsx`
- Modify: `frontend/src/test/limitationFixtures.ts`
- Regenerate: `frontend/src/api/openapi.json`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: Task 4 rolling API union.
- Produces: rolling form option, 1–730 day validation, saved-rule summary, and inclusive effective-range dashboard copy.

- [ ] **Step 1: Regenerate types and write failing rolling UI tests**

```bash
pnpm --dir frontend generate:api
```

Add tests that selecting “Last N days” reveals only the days field, rejects blank/0/731, submits `{ type: 'rolling', days: 5 }`, edits an existing rolling rule, and renders `last 5 days (Aug 18–Aug 22)` plus pending count.

```tsx
await user.click(screen.getByRole('radio', { name: /last n days/i }))
await user.type(screen.getByLabelText(/number of days/i), '5')
await user.click(screen.getByRole('button', { name: /save rule/i }))
expect(capturedBody.window).toEqual({ type: 'rolling', days: 5 })
```

- [ ] **Step 2: Run tests and verify red**

```bash
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx src/dashboard/transaction-limit-alerts.test.tsx
```

Expected: rolling controls and copy are absent.

- [ ] **Step 3: Implement rolling controls and copy**

Use a number input with `min={1}`, `max={730}`, and `inputMode="numeric"`. Reset irrelevant state when switching to all-time, but preserve server-returned rolling state while editing. Render API-provided effective dates; never recompute the date range in the browser.

- [ ] **Step 4: Verify and commit rolling UI support**

```bash
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx src/dashboard/transaction-limit-alerts.test.tsx
pnpm --dir frontend typecheck
git add frontend/src/limitations frontend/src/dashboard/TransactionLimitAlerts.tsx frontend/src/dashboard/transaction-limit-alerts.test.tsx frontend/src/test/limitationFixtures.ts frontend/src/api/openapi.json frontend/src/api/generated.ts
git diff --staged --check
git commit -m "feat: configure rolling transaction limits"
```

## Checkpoint B: Rolling Extension

- [ ] Confirm a five-day rule includes both calculated boundary dates.
- [ ] Confirm a day-six match is excluded and a null-date pending transaction is excluded.
- [ ] Confirm all-time behavior is unchanged.
- [ ] Confirm `git show --stat HEAD~1..HEAD` contains rolling UI only and no fixed behavior.
- [ ] Review with the owner before the fixed-date extension.

### Task 6: Extend Persistence and Backend Evaluation for Fixed Windows

**Commit group:** fixed only (3 of 3 window groups); must follow rolling commits.

**Files:**

- Create: `backend/alembic/versions/0005_transaction_limitations_fixed.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/limitation_service.py`
- Modify: `backend/tests/migrations/test_transaction_limitations.py`
- Modify: `backend/tests/services/test_limitation_service.py`
- Modify: `backend/tests/api/test_limitations.py`

**Interfaces:**

- Consumes: all-time and rolling support.
- Produces: `FixedWindow`, nullable `start_date`/`end_date`, inclusive fixed evaluation and output.

- [ ] **Step 1: Write failing fixed migration, validation, and date-boundary tests**

Cover both dates required, reversed dates rejected, same-day range accepted, start/end inclusive, outside dates excluded, posted-date precedence, authorized-date fallback, null-date exclusion, and PATCH from rolling to fixed clearing `rolling_days` atomically.

```python
async def test_fixed_window_includes_both_boundaries(
    limitation_service: LimitationService,
    owner: Owner,
) -> None:
    result = await limitation_service.evaluate_active_alerts(owner.id)
    alert = result.alerts[0]
    assert alert.match_count == 2
    assert alert.window.effective_start_date == date(2026, 7, 1)
    assert alert.window.effective_end_date == date(2026, 7, 31)
```

- [ ] **Step 2: Run focused backend tests and verify red**

```bash
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py tests/services/test_limitation_service.py tests/api/test_limitations.py -q
```

Expected: fixed cases fail because revision `0005` and `FixedWindow` do not exist.

- [ ] **Step 3: Add revision `0005` and ORM date fields**

Use SQLite batch mode to add `start_date` and `end_date`, then replace the window check with exactly these valid states:

```sql
(window_type = 'all_time' AND rolling_days IS NULL AND start_date IS NULL AND end_date IS NULL)
OR (window_type = 'rolling' AND rolling_days BETWEEN 1 AND 730 AND start_date IS NULL AND end_date IS NULL)
OR (window_type = 'fixed' AND rolling_days IS NULL AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_date <= end_date)
```

As in `0004`, downgrade is non-destructive: if any fixed rules exist, raise `RuntimeError("Convert or delete fixed transaction limitations before downgrading to 0004.")`. Test the guard, convert the fixture to a supported earlier variant, then prove the clean downgrade.

- [ ] **Step 4: Extend the discriminated union and fixed predicate**

```python
class FixedWindow(BaseModel):
    type: Literal["fixed"]
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates_are_ordered(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self
```

Filter `coalesce(posted_date, authorized_date)` with inclusive `between(start_date, end_date)`. When changing variants, write all variant columns in one transaction so no stale rolling value survives a fixed update.

- [ ] **Step 5: Verify and commit fixed backend support**

```bash
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py tests/services/test_limitation_service.py tests/api/test_limitations.py tests/api/test_search.py -q
git add backend/alembic/versions/0005_transaction_limitations_fixed.py backend/app/models.py backend/app/schemas.py backend/app/services/limitation_service.py backend/tests/migrations/test_transaction_limitations.py backend/tests/services/test_limitation_service.py backend/tests/api/test_limitations.py
git diff --staged --check
git commit -m "feat: add fixed transaction limitation windows"
```

### Task 7: Add Fixed-Date Management and Alert Copy

**Commit group:** fixed only (3 of 3 window groups).

**Files:**

- Modify: `frontend/src/limitations/TransactionLimitationForm.tsx`
- Modify: `frontend/src/limitations/TransactionLimitationList.tsx`
- Modify: `frontend/src/limitations/transaction-limitations.test.tsx`
- Modify: `frontend/src/dashboard/TransactionLimitAlerts.tsx`
- Modify: `frontend/src/dashboard/transaction-limit-alerts.test.tsx`
- Modify: `frontend/src/test/limitationFixtures.ts`
- Regenerate: `frontend/src/api/openapi.json`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: Task 6 fixed API union.
- Produces: fixed-range form, client validation, saved-rule summary, and inclusive dashboard copy.

- [ ] **Step 1: Regenerate types and write failing fixed UI tests**

```bash
pnpm --dir frontend generate:api
```

Test that fixed selection reveals start/end date inputs only, rejects missing/reversed dates, accepts same-day ranges, submits ISO values, edits fixed rules, and renders `Jul 1–Jul 31, 2026` from response dates.

```tsx
await user.click(screen.getByRole('radio', { name: /fixed date range/i }))
await user.type(screen.getByLabelText(/start date/i), '2026-07-01')
await user.type(screen.getByLabelText(/end date/i), '2026-07-31')
await user.click(screen.getByRole('button', { name: /save rule/i }))
expect(capturedBody.window).toEqual({
  type: 'fixed',
  start_date: '2026-07-01',
  end_date: '2026-07-31',
})
```

- [ ] **Step 2: Run tests and verify red**

```bash
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx src/dashboard/transaction-limit-alerts.test.tsx
```

Expected: fixed controls and copy are absent.

- [ ] **Step 3: Implement fixed inputs, validation, and copy**

Use native `type="date"` inputs and a field-level error on `end_date` when it precedes `start_date`. Clear irrelevant rolling state when the user changes variants. Send only the selected discriminated object. Format the server-returned effective dates with existing date-format helpers extended by a focused pure function test.

- [ ] **Step 4: Verify and commit fixed UI support**

```bash
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx src/dashboard/transaction-limit-alerts.test.tsx
pnpm --dir frontend typecheck
git add frontend/src/limitations frontend/src/dashboard/TransactionLimitAlerts.tsx frontend/src/dashboard/transaction-limit-alerts.test.tsx frontend/src/test/limitationFixtures.ts frontend/src/api/openapi.json frontend/src/api/generated.ts
git diff --staged --check
git commit -m "feat: configure fixed-date transaction limits"
```

## Checkpoint C: All Window Variants

- [ ] Confirm the API discriminated union contains exactly all-time, rolling, and fixed.
- [ ] Confirm migration upgrade `0002 → 0003 → 0004 → 0005` passes.
- [ ] Confirm each downgrade behavior is tested and documented.
- [ ] Confirm switching window variants removes irrelevant persisted values.
- [ ] Confirm all three date modes preserve pending and per-card semantics.
- [ ] Inspect commit history: no commit contains behavior for two window variants.

### Task 8: Add End-to-End, Performance, and Contract Gates

**Files:**

- Create: `frontend/e2e/transaction-limitations.spec.ts`
- Create: `backend/tests/performance/test_limitation_evaluation.py`
- Modify: `README.md`
- Modify: `backend/pyproject.toml`
- Regenerate: `frontend/src/api/openapi.json`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: complete feature and deterministic demo/test fixtures.
- Produces: owner-flow proof, documented local performance evidence, and discoverable feature documentation.

- [ ] **Step 1: Add a deterministic E2E fixture path**

Prefer the existing demo bank and test setup. If its data cannot produce one qualifying and one non-qualifying card without production code hooks, extend demo fixture data with clearly named transactions; do not add an E2E-only API route.

- [ ] **Step 2: Write the E2E flow**

```ts
test('owner creates and disables a dashboard transaction alert', async ({ page }) => {
  await signInAsOwner(page)
  await page.getByRole('link', { name: /transaction limits/i }).click()
  await page.getByLabel(/keyword or phrase/i).fill('Paze')
  await page.getByLabel(/transaction threshold/i).fill('10')
  await page.getByRole('radio', { name: /all cards/i }).check()
  await page.getByRole('button', { name: /save rule/i }).click()
  await page.getByRole('link', { name: /view cards/i }).click()
  await expect(page.getByText(/Paze.*10 matches.*pending/i).first()).toBeVisible()
  await page.getByRole('link', { name: /transaction limits/i }).click()
  await page.getByRole('checkbox', { name: /enabled.*Paze/i }).uncheck()
  await page.getByRole('link', { name: /view cards/i }).click()
  await expect(page.getByText(/Paze.*10 matches/i)).toHaveCount(0)
})
```

- [ ] **Step 3: Add the synthetic performance check**

Seed 100 enabled all-time/rolling/fixed rules across eight cards and 100,000 transactions in a temporary migrated SQLite database. Warm the query once, record at least 20 runs with `time.perf_counter`, calculate p95, and assert fewer than 500 ms. Register a `performance` marker in `backend/pyproject.toml` so normal correctness runs stay stable; document the exact command and machine context in the test output.

```python
durations_ms = []
for _ in range(20):
    started = perf_counter()
    await service.evaluate_active_alerts(owner.id, as_of_date=date(2026, 8, 22))
    durations_ms.append((perf_counter() - started) * 1000)
p95_ms = sorted(durations_ms)[18]
assert p95_ms < 500
```

- [ ] **Step 4: Update README discoverability**

Add one concise feature paragraph and link the PRD. State “informational alerts only,” local-cache evaluation, per-card grouping, pending counts, and the three windows. Do not duplicate the PRD.

- [ ] **Step 5: Verify generated contract is stable**

```bash
pnpm --dir frontend generate:api
git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/generated.ts
```

Expected: no diff after regeneration.

- [ ] **Step 6: Run complete feature verification**

```bash
uv run --directory backend pytest tests/migrations/test_transaction_limitations.py tests/services/test_limitation_service.py tests/api/test_limitations.py tests/api/test_search.py -q
pnpm --dir frontend test -- src/limitations/transaction-limitations.test.tsx src/dashboard/transaction-limit-alerts.test.tsx src/dashboard/dashboard.test.tsx
pnpm --dir frontend typecheck
pnpm --dir frontend build
pnpm --dir frontend e2e -- transaction-limitations.spec.ts
uv run --directory backend pytest tests/performance/test_limitation_evaluation.py -m performance -q
```

Expected: every command exits zero.

- [ ] **Step 7: Run the full gate and classify only the known baseline exception**

```bash
make check
```

Expected: zero failures after the pre-existing static-app issue is fixed. If the owner explicitly waived that baseline issue, prove that the same single test is the only failure and that every transaction-limitations test passes; do not call the repository fully green.

- [ ] **Step 8: Commit cross-window verification and documentation**

```bash
git add frontend/e2e/transaction-limitations.spec.ts backend/tests/performance/test_limitation_evaluation.py backend/pyproject.toml README.md frontend/src/api/openapi.json frontend/src/api/generated.ts
git diff --staged --check
git commit -m "test: verify transaction limitations end to end"
```

## 5. Commit Sequence Contract

The implementation history must preserve this order. A window group can contain multiple small commits, but a commit can belong to only one group and must never introduce two variants.

| Order | Required commit | Window group |
| --- | --- | --- |
| 1 | `feat: add all-time transaction limitation persistence` | all-time |
| 2 | `feat: evaluate all-time transaction limitation alerts` | all-time |
| 3 | `feat: manage and display all-time transaction limits` | all-time |
| 4 | `feat: add rolling transaction limitation windows` | rolling |
| 5 | `feat: configure rolling transaction limits` | rolling |
| 6 | `feat: add fixed transaction limitation windows` | fixed |
| 7 | `feat: configure fixed-date transaction limits` | fixed |
| 8 | `test: verify transaction limitations end to end` | cross-window verification only |

Before each commit:

```bash
git diff --staged
git diff --staged --check
git status --short
```

Inspect staged content for secrets and transaction text. Generated API files belong in the commit that changes their contract. Do not squash rolling into all-time or fixed into rolling.

## 6. Risks and Mitigations

| Risk | Impact | Mitigation / proof |
| --- | --- | --- |
| Query-time evaluation slows as rules grow | High | One grouped query per rule, FTS reuse, no rule-card N+1, 100-rule/100k-transaction p95 gate. |
| Search and alert matching drift | High | Share normalized predicate construction and run parity cases for punctuation, short terms, and Unicode. |
| Pending replacement double-counts | Medium | Always evaluate current transaction rows; sync modifications/removals are reflected without stored counters. Test pending-to-posted replacement fixtures. |
| Rolling window is off by one | High | Define `start = as_of - (days - 1)`, inclusive `between`, injected date tests at both boundaries. |
| Host timezone differs from owner expectation | Medium | Parent product is local single-owner; use host calendar and state it in UI/PRD. Ask first before adding timezone configuration. |
| Selected cards disappear on disconnect | Medium | Cascade only association rows, retain the rule, expose zero-target state, require edit before it can alert. |
| PATCH leaves stale variant columns | High | Merge into a domain state, validate, and write all window columns atomically; cross-variant tests. |
| Alert request breaks dashboard | High | Separate TanStack query and scoped error; card/search tests continue to pass when alert endpoint fails. |
| Migration downgrade encounters later-window rules | Medium | Refuse downgrade with a precise conversion/deletion instruction; never delete rules automatically. Migration tests prove both guard and clean downgrade. |
| Navigation change breaks existing journey tests | Medium | Add a utility destination without silently renumbering existing steps; update focused shell/connection tests. |
| Existing baseline is already red | Medium | Record exact known failure; require focused green suites and owner decision before full completion claim. |

## 7. Requirement Traceability

| PRD requirement group | Implemented by | Verified by |
| --- | --- | --- |
| `FR-LIM-RULE-*` | Tasks 1–3, 4, 6 | Migration, service, API, and management tests |
| `FR-LIM-MATCH-*` | Tasks 2, 4, 6 | Search parity and evaluation service tests |
| `FR-LIM-WIN-001` | Tasks 1–3 | All-time boundary/no-date tests and UI tests |
| `FR-LIM-WIN-002..003` | Tasks 4–5 | Rolling migration/service/API/UI tests |
| `FR-LIM-WIN-004..005` | Tasks 6–7 | Fixed migration/service/API/UI tests |
| `FR-LIM-WIN-006` | Commit sequence contract | `git log`/`git show` checkpoint inspection |
| `FR-LIM-ALERT-*` | Tasks 2–3, 5, 7 | Dashboard alert and API tests |
| `FR-LIM-UX-*` | Tasks 3, 5, 7 | Management tests, axe, and E2E |
| `NFR-LIM-001..009` | Tasks 2–8 | Provider-call guard, perf test, auth tests, axe, full gate |

## 8. Final Verification Checklist

- [ ] PRD semantics still match implemented contracts; update the PRD before accepting intentional changes.
- [ ] Placeholder scan returns no incomplete implementation instructions.
- [ ] API names and field types are identical across Pydantic, OpenAPI, generated TypeScript, fixtures, and components.
- [ ] All three migration revisions upgrade in order and have tested downgrade behavior.
- [ ] All-time, rolling, and fixed behavior live in successive non-mixed commit groups.
- [ ] Equality activates; below-threshold deactivates; card counts never aggregate.
- [ ] Pending counts affect thresholds and are always displayed.
- [ ] All-card rules include a card connected after rule creation.
- [ ] Selected-card ownership and zero-target disconnection states are proven.
- [ ] Literal search parity covers curly punctuation, ASCII punctuation, wildcard characters, Unicode case folding, and short terms.
- [ ] Alert failures do not break transaction search or cached card rendering.
- [ ] Accessibility, typecheck, build, E2E, and performance commands have fresh zero-exit evidence.
- [ ] `make check` is green, or the final report names the exact owner-waived pre-existing failure without claiming a green repository.
- [ ] `git status --short` contains no unintended or generated build output.

## 9. Execution Handoff

Recommended execution is subagent-driven, one fresh implementer per task with spec-compliance and code-quality review between tasks. Inline execution is also valid when tasks are completed sequentially with Checkpoints A–C and the exact commit sequence above. In either mode, implementation must begin from an attached feature branch in an isolated worktree, not this detached planning state.
