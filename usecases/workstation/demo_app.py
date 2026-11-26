"""Demo of the workstation use case: photos play one after the other, OK / NOK + boxes.

    streamlit run usecases/workstation/demo_app.py --server.port 8502

Local demo tool of the workstation pair: it calls the analyzer directly. The team
dashboard (dashboard/app.py) stays the official screen and only talks to the API.

- The playlist holds the photos the analyzer is known to handle correctly (see
  ``PLAYLIST``); "Toutes les photos" shows the whole dataset, pilot lot included.
- Honesty: each conforming photo is judged by an analyzer whose "normal" was learned
  WITHOUT that photo (leave-one-out), exactly like in evaluate.py.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import cv2
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, if not installed

from usecases.workstation.evaluate import build_analyzer  # noqa: E402
from usecases.workstation.render import describe, render  # noqa: E402
from usecases.workstation.station import labelled_photos, load_station  # noqa: E402
from visionhub.contracts import FrameMeta  # noqa: E402
from visionhub.decision import decide  # noqa: E402

STATION = "presse_5s"
# Photos handled correctly AND precisely (only the real problem reported), 2026-11-26.
PLAYLIST = [
    "good/good_003.png",
    "anomaly/anomaly_006.png",
    "anomaly/anomaly_011.png",
    "good/good_004.png",
    "anomaly/anomaly_007.png",
    "anomaly/anomaly_014.png",
    "good/good_005.png",
    "anomaly/anomaly_008.png",
    "anomaly/anomaly_012.png",
    "good/good_001.png",
    "anomaly/anomaly_009.png",
    "anomaly/anomaly_010.png",
]
EXPECTED = {
    "good": "Poste conforme",
    "disorder": "Désordre (établi / outillage)",
    "zone_object": "Objet dans la zone rouge",
    "zone_person": "Personne dans la zone rouge",
}

st.set_page_config(page_title="Poste 5S - démo", layout="wide")


@st.cache_resource(show_spinner="Apprentissage de la normalité du poste...")
def analyzers(data_root: str):
    """One analyzer learned on all conforming photos (for anomalies), and one per
    conforming photo learned WITHOUT it (leave-one-out)."""
    station = load_station(STATION, data_root)
    rows = labelled_photos(station)
    goods = [r["filename"] for r in rows if r["kind"] == "good"]

    def path(name: str) -> str:
        return str(station["dataset_dir"] / name)

    full, thresholds = build_analyzer(station, [path(g) for g in goods], {})
    held_out = {
        g: build_analyzer(station, [path(o) for o in goods if o != g], {})[0] for g in goods
    }
    return station, {r["filename"]: r["kind"] for r in rows}, full, held_out, thresholds


def main() -> None:
    st.sidebar.title("Poste 5S")
    data_root = st.sidebar.text_input(
        "Dossier des données", os.environ.get("WORKSTATION_DATA_ROOT", "data")
    )
    station, kinds, full, held_out, thresholds = analyzers(data_root)
    everything = st.sidebar.toggle("Toutes les photos (lot pilote compris)", value=False)
    playlist = list(kinds) if everything else [p for p in PLAYLIST if p in kinds]
    delay = st.sidebar.slider("Secondes par photo", 1, 8, 3)

    state = st.session_state
    state.setdefault("index", 0)
    state.setdefault("playing", False)
    state.index %= len(playlist)
    c1, c2, c3 = st.sidebar.columns(3)
    if c1.button("⏮"):
        state.index = (state.index - 1) % len(playlist)
    if c2.button("⏸" if state.playing else "▶"):
        state.playing = not state.playing
    if c3.button("⏭"):
        state.index = (state.index + 1) % len(playlist)
    st.sidebar.caption(f"Photo {state.index + 1} / {len(playlist)}")
    st.sidebar.markdown(
        "**Légende** : vert = en place / zone vide, rouge = écart, "
        "orange = objet inconnu (unknown object), violet = personne (person)."
    )

    name = playlist[state.index]
    kind = kinds[name]
    analyzer = held_out.get(name, full)
    image = cv2.imread(str(station["dataset_dir"] / name))
    start = time.perf_counter()
    result = analyzer.analyze(
        image, FrameMeta(frame_id=name, workstation_id="PRESSE-5S", camera_id="CAM-1")
    )
    latency = (time.perf_counter() - start) * 1000
    decision = decide(result.score, thresholds)

    # The verdict banner is drawn on the image itself (render.py): no second banner here.
    left, right = st.columns([3, 1])
    left.image(
        cv2.cvtColor(render(image, analyzer, result, decision), cv2.COLOR_BGR2RGB),
        width="stretch",
    )
    with right:
        st.subheader("Constat")
        problems = describe(result)
        if problems:
            for line in problems:
                st.markdown(f"- {line}")
        else:
            st.markdown("- Rien à signaler")
        st.subheader("Vérité terrain")
        st.markdown(f"{EXPECTED.get(kind, kind)}")
        ok = (decision.value == "conforme") == (kind == "good")
        st.markdown("✅ verdict correct" if ok else "❌ verdict incorrect")
        st.caption(f"{name} · vue {analyzer.last_view} · {latency:.0f} ms")

    if state.playing:
        time.sleep(delay)
        state.index = (state.index + 1) % len(playlist)
        st.rerun()


main()
