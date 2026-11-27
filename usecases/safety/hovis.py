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
- a problem ends only after ``hold_s`` seconds (5 s) without being seen: a detection that
  flickers (gloves seen, missed, seen) stays ONE episode and does not blink on screen, so the
  team leader is not spammed. Cost: the issue stays ~5 s after the operator fixed it.
- shoes: ``PersonPPE`` (contract) has no ``shoes`` field yet, so pass the analyzer's
  ``last_states`` (``person_states``), which has them: shoes then raise issues like the
  other PPE. Only the Core storage still waits for the contract change;
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
    result: AnalysisResult,
    low: float = 0.4,
    required: tuple[str, ...] = DEFAULT_REQUIRED,
    person_states: list[dict[str, PPEState]] | None = None,
) -> list[tuple[str, str, str, str]]:
    """Problems of one frame: (key, category, label, instruction), station level, sorted.

    ``person_states``: the analyzer's ``last_states`` (shoes included). Without it, the PPE
    states are read from the contract, which has no shoes yet.
    """
    if result.details.kind != "safety" or result.score < low:
        return []
    if person_states is None:
        person_states = [
            {item: getattr(p, item, None) for item in required} for p in result.details.persons
        ]  # fmt: skip
    keys: set[str] = set()
    for states in person_states:
        for item in required:
            if states.get(item) == PPEState.ABSENT:
                keys.add(item)
    if any(person.phone for person in result.details.persons):
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
        hold_s: float = 5.0,
    ) -> None:
        self.station_id = station_id
        self.low = low
        self.required = required
        self.hold_s = hold_s
        self._since: dict[str, str] = {}
        self._last_seen: dict[str, datetime] = {}
        self._problem: dict[str, tuple[str, str, str]] = {}  # key -> (category, label, instr.)
        self._idle_phone = deque(maxlen=3)  # phone lying on the station, last 3 frames

    def clear(self) -> None:
        """Forget every ongoing problem at once (e.g. camera covered: nobody can be seen)."""
        self._since.clear()
        self._last_seen.clear()
        self._idle_phone.clear()

    def update(
        self,
        result: AnalysisResult,
        now: datetime | None = None,
        idle_phone: bool = False,
        person_states: list[dict[str, PPEState]] | None = None,
    ) -> list[dict]:
        """Issues to display after this frame, in the argos-ui ``StationIssue`` format.

        ``idle_phone``: a phone was seen on the station, touching nobody (analyzer's
        ``last_idle_phones``). ``person_states``: analyzer's ``last_states`` (for shoes).
        """
        now = now or datetime.now(UTC)
        stamp = now.isoformat()
        problems = current_problems(result, self.low, self.required, person_states)
        self._idle_phone.append(idle_phone)
        in_use = any(key == "phone" for key, *_ in problems)
        if sum(self._idle_phone) >= 2 and not in_use:  # 2 of the last 3 frames
            problems.append(("phone_on_station", "POSTE", *IDLE_PHONE_ISSUE))
        for key, *rest in problems:
            self._last_seen[key], self._problem[key] = now, tuple(rest)
        if in_use:  # the same phone is never reported twice
            self._last_seen.pop("phone_on_station", None)
        # A problem not seen for hold_s seconds is over: if it comes back, new episode.
        held = {k for k, t in self._last_seen.items() if (now - t).total_seconds() <= self.hold_s}
        self._last_seen = {k: t for k, t in self._last_seen.items() if k in held}
        self._since = {k: v for k, v in self._since.items() if k in held}
        issues = []
        for key in sorted(held):
            category, label, instruction = self._problem[key]
            since = self._since.setdefault(key, stamp)
            issues.append({
                "id": f"{self.station_id}:safety:{key}",
                "category": category,
                "label": label,
                "instruction": instruction,
                "since": since,
            })  # fmt: skip
        return issues


def station_checks(issues: list[dict]) -> dict[str, bool]:
    """Safety part of ``StationLive.checks`` (True = green tile on the operator screen).

    argos-ui files a phone in hand under "Sécurité · comportement", so COMPORTEMENT turns
    the Sécurité tile red too; a phone lying on the station turns the Poste tile red.
    """
    categories = {issue["category"] for issue in issues}
    return {
        "securite": not categories & {"SECURITE_EPI", "COMPORTEMENT"},
        "poste": "POSTE" not in categories,
    }


def station_ppe(
    person_states: list[dict[str, PPEState]],
    issues: list[dict],
    required: tuple[str, ...] = DEFAULT_REQUIRED,
) -> dict[str, str]:
    """State of each mandatory PPE for the station, for pictograms on the operator screen.

    ``person_states``: the analyzer's ``last_states`` (one dict per person).
    - "absent": there is an issue for it (so the pictogram and the issue list always agree,
      smoothing and hold time included);
    - "present": every person seen wears it;
    - "uncertain": not visible, or no one in view. Never shown as a fault.
    """
    flagged = {issue["id"].rsplit(":", 1)[-1] for issue in issues}
    states = {}
    for item in required:
        if item in flagged:
            states[item] = "absent"
        elif person_states and all(p.get(item) == PPEState.PRESENT for p in person_states):
            states[item] = "present"
        else:
            states[item] = "uncertain"
    return states
