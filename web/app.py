import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / "output" / "web_jobs"
PIPELINE_SCRIPT = BASE_DIR / "run_pipeline.py"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(16))
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    

    store = MongoStore()
    app.config["MONGO_STORE"] = store

    def mongo_ready() -> bool:
        return store.db is not None

    def users_col():
        if store.db is None:
            raise RuntimeError("MongoDB is not configured. Add MONGODB_URI to .env first.")
        return store.db["users"]

    def jobs_col():
        if store.db is None:
            raise RuntimeError("MongoDB is not configured. Add MONGODB_URI to .env first.")
        return store.db["web_jobs"]

    def analysis_sessions_col():
        if store.db is None:
            raise RuntimeError("MongoDB is not configured. Add MONGODB_URI to .env first.")
        return store.db["analysis_sessions"]

    def current_user() -> Optional[dict]:
        user_id = session.get("user_id")
        if not user_id or not mongo_ready():
            return None
        return users_col().find_one({"user_id": user_id})
    def login_required():
        if "user_id" not in session:
            return redirect(url_for("login"))
        return None

    def mongo_or_config_page():
        if mongo_ready():
            return None
        return render_template("config_error.html")

    def get_job_or_404(job_id: str) -> dict:
        doc = jobs_col().find_one({"job_id": job_id})
        if not doc:
            abort(404)
        if doc.get("user_id") != session.get("user_id"):
            abort(403)
        return infer_job_status(doc)
    
    def infer_job_status(job: dict) -> dict:
        run_id = str(job.get("run_id", ""))
        run_root = BASE_DIR / "output" / "agent_runs" / run_id
        combined_path = run_root / "combined_per_stock_reports.txt"
        manifest_path = run_root / "run_manifest.json"
        current_status = str(job.get("status", "unknown"))

        analysis_doc = analysis_sessions_col().find_one({"session_key": run_id}) if mongo_ready() else None
        inferred_status = current_status

        if analysis_doc and str(analysis_doc.get("status", "")) == "completed":
            inferred_status = "completed"
        elif combined_path.exists() and manifest_path.exists():
            inferred_status = "completed"
        elif current_status == "running" and not process_is_running(job.get("pid")):
            inferred_status = "completed" if combined_path.exists() else "error"

        if inferred_status != current_status:
            updates = {
                "status": inferred_status,
                "updated_at": datetime.utcnow().isoformat(),
            }
            if manifest_path.exists():
                updates["manifest_path"] = str(manifest_path)
            if combined_path.exists():
                updates["combined_reports_path"] = str(combined_path)
            if analysis_doc:
                updates["analysis_session_id"] = str(analysis_doc.get("_id"))
            jobs_col().update_one({"job_id": job["job_id"]}, {"$set": updates})
            refreshed = jobs_col().find_one({"job_id": job["job_id"]})
            if refreshed:
                return refreshed
            return {**job, **updates}

        return job

    def read_text_file(path_str: str) -> str:
        if not path_str:
            return ""
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def rel_to_base(path_str: str) -> str:
        if not path_str:
            return ""
        try:
            return str(Path(path_str).resolve().relative_to(BASE_DIR.resolve()))
        except Exception:
            return ""

    def process_is_running(pid: Optional[int]) -> bool:
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    def wait_for_job(job_id: str, proc: subprocess.Popen, run_id: str) -> None:
        # Here I block until the subprocess finishes and capture its exit code
        returncode = proc.wait()
        
        status = "completed" if returncode == 0 else "error" # Map exit code to a human-readable status string
        jobs_col().update_one(
            {"job_id": job_id},
            {   # Persist the final status, return code, and finish timestamp in the DB
                "$set": {
                    "status": status,
                    "return_code": int(returncode),
                    "finished_at": datetime.utcnow().isoformat(),
                }
            },
        )

        # Look up the analysis session created by the pipeline using the run_id as key:
        analysis_doc = analysis_sessions_col().find_one({"session_key": run_id})
        if analysis_doc:
            jobs_col().update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "analysis_session_id": str(analysis_doc.get("_id")),
                    }
                },
            )
    @app.route("/")
    def index():
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))
    return app


    