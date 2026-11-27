"""Safety result -> HOVIS station issues (argos-ui StationIssue format)."""

from datetime import UTC, datetime, timedelta

from usecases.safety.hovis import StationIssueTracker, current_problems, station_checks
from visionhub.contracts import AnalysisResult, PersonPPE, PPEState, SafetyDetails, UseCase

A, P, U = PPEState.ABSENT, PPEState.PRESENT, PPEState.UNCERTAIN
T0 = datetime(2026, 11, 27, 8, 0, tzinfo=UTC)


def result(score, persons):
    return AnalysisResult(
        use_case=UseCase.SAFETY, score=score, model_name="yolo-safety", model_version="test",
        details=SafetyDetails(person_count=len(persons), persons=persons),
    )  # fmt: skip


def person(i=0, helmet=P, glasses=P, gloves=P, phone=False):
    return PersonPPE(
        person_index=i, helmet=helmet, vest=U, glasses=glasses, gloves=gloves, phone=phone
    )


def test_conforme_frame_shows_nothing():
    assert current_problems(result(0.1, [person(gloves=A)])) == []


def test_absent_ppe_and_phone_become_issues():
    problems = current_problems(result(0.9, [person(glasses=A, phone=True)]))
    assert [(k, c, label) for k, c, label, _ in problems] == [
        ("glasses", "SECURITE_EPI", "Lunettes absentes"),
        ("phone", "COMPORTEMENT", "Téléphone en main"),
    ]


def test_uncertain_never_becomes_an_issue():
    assert current_problems(result(0.9, [person(helmet=U, glasses=U, gloves=U)])) == []


def test_one_issue_per_problem_for_the_station_not_per_person():
    problems = current_problems(result(0.9, [person(0, gloves=A), person(1, gloves=A)]))
    assert [k for k, *_ in problems] == ["gloves"]


def test_non_required_ppe_is_ignored():
    assert current_problems(result(0.9, [person(helmet=A)]), required=("gloves",)) == []


def test_issue_format_matches_argos_ui_station_issue():
    issue = StationIssueTracker("C3·P06").update(result(0.9, [person(gloves=A)]), T0)[0]
    assert set(issue) == {"id", "category", "label", "instruction", "since"}
    assert issue == {
        "id": "C3·P06:safety:gloves",
        "category": "SECURITE_EPI",
        "label": "Gants absents",
        "instruction": "Mettez vos gants",
        "since": T0.isoformat(),
    }


def test_since_stays_the_same_while_the_problem_lasts():
    tracker = StationIssueTracker("P1")
    tracker.update(result(0.9, [person(gloves=A)]), T0)
    later = tracker.update(result(0.9, [person(gloves=A)]), T0 + timedelta(minutes=2))
    assert later[0]["since"] == T0.isoformat()


def test_problem_that_comes_back_is_a_new_episode():
    tracker = StationIssueTracker("P1")
    tracker.update(result(0.9, [person(gloves=A)]), T0)
    assert tracker.update(result(0.1, [person()]), T0 + timedelta(minutes=1)) == []
    back = tracker.update(result(0.9, [person(gloves=A)]), T0 + timedelta(minutes=5))
    assert back[0]["since"] == (T0 + timedelta(minutes=5)).isoformat()


def test_no_identity_in_issues():
    issues = StationIssueTracker("P1").update(result(0.9, [person(3, gloves=A)]), T0)
    assert "3" not in issues[0]["id"].split(":")[-1]
    assert "person" not in str(issues)


def test_phone_lying_on_the_station_is_a_poste_issue_after_two_frames():
    tracker = StationIssueTracker("P1")
    assert tracker.update(result(0.1, [person()]), T0, idle_phone=True) == []
    issues = tracker.update(result(0.1, [person()]), T0, idle_phone=True)
    assert [(i["category"], i["label"]) for i in issues] == [("POSTE", "Téléphone sur le poste")]


def test_phone_in_use_is_not_also_reported_as_lying_on_the_station():
    tracker = StationIssueTracker("P1")
    tracker.update(result(0.9, [person(phone=True)]), T0, idle_phone=True)
    issues = tracker.update(result(0.9, [person(phone=True)]), T0, idle_phone=True)
    assert [i["category"] for i in issues] == ["COMPORTEMENT"]


def test_phone_in_hand_turns_the_securite_tile_red_and_lying_phone_the_poste_tile():
    tracker = StationIssueTracker("P1")
    assert station_checks([]) == {"securite": True, "poste": True}
    in_hand = tracker.update(result(0.9, [person(phone=True)]), T0)
    assert station_checks(in_hand) == {"securite": False, "poste": True}
    other = StationIssueTracker("P2")
    other.update(result(0.1, [person()]), T0, idle_phone=True)
    lying = other.update(result(0.1, [person()]), T0, idle_phone=True)
    assert station_checks(lying) == {"securite": True, "poste": False}


def test_flickering_detection_stays_one_episode_and_does_not_blink():
    """Gloves missed on a few frames: the issue stays on screen with the same start."""
    tracker = StationIssueTracker("P1", hold_s=5)
    tracker.update(result(0.9, [person(gloves=A)]), T0)
    gap = tracker.update(result(0.1, [person()]), T0 + timedelta(seconds=2))
    back = tracker.update(result(0.9, [person(gloves=A)]), T0 + timedelta(seconds=4))
    assert [i["label"] for i in gap] == ["Gants absents"]
    assert back[0]["since"] == T0.isoformat()


def test_problem_ends_after_the_hold_time():
    tracker = StationIssueTracker("P1", hold_s=5)
    tracker.update(result(0.9, [person(gloves=A)]), T0)
    assert tracker.update(result(0.1, [person()]), T0 + timedelta(seconds=6)) == []
