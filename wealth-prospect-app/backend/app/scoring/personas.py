"""
Persona definitions. Each persona is a *lens* on the same prospect: the
same underlying signals, weighted for what that professional actually
cares about. Weights live here (not buried in code) so they can be shown
in the UI and tuned per customer later.
"""
from __future__ import annotations

PERSONAS: dict[str, dict] = {
    "realtor": {
        "label": "Realtor",
        "question": "Who is likely to buy or sell a home in the next 12 months, and can afford a move-up?",
        "score_field": "realtor_score",
        "primary_metric": "real_estate_equity",
        "weights": {
            "tenure_sweet_spot": 18,
            "high_equity": 12,
            "listed_home": 40,
            "sold_recently_no_purchase": 15,
            "life_event": 18,
            "job_change_relocation": 25,
            "capacity_move_up": 8,
            "multi_property_investor": 6,
            "just_bought_penalty": -20,
        },
    },
    "wealth_manager": {
        "label": "Wealth Manager",
        "question": "Who has, or is about to have, significant investable assets and no advisor?",
        "score_field": "wealth_manager_score",
        "primary_metric": "investable_assets",
        "weights": {
            "investable_assets": 35,
            "liquidity_event_12m": 25,
            "lockup_expiry_upcoming": 25,
            "inheritance": 18,
            "retirement_transition": 12,
            "business_owner_complexity": 6,
            "philanthropic_capacity": 5,
            "has_advisor_penalty": -25,
        },
    },
    "financial_planner": {
        "label": "Financial Planner",
        "question": "Who is going through a life transition where planning advice is needed right now?",
        "score_field": "financial_planner_score",
        "primary_metric": "income_estimate",
        "weights": {
            "life_transition": 18,
            "wealth_sweet_spot": 15,
            "age_planning_window": 10,
            "self_employed": 10,
            "high_income": 8,
            "has_advisor_penalty": -20,
        },
    },
}

PERSONA_KEYS = list(PERSONAS.keys())
