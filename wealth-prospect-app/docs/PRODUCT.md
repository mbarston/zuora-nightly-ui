# Prospect Lens — product strategy

## 1. What WealthEngine actually sells

WealthEngine (now part of Euromoney/Altrata alongside Wealth-X and BoardEx)
sells **wealth screening**: upload a list of names, get back an estimated net
worth, an "estimated giving capacity" or "propensity to buy" score, and a
handful of attributes. Under the hood it fuses:

- **Licensed consumer marketing data** (Experian/Acxiom-style compiled files:
  modelled income, home value, presence of investments, lifestyle segments).
- **Public records** it has aggregated: property, business affiliations,
  SEC filings, FEC and nonprofit giving, professional licences.
- **Proprietary modelling** (the "WealthEngine score") which customers cannot
  inspect or tune.

Its weaknesses, from talking to users and reading reviews:

| Weakness | Consequence for the customer |
|---|---|
| Black-box score | Advisors can't defend the number to a compliance officer or explain it to a prospect. |
| Point-in-time screening | Nothing tells you *when* to call. A $10M person who just sold a company is worth more than ten $10M people who didn't. |
| One score for everyone | A realtor, a private banker and a planner want different things; WE gives them all "capacity". |
| Enterprise pricing | Effectively closed to solo advisors and small brokerages — the long tail of the market. |
| Data-licensing exposure | Compiled consumer data is getting harder to use lawfully (CPRA, state privacy laws, FCRA gray areas). |

## 2. Our thesis

1. **Public records + first-party data beat purchased consumer data** for the
   people who actually matter. Wealth is *visible* at the top: SEC filings,
   business registrations, deeds, 990s, FEC. The purchased data mostly adds
   noise on the mass-market end that our customers don't target anyway.
2. **Timing beats capacity.** The product's core loop is *triggers*, not
   scores: lockup expiries, Form 4 sales, business exits, listings, probate,
   job changes. That's what lets a small advisor beat a big one.
3. **Explainability is the moat.** Every score decomposes into named factors
   with links to source documents. That is a compliance feature, a sales
   feature ("here's why I'm calling") and a trust feature.
4. **Persona lenses, not one score.** Same evidence, different weights. The
   weights are visible and, later, tunable per customer with feedback.

## 3. Data-source strategy

| Source | What it gives | Legal basis | Cost | Status |
|---|---|---|---|---|
| **SEC EDGAR** (Forms 3/4/5, S-1, 13D/G) | Insider holdings, sales, option exercises, IPO lockups | Public record | Free | Live client (full-text search); XML parsing of transaction values is next |
| **FEC** individual contributions | Affluence signal; also employer + occupation | Public record; *not* for solicitation | Free | Live client |
| **County assessor / recorder** | Ownership, value, purchase price/date, mortgages, listings, sales | Public record; national coverage via ATTOM/CoreLogic/Regrid | Free–$0.30/lookup | Synthetic; adapter interface ready |
| **Secretary of State / OpenCorporates** | Entity ownership, officers, formation, dissolution | Public record | Free–commercial licence | Live client (officer search) |
| **IRS 990 / ProPublica** | Board seats, foundation grants, named gifts | Public record | Free | Synthetic; needs a Part VII person index |
| **Court records** (probate, divorce) | Life-event triggers | Public; commercial use restricted in some states | Free–$ | Synthetic; gate per jurisdiction |
| **Census ACS** | ZIP-level income/home-value priors | Public | Free | Synthetic (static table) |
| **Customer's own CRM / imports** | Names, relationships, employment, existing advisor | First-party | Free | CSV import; CRM sync planned |
| **Professional-network enrichment** (PDL, Clearbit, etc.) | Title, employer, job changes | Vendor terms | $0.03–0.20 | Planned |

What we deliberately **don't** use: credit-bureau-derived attributes, compiled
consumer marketing files, scraped social data. This is both a legal posture
and a positioning statement.

## 4. Scoring model (v0)

**Wealth estimate** = real-estate equity + private-business equity + public
equity + liquid financial assets. Each component is computed from signals
with a named formula (see `backend/app/scoring/engine.py`), and the range
(P10–P90) narrows as coverage across the six evidence categories improves.

**Persona propensity** (0–100), each with visible weights in
`backend/app/scoring/personas.py`:

- **Realtor** — home tenure in the 6–12-year move window, equity ratio,
  listing/sale activity, life events, relocation, capacity for a move-up,
  penalty for a purchase in the last 18 months.
- **Wealth manager** — investable assets tiering, liquidity events in the
  last 12/24 months, upcoming lockup expiry, inheritance, retirement
  transition, business-owner complexity, philanthropic capacity, penalty for
  an existing advisor.
- **Financial planner** — life transitions (birth, marriage, divorce,
  retirement, inheritance), job change, newly formed business, the
  $250K–$5M "planning sweet spot", accumulation-age bands, self-employment,
  high income, penalty for an existing advisor.

v1 plan: keep the factor structure but learn weights from outcome feedback
(stage changes, meetings booked, closed clients) per customer, so the model
stays explainable while getting sharper.

## 5. Compliance posture

- **Not an FCRA consumer report.** Marketing prospecting only; contract and
  in-app notices prohibit eligibility uses. No credit data ingested.
- **Fair Housing.** The realtor lens uses timing and capacity only. No
  protected-class attributes are stored or inferred.
- **CCPA/CPRA & state laws.** Access/deletion via the suppression registry;
  deletion removes the prospect and every signal. Data-retention policy per
  customer is a v1 item.
- **FEC.** Used as an affluence indicator only, never to build donor lists.
- **Court/vital records.** Enabled per jurisdiction after counsel review.
- **Provenance.** Every signal stores source, reference, date and
  confidence so "what do you know about me and where did it come from" has
  a one-click answer.

## 6. Go-to-market

- **Wedge:** independent RIAs and boutique real-estate teams that
  WealthEngine's pricing excludes. Sell the *trigger feed* ("here are the 12
  people in your territory with a liquidity event this month") rather than
  the screening tool.
- **Pricing (hypothesis):** per-seat SaaS with tiers by monitored-prospect
  count; live-data connectors as add-ons that map to our marginal cost.
- **Distribution:** CRM integrations (Salesforce, Wealthbox, Redtail,
  Follow Up Boss) so triggers land where reps already work; territory-based
  alerts by email/Slack.

## 7. Roadmap

**Now (this repo):** signal model, transparent scoring, persona lenses,
triggers, connector registry with SEC/FEC/OpenCorporates live clients,
prospect workflow, lists/export, import, suppression.

**Next:**
1. Parse Form 4 XML for transaction values and holdings; S-1/424B for lockup
   dates; 13D/G for large holders.
2. Property connector against a county open-data portal (e.g. Travis County
   TX) and an ATTOM adapter.
3. Territory watchlists + scheduled re-enrichment + trigger digests
   (email/Slack).
4. Entity resolution (name + address + employer matching with confidence)
   so live lookups don't attach the wrong person's filings.
5. Auth (reuse the Google SSO pattern from the parent repo), multi-tenant
   workspaces, Postgres.
6. Outcome feedback → per-customer weight tuning.
7. CRM sync.
