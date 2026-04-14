import time
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from ..api import create_app
from .. import db as _db
from ..config import DB_PATH

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_dashboard_app(db_path: Path = DB_PATH):
    app = create_app(db_path=db_path)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR), auto_reload=True)
    # cache_size=0 for Python 3.14 compatibility
    templates.env.cache = {}
    templates.env.auto_reload = True

    @app.get("/")
    def dashboard(request: Request):
        all_jobs = _db.get_all_jobs(db_path)
        open_jobs = [j for j in all_jobs if j["state"] == "open"]
        assigned_jobs = [j for j in all_jobs if j["state"] == "assigned"]
        delivered_jobs = [j for j in all_jobs if j["state"] == "delivered"]
        completed_jobs = [j for j in all_jobs if j["state"] == "completed"]
        expired_jobs = [j for j in all_jobs if j["state"] == "expired"]

        # Attach bid counts
        for job in all_jobs:
            job["bid_count"] = len(_db.get_bids_for_job(db_path, job["id"]))

        leaderboard = _db.get_leaderboard(db_path, limit=10)

        stats = {
            "total": len(all_jobs),
            "open": len(open_jobs),
            "assigned": len(assigned_jobs),
            "delivered": len(delivered_jobs),
            "completed": len(completed_jobs),
            "expired": len(expired_jobs),
        }

        now = int(time.time())

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "stats": stats,
                "open_jobs": open_jobs,
                "assigned_jobs": assigned_jobs,
                "delivered_jobs": delivered_jobs,
                "completed_jobs": completed_jobs,
                "leaderboard": leaderboard,
                "now": now,
            },
        )

    return app


# Allow running directly: python -m xlayerjobs.dashboard.app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_dashboard_app(), host="0.0.0.0", port=8000, reload=False)
