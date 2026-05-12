"""
Workload generator for the Load Balancing project.

Open-loop benchmark tool: produces a deterministic stream of incoming
requests defined by (arrival_time, request_id, x). The dispatcher consumes
the stream, sleeping between arrivals, so the offered load is independent
of the system's response time.

Arrival process
---------------
Poisson process with rate ``lam`` (requests / second). Inter-arrival times
are i.i.d. Exponential(lam).

Request size distribution
-------------------------
The parameter ``x`` is the request's intrinsic size / difficulty (see the
project assignment). The actual CPU work on the server is then
    work = base_work * x * Pareto(alpha)
so heavy-tailed behaviour in observed service times comes both from
heavy-tailed ``x`` (if chosen) and from the Pareto multiplier inside the
server. We make ``x`` itself configurable so the dispatcher's size-aware
policies (LWL, SITA) have non-trivial information to use.

Supported distributions for ``x`` (selected via ``size_dist``):
  * "bounded_pareto"  -- bounded Pareto with shape alpha_x in (x_min, x_max).
                          Default; produces heavy-tailed sizes.
  * "uniform"         -- Uniform(x_min, x_max). Mild variation, useful as
                          an ablation that isolates the in-server Pareto.
  * "exponential"     -- Exponential with mean ``x_mean``. Light-tailed.
  * "fixed"           -- Constant x = x_min. Strips ``x`` of all
                          information; useful as a sanity-check ablation.

Reproducibility
---------------
Each call to ``generate_workload`` uses its own ``random.Random`` instance
seeded from ``config.INITIAL_SEED`` plus an optional offset, so two team
members running with the same parameters see the exact same workload.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterator, List

import config


@dataclass(frozen=True)
class Request:
    """A single incoming job, materialised by the generator."""
    arrival_time: float       # seconds since the start of the workload
    request_id: int
    x: float                  # job's intrinsic size / difficulty


# ---------------------------------------------------------------------------
# Sampler for x
# ---------------------------------------------------------------------------

def _sample_x(rng: random.Random,
              size_dist: str,
              x_min: float,
              x_max: float,
              alpha_x: float,
              x_mean: float) -> float:
    """Draw one request size according to the configured distribution."""
    if size_dist == "fixed":
        return x_min

    if size_dist == "uniform":
        return rng.uniform(x_min, x_max)

    if size_dist == "exponential":
        # Lower-bounded so x > 0 strictly.
        return max(rng.expovariate(1.0 / x_mean), 1e-9)

    if size_dist == "bounded_pareto":
        # Inverse-CDF sampling for the bounded Pareto on [x_min, x_max]:
        #   F(x) = (1 - (x_min/x)^alpha) / (1 - (x_min/x_max)^alpha)
        # => x = x_min * (1 - u*(1 - (x_min/x_max)^alpha)) ^ (-1/alpha)
        u = rng.random()
        ratio = (x_min / x_max) ** alpha_x
        return x_min * (1.0 - u * (1.0 - ratio)) ** (-1.0 / alpha_x)

    raise ValueError(f"Unknown size_dist: {size_dist!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_workload(
    num_requests: int,
    lam: float,
    *,
    size_dist: str = "bounded_pareto",
    x_min: float = 1.0,
    x_max: float = 50.0,
    alpha_x: float = 1.5,
    x_mean: float = 5.0,
    seed_offset: int = 0,
) -> List[Request]:
    """
    Materialise ``num_requests`` requests as a list of ``Request`` objects.

    Parameters
    ----------
    num_requests : int
        Total number of requests in the workload.
    lam : float
        Poisson arrival rate (requests / second).
    size_dist : str
        One of {"bounded_pareto", "uniform", "exponential", "fixed"}.
    x_min, x_max : float
        Lower / upper bounds for "bounded_pareto" and "uniform" sizes.
        For "fixed", ``x_min`` is the constant value used.
    alpha_x : float
        Pareto shape parameter for "bounded_pareto" sizes.
        Smaller alpha_x => heavier tail.
    x_mean : float
        Mean of the Exponential distribution for "exponential" sizes.
    seed_offset : int
        Added to ``config.INITIAL_SEED`` to allow varying the workload
        while staying reproducible. Default 0.

    Returns
    -------
    list[Request]
        Sorted by arrival_time (i.e. in arrival order).
    """
    if lam <= 0:
        raise ValueError("lam must be > 0")
    if num_requests <= 0:
        raise ValueError("num_requests must be > 0")

    rng = random.Random(config.INITIAL_SEED + seed_offset)

    requests: List[Request] = []
    t = 0.0
    for rid in range(num_requests):
        t += rng.expovariate(lam)
        x = _sample_x(rng, size_dist, x_min, x_max, alpha_x, x_mean)
        requests.append(Request(arrival_time=t, request_id=rid, x=x))

    return requests


def iter_workload(*args, **kwargs) -> Iterator[Request]:
    """Streaming variant of ``generate_workload`` (rarely needed)."""
    for r in generate_workload(*args, **kwargs):
        yield r


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick visual check: print a summary of a small workload.
    import argparse

    p = argparse.ArgumentParser(description="Inspect a generated workload.")
    p.add_argument("--n", type=int, default=20, help="number of requests")
    p.add_argument("--lam", type=float, default=2.0, help="arrival rate (req/s)")
    p.add_argument("--dist", default="bounded_pareto",
                   choices=["bounded_pareto", "uniform", "exponential", "fixed"])
    p.add_argument("--seed-offset", type=int, default=0)
    args = p.parse_args()

    wl = generate_workload(args.n, args.lam, size_dist=args.dist,
                           seed_offset=args.seed_offset)
    xs = [r.x for r in wl]
    print(f"Workload: n={args.n}, lam={args.lam}, dist={args.dist}, seed_offset={args.seed_offset}")
    print(f"x: min={min(xs):.3f}  mean={sum(xs)/len(xs):.3f}  max={max(xs):.3f}")
    print(f"arrival_times: first={wl[0].arrival_time:.3f}s  last={wl[-1].arrival_time:.3f}s")
    print()
    for r in wl[:10]:
        print(f"  t={r.arrival_time:8.4f}s  id={r.request_id:4d}  x={r.x:8.4f}")
    if len(wl) > 10:
        print(f"  ... and {len(wl) - 10} more")
