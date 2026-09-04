from datetime import datetime, timedelta

from app.scoring.engine import estimate_wealth, remaining_mortgage, score_prospect, Sig, wealth_tier

NOW = datetime(2026, 9, 4)


def sig(kind, data, days_ago=30, conf=0.8, sid=None):
    return {"id": sid, "kind": kind, "source": "test", "confidence": conf,
            "observed_at": NOW - timedelta(days=days_ago), "data": data}


def test_empty_signals_are_safe():
    r = score_prospect([], now=NOW)
    assert r.wealth.net_worth_p50 == 0
    assert r.wealth.wealth_tier == "mass"
    assert 0 <= r.personas["realtor"].score <= 100
    assert r.triggers == []


def test_remaining_mortgage_amortises():
    assert remaining_mortgage(400_000, 0) == 400_000
    mid = remaining_mortgage(400_000, 15)
    assert 250_000 < mid < 320_000
    assert remaining_mortgage(400_000, 30) == 0


def test_wealth_tiers():
    assert wealth_tier(100_000) == "mass"
    assert wealth_tier(600_000) == "affluent"
    assert wealth_tier(2_000_000) == "hnw"
    assert wealth_tier(10_000_000) == "vhnw"
    assert wealth_tier(50_000_000) == "ultra"


def test_real_estate_equity_uses_market_value_minus_mortgage():
    s = [sig("property.owned", {"address": "1 Main", "market_value": 1_000_000, "purchase_price": 500_000,
                                "purchase_date": "2016-09-01", "is_primary": True}, sid=1)]
    w = estimate_wealth([Sig.from_any(x) for x in s], now=NOW)
    # 80% LTV on 500k = 400k principal, ~10 years paid → equity well above 600k
    assert 600_000 < w.real_estate_equity < 800_000
    assert any(f.name == "real_estate" and f.signal_ids == [1] for f in w.factors)


def test_business_and_public_equity_roll_up():
    s = [
        sig("business.ownership", {"entity": "Acme", "industry": "technology", "est_revenue": 4_000_000,
                                   "ownership_pct": 50, "status": "active"}),
        sig("equity.insider_holding", {"company": "NMBD", "ticker": "NMBD", "value": 2_000_000}),
    ]
    w = estimate_wealth([Sig.from_any(x) for x in s], now=NOW)
    assert w.business_equity == 4_000_000 * 2.5 * 0.5
    assert w.public_equity == 2_000_000
    # investable excludes private business but includes 80% of marketable stock
    assert w.investable_assets >= 1_600_000
    assert w.net_worth_p10 < w.net_worth_p50 < w.net_worth_p90


def test_confidence_tightens_range():
    thin = estimate_wealth([Sig.from_any(sig("property.owned", {"market_value": 1_000_000, "mortgage_balance_est": 0}))], now=NOW)
    rich = estimate_wealth([Sig.from_any(x) for x in [
        sig("property.owned", {"market_value": 1_000_000, "mortgage_balance_est": 0}, conf=0.95),
        sig("employment.title", {"title": "VP", "seniority": "vp", "industry": "technology"}, conf=0.95),
        sig("demographic.household", {"age_band": "45-54"}, conf=0.95),
        sig("business.ownership", {"entity": "X", "est_revenue": 1_000_000, "status": "active"}, conf=0.95),
        sig("equity.insider_holding", {"value": 500_000}, conf=0.95),
        sig("donation.charitable", {"amount": 10_000, "org": "Y"}, conf=0.95),
    ]], now=NOW)
    assert rich.confidence > thin.confidence
    assert (rich.net_worth_p90 / rich.net_worth_p50) < (thin.net_worth_p90 / thin.net_worth_p50)


def test_realtor_score_listed_home_is_hot():
    s = [
        sig("property.owned", {"address": "1 Main", "market_value": 900_000, "purchase_price": 500_000,
                               "purchase_date": "2018-05-01", "is_primary": True}, sid=1),
        sig("property.listed", {"address": "1 Main", "list_price": 950_000, "listed_at": "2026-08-20"}, sid=2),
    ]
    r = score_prospect(s, now=NOW)
    assert r.personas["realtor"].score >= 70
    assert any(f.name == "listed" for f in r.personas["realtor"].factors)
    assert any(t["key"] == "listed_home" and t["urgency"] == "hot" for t in r.triggers)
    assert "in market" in r.personas["realtor"].next_best_action


def test_realtor_penalises_recent_purchase():
    s = [sig("property.owned", {"market_value": 900_000, "purchase_price": 850_000,
                                "purchase_date": "2026-03-01", "is_primary": True}, sid=1)]
    r = score_prospect(s, now=NOW)
    assert any(f.name == "just_bought" and f.value < 0 for f in r.personas["realtor"].factors)
    assert any(t["key"] == "bought_home" for t in r.triggers)


def test_wealth_manager_lockup_and_liquidity():
    s = [
        sig("demographic.household", {"age_band": "45-54"}),
        sig("employment.title", {"title": "CTO", "seniority": "cxo", "industry": "technology"}),
        sig("equity.insider_holding", {"company": "Nimbus", "ticker": "NMBD", "value": 6_000_000}),
        sig("equity.insider_transaction", {"ticker": "NMBD", "type": "sale", "value": 1_500_000, "date": "2026-07-15"}),
        sig("equity.ipo_lockup", {"company": "Nimbus", "ticker": "NMBD", "lockup_expiry": "2026-11-01", "est_holding_value": 6_000_000}),
    ]
    r = score_prospect(s, now=NOW)
    wm = r.personas["wealth_manager"]
    assert wm.score >= 85
    names = {f.name for f in wm.factors}
    assert {"investable", "liquidity", "lockup"} <= names
    assert "lockup" in wm.next_best_action.lower()
    keys = {t["key"] for t in r.triggers}
    assert {"insider_sale", "lockup_expiry"} <= keys


def test_existing_advisor_penalty():
    base = [sig("demographic.household", {"age_band": "55-64"}),
            sig("employment.title", {"title": "Partner", "seniority": "partner", "industry": "legal"})]
    with_adv = base + [sig("advisor.relationship", {"firm": "Merrill", "type": "wealth_advisor"})]
    a = score_prospect(base, now=NOW).personas["wealth_manager"].score
    b = score_prospect(with_adv, now=NOW).personas["wealth_manager"].score
    assert b < a


def test_financial_planner_life_transition():
    s = [
        sig("demographic.household", {"age_band": "35-44"}),
        sig("employment.title", {"title": "Senior Engineer", "seniority": "senior_ic", "industry": "technology"}),
        sig("life_event", {"type": "birth", "date": "2026-06-01", "detail": "New child"}, sid=9),
        sig("business.ownership", {"entity": "New LLC", "est_revenue": 150_000, "formed_at": "2026-05-01", "status": "active"}),
    ]
    r = score_prospect(s, now=NOW)
    fp = r.personas["financial_planner"]
    assert fp.score >= 60
    assert any(f.name == "life_birth" and f.signal_ids == [9] for f in fp.factors)
    assert any(t["key"] == "new_business" for t in r.triggers)


def test_explanation_serialises():
    r = score_prospect([sig("employment.title", {"title": "VP", "seniority": "vp"})], now=NOW)
    e = r.to_explanation()
    assert set(e) == {"wealth", "personas", "triggers"}
    assert e["personas"]["realtor"]["factors"][0]["label"] == "Base rate"


def test_lockup_not_double_counted_with_holding():
    s = [
        sig("equity.insider_holding", {"company": "Nimbus", "ticker": "NMBD", "value": 5_000_000}),
        sig("equity.ipo_lockup", {"company": "Nimbus", "ticker": "NMBD", "lockup_expiry": "2026-12-01", "est_holding_value": 5_000_000}),
    ]
    w = estimate_wealth([Sig.from_any(x) for x in s], now=NOW)
    assert w.public_equity == 5_000_000
    # but a lockup for a ticker we have no holding for is still counted
    only_lockup = estimate_wealth([Sig.from_any(s[1])], now=NOW)
    assert only_lockup.public_equity == 5_000_000
