"""Local SQLite of the retraining policies (ARGOS_MLOPS_HOME/retraining.sqlite).

- policies: insert-only (policy_id, version): every change is a NEW version, history kept;
- proposals: UNIQUE(policy_id, evidence_key): the same evidence never yields two proposals;
- ledger: launches counted for budgets / delays; reservations are taken inside a
  ``BEGIN IMMEDIATE`` transaction, so concurrent evaluations cannot exceed a budget nor
  launch one proposal twice;
- audit: append-only journal of every action.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mlops.retraining.models import Evaluation, Proposal, RetrainPolicyConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (policy_id TEXT NOT NULL, version INTEGER NOT NULL,
  created_at TEXT NOT NULL, author TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY (policy_id, version));
CREATE TABLE IF NOT EXISTS manual_requests (request_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL,
  at TEXT NOT NULL, actor TEXT NOT NULL, note TEXT, consumed_by TEXT);
CREATE TABLE IF NOT EXISTS evaluations (evaluation_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL,
  at TEXT NOT NULL, eligible INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposals (proposal_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL,
  evidence_key TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE (policy_id, evidence_key));
CREATE TABLE IF NOT EXISTS ledger (ledger_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL,
  model_id TEXT NOT NULL, proposal_id TEXT NOT NULL, at TEXT NOT NULL, status TEXT NOT NULL,
  job_run_id INTEGER, idempotency_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
  policy_id TEXT, actor TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL);
"""

COUNTED = ("reserved", "launched", "uncertain")  # a reservation already consumes the budget


def default_path() -> Path:
    home = Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL"))
    return home / "retraining.sqlite"


class RetrainingStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or default_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=15, isolation_level=None)

    @contextmanager
    def tx(self):
        """Serialized write transaction (BEGIN IMMEDIATE takes the database write lock)."""
        with self._lock:
            c = self._conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            finally:
                c.close()

    def _rows(self, q: str, args: tuple = ()) -> list[tuple]:
        c = self._conn()
        try:
            return c.execute(q, args).fetchall()
        finally:
            c.close()

    # ------------------------------------------------------------------ policies

    def add_policy(self, p: RetrainPolicyConfig) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO policies VALUES (?,?,?,?,?)",
                (p.policy_id, p.version, p.created_at, p.author, p.model_dump_json()),
            )

    def next_version(self, policy_id: str) -> int:
        row = self._rows("SELECT MAX(version) FROM policies WHERE policy_id=?", (policy_id,))
        return (row[0][0] or 0) + 1

    def policy(self, policy_id: str, version: int | None = None) -> RetrainPolicyConfig | None:
        q = "SELECT payload FROM policies WHERE policy_id=?"
        rows = self._rows(
            q + (" AND version=?" if version else " ORDER BY version DESC LIMIT 1"),
            (policy_id, version) if version else (policy_id,),
        )
        return RetrainPolicyConfig.model_validate_json(rows[0][0]) if rows else None

    def history(self, policy_id: str) -> list[RetrainPolicyConfig]:
        rows = self._rows(
            "SELECT payload FROM policies WHERE policy_id=? ORDER BY version DESC", (policy_id,)
        )
        return [RetrainPolicyConfig.model_validate_json(r[0]) for r in rows]

    def policies(self) -> list[RetrainPolicyConfig]:
        rows = self._rows(
            "SELECT payload FROM policies p WHERE version = (SELECT MAX(version) "
            "FROM policies q WHERE q.policy_id = p.policy_id) ORDER BY created_at"
        )
        return [RetrainPolicyConfig.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------------ manual requests

    def add_manual_request(self, policy_id: str, at: str, actor: str, note: str | None) -> str:
        rid = uuid.uuid4().hex[:16]
        with self.tx() as c:
            c.execute(
                "INSERT INTO manual_requests VALUES (?,?,?,?,?,NULL)",
                (rid, policy_id, at, actor, note),
            )
        return rid

    def consumed_manual(self, proposal_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT request_id, at, actor, note FROM manual_requests WHERE consumed_by=?",
            (proposal_id,),
        )
        return [{"request_id": r[0], "at": r[1], "actor": r[2], "note": r[3]} for r in rows]

    def pending_manual(self, policy_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT request_id, at, actor, note FROM manual_requests WHERE policy_id=? "
            "AND consumed_by IS NULL ORDER BY at",
            (policy_id,),
        )
        return [{"request_id": r[0], "at": r[1], "actor": r[2], "note": r[3]} for r in rows]

    # ------------------------------------------------------------------ evaluations

    def add_evaluation(self, e: Evaluation) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO evaluations VALUES (?,?,?,?,?)",
                (e.evaluation_id, e.policy_id, e.at, int(e.eligible), e.model_dump_json()),
            )

    def evaluations(self, policy_id: str | None = None, limit: int = 50) -> list[Evaluation]:
        q, a = "SELECT payload FROM evaluations", ()
        if policy_id:
            q, a = q + " WHERE policy_id=?", (policy_id,)
        rows = self._rows(q + " ORDER BY at DESC LIMIT ?", (*a, limit))
        return [Evaluation.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------------ proposals

    def create_proposal(self, p: Proposal, manual_ids: list[str]) -> Proposal | None:
        """Insert unless the SAME evidence already produced a proposal (returns None)."""
        with self.tx() as c:
            if c.execute(
                "SELECT 1 FROM proposals WHERE policy_id=? AND evidence_key=?",
                (p.policy_id, p.evidence_key),
            ).fetchone():
                return None
            c.execute(
                "INSERT INTO proposals VALUES (?,?,?,?,?,?,?)",
                (
                    p.proposal_id,
                    p.policy_id,
                    p.evidence_key,
                    p.status,
                    p.created_at,
                    p.updated_at,
                    p.model_dump_json(),
                ),
            )
            for rid in manual_ids:  # a manual request is consumed by ONE proposal
                c.execute(
                    "UPDATE manual_requests SET consumed_by=? WHERE request_id=?",
                    (p.proposal_id, rid),
                )
        return p

    def proposal(self, proposal_id: str) -> Proposal | None:
        rows = self._rows("SELECT payload FROM proposals WHERE proposal_id=?", (proposal_id,))
        return Proposal.model_validate_json(rows[0][0]) if rows else None

    def proposals(self, policy_id: str | None = None, status: str | None = None) -> list[Proposal]:
        q, a = "SELECT payload FROM proposals WHERE 1=1", []
        if policy_id:
            q, a = q + " AND policy_id=?", [*a, policy_id]
        if status:
            q, a = q + " AND status=?", [*a, status]
        return [
            Proposal.model_validate_json(r[0])
            for r in self._rows(q + " ORDER BY created_at DESC", tuple(a))
        ]

    def save_proposal(self, p: Proposal, c: sqlite3.Connection | None = None) -> None:
        args = (p.status, p.updated_at, p.model_dump_json(), p.proposal_id)
        q = "UPDATE proposals SET status=?, updated_at=?, payload=? WHERE proposal_id=?"
        if c is not None:
            c.execute(q, args)
        else:
            with self.tx() as cx:
                cx.execute(q, args)

    # ------------------------------------------------------------------ ledger / reservation

    def ledger(self, policy_id: str | None = None) -> list[dict[str, Any]]:
        q, a = (
            "SELECT ledger_id, policy_id, model_id, proposal_id, at, status, job_run_id, "
            "idempotency_key FROM ledger",
            (),
        )
        if policy_id:
            q, a = q + " WHERE policy_id=?", (policy_id,)
        keys = (
            "ledger_id",
            "policy_id",
            "model_id",
            "proposal_id",
            "at",
            "status",
            "job_run_id",
            "idempotency_key",
        )
        return [dict(zip(keys, r, strict=True)) for r in self._rows(q + " ORDER BY at DESC", a)]

    def reserve(
        self, proposal_id: str, check: Callable[[sqlite3.Connection, Proposal], str | None], at: str
    ) -> tuple[Proposal | None, str | None]:
        """Atomically: proposal still launchable + budget / delay checks (``check`` returns a
        refusal reason) + ledger reservation + proposal -> launching."""
        with self.tx() as c:
            row = c.execute(
                "SELECT payload FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if not row:
                return None, "unknown proposal"
            p = Proposal.model_validate_json(row[0])
            if p.status not in ("pending", "accepted"):
                return p, f"proposal is {p.status}: it cannot be launched (again)"
            reason = check(c, p)
            if reason:
                return p, reason
            key = f"policy-{p.proposal_id}"  # stable: retries reuse the SAME idempotency key
            c.execute(
                "INSERT INTO ledger VALUES (?,?,?,?,?,?,NULL,?)",
                (uuid.uuid4().hex, p.policy_id, p.model_id, p.proposal_id, at, "reserved", key),
            )
            p.status, p.updated_at, p.idempotency_key = "launching", at, key
            self.save_proposal(p, c)
            return p, None

    def settle(self, proposal_id: str, status: str, job_run_id: int | None = None) -> None:
        """Ledger status of the proposal's reservation: launched | uncertain | released."""
        with self.tx() as c:
            c.execute(
                "UPDATE ledger SET status=?, job_run_id=COALESCE(?, job_run_id) "
                "WHERE proposal_id=?",
                (status, job_run_id, proposal_id),
            )

    @staticmethod
    def counted_since(c: sqlite3.Connection, policy_id: str, since: str) -> int:
        return c.execute(
            f"SELECT COUNT(*) FROM ledger WHERE policy_id=? AND at>=? AND status IN {COUNTED}",
            (policy_id, since),
        ).fetchone()[0]

    @staticmethod
    def last_launch(c: sqlite3.Connection, policy_id: str) -> str | None:
        return c.execute(
            f"SELECT MAX(at) FROM ledger WHERE policy_id=? AND status IN {COUNTED}", (policy_id,)
        ).fetchone()[0]

    # ------------------------------------------------------------------ audit

    def log(
        self, at: str, actor: str, event: str, policy_id: str | None = None, **payload: Any
    ) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO audit (at, policy_id, actor, event, payload) VALUES (?,?,?,?,?)",
                (at, policy_id, actor, event, json.dumps(payload, default=str)),
            )

    def audit(self, policy_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        q, a = "SELECT id, at, policy_id, actor, event, payload FROM audit", ()
        if policy_id:
            q, a = q + " WHERE policy_id=?", (policy_id,)
        rows = self._rows(q + " ORDER BY id DESC LIMIT ?", (*a, limit))
        return [
            {
                "id": r[0],
                "at": r[1],
                "policy_id": r[2],
                "actor": r[3],
                "event": r[4],
                **json.loads(r[5]),
            }
            for r in rows
        ]
