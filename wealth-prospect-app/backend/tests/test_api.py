import io


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_seeded_and_scored(client):
    s = client.get("/api/stats").json()
    assert s["prospects"] == 30
    assert s["signals_total"] > 30
    assert sum(s["tiers"].values()) == 30


def test_list_filters_and_sorting(client):
    r = client.get("/api/prospects", params={"persona": "realtor", "min_score": 40, "page_size": 10}).json()
    assert all(i["score"]["realtor_score"] >= 40 for i in r["items"])
    scores = [i["score"]["realtor_score"] for i in r["items"]]
    assert scores == sorted(scores, reverse=True)
    r2 = client.get("/api/prospects", params={"persona": "wealth_manager", "sort": "net_worth", "order": "asc", "page_size": 5}).json()
    nw = [i["score"]["net_worth_p50"] for i in r2["items"]]
    assert nw == sorted(nw)


def test_search(client):
    first = client.get("/api/prospects", params={"page_size": 1}).json()["items"][0]
    r = client.get("/api/prospects", params={"q": first["last_name"]}).json()
    assert any(i["id"] == first["id"] for i in r["items"])


def test_detail_has_explanation_and_signals(client):
    pid = client.get("/api/prospects", params={"page_size": 1}).json()["items"][0]["id"]
    d = client.get(f"/api/prospects/{pid}").json()
    assert d["signals"]
    assert set(d["explanation"]) == {"wealth", "personas", "triggers"}
    assert all("signal_ids" in f for f in d["explanation"]["personas"]["realtor"]["factors"])
    assert client.get("/api/prospects/999999").status_code == 404


def test_create_enrich_and_stage(client):
    r = client.post("/api/prospects", json={"first_name": "Dana", "last_name": "Whitaker", "city": "Austin",
                                             "state": "TX", "zip": "78746", "tags": ["referral"]})
    assert r.status_code == 201
    p = r.json()
    assert p["score"] is not None and p["score"]["net_worth_p50"] > 0
    d = client.post(f"/api/prospects/{p['id']}/enrich").json()
    assert d["signals"]
    # enrichment is idempotent — dedupe keys prevent duplicates
    n1 = len(d["signals"])
    n2 = len(client.post(f"/api/prospects/{p['id']}/enrich").json()["signals"])
    assert n1 == n2
    a = client.post(f"/api/prospects/{p['id']}/activities", json={"kind": "call", "body": "Intro call"})
    assert a.status_code == 201
    assert client.get(f"/api/prospects/{p['id']}").json()["stage"] == "contacted"
    assert client.patch(f"/api/prospects/{p['id']}", json={"stage": "bogus"}).status_code == 422
    assert client.patch(f"/api/prospects/{p['id']}", json={"stage": "meeting"}).json()["stage"] == "meeting"


def test_csv_import(client):
    csv = "First Name,Last Name,Email,City,State,Zip,Title\nMorgan,Ellery,morgan@example.com,Denver,co,80206,Founder\nBad,,x@example.com,,,,\n"
    r = client.post("/api/prospects/import", files={"file": ("p.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert r.status_code == 201
    j = r.json()
    assert j["created"] == 1 and len(j["errors"]) == 1
    again = client.post("/api/prospects/import", files={"file": ("p.csv", io.BytesIO(csv.encode()), "text/csv")}).json()
    assert again["skipped_duplicates"] == 1


def test_lists_and_export_respect_suppression(client):
    l = client.post("/api/lists", json={"name": "Test list", "persona": "realtor"}).json()
    ids = [i["id"] for i in client.get("/api/prospects", params={"page_size": 3}).json()["items"]]
    assert client.post(f"/api/lists/{l['id']}/members", json={"prospect_ids": ids}).json()["member_count"] == 3
    victim = client.get(f"/api/prospects/{ids[0]}").json()
    s = client.post("/api/compliance/suppressions", json={"email": victim["email"], "reason": "opt_out"})
    assert s.status_code == 201
    assert client.get(f"/api/prospects/{ids[0]}").json()["suppressed"] is True
    body = client.get(f"/api/lists/{l['id']}/export.csv").text
    assert victim["email"] not in body
    assert body.count("\n") == 3  # header + 2 rows
    assert all(i["id"] != ids[0] for i in client.get("/api/prospects", params={"page_size": 500}).json()["items"])
    client.delete(f"/api/compliance/suppressions/{s.json()['id']}")
    assert client.get(f"/api/prospects/{ids[0]}").json()["suppressed"] is False
    assert client.post("/api/lists", json={"name": "Test list"}).status_code == 409


def test_sources_registry(client):
    j = client.get("/api/sources").json()
    assert j["live_connectors"] is False
    keys = {s["key"] for s in j["sources"]}
    assert {"sec_edgar", "fec", "property_records", "business_registry"} <= keys
    assert all(s["mode"] == "synthetic" for s in j["sources"])
    assert all(s["legal_basis"] for s in j["sources"])
