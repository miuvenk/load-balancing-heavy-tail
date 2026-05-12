"""
Flask-based worker server for the Load Balancing project.

Each instance of this module is launched as an independent OS process by
main.py and pinned to a dedicated CPU core (on Linux/Windows). It exposes a
small JSON HTTP API used by the dispatcher.

Endpoints:
    POST /process  -- submit a job  {"x": <float>, "request_id": <optional>}
                      Blocks until the job has finished. Returns the result.
    GET  /queue    -- introspection used by the dispatcher (JSQ, LAS).
                      Returns {"pending": <int>, "in_service_age": <float or null>,
                              "in_service_x": <float or null>}.
    GET  /health   -- readiness probe used by the dispatcher to wait for boot.

NOTE FOR ESMA (refactor, May 2026):
    The previous version of process_request() had a `return` statement
    indented inside the for-loop, which made the loop exit on the first
    iteration. That meant no real CPU work was performed regardless of x or
    the Pareto multiplier. This file now:
      * fixes that bug,
      * realigns process_request() with the exact reference code in the
        assignment PDF (n = base_work * x * multiplier, base_work=20_000),
      * runs the CPU work on a single background worker thread so the HTTP
        server can still answer /queue while a job is in service. The single
        worker preserves the FIFO single-server semantics required by the
        queueing-theory framing of the project.
    See CHANGES.md at the repo root for a fuller description.
"""

from flask import Flask, request, jsonify
import math
import random
import os
import sys
import threading
import queue
import time

import config


app = Flask(__name__)

# ---------------------------------------------------------------------------
# Reference computation (matches the assignment PDF exactly)
# ---------------------------------------------------------------------------

def process_request(x, alpha=config.ALPHA, base_work=20_000):
    """
    Reference CPU-bound task with heavy-tailed processing time.

    Faithful reproduction of the snippet in project2026.pdf (section 3):
        multiplier = random.paretovariate(alpha)
        n = int(base_work * x * multiplier)
        acc = sum_{i=0..n-1} sin(i)*cos(i)

    x:          request size / difficulty (passed in from the dispatcher)
    alpha:      shape parameter of the Pareto multiplier (smaller -> heavier tail)
    base_work:  scaling factor; with base_work=20_000 a typical request finishes
                in tens to hundreds of milliseconds on a modern core.
    """
    multiplier = random.paretovariate(alpha)
    n = int(base_work * x * multiplier)

    acc = 0.0
    for i in range(n):
        acc += math.sin(i) * math.cos(i)
    return acc


# ---------------------------------------------------------------------------
# Single background worker + introspectable queue
# ---------------------------------------------------------------------------
# We deliberately use ONE worker thread per server process so each server
# behaves as a single-server FIFO queue (M/G/1-style in the queueing model).
# Flask itself runs with threaded=True so that /queue can be answered while
# the worker is busy with a long job.

_job_queue: "queue.Queue[dict]" = queue.Queue()
_state_lock = threading.Lock()
_current_job: dict | None = None  # job currently being executed by the worker


def _worker_loop():
    """Pull jobs from the FIFO queue and execute them one at a time."""
    global _current_job
    while True:
        job = _job_queue.get()
        with _state_lock:
            job["started_at"] = time.time()
            _current_job = job
        try:
            job["result"] = process_request(job["x"], config.ALPHA)
            job["status"] = "completed"
        except Exception as exc:  # don't let a bad job kill the worker
            job["result"] = None
            job["status"] = f"error: {exc}"
        finally:
            job["finished_at"] = time.time()
            with _state_lock:
                _current_job = None
            job["done_event"].set()
            _job_queue.task_done()


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.route("/process", methods=["POST"])
def handle_process():
    """
    Submit a job and wait synchronously for its completion.

    Expected JSON body: {"x": <float>, "request_id": <optional string>}
    Returns:
        {"status": "completed",
         "server_id": <pid>,
         "request_id": <echoed>,
         "result": <float>,
         "service_time": <seconds the worker spent on this job>}
    """
    data = request.get_json(force=True, silent=True) or {}
    x = float(data.get("x", 1.0))
    request_id = data.get("request_id")

    job = {
        "x": x,
        "request_id": request_id,
        "enqueued_at": time.time(),
        "done_event": threading.Event(),
    }
    _job_queue.put(job)

    # Block until the worker has processed this job.
    job["done_event"].wait()

    return jsonify({
        "status": job["status"],
        "server_id": os.getpid(),
        "request_id": request_id,
        "result": job["result"],
        "service_time": job["finished_at"] - job["started_at"],
    })


@app.route("/queue", methods=["GET"])
def handle_queue():
    """
    Introspection endpoint used by the dispatcher.

    Returns:
        pending:         number of jobs waiting in the FIFO queue
                         (does NOT include the one currently in service)
        in_service_age:  seconds the currently-running job has been running,
                         or null if the worker is idle
        in_service_x:    x value of the currently-running job, or null if idle
    """
    with _state_lock:
        cj = _current_job
        in_service_age = (time.time() - cj["started_at"]) if cj else None
        in_service_x = cj["x"] if cj else None
    return jsonify({
        "pending": _job_queue.qsize(),
        "in_service_age": in_service_age,
        "in_service_x": in_service_x,
        "server_id": os.getpid(),
    })


@app.route("/health", methods=["GET"])
def handle_health():
    return jsonify({"status": "ok", "server_id": os.getpid()})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5001

    # Per-server deterministic randomness for the Pareto multiplier.
    random.seed(config.INITIAL_SEED + port)

    # Start the single background worker.
    worker = threading.Thread(target=_worker_loop, daemon=True, name=f"worker-{port}")
    worker.start()

    # threaded=True so /queue can be served while the worker is busy.
    # use_reloader=False so the process count stays at 1 (important for CPU pinning).
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
