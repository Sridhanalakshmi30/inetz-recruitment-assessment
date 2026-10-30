import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as system


def test_questions_rotate_across_candidates_and_history():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    system.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        first = system.Candidate(full_name="First", email="first@example.com", role="Python Full Stack")
        second = system.Candidate(full_name="Second", email="second@example.com", role="Python Full Stack")
        db.add_all([first, second])
        db.flush()
        for round_name in ("aptitude", "technical"):
            first_set = system.fresh_snapshot(db, first, round_name)
            db.add(system.Attempt(candidate_id=first.id, round=round_name, snapshot=json.dumps(first_set)))
            db.flush()
            second_set = system.fresh_snapshot(db, second, round_name)
            assert {q["question"] for q in first_set}.isdisjoint(q["question"] for q in second_set)
            db.add(system.Attempt(candidate_id=second.id, round=round_name, snapshot=json.dumps(second_set)))
            db.flush()
            old = db.scalar(select(system.Attempt).where(system.Attempt.candidate_id == first.id,
                                                         system.Attempt.round == round_name))
            db.add(system.AssessmentHistory(candidate_id=first.id, round=round_name, score=0,
                                            submitted_at=system.now(), details=json.dumps({"snapshot": old.snapshot})))
            db.delete(old)
            db.flush()
            next_set = system.fresh_snapshot(db, first, round_name)
            assert {q["question"] for q in first_set}.isdisjoint(q["question"] for q in next_set)
            db.add(system.AssessmentHistory(candidate_id=first.id, round=round_name, score=0,
                                            submitted_at=system.now(), details=json.dumps({"snapshot": json.dumps(next_set)})))
            db.flush()
            third_set = system.fresh_snapshot(db, first, round_name)
            assert {q["question"] for q in first_set + next_set}.isdisjoint(q["question"] for q in third_set)
        db.rollback()
    engine.dispose()


def test_exhausted_pool_does_not_repeat_questions():
    first_set = system.mcq_snapshot("technical", "Unknown role")
    with pytest.raises(ValueError, match="Not enough unused questions"):
        system.mcq_snapshot("technical", "Unknown role", {q["question"] for q in first_set})
    with pytest.raises(ValueError, match="Not enough unused questions"):
        system.mcq_snapshot("technical", "Unknown role", set(), {q["question"] for q in first_set})


@pytest.mark.parametrize("same_candidate", [False, True])
def test_simultaneous_candidates_get_distinct_questions(monkeypatch, same_candidate, request):
    questions = [{"question": f"Shared question {number}", "options": ["A", "B", "C", "D"], "answer": 0}
                 for number in range(40)]
    def deterministic_snapshot(round_name, role, candidate_seen, global_seen):
        available = [item for item in questions if item["question"] not in global_seen]
        sleep(0.05)
        return available[:20]
    monkeypatch.setattr(system, "mcq_snapshot", deterministic_snapshot)
    path = Path(f"question_rotation_test_{uuid4().hex}.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 10})
    request.addfinalizer(lambda: (engine.dispose(), path.unlink(missing_ok=True)))
    system.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    system.app.state.config = {"pass_marks": {"aptitude": 8, "technical": 8}, "violation_limit": 3}
    with factory() as db:
        db.add(system.QuestionPoolLock(id=1))
        db.add_all([system.Candidate(full_name=name, email=f"{name}@example.com", role="Python Full Stack", stage="Technical MCQ")
                    for name in ("first", "second")])
        db.commit()

    barrier = Barrier(2)
    def allocate(name):
        with factory() as db:
            candidate = db.scalar(select(system.Candidate).where(system.Candidate.full_name == name))
            barrier.wait()
            attempt = system.ensure_attempt(db, candidate, "technical")
            return attempt.id, {item["question"] for item in json.loads(attempt.snapshot)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(allocate, "first")
        second = pool.submit(allocate, "first" if same_candidate else "second")
        first_id, first_questions = first.result()
        second_id, second_questions = second.result()
        if same_candidate:
            assert first_id == second_id
            assert first_questions == second_questions
        else:
            assert first_questions.isdisjoint(second_questions)
