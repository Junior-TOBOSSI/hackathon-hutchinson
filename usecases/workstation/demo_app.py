"""Demo of the workstation use case: pick a SECTION, pick a photo, get OK / NOK + boxes.

    streamlit run usecases/workstation/demo_app.py --server.port 8502 \\
        --browser.gatherUsageStats false

Local demo tool of the workstation pair: it calls the analyzer directly. The team
dashboard (dashboard/app.py) stays the official screen and only talks to the API.

- One section = one workstation = one station file (``stations/*.yaml``) and its dataset.
- Honesty: a conforming photo is judged by an analyzer whose "normal" was learned
  WITHOUT that photo (leave-one-out), exactly like in evaluate.py.
- YOLO is loaded once and shared by every analyzer; a section is prepared the first time
  it is opened.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import cv2
import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, if not installed

from usecases.workstation.evaluate import build_analyzer, shared_detector  # noqa: E402
from usecases.workstation.render import describe, render  # noqa: E402
from usecases.workstation.station import STATIONS_DIR, labelled_photos, load_station  # noqa: E402
from visionhub.contracts import FrameMeta  # noqa: E402
from visionhub.decision import decide  # noqa: E402

VERDICT = {
    "conforme": "✅ Workstation OK",
    "a_verifier": "🟠 To check",
    "anomalie": "❌ Workstation NOK",
}

st.set_page_config(page_title="Workstation 5S - demo", layout="wide")


def sections() -> dict[str, str]:
    """Station name -> title, for every station file."""
    out = {}
    for path in sorted(STATIONS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        out[data["name"]] = data.get("title", data["name"])
    return out


@st.cache_resource(show_spinner="Loading the detector (YOLO26)...")
def detector():
    return shared_detector({})


@st.cache_resource(show_spinner="Learning what is normal for this section...")
def prepare(station_name: str, data_root: str):
    """The analyzer learned on all conforming photos (for anomalies), and one per
    conforming photo learned WITHOUT it (leave-one-out)."""
    station = load_station(station_name, data_root)
    rows = labelled_photos(station)
    goods = [r["filename"] for r in rows if r["kind"] == "good"]

    def path(name: str) -> str:
        return str(station["dataset_dir"] / name)

    det = detector()
    full, thresholds = build_analyzer(station, [path(g) for g in goods], {}, detector=det)
    held_out = {
        g: build_analyzer(station, [path(o) for o in goods if o != g], {}, detector=det)[0]
        for g in goods
    }
    return station, rows, full, held_out, thresholds


def main() -> None:
    data_root = st.sidebar.text_input(
        "Data folder", os.environ.get("WORKSTATION_DATA_ROOT", "data")
    )
    titles = sections()
    st.title("Workstation 5S check")
    name = st.segmented_control(
        "Section", list(titles), format_func=titles.get, default=list(titles)[0]
    )
    if name is None:
        st.info("Choose a section.")
        return
    station, rows, full, held_out, thresholds = prepare(name, data_root)
    if not rows:
        st.error(f"No dataset found for {name} in {data_root}.")
        return

    state = st.session_state
    key = f"index_{name}"
    state.setdefault(key, 0)
    state.setdefault("playing", False)

    def label(i: int) -> str:
        r = rows[i]
        return f"{Path(r['filename']).stem}  ·  {r['kind']}"

    st.sidebar.markdown(f"### {titles[name]}")
    c1, c2, c3 = st.sidebar.columns(3)
    if c1.button("⏮"):
        state[key] = (state[key] - 1) % len(rows)
    if c2.button("⏸" if state.playing else "▶"):
        state.playing = not state.playing
    if c3.button("⏭"):
        state[key] = (state[key] + 1) % len(rows)
    state[key] = st.sidebar.selectbox(
        "Photo to evaluate", range(len(rows)), index=state[key] % len(rows), format_func=label
    )
    delay = st.sidebar.slider("Seconds per photo (autoplay)", 1, 8, 3)
    st.sidebar.markdown(
        "**Legend**: green = in place / zone clear, red = deviation, "
        "orange = unknown object, purple = person."
    )

    row = rows[state[key]]
    analyzer = held_out.get(row["filename"], full)
    image = cv2.imread(str(station["dataset_dir"] / row["filename"]))
    start = time.perf_counter()
    meta = FrameMeta(frame_id=row["filename"], workstation_id=name, camera_id="CAM-1")
    result = analyzer.analyze(image, meta)
    latency = (time.perf_counter() - start) * 1000
    decision = decide(result.score, thresholds)

    left, right = st.columns([3, 1])
    shown = render(image, analyzer, result, decision)
    left.image(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB), width="stretch")
    with right:
        st.subheader(VERDICT[decision.value])
        st.markdown("**Findings**")
        for line in describe(result) or ["Nothing to report"]:
            st.markdown(f"- {line}")
        st.markdown("**Ground truth**")
        st.markdown("Conforming" if row["kind"] == "good" else f"Anomaly: {row['kind']}")
        ok = (decision.value == "conforme") == (row["kind"] == "good")
        st.markdown("✅ correct verdict" if ok else "❌ wrong verdict")
        st.caption(f"{row['filename']} · {latency:.0f} ms")

    if state.playing:
        time.sleep(delay)
        state[key] = (state[key] + 1) % len(rows)
        st.rerun()


main()
