import pytest
from fastapi.testclient import TestClient
from xlayerjobs.api import create_app


@pytest.fixture
def client(tmp_db_path):
    app = create_app(db_path=tmp_db_path)
    return TestClient(app)


def test_create_job(client):
    resp = client.post("/jobs", json={
        "poster": "0xPoster",
        "title": "Build a DeFi bot",
        "description": "Need a yield farming bot",
        "reward_usdt": 250.0,
        "deadline_hours": 72,
        "required_skills": "python,web3",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["id"] == 1
    assert data["title"] == "Build a DeFi bot"
    assert data["state"] == "open"
    assert data["reward_usdt"] == 250.0


def test_list_jobs(client):
    # Create two jobs
    for i in range(2):
        client.post("/jobs", json={
            "poster": f"0xPoster{i}",
            "title": f"Job {i}",
            "description": "Description",
            "reward_usdt": 100.0,
            "deadline_hours": 24,
        })
    resp = client.get("/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 2


def test_bid_on_job(client):
    # Create a job
    job = client.post("/jobs", json={
        "poster": "0xPoster",
        "title": "Analytics job",
        "description": "Analyse on-chain data",
        "reward_usdt": 50.0,
        "deadline_hours": 48,
    }).json()
    job_id = job["id"]

    resp = client.post(f"/jobs/{job_id}/bid", json={
        "bidder": "0xAgent",
        "message": "I'll do it in 24h",
        "delivery_time_hours": 24,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["bid_id"] == 1
    assert data["job_id"] == job_id


def test_accept_bid(client):
    job = client.post("/jobs", json={
        "poster": "0xPoster",
        "title": "Smart contract audit",
        "description": "Audit the escrow contract",
        "reward_usdt": 500.0,
        "deadline_hours": 120,
        "required_skills": "solidity",
    }).json()
    job_id = job["id"]

    bid = client.post(f"/jobs/{job_id}/bid", json={
        "bidder": "0xAuditor",
        "message": "Expert auditor here",
        "delivery_time_hours": 48,
    }).json()
    bid_id = bid["bid_id"]

    resp = client.post(f"/jobs/{job_id}/accept", json={
        "bid_id": bid_id,
        "poster": "0xPoster",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "assigned"
    assert data["assigned_to"] == "0xAuditor"


def test_full_flow(client):
    # 1. Create job
    job = client.post("/jobs", json={
        "poster": "0xClient",
        "title": "Full stack dApp",
        "description": "Build a full stack dApp on X Layer",
        "reward_usdt": 1000.0,
        "deadline_hours": 168,
        "required_skills": "react,solidity,python",
    }).json()
    job_id = job["id"]
    assert job["state"] == "open"

    # 2. Bid
    bid = client.post(f"/jobs/{job_id}/bid", json={
        "bidder": "0xDev",
        "message": "I specialise in dApps",
        "delivery_time_hours": 120,
    }).json()
    bid_id = bid["bid_id"]

    # 3. Accept bid
    accepted = client.post(f"/jobs/{job_id}/accept", json={
        "bid_id": bid_id,
        "poster": "0xClient",
    }).json()
    assert accepted["state"] == "assigned"
    assert accepted["assigned_to"] == "0xDev"

    # 4. Deliver
    delivered = client.post(f"/jobs/{job_id}/deliver", json={
        "proof_hash": "0xdeadbeef1234567890",
    }).json()
    assert delivered["state"] == "delivered"
    assert delivered["proof_hash"] == "0xdeadbeef1234567890"

    # 5. Complete
    completed = client.post(f"/jobs/{job_id}/complete").json()
    assert completed["state"] == "completed"

    # 6. Verify reputation updated
    rep = client.get("/reputation/0xDev").json()
    assert rep["jobs_completed"] == 1
    assert rep["total_earned_usd"] == 1000.0

    poster_rep = client.get("/reputation/0xClient").json()
    assert poster_rep["total_spent_usd"] == 1000.0

    # 7. Check leaderboard
    lb = client.get("/leaderboard").json()
    assert len(lb) >= 1
    assert lb[0]["address"] == "0xDev"
