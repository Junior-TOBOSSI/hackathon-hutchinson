"""Translate safety results into HOVIS station issues (argos-ui ``StationIssue``).

The HOVIS interface (argos-ui/src/api/types.ts) shows, for each station, a list of current
problems:

    { id, category: "SECURITE_EPI" | "COMPORTEMENT", label, instruction, since }

This module turns the output of the safety analyzer (``AnalysisResult`` with
``SafetyDetails``) into that list. It does not touch the platform: the integration team
calls it where the ``StationLive`` object is built.

Rules:
- an issue is shown only when the frame is not "conforme" (score >= ``low`` threshold):
  the score is already smoothed over several frames, so a single bad frame shows nothing;
- only ABSENT mandatory PPE and phone use become issues; UNCERTAIN ("not visible") never
  does, so an operator is never accused because a hand is hidden;
- one issue per problem for the whole station (the screen says "Gants absents", not one
  line per person); persons are never identified;
- ``since`` is the first time the problem was seen and stays the same while it lasts, so
  the screen shows one ongoing problem, not a new one at every frame.
- shoes appear as soon as ``PersonPPE`` has a ``shoes`` field (contract change pending);
- a phone lying on the station (seen, touching nobody) gives a POSTE issue "Téléphone sur
  le poste" when seen on 2 of the last 3 frames. This is workstation tidiness: to be agreed
  with the Workstation group so that the same phone is not reported twice.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from visionhub.contracts import AnalysisResult, PPEState

# PPE field -> (label, instruction) shown to the operator.
PPE_ISSUES = {
    "helmet": ("Casque absent", "Mettez votre casque"),
    "glasses": ("Lunettes absentes", "Mettez vos lunettes"),
    "gloves": ("Gants absents", "Mettez vos gants"),
    "shoes": ("Chaussures de sécurité non détectées", "Vérifiez vos chaussures de sécurité"),
}
PHONE_ISSUE = ("Téléphone en main", "Rangez votre téléphone")
IDLE_PHONE_ISSUE = ("Téléphone sur le poste", "Rangez le téléphone")
DEFAULT_REQUIRED = ("helmet", "glasses", "gloves", "shoes")


def current_problems(
    result: AnalysisResult, low: float = 0.4, required: tuple[str, ...] = DEFAULT_REQUIRED
) -> list[tuple[str, str, str, str]]:
    """Problems of one frame: (key, category, label, instruction), station level, sorted."""
    if result.details.kind != "safety" or result.score < low:
        return []
    keys: set[str] = set()
    for person in result.details.persons:
        for item in required:
            if getattr(person, item, None) == PPEState.ABSENT:  # field may not exist yet
                keys.add(item)
        if person.phone:
            keys.add("phone")
    problems = []
    for key in sorted(keys):
        if key == "phone":
            problems.append((key, "COMPORTEMENT", *PHONE_ISSUE))
        else:
            problems.append((key, "SECURITE_EPI", *PPE_ISSUES[key]))
    return problems


class StationIssueTracker:
    """Keeps, for one station, when each ongoing problem started."""

    def __init__(
        self,
        station_id: str,
        low: float = 0.4,
        required: tuple[str, ...] = DEFAULT_REQUIRED,
    ) -> None:
        self.station_id = station_id
        self.low = low
        self.required = required
        self._since: dict[str, str] = {}
        self._idle_phone = deque(maxlen=3)  # phone lying on the station, last 3 frames

    def update(
        self, result: AnalysisResult, now: datetime | None = None, idle_phone: bool = False
    ) -> list[dict]:
        """Issues to display after this frame, in the argos-ui ``StationIssue`` format.

        ``idle_phone``: a phone was seen on the station, touching nobody (analyzer's
        ``last_idle_phones``).
        """
        stamp = (now or datetime.now(UTC)).isoformat()
        problems = current_problems(result, self.low, self.required)
        self._idle_phone.append(idle_phone)
        in_use = any(key == "phone" for key, *_ in problems)
        if sum(self._idle_phone) >= 2 and not in_use:  # 2 of the last 3 frames
            problems.append(("phone_on_station", "POSTE", *IDLE_PHONE_ISSUE))
        active = {key for key, *_ in problems}
        # A problem that disappeared is forgotten: if it comes back, it is a new episode.
        self._since = {k: v for k, v in self._since.items() if k in active}
        issues = []
        for key, category, label, instruction in problems:
            since = self._since.setdefault(key, stamp)
            issues.append({
                "id": f"{self.station_id}:safety:{key}",
                "category": category,
                "label": label,
                "instruction": instruction,
                "since": since,
            })  # fmt: skip
        return issues
