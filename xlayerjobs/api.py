import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import db as _db
from .config import DB_PATH


# ── Request models ────────────────────────────────────────────────────────────

class CreateJobRequest(BaseModel):
    poster: str
    title: str
    description: str
    reward_usdt: float
    deadline_hours: int
    required_skills: str = ""


class BidRequest(BaseModel):
    bidder: str
    message: str = ""
    delivery_time_hours: int


class AcceptBidRequest(BaseModel):
    bid_id: int
    poster: str


class DeliverRequest(BaseModel):
    proof_hash: str


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(db_path: Path = DB_PATH) -> FastAPI:
    app = FastAPI(title="X Layer Jobs", version="0.1.0")
    _db.initialize(db_path)

    # ── Jobs ──────────────────────────────────────────────────────────────────

    @app.post("/jobs", status_code=200)
    def create_job(req: CreateJobRequest):
        now = int(time.time())
        deadline = now + req.deadline_hours * 3600
        job_id = _db.insert_job(
            db_path,
            {
                "poster": req.poster,
                "title": req.title,
                "description": req.description,
                "reward_usdt": req.reward_usdt,
                "deadline": deadline,
                "required_skills": req.required_skills,
                "state": "open",
                "created_at": now,
            },
        )
        return _db.get_job(db_path, job_id)

    @app.get("/jobs")
    def list_jobs(state: Optional[str] = None):
        return _db.get_all_jobs(db_path, state=state)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: int):
        job = _db.get_job(db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        bids = _db.get_bids_for_job(db_path, job_id)
        return {**job, "bids": bids}

    @app.post("/jobs/{job_id}/bid")
    def bid_on_job(job_id: int, req: BidRequest):
        job = _db.get_job(db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["state"] != "open":
            raise HTTPException(status_code=400, detail=f"Job is not open (state={job['state']})")
        bid_id = _db.insert_bid(
            db_path,
            {
                "job_id": job_id,
                "bidder": req.bidder,
                "message": req.message,
                "delivery_time_hours": req.delivery_time_hours,
                "created_at": int(time.time()),
            },
        )
        return {"bid_id": bid_id, "job_id": job_id}

    @app.post("/jobs/{job_id}/accept")
    def accept_bid(job_id: int, req: AcceptBidRequest):
        job = _db.get_job(db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["state"] != "open":
            raise HTTPException(status_code=400, detail=f"Job is not open (state={job['state']})")
        if job["poster"] != req.poster:
            raise HTTPException(status_code=403, detail="Only the job poster can accept a bid")
        bids = _db.get_bids_for_job(db_path, job_id)
        bid = next((b for b in bids if b["id"] == req.bid_id), None)
        if not bid:
            raise HTTPException(status_code=404, detail="Bid not found")
        _db.update_job(db_path, job_id, {"state": "assigned", "assigned_to": bid["bidder"]})
        return _db.get_job(db_path, job_id)

    @app.post("/jobs/{job_id}/deliver")
    def deliver_work(job_id: int, req: DeliverRequest):
        job = _db.get_job(db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["state"] != "assigned":
            raise HTTPException(status_code=400, detail=f"Job is not assigned (state={job['state']})")
        _db.update_job(db_path, job_id, {"state": "delivered"})
        return {**_db.get_job(db_path, job_id), "proof_hash": req.proof_hash}

    @app.post("/jobs/{job_id}/complete")
    def complete_job(job_id: int):
        job = _db.get_job(db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["state"] != "delivered":
            raise HTTPException(status_code=400, detail=f"Job is not delivered (state={job['state']})")
        _db.update_job(db_path, job_id, {"state": "completed"})

        # Update reputation for assignee (earned) and poster (spent)
        assignee = job["assigned_to"]
        poster = job["poster"]
        reward = job["reward_usdt"]

        if assignee:
            rep = _db.get_reputation(db_path, assignee) or {
                "address": assignee,
                "jobs_completed": 0,
                "jobs_failed": 0,
                "jobs_disputed": 0,
                "avg_delivery_hours": 0.0,
                "total_earned_usd": 0.0,
                "total_spent_usd": 0.0,
            }
            _db.upsert_reputation(
                db_path,
                {
                    **rep,
                    "jobs_completed": rep["jobs_completed"] + 1,
                    "total_earned_usd": rep["total_earned_usd"] + reward,
                },
            )

        poster_rep = _db.get_reputation(db_path, poster) or {
            "address": poster,
            "jobs_completed": 0,
            "jobs_failed": 0,
            "jobs_disputed": 0,
            "avg_delivery_hours": 0.0,
            "total_earned_usd": 0.0,
            "total_spent_usd": 0.0,
        }
        _db.upsert_reputation(
            db_path,
            {
                **poster_rep,
                "total_spent_usd": poster_rep["total_spent_usd"] + reward,
            },
        )

        return _db.get_job(db_path, job_id)

    # ── Reputation ────────────────────────────────────────────────────────────

    @app.get("/reputation/{address}")
    def get_reputation(address: str):
        rep = _db.get_reputation(db_path, address)
        if not rep:
            raise HTTPException(status_code=404, detail="No reputation record found")
        return rep

    @app.get("/leaderboard")
    def leaderboard():
        return _db.get_leaderboard(db_path, limit=10)

    # ── Service Discovery (Moltbook-sourced, Supabase-backed) ────────────

    @app.get("/services")
    def search_services(
        q: str | None = None,
        type: str | None = None,
        max_price: float | None = None,
        sort: str = "price",
        limit: int = 20,
    ):
        """Search the service directory. Sourced from Moltbook, structured by AI."""
        from .discovery import search_services as _search
        return _search(query=q, service_type=type, max_price=max_price, sort_by=sort, limit=limit)

    @app.get("/services/types")
    def service_types():
        """Get available service types with counts and price ranges."""
        from .discovery import get_service_types
        return get_service_types()

    return app
