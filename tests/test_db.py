import time
import pytest
from xlayerjobs import db


def make_job(overrides=None):
    base = {
        "poster": "0xPoster",
        "title": "Test Job",
        "description": "Do something useful",
        "reward_usdt": 100.0,
        "deadline": int(time.time()) + 86400,
        "required_skills": "python,solidity",
        "state": "open",
        "created_at": int(time.time()),
    }
    if overrides:
        base.update(overrides)
    return base


def test_create_and_get_job(tmp_db_path):
    db.initialize(tmp_db_path)
    job_id = db.insert_job(tmp_db_path, make_job())
    assert job_id == 1
    job = db.get_job(tmp_db_path, job_id)
    assert job is not None
    assert job["title"] == "Test Job"
    assert job["poster"] == "0xPoster"
    assert job["state"] == "open"
    assert job["reward_usdt"] == 100.0


def test_list_jobs_filter_by_state(tmp_db_path):
    db.initialize(tmp_db_path)
    db.insert_job(tmp_db_path, make_job({"state": "open"}))
    db.insert_job(tmp_db_path, make_job({"state": "open"}))
    db.insert_job(tmp_db_path, make_job({"state": "completed"}))

    all_jobs = db.get_all_jobs(tmp_db_path)
    assert len(all_jobs) == 3

    open_jobs = db.get_all_jobs(tmp_db_path, state="open")
    assert len(open_jobs) == 2

    completed = db.get_all_jobs(tmp_db_path, state="completed")
    assert len(completed) == 1


def test_insert_and_get_bids(tmp_db_path):
    db.initialize(tmp_db_path)
    job_id = db.insert_job(tmp_db_path, make_job())

    bid1 = db.insert_bid(
        tmp_db_path,
        {
            "job_id": job_id,
            "bidder": "0xAgent1",
            "message": "I can do this!",
            "delivery_time_hours": 24,
            "created_at": int(time.time()),
        },
    )
    bid2 = db.insert_bid(
        tmp_db_path,
        {
            "job_id": job_id,
            "bidder": "0xAgent2",
            "message": "Pick me",
            "delivery_time_hours": 48,
            "created_at": int(time.time()),
        },
    )

    bids = db.get_bids_for_job(tmp_db_path, job_id)
    assert len(bids) == 2
    assert bids[0]["bidder"] == "0xAgent1"
    assert bids[1]["delivery_time_hours"] == 48


def test_reputation_upsert(tmp_db_path):
    db.initialize(tmp_db_path)
    addr = "0xSomeAgent"

    # Insert
    db.upsert_reputation(
        tmp_db_path,
        {
            "address": addr,
            "jobs_completed": 5,
            "jobs_failed": 1,
            "jobs_disputed": 0,
            "avg_delivery_hours": 12.5,
            "total_earned_usd": 500.0,
            "total_spent_usd": 0.0,
        },
    )
    rep = db.get_reputation(tmp_db_path, addr)
    assert rep is not None
    assert rep["jobs_completed"] == 5
    assert rep["total_earned_usd"] == 500.0

    # Update
    db.upsert_reputation(
        tmp_db_path,
        {
            "address": addr,
            "jobs_completed": 6,
            "total_earned_usd": 600.0,
        },
    )
    rep = db.get_reputation(tmp_db_path, addr)
    assert rep["jobs_completed"] == 6
    assert rep["total_earned_usd"] == 600.0
