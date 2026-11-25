"""Minimal Streamlit dashboard.

It contains NO business logic and talks ONLY to the API (API_URL). It can be replaced
by any other front-end using the same endpoints.

Run it with:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
REFRESH_SECONDS = float(os.environ.get("DASHBOARD_REFRESH_SECONDS", "2"))
DECISION_LABELS = {
    "conforme": "🟢 conforme",
    "a_verifier": "🟠 à vérifier",
    "anomalie": "🔴 anomalie",
}

st.set_page_config(page_title="visionhub", page_icon="🏭", layout="wide")


# ------------------------------------------------------------------ API helpers


def api_get(path: str, **params):
    response = requests.get(f"{API_URL}{path}", params=params, timeout=5)
    response.raise_for_status()
    return response.json()


def api_send(method: str, path: str, payload: dict):
    response = requests.request(method, f"{API_URL}{path}", json=payload, timeout=5)
    if not response.ok:
        st.error(f"Erreur API {response.status_code} : {response.text}")
        return None
    return response.json()


def summarize(event: dict) -> str:
    """Short human-readable text of the details (display only)."""
    d = event["details"]
    if d["kind"] == "quality":
        return f"{len(d['zones'])} zone(s) anormale(s)"
    if d["kind"] == "workstation":
        parts = []
        if d["missing"]:
            parts.append("manquant : " + ", ".join(d["missing"]))
        if d["misplaced"]:
            parts.append("mal placé : " + ", ".join(d["misplaced"]))
        return " ; ".join(parts) or "poste conforme à la référence"
    issues = []
    for p in d["persons"]:
        bad = [k for k in ("helmet", "vest", "glasses", "gloves") if p[k] != "present"]
        items = [f"{k}={p[k]}" for k in bad] + (["téléphone"] if p["phone"] else [])
        if items:
            issues.append(f"personne {p['person_index']} : " + ", ".join(items))
    return f"{d['person_count']} personne(s)" + (" — " + " ; ".join(issues) if issues else "")


# ------------------------------------------------------------------ header

st.title("🏭 visionhub — vision au poste de production")

try:
    health = api_get("/health")
    use_cases = api_get("/use-cases")
except requests.RequestException as exc:
    st.error(f"API injoignable sur {API_URL} : {exc}")
    st.stop()

status = "▶️ en cours" if health["pipeline_running"] else "⏸️ arrêtée"
st.caption(
    f"API {API_URL} · source : {health['source']} · device : {health['device']} · "
    f"chaîne d'analyse : {status} · images traitées : {health['frames_processed']}"
)
if health.get("pipeline_error"):
    st.error(f"Chaîne d'analyse arrêtée : {health['pipeline_error']}")
for uc in use_cases:
    if uc["status"] != "ok":
        st.error(f"Cas d'usage {uc['use_case']} non chargé : {uc['error']}")

names = [uc["use_case"] for uc in use_cases]

with st.sidebar:
    st.header("Filtres")
    selected = st.selectbox("Cas d'usage", ["tous", *names])
    limit = st.slider("Nombre d'événements affichés", 10, 200, 30, step=10)
    auto = st.toggle("Rafraîchissement automatique", value=True)

    st.header("Seuils")
    st.caption("score < bas → conforme · bas ≤ score < haut → à vérifier · score ≥ haut → anomalie")
    for uc in use_cases:
        if uc["status"] != "ok":
            continue
        t = uc["thresholds"]
        low, high = st.slider(
            f"{uc['use_case']} (bas, haut)",
            0.0,
            1.0,
            (float(t["low"]), float(t["high"])),
            step=0.01,
            key=f"thr-{uc['use_case']}",
        )
        if (low, high) != (t["low"], t["high"]):
            if st.button(f"Appliquer à {uc['use_case']}", key=f"apply-{uc['use_case']}"):
                if api_send("PUT", f"/thresholds/{uc['use_case']}", {"low": low, "high": high}):
                    st.toast(f"Seuils {uc['use_case']} mis à jour : {low:.2f} / {high:.2f}")
                    st.rerun()


# ------------------------------------------------------------------ live part


@st.fragment(run_every=REFRESH_SECONDS if auto else None)
def live() -> None:
    filters = {} if selected == "tous" else {"use_case": selected}

    # Counters
    stats = api_get("/stats")
    st.subheader("Compteurs")
    cols = st.columns(len(names) + 1)
    cols[0].metric("Total", stats["total"])
    cols[0].metric("Taux « à vérifier »", f"{stats['review_rate']:.0%}")
    cols[0].metric("En attente de verdict", stats["pending_review"])
    for col, name in zip(cols[1:], names, strict=True):
        s = stats["by_use_case"].get(name)
        col.markdown(f"**{name}**")
        if not s:
            col.caption("aucun événement")
            continue
        for decision, label in DECISION_LABELS.items():
            col.metric(label, s["counts"].get(decision, 0))
        col.caption(f"taux à vérifier : {s['review_rate']:.0%}")

    left, right = st.columns([3, 2])

    # Event feed
    with left:
        st.subheader("Derniers événements")
        events = api_get("/events", limit=limit, **filters)
        if events:
            rows = [
                {
                    "heure": pd.to_datetime(e["frame"]["timestamp"]).strftime("%H:%M:%S"),
                    "cas d'usage": e["use_case"],
                    "décision": DECISION_LABELS[e["decision"]],
                    "score": round(e["score"], 3),
                    "seuils": "{low:.2f}/{high:.2f}".format(**e["thresholds_used"]),
                    "latence (ms)": round(e["latency_ms"], 1),
                    "détails": summarize(e),
                    "verdict": (e["operator_feedback"] or {}).get("verdict", ""),
                }
                for e in events
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        else:
            st.info("Aucun événement pour l'instant.")

    # Review queue
    with right:
        st.subheader("À vérifier")
        queue = api_get(
            "/events", decision="a_verifier", pending_feedback="true", limit=10, **filters
        )
        if not queue:
            st.success("Rien à vérifier.")
        for e in queue:
            with st.container(border=True):
                st.markdown(
                    f"**{e['use_case']}** · score {e['score']:.2f} · "
                    f"{pd.to_datetime(e['frame']['timestamp']).strftime('%H:%M:%S')}"
                )
                st.caption(summarize(e))
                ok_col, ko_col = st.columns(2)
                for col, verdict, label in (
                    (ok_col, "conforme", "✅ Conforme"),
                    (ko_col, "defaut", "❌ Défaut"),
                ):
                    if col.button(label, key=f"{verdict}-{e['event_id']}"):
                        path = f"/events/{e['event_id']}/feedback"
                        if api_send("POST", path, {"verdict": verdict}):
                            st.toast(f"Verdict « {verdict} » enregistré")
                            st.rerun(scope="fragment")


live()
