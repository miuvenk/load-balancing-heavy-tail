"""
Dispatcher for the Load Balancing project.

The dispatcher consumes a workload from ``load_generator`` and, for each
request, picks a server according to the configured policy, sends the
request over HTTP (JSON) to that server's ``/process`` endpoint, and
records the per-request timing in a CSV file.

The selection itself is encapsulated in:

    dispatch(request, servers) -> Server

which is the exact signature requested by the project assignment.

Policies (selected via --policy):
    random        Baseline. Pick a server uniformly at random.
    round_robin   Cycle through servers in fixed order.
    jsq           Join Shortest Queue (pending count, dispatcher-side).
                  Also queries /queue when --use-server-query is set.
                  Random tie-break across equal-count servers.
    lwl           Least Work Left. Server minimising the sum of pending x.
                  Random tie-break across equal-pending_x servers.
    sita          Size-Interval Task Assignment. Partition x into 3 bands
                  by precomputed quantiles of the actual workload, one
                  server per band.

Output
------
Each run writes a CSV with one row per completed request:

    request_id, policy, lam, alpha, size_dist, x,
    arrival_time, dispatch_time, completion_time,
    response_time, wait_time, service_time,
    server_port, server_pid

Default path: data/<policy>_lam<lam>_alpha<alpha>.csv  (override with --out).
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import requests

# Make ``import config`` work whether you invoke this as
#   python -m src.dispatcher ...
# or directly
#   python src/dispatcher.py ...
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config  # noqa: E402
from src.load_generator import Request, generate_workload  # noqa: E402


# ---------------------------------------------------------------------------
# Server handle (dispatcher-side bookkeeping for one worker)
# ---------------------------------------------------------------------------

@dataclass
class Server:
    """Bookkeeping for one worker."""
    server_id: int
    host: str
    port: int

    lock: threading.Lock = field(default_factory=threading.Lock)
    pending: int = 0           # in-flight requests sent but not yet completed
    pending_x: float = 0.0     # sum of x over those requests

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def snapshot(self):
        with self.lock:
            return self.pending, self.pending_x

    def reserve(self, x: float) -> None:
        with self.lock:
            self.pending += 1
            self.pending_x += x

    def release(self, x: float) -> None:
        with self.lock:
            self.pending -= 1
            self.pending_x -= x


def build_servers(host: str = "127.0.0.1") -> List[Server]:
    return [Server(server_id=sid, host=host, port=port)
            for sid, port in sorted(config.SERVER_PORTS.items())]


def wait_for_servers(servers: List[Server], timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    for s in servers:
        while True:
            try:
                if requests.get(f"{s.url}/health", timeout=1.0).ok:
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                raise RuntimeError(f"Server on port {s.port} did not become ready")
            time.sleep(0.2)


# ---------------------------------------------------------------------------
# Policies. Each is a callable ``(request, servers) -> Server``.
# ---------------------------------------------------------------------------

class _RoundRobin:
    def __init__(self):
        self._next = 0
        self._lock = threading.Lock()

    def __call__(self, request, servers):
        with self._lock:
            srv = servers[self._next % len(servers)]
            self._next += 1
        return srv


def _policy_random(rng):
    def _dispatch(request, servers):
        return rng.choice(servers)
    return _dispatch


def _policy_jsq(use_server_query, rng=None):
    """Join Shortest Queue (pending count) with random tie-break.

    With deterministic tie-breaking (e.g. lowest port wins), low-load
    workloads send every request to the same server because the chosen
    server's pending count is back to zero before the next arrival. The
    random tie-break fixes that.
    """
    rng = rng if rng is not None else random.Random(config.INITIAL_SEED)
    def _dispatch(request, servers):
        if use_server_query:
            ann = []
            for s in servers:
                try:
                    q = requests.get(f"{s.url}/queue", timeout=0.5).json()
                    inflight = q["pending"] + (1 if q["in_service_age"] is not None else 0)
                except Exception:
                    inflight = s.snapshot()[0]
                ann.append((inflight, s))
        else:
            ann = [(s.snapshot()[0], s) for s in servers]
        min_count = min(a[0] for a in ann)
        candidates = [srv for c, srv in ann if c == min_count]
        return rng.choice(candidates)
    return _dispatch


def _policy_lwl(rng=None):
    """Least Work Left = min sum of pending x, random tie-break.

    SRPT-flavoured but the dispatcher only knows x, not the random Pareto
    multiplier inside the server. As a result LWL CAN make bad choices when
    a single small-x job hits an unlucky large multiplier — that's a real
    finding for the report.
    """
    rng = rng if rng is not None else random.Random(config.INITIAL_SEED + 1)
    def _dispatch(request, servers):
        snaps = [(s.snapshot(), s) for s in servers]
        min_w = min(snap[1] for snap, _ in snaps)
        candidates = [srv for (snap, srv) in snaps if snap[1] == min_w]
        if len(candidates) > 1:
            min_p = min(srv.snapshot()[0] for srv in candidates)
            candidates = [srv for srv in candidates if srv.snapshot()[0] == min_p]
        return rng.choice(candidates)
    return _dispatch


def _policy_sita(thresholds):
    """Size-Interval Task Assignment with precomputed quantile thresholds."""
    def _dispatch(request, servers):
        for i, t in enumerate(thresholds):
            if request.x <= t:
                return servers[i]
        return servers[-1]
    return _dispatch


def compute_sita_thresholds(workload, n_servers):
    """Equal-count quantile boundaries over the workload x values."""
    xs = sorted(r.x for r in workload)
    return [xs[min((i * len(xs)) // n_servers, len(xs) - 1)]
            for i in range(1, n_servers)]


def make_policy(name, workload, servers, *, use_server_query=False,
                seed=config.INITIAL_SEED):
    name = name.lower()
    if name == "random":
        return _policy_random(random.Random(seed))
    if name == "round_robin":
        return _RoundRobin()
    if name == "jsq":
        return _policy_jsq(use_server_query=use_server_query)
    if name == "lwl":
        return _policy_lwl()
    if name == "sita":
        thresholds = compute_sita_thresholds(workload, len(servers))
        print(f"[dispatcher] SITA thresholds (x): {thresholds}")
        return _policy_sita(thresholds)
    raise ValueError(f"Unknown policy: {name!r}")


# ---------------------------------------------------------------------------
# Per-request worker (HTTP POST + bookkeeping)
# ---------------------------------------------------------------------------

@dataclass
class RequestResult:
    request_id: int
    x: float
    arrival_time: float
    dispatch_time: float
    completion_time: float
    response_time: float
    wait_time: float
    service_time: float
    server_port: int
    server_pid: int


def _send_one(request, server, t0, session, results, results_lock, http_timeout,
              dispatch_time):
    # NB: server.reserve() must already have been called by the dispatcher
    # main thread before this worker starts (otherwise JSQ/LWL race).
    try:
        resp = session.post(
            f"{server.url}/process",
            json={"x": request.x, "request_id": request.request_id},
            timeout=http_timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        completion_time = time.time() - t0
        service_time = float(payload.get("service_time", 0.0))
        server_pid = int(payload.get("server_id", -1))
        rr = RequestResult(
            request_id=request.request_id,
            x=request.x,
            arrival_time=request.arrival_time,
            dispatch_time=dispatch_time,
            completion_time=completion_time,
            response_time=completion_time - request.arrival_time,
            wait_time=(completion_time - request.arrival_time) - service_time,
            service_time=service_time,
            server_port=server.port,
            server_pid=server_pid,
        )
        with results_lock:
            results.append(rr)
    except Exception as exc:
        print(f"[dispatcher] request {request.request_id} failed on port "
              f"{server.port}: {exc}", file=sys.stderr)
    finally:
        server.release(request.x)


# ---------------------------------------------------------------------------
# Experiment driver
# ---------------------------------------------------------------------------

def run_experiment(*, policy_name, lam, alpha, num_requests, size_dist,
                   x_min, x_max, alpha_x, x_mean, host, out_csv,
                   use_server_query, http_timeout, seed_offset):
    if alpha != config.ALPHA:
        print(f"[dispatcher] WARNING: --alpha={alpha} differs from "
              f"config.ALPHA={config.ALPHA}. Restart servers to apply.")

    workload = generate_workload(num_requests=num_requests, lam=lam,
                                 size_dist=size_dist, x_min=x_min, x_max=x_max,
                                 alpha_x=alpha_x, x_mean=x_mean,
                                 seed_offset=seed_offset)

    servers = build_servers(host=host)
    print(f"[dispatcher] waiting for {len(servers)} servers to be ready...")
    wait_for_servers(servers, timeout=30.0)
    print(f"[dispatcher] servers ready on ports {[s.port for s in servers]}")

    dispatch = make_policy(policy_name, workload, servers,
                           use_server_query=use_server_query)

    session = requests.Session()
    results = []
    results_lock = threading.Lock()
    threads = []

    print(f"[dispatcher] policy={policy_name}, lam={lam}, "
          f"n={num_requests}, size_dist={size_dist}")
    t0 = time.time()
    for r in workload:
        now = time.time() - t0
        if r.arrival_time > now:
            time.sleep(r.arrival_time - now)
        srv = dispatch(r, servers)
        # Reserve in the main thread so the NEXT dispatch sees the updated
        # counter. (If we did this inside the worker thread, JSQ/LWL would
        # race: the main loop dispatches several requests in a row before
        # any worker has incremented its server's counter.)
        srv.reserve(r.x)
        dispatch_time = time.time() - t0
        th = threading.Thread(target=_send_one,
                              args=(r, srv, t0, session, results, results_lock,
                                    http_timeout, dispatch_time),
                              daemon=True, name=f"req-{r.request_id}")
        th.start()
        threads.append(th)

    print(f"[dispatcher] all {num_requests} requests dispatched; "
          f"waiting for in-flight responses...")
    for th in threads:
        th.join()
    elapsed = time.time() - t0
    print(f"[dispatcher] done in {elapsed:.2f}s, {len(results)} results collected")

    results.sort(key=lambda r: r.request_id)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "request_id", "policy", "lam", "alpha", "size_dist", "x",
            "arrival_time", "dispatch_time", "completion_time",
            "response_time", "wait_time", "service_time",
            "server_port", "server_pid",
        ])
        for r in results:
            w.writerow([
                r.request_id, policy_name, lam, alpha, size_dist, f"{r.x:.6f}",
                f"{r.arrival_time:.6f}", f"{r.dispatch_time:.6f}",
                f"{r.completion_time:.6f}",
                f"{r.response_time:.6f}", f"{r.wait_time:.6f}",
                f"{r.service_time:.6f}",
                r.server_port, r.server_pid,
            ])
    print(f"[dispatcher] wrote {out_csv}")
    _print_summary(results, servers)


def _print_summary(results, servers):
    if not results:
        print("[dispatcher] no results to summarise")
        return
    rts = sorted(r.response_time for r in results)
    n = len(rts)

    def pct(p):
        return rts[min(int(p * n), n - 1)]

    print()
    print(f"  n              = {n}")
    print(f"  mean response  = {sum(rts) / n:.4f} s")
    print(f"  p50 response   = {pct(0.50):.4f} s")
    print(f"  p90 response   = {pct(0.90):.4f} s")
    print(f"  p99 response   = {pct(0.99):.4f} s")
    print(f"  max response   = {rts[-1]:.4f} s")
    print()
    print("  load per server (count, sum_x, sum_service_time):")
    by_port = {s.port: {"n": 0, "x": 0.0, "svc": 0.0} for s in servers}
    for r in results:
        b = by_port.setdefault(r.server_port, {"n": 0, "x": 0.0, "svc": 0.0})
        b["n"] += 1
        b["x"] += r.x
        b["svc"] += r.service_time
    for port in sorted(by_port):
        b = by_port[port]
        print(f"    port {port}: n={b['n']:5d}  sum_x={b['x']:10.2f}  "
              f"sum_service={b['svc']:10.2f}s")


def _parse_args():
    p = argparse.ArgumentParser(description="Dispatcher / experiment runner.")
    p.add_argument("--policy", default="random",
                   choices=["random", "round_robin", "jsq", "lwl", "sita"])
    p.add_argument("--lam", type=float, default=1.0)
    p.add_argument("--alpha", type=float, default=config.ALPHA)
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--size-dist", default="bounded_pareto",
                   choices=["bounded_pareto", "uniform", "exponential", "fixed"])
    p.add_argument("--x-min", type=float, default=1.0)
    p.add_argument("--x-max", type=float, default=50.0)
    p.add_argument("--alpha-x", type=float, default=1.5)
    p.add_argument("--x-mean", type=float, default=5.0)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--use-server-query", action="store_true")
    p.add_argument("--http-timeout", type=float, default=600.0)
    p.add_argument("--seed-offset", type=int, default=0)
    return p.parse_args()


def main():
    args = _parse_args()
    out = args.out
    if out is None:
        out = Path("data") / f"{args.policy}_lam{args.lam}_alpha{args.alpha}.csv"
    run_experiment(
        policy_name=args.policy, lam=args.lam, alpha=args.alpha,
        num_requests=args.n, size_dist=args.size_dist,
        x_min=args.x_min, x_max=args.x_max, alpha_x=args.alpha_x,
        x_mean=args.x_mean, host=args.host, out_csv=out,
        use_server_query=args.use_server_query,
        http_timeout=args.http_timeout, seed_offset=args.seed_offset,
    )


if __name__ == "__main__":
    main()
