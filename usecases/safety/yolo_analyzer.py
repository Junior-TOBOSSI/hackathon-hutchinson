"""Real safety analyzer: PPE (helmet, glasses, gloves, shoes) and phone use, with YOLO.

Two models:
- the PPE model (SH17 classes: person, face, head, hands, helmet, glasses, gloves, shoes,
  foot), our retrained weights or the official SH17 ones (same class names);
- a generic COCO model, used only for its "cell phone" class (no training needed).

Rule of evidence: "not seen" is not "absent". A PPE is ABSENT only when the body part it
protects is visible without it (bare hand -> no gloves, head -> no helmet, face -> no
glasses, whole body with no shoes -> no shoes); when the body part is not visible the
state is UNCERTAIN and raises no alert. Only the PPE listed in ``required`` count.

Score (higher = worse): an absent PPE or a phone in use gives 0.4 + 0.6 x confidence of
the evidence, so the decision layer (thresholds 0.4 / 0.7) turns weak evidence into
"a_verifier" and strong evidence into "anomalie". Missing shoes inferred from a fully
visible body only get ``shoes_absent_score`` (0.5 = "a_verifier"): the model finds only
about half of the shoes, a red alert would be wrong too often. The frame score is the
worst person; it is then smoothed: the returned score is the MEDIAN of the last
``smoothing_frames`` scores. With 3 frames, a single wrong frame never raises an alert,
and a problem seen on 2 frames out of 3 does (a phone half hidden by the hand is often
missed on one frame: requiring every frame would drop real alerts).

Privacy: the result only holds PPE states and person boxes. No image, no face.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from visionhub.analyzer import Analyzer
from visionhub.contracts import (
    AnalysisResult,
    BBox,
    FrameMeta,
    PersonPPE,
    PPEState,
    SafetyDetails,
    UseCase,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PPE_ITEMS = ("helmet", "glasses", "gloves", "shoes")
PHONE_CLASS = "cell phone"
PHONE_ZONE = ("hands", "gloves", "head")  # a phone touching one of these is "in use"
PRIVACY_CLASSES = ("face", "head", "person")  # boxes used to hide faces before display

DEFAULTS: dict[str, Any] = {
    "weights": "data/models/safety/sh17_yolov8n.pt",
    "phone_weights": "data/models/yolov8n_coco.pt",
    "detect_phone": True,
    "imgsz": 640,
    "conf": 0.25,  # default confidence threshold
    "class_conf": {},  # per-class override, e.g. {"gloves": 0.3}
    "phone_conf": 0.30,
    "required": list(PPE_ITEMS),
    "smoothing_frames": 3,
    "shoes_absent_score": 0.5,
    "full_body_bottom": 0.97,  # person box ending above this (normalized y) = feet in view
    "phone_margin": 0.5,
    "privacy_conf": 0.10,  # faces, heads, persons kept from this confidence on, for hiding
    "require_head": True,  # a person counts only if a head or face is seen inside its box
    "operator_only": True,  # check only the station operator (largest person), not passers-by
    "min_contrast": 12.0,  # below (grey-level std): camera covered or in the dark
    "min_sharpness": 10.0,  # below (Laplacian variance): lens covered (e.g. by a hand)
}


@dataclass(frozen=True)
class Det:
    """One detection: class name, confidence, normalized box (x1, y1, x2, y2)."""

    name: str
    conf: float
    box: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2

    @property
    def area(self) -> float:
        return (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])


@dataclass
class PersonAssessment:
    box: tuple[float, float, float, float]
    states: dict[str, PPEState] = field(default_factory=dict)
    evidence: dict[str, float] = field(default_factory=dict)  # risk of each absent PPE
    phone: bool = False
    phone_risk: float = 0.0


# --------------------------------------------------------------------------- pure logic


def contains(outer: tuple[float, ...], point: tuple[float, float]) -> bool:
    return outer[0] <= point[0] <= outer[2] and outer[1] <= point[1] <= outer[3]


def touches(a: tuple[float, ...], b: tuple[float, ...], margin: float) -> bool:
    """True if box a, widened by margin x its own size, overlaps box b."""
    dx, dy = margin * (a[2] - a[0]), margin * (a[3] - a[1])
    return a[0] - dx < b[2] and b[0] < a[2] + dx and a[1] - dy < b[3] and b[1] < a[3] + dy


def covered(hand: tuple[float, ...], gloves: list[Det], min_share: float = 0.5) -> bool:
    """True if a glove box covers at least ``min_share`` of the hand box: a gloved hand is
    often ALSO detected as "hands", it is not a bare hand."""
    area = max(1e-9, (hand[2] - hand[0]) * (hand[3] - hand[1]))
    for g in gloves:
        w = min(hand[2], g.box[2]) - max(hand[0], g.box[0])
        h = min(hand[3], g.box[3]) - max(hand[1], g.box[1])
        if w > 0 and h > 0 and w * h / area >= min_share:
            return True
    return False


def risk(conf: float) -> float:
    """Evidence confidence -> score: 0.4 (weak, a_verifier) to 1.0 (certain, anomalie)."""
    return min(1.0, 0.4 + 0.6 * conf)


def assign_to_persons(persons: list[Det], parts: list[Det]) -> list[list[Det]]:
    """Give each part to the smallest person box that contains its center."""
    groups: list[list[Det]] = [[] for _ in persons]
    for part in parts:
        owners = [i for i, p in enumerate(persons) if contains(p.box, part.center)]
        if owners:
            groups[min(owners, key=lambda i: persons[i].area)].append(part)
    return groups


def assess_person(person: Det, parts: list[Det], phones: list[Det], p: dict) -> PersonAssessment:
    """PPE states of one person, from the parts assigned to it (rule of evidence)."""
    by_name: dict[str, list[Det]] = {}
    for d in parts:
        by_name.setdefault(d.name, []).append(d)
    # A hand covered by a glove box is a gloved hand (the model often sees both): only the
    # hands NOT covered by a glove are bare hands.
    if "hands" in by_name:
        bare = [h for h in by_name["hands"] if not covered(h.box, by_name.get("gloves", []))]
        if bare:
            by_name["hands"] = bare
        else:
            del by_name["hands"]
    best = {name: max(d.conf for d in dets) for name, dets in by_name.items()}
    out = PersonAssessment(box=person.box)

    def decide(item: str, worn: str, evidence: str) -> None:
        if evidence in best and item == "gloves":  # one bare hand is enough to break the rule
            out.states[item], out.evidence[item] = PPEState.ABSENT, risk(best[evidence])
        elif worn in best:
            out.states[item] = PPEState.PRESENT
        elif evidence in best:
            out.states[item], out.evidence[item] = PPEState.ABSENT, risk(best[evidence])
        else:
            out.states[item] = PPEState.UNCERTAIN

    decide("gloves", "gloves", "hands")
    decide("helmet", "helmet", "head")
    decide("glasses", "glasses", "face")
    decide("shoes", "shoes", "foot")
    if out.states["shoes"] == PPEState.UNCERTAIN and person.box[3] < p["full_body_bottom"]:
        # Whole body in the image, feet in view, yet no shoe detected.
        out.states["shoes"], out.evidence["shoes"] = PPEState.ABSENT, p["shoes_absent_score"]

    zones = [d.box for d in parts if d.name in PHONE_ZONE]
    for phone in phones:
        if any(touches(phone.box, z, p["phone_margin"]) for z in zones):
            out.phone, out.phone_risk = True, max(out.phone_risk, risk(phone.conf))
    return out


def scene_visible(image: np.ndarray, min_contrast: float, min_sharpness: float) -> bool:
    """False when the camera sees nothing usable: lens covered by a hand, cap, darkness.

    A covered lens gives a dark or uniform, blurry image: low contrast (grey-level standard
    deviation) and almost no edges (variance of the Laplacian).
    """
    import cv2  # installed with ultralytics

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(grey, (160, max(1, 160 * grey.shape[0] // grey.shape[1])))
    sharpness = cv2.Laplacian(small, cv2.CV_64F).var()
    return float(small.std()) >= min_contrast and float(sharpness) >= min_sharpness


def keep_real_persons(dets: list[Det]) -> list[Det]:
    """Drop person boxes with no head or face inside: a hand on the lens, a coat, a reflection.

    Somebody working at the station shows a head (or a face) to the front camera.
    """
    anchors = [d.center for d in dets if d.name in ("head", "face")]
    return [
        d for d in dets if d.name != "person" or any(contains(d.box, c) for c in anchors)
    ]  # fmt: skip


def idle_phones(dets: list[Det], phones: list[Det], p: dict) -> list[Det]:
    """Phones that touch no hand, gloved hand or head in the frame: not in use, lying around."""
    zones = [d.box for d in dets if d.name in PHONE_ZONE]
    return [ph for ph in phones if not any(touches(ph.box, z, p["phone_margin"]) for z in zones)]


def assess_frame(
    dets: list[Det], phones: list[Det], p: dict
) -> tuple[list[PersonAssessment], float]:
    """All persons of one frame and the raw frame score (worst person, required PPE only)."""
    persons = [d for d in dets if d.name == "person"]
    parts = [d for d in dets if d.name != "person"]
    groups = assign_to_persons(persons, parts)
    if p.get("operator_only") and persons:
        # Only the operator of the station: the largest person, i.e. the closest to the camera.
        # Passers-by, people in the background, posters or reflections raise nothing. Their
        # heads, faces and hands stay with them (parts are assigned before the choice).
        main = max(range(len(persons)), key=lambda i: persons[i].area)
        persons, groups = [persons[main]], [groups[main]]
    assessed = [
        assess_person(person, g, phones, p) for person, g in zip(persons, groups, strict=True)
    ]
    score = 0.0
    for a in assessed:
        for item in p["required"]:
            score = max(score, a.evidence.get(item, 0.0))
        score = max(score, a.phone_risk)
    return assessed, score


# --------------------------------------------------------------------------- analyzer


class YoloSafetyAnalyzer(Analyzer):
    use_case = UseCase.SAFETY
    name = "yolo-safety"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        from ultralytics import YOLO  # optional dependency: pip install -e ".[safety]"

        self.p = {**DEFAULTS, **{k: v for k, v in config.items() if k in DEFAULTS}}
        self.device = config.get("device", "cpu")
        self.model = YOLO(str(_resolve(self.p["weights"])))
        self.names = {i: str(n).lower() for i, n in self.model.names.items()}
        self.phone_model, self.phone_id = None, None
        if self.p["detect_phone"]:
            self.phone_model = YOLO(str(_resolve(self.p["phone_weights"])))
            self.phone_id = next(i for i, n in self.phone_model.names.items() if n == PHONE_CLASS)
        self.recent: deque[float] = deque(maxlen=max(1, int(self.p["smoothing_frames"])))

    def _predict(self, model, image: np.ndarray, conf: float, classes=None) -> list[Det]:
        result = model.predict(image, conf=conf, classes=classes, imgsz=self.p["imgsz"],
                               device=self.device, verbose=False)[0]  # fmt: skip
        names = model.names
        return [
            Det(str(names[int(c)]).lower(), float(s), tuple(float(v) for v in box))
            for c, s, box in zip(
                result.boxes.cls, result.boxes.conf, result.boxes.xyxyn, strict=True
            )
        ]

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        class_conf = self.p["class_conf"]
        low = min([self.p["conf"], *class_conf.values(), self.p["privacy_conf"]])
        # Camera covered (hand on the lens) or in the dark: nobody can be seen, so no person,
        # no PPE problem; the station screen then shows the part instead of the camera.
        self.last_camera_blocked = not scene_visible(
            image, self.p["min_contrast"], self.p["min_sharpness"]
        )  # fmt: skip
        raw = [] if self.last_camera_blocked else self._predict(self.model, image, low)
        dets = [d for d in raw if d.conf >= class_conf.get(d.name, self.p["conf"])]
        if self.p["require_head"]:
            dets = keep_real_persons(dets)
        # Privacy: faces must be hidden even when the model is unsure, so the boxes used
        # for hiding keep a much lower threshold than the business rules (one inference).
        self.last_privacy = [
            d for d in raw if d.name in PRIVACY_CLASSES and d.conf >= self.p["privacy_conf"]
        ]  # fmt: skip
        phones = []
        if self.phone_model is not None and not self.last_camera_blocked:
            phones = self._predict(self.phone_model, image, self.p["phone_conf"], [self.phone_id])

        # Kept for overlays (e.g. a debug view drawing boxes) without a second inference.
        self.last_detections, self.last_phones = dets, phones
        # Phones touching nobody's hand or head: lying on the station (workstation tidiness).
        self.last_idle_phones = idle_phones(dets, phones, self.p)
        assessed, raw_score = assess_frame(dets, phones, self.p)
        # PPE states of each person, shoes included even before the contract has them.
        self.last_states = [dict(a.states) for a in assessed]
        self.recent.append(raw_score)
        # Smoothing: median of the window. While the window is not full yet (start-up),
        # no alert: one frame alone is never enough.
        full = len(self.recent) == self.recent.maxlen
        score = float(np.median(list(self.recent))) if full else 0.0

        persons = []
        has_shoes_field = "shoes" in PersonPPE.model_fields  # once the contract has it
        for i, a in enumerate(assessed):
            x1, y1, x2, y2 = (min(1.0, max(0.0, v)) for v in a.box)
            fields = {
                "person_index": i,
                "bbox": BBox(x1=x1, y1=y1, x2=max(x1, x2), y2=max(y1, y2)),
                "helmet": a.states["helmet"],
                "vest": PPEState.UNCERTAIN,  # not checked: not required at this workstation
                "glasses": a.states["glasses"],
                "gloves": a.states["gloves"],
                "phone": a.phone,
            }
            if has_shoes_field:
                fields["shoes"] = a.states["shoes"]
            persons.append(PersonPPE(**fields))

        return AnalysisResult(
            use_case=self.use_case,
            score=score,
            model_name=self.name,
            model_version=self.version,
            details=SafetyDetails(person_count=len(persons), persons=persons),
        )


def _resolve(path: str) -> Path:
    """Relative weight paths are relative to the repository root."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p
