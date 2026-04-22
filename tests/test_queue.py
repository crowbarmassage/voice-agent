"""Queue state-transition tests.

Validates that work item status transitions follow the allowed state machine
and that invalid transitions are rejected.

Valid transitions:
    pending       → in_progress
    in_progress   → completed | failed | retry_scheduled
    retry_scheduled → in_progress | human_required
    failed        → retry_scheduled | human_required
"""
import pytest

from voice_agent.db.repository import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    QueueRepository,
)
from voice_agent.db.tables import Base, WorkItemRow

# Use SQLite in-memory for unit tests (no Postgres needed)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def repo(db_session):
    return QueueRepository(db_session)


def _make_item(db_session: Session, status: str = "pending", **kwargs) -> WorkItemRow:
    defaults = {
        "id": "wi_001",
        "use_case": "claim_status",
        "payor": "UHC",
        "phone_number": "+18005551234",
        "context": {},
        "status": status,
    }
    defaults.update(kwargs)
    item = WorkItemRow(**defaults)
    db_session.add(item)
    db_session.commit()
    return item


class TestValidTransitions:
    """Verify the transition table is complete and correct."""

    def test_pending_can_go_to_in_progress(self):
        assert "in_progress" in VALID_TRANSITIONS["pending"]

    def test_pending_cannot_go_to_completed(self):
        assert "completed" not in VALID_TRANSITIONS["pending"]

    def test_in_progress_can_go_to_completed(self):
        assert "completed" in VALID_TRANSITIONS["in_progress"]

    def test_in_progress_can_go_to_failed(self):
        assert "failed" in VALID_TRANSITIONS["in_progress"]

    def test_in_progress_cannot_go_to_pending(self):
        assert "pending" not in VALID_TRANSITIONS["in_progress"]

    def test_retry_scheduled_can_go_to_in_progress(self):
        assert "in_progress" in VALID_TRANSITIONS["retry_scheduled"]

    def test_failed_can_go_to_retry_scheduled(self):
        assert "retry_scheduled" in VALID_TRANSITIONS["failed"]

    def test_completed_has_no_transitions(self):
        assert "completed" not in VALID_TRANSITIONS

    def test_human_required_has_no_transitions(self):
        assert "human_required" not in VALID_TRANSITIONS


class TestQueueRepository:
    """Integration tests for the queue repository."""

    def test_pull_next_transitions_to_in_progress(self, db_session, repo):
        _make_item(db_session, status="pending")
        item = repo.pull_next()
        assert item is not None
        assert item.status == "in_progress"

    def test_pull_next_empty_queue_returns_none(self, db_session, repo):
        assert repo.pull_next() is None

    def test_pull_next_skips_in_progress(self, db_session, repo):
        _make_item(db_session, status="in_progress")
        assert repo.pull_next() is None

    def test_complete_from_in_progress(self, db_session, repo):
        _make_item(db_session, status="in_progress")
        repo.complete("wi_001")
        item = db_session.get(WorkItemRow, "wi_001")
        assert item.status == "completed"

    def test_complete_from_pending_raises(self, db_session, repo):
        _make_item(db_session, status="pending")
        with pytest.raises(InvalidTransitionError):
            repo.complete("wi_001")

    def test_fail_auto_schedules_retry(self, db_session, repo):
        _make_item(db_session, status="in_progress", max_retries=3)
        repo.fail("wi_001")
        item = db_session.get(WorkItemRow, "wi_001")
        assert item.status == "retry_scheduled"
        assert item.retry_count == 1
        assert item.next_retry_at is not None

    def test_fail_exhausted_retries_goes_to_human(self, db_session, repo):
        _make_item(db_session, status="in_progress", retry_count=3, max_retries=3)
        repo.fail("wi_001")
        item = db_session.get(WorkItemRow, "wi_001")
        assert item.status == "human_required"

    def test_invalid_transition_raises_with_details(self, db_session, repo):
        _make_item(db_session, status="pending")
        with pytest.raises(InvalidTransitionError) as exc_info:
            repo.complete("wi_001")
        assert exc_info.value.from_status == "pending"
        assert exc_info.value.to_status == "completed"

    def test_pull_by_use_case(self, db_session, repo):
        _make_item(db_session, id="wi_001", use_case="claim_status", status="pending")
        _make_item(db_session, id="wi_002", use_case="eligibility", status="pending")
        item = repo.pull_next(use_case="eligibility")
        assert item is not None
        assert item.id == "wi_002"
