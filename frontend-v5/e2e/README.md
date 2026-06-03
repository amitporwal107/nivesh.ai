# Nivesh V5 E2E Tests

## Quick Start

```bash
# 1. Set up env vars
cp .env.test.example .env.test
# Edit .env.test with your SESSION_TOKEN

# 2. Install Playwright browsers
npx playwright install chromium

# 3. Run all tests
npx playwright test

# 4. Run specific test file
npx playwright test e2e/tests/homepage.spec.ts

# 5. Run with UI mode
npx playwright test --ui

# 6. View HTML report
npx playwright show-report
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BASE_URL` | Yes | Staging URL (default: `https://staging.niveshcopilot.com`) |
| `SESSION_TOKEN` | Yes | Valid session token from `GET /api/auth/dev-set-cookie?token=...` |
| `TEST_USER_NAME` | No | Expected user name for assertions |
| `TEST_USER_EMAIL` | No | Expected user email for assertions |

## Test Structure

```
e2e/
├── DISCOVERY.md              # Route map, API endpoints, selectors, bugs
├── README.md                 # This file
├── auth.setup.ts             # Session injection (runs before all tests)
├── fixtures/                 # Real API response snapshots
│   ├── user-profile.json
│   ├── holdings-enriched.json
│   ├── portfolio-trend.json
│   └── ...
├── helpers/
│   └── api-mock.ts           # Route mocking utilities
├── prototype-reference/      # Screenshots of design prototype (visual reference)
├── screenshots/              # Playwright screenshots (gitignored)
└── tests/
    ├── homepage.spec.ts      # Public landing page
    ├── login.spec.ts         # Sign-in (magic link + Google states)
    ├── onboarding.spec.ts    # 3-method investment connection
    ├── dashboard.spec.ts     # Main overview
    ├── portfolio.spec.ts     # Holdings + allocation
    ├── analytics-dashboards.spec.ts  # Concentration, Diversification, Risk, Performance, Goals, Tax
    ├── workspace.spec.ts     # Plan, Recommendations, Chat, Settings
    └── navigation.spec.ts    # Sidebar routing, mobile nav, 401 handling
```

## Auth Approach

Google OAuth cannot be automated end-to-end. Tests use:
1. **`auth.setup.ts`** — calls `/api/auth/dev-set-cookie?token=...` to inject a real session cookie
2. **Fixture mocking** — `helpers/api-mock.ts` intercepts API routes with captured fixtures for deterministic tests
3. **Two test projects**: `desktop-chrome` (authenticated) and `unauthenticated` (public pages + 401)

## Fixtures

Fixtures are **real API responses** captured from staging. To refresh:

```bash
SESSION_TOKEN=your-token ./e2e/capture-fixtures.sh
```

## Known Issues (from DISCOVERY.md)

- **BUG-011**: Dashboard crashes due to Zod contract drift on `/api/portfolio/trend`
- **BUG-012**: Google Sign-In `prompt()` silently fails; `renderButton()` fix pending deploy
- **BUG-013**: `/api/auth/me` rate-limited (429) on rapid calls
- **BUG-014**: Concentration treemap blank in some viewports
- **BUG-015**: Sidebar missing on some pages (viewport breakpoint issue)

## Updating Snapshots

```bash
npx playwright test --update-snapshots
```

## CI

```bash
CI=1 npx playwright test --reporter=list
```
