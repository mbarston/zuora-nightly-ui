# Prospect Lens

Wealth-prospecting intelligence for realtors, wealth managers and financial
planners. A WealthEngine-style product built on a different premise: instead
of buying opaque consumer data and returning a black-box score, Prospect Lens
assembles **public-record and first-party signals**, estimates wealth with a
**transparent balance-sheet model**, and scores each person through the
**lens of the professional asking** — with every point traceable to the
evidence that produced it.

> Working name. "Prospect Lens" has not been trademark-checked.

See [`docs/PRODUCT.md`](docs/PRODUCT.md) for the competitive analysis,
data-source strategy, compliance posture and roadmap.

## What it does today

| Area | Capability |
|---|---|
| **Signals** | Every fact is a `Signal` with kind, source, reference, observed date and confidence. 16 signal kinds across property, equity, business, giving, income, demographics, life events and advisor relationships. |
| **Wealth engine** | Real-estate equity (amortised mortgage model), private-business equity (revenue multiples), public equity (Form 4 / lockups), liquid financial assets (income × age curve + liquidity events + giving-capacity cross-check). Outputs P10/P50/P90 net worth, investable assets, income estimate, tier and a confidence score that widens/narrows the range. |
| **Persona lenses** | 0–100 propensity for **Realtor** (12-month move), **Wealth Manager** (investable + liquidity timing, no advisor), **Financial Planner** (life transitions). Each score lists its factors, the signal ids behind them and a next-best action. Weights live in one file and are exposed via the API. |
| **Triggers** | Hot/warm timing events: home listed/sold, insider sale, IPO lockup expiry, business exit, new business, job change/relocation, inheritance, retirement, divorce, marriage, birth, major gift. |
| **Connectors** | Registry with provenance metadata (legal basis, cost, coverage, refresh). Live clients for SEC EDGAR full-text search, FEC Schedule A and OpenCorporates officers; synthetic fallbacks for everything so the app runs fully offline. |
| **Workflow** | Prospect table with persona ranking, filters and bulk add-to-list · detail page with factor↔evidence highlighting · lists with CSV export (next-best action included) · CSV import with auto-enrich · stage pipeline and activity log. |
| **Compliance** | Suppression registry (opt-out / DNC / CCPA delete) enforced across search, lists and exports · permissible-use notice · per-signal provenance. |

## Quick start

```bash
cd wealth-prospect-app
./run-dev.sh            # creates .venv, installs deps, starts API :8787 + Vite :5173
```

Open http://localhost:5173. The first start seeds 240 synthetic prospects so
every screen is populated. Nothing in the seed is real data.

Production-style (single process serving the built SPA):

```bash
cd frontend && npm run build && cd ../backend && uvicorn app.main:app --port 8787
# or
docker build -t prospect-lens . && docker run -p 8787:8787 -v pl-data:/data prospect-lens
```

Run tests:

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

## Turning on real data

```bash
export LIVE_CONNECTORS=true
export FEC_API_KEY=...                 # free at api.open.fec.gov
export SEC_USER_AGENT="Your App you@example.com"
```

With live mode on, **Re-enrich** calls SEC EDGAR, FEC and OpenCorporates for
that person; the other connectors keep returning synthetic data until their
live implementations land (see roadmap). Live hits are deduped against
existing signals by `dedupe_key`, so re-enrichment is idempotent.

## Layout

```
wealth-prospect-app/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, SPA serving, seed-on-start
│   │   ├── models.py            Prospect, Signal, ScoreSnapshot, lists, activity, suppression
│   │   ├── services.py          enrich() + rescore() orchestration, suppression matching
│   │   ├── seed.py              deterministic synthetic book
│   │   ├── scoring/
│   │   │   ├── signals.py       signal vocabulary + calibration tables
│   │   │   ├── personas.py      persona definitions and weights
│   │   │   └── engine.py        wealth estimate, triggers, persona scores, explanations
│   │   ├── connectors/
│   │   │   ├── base.py          Connector contract + provenance metadata
│   │   │   ├── registry.py      all sources; live SEC/FEC/OpenCorporates clients
│   │   │   └── synthetic.py     archetype-based synthetic signal generator
│   │   └── routers/             prospects, lists, meta (stats/sources/compliance)
│   └── tests/                   scoring + API tests
├── frontend/                    Vite + React + TypeScript + Tailwind
│   └── src/pages/               Dashboard, Prospects, ProspectDetail, Lists, Import, Sources, Compliance
└── docs/PRODUCT.md              strategy
```

## API

Interactive docs at `/docs`. Main endpoints:

- `GET /api/prospects?persona=&min_score=&tier=&trigger=&hot_only=&q=&sort=&page=`
- `POST /api/prospects` · `POST /api/prospects/import` (CSV) · `GET/PATCH/DELETE /api/prospects/{id}`
- `POST /api/prospects/{id}/enrich` · `POST /api/prospects/{id}/rescore` · `POST /api/prospects/{id}/activities`
- `GET/POST /api/lists` · `POST /api/lists/{id}/members` · `GET /api/lists/{id}/export.csv`
- `GET /api/stats` · `GET /api/sources` · `GET /api/prospects/meta/personas`
- `GET /api/compliance` · `POST/DELETE /api/compliance/suppressions`
