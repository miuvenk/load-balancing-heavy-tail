# Load Balancing with Heavy-Tailed Tasks

This project designs and evaluates dispatching strategies for a set of identical servers under heavy-tailed workloads, where most requests complete quickly but a few stragglers take disproportionately long.

It is a project for the **Software Performance and Scalability** course at Ca' Foscari University of Venice (Prof. Andrea Marin).

---

## Project Structure

```
.
├── config.py               # Shared configuration (ports, seed, alpha, x_min)
├── main.py                 # Starts 3 server processes, pins each to a CPU core
├── src/
│   ├── server.py           # Flask-based worker server (FIFO single-server queue)
│   ├── dispatcher.py       # Dispatcher + experiment runner (all policies)
│   └── load_generator.py   # Open-loop workload generator (Poisson arrivals)
├── notebooks/
│   ├── plot_results.py     # Reads CSVs, produces PNG figures
│   └── figures/            # Generated plots (gitignored)
├── data/                   # Experiment result CSVs (gitignored)
├── run_experiments.ps1     # PowerShell: runs Sweeps 1, 3, 4
├── run_alpha_sweep.ps1     # PowerShell: runs Sweep 2 (alpha), manages server restarts
├── run_bottleneck_sweep.ps1# PowerShell: runs Bottleneck sweep 5 (lam=40..147)
└── generate_plots.ps1      # PowerShell: generates per-sweep figure sets
```

---

## System Model

- **3 identical servers**, each pinned to a dedicated CPU core
- **Dispatcher** on Core 0, servers on Cores 1, 2, 3
- Each request has a size parameter `x > 0`
- Server processing time: `base_work (20,000) * x * Pareto(alpha)` — heavy-tailed by design
- Open-loop benchmark: Poisson arrivals at rate `lambda` req/s

---

## Dispatching Policies

| Policy | Description |
|---|---|
| `random` | Baseline — pick a server uniformly at random |
| `round_robin` | Cycle through servers in fixed order |
| `jsq` | Join Shortest Queue — send to server with fewest pending requests |
| `lwl` | Least Work Left — send to server with minimum sum of pending x |
| `sita` | Size-Interval Task Assignment — partition x into 3 bands, one server per band |

---

## Installation

```bash
# Clone the repository
git clone https://github.com/miuvenk/load-balancing-heavy-tail.git
cd load-balancing-heavy-tail

# Install Python dependencies
pip install -r requirements.txt
```

**Requirements:** Python 3.8+, Flask, requests, psutil, matplotlib, numpy

---

## Running the Servers

```bash
# Terminal 1 — start 3 servers (pinned to cores 1, 2, 3)
python main.py
```

> **macOS users:** CPU pinning via `cpu_affinity()` is not supported. Comment out the affinity lines in `main.py`.

---

## Running a Single Experiment

```bash
# Terminal 2 — run dispatcher with a specific policy
python src/dispatcher.py --policy jsq --lam 10 --n 1000

# Available options:
#   --policy     random | round_robin | jsq | lwl | sita
#   --lam        arrival rate (req/s)
#   --n          number of requests
#   --alpha      Pareto shape (default: 1.3, must match config.py)
#   --size-dist  bounded_pareto | uniform | exponential | fixed
#   --out        output CSV path
```

---

## Running the Full Experiment Suite

The full experiment suite is split across PowerShell scripts. Run them in this order:

### Step 1 — Main Suite (Sweeps 1, 3, 4, 5)

Start servers first, then in a second terminal:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_experiments.ps1
```

Duration: ~2h 19m (70 runs)

### Step 2 — Alpha Sweep (Sweep 2)

Stop the servers. This script manages server restarts automatically:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_alpha_sweep.ps1
```

Duration: ~43m (25 runs)

### Step 3 — Bottleneck Sweep

Start servers again, then:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_bottleneck_sweep.ps1
```

Duration: ~20m (35 runs)

### Step 4 — Generate Plots

```powershell
powershell -ExecutionPolicy Bypass -File .\generate_plots.ps1
```

Plots are written to `notebooks/figures/sweep{N}_*/`.

> **First-time PowerShell setup:**
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

---

## Experiment Sweeps

| Sweep | Script | lambda | N | alpha | Purpose |
|---|---|---|---|---|---|
| 1 — Load sweep | run_experiments.ps1 | 2, 5, 8, 12, 15, 18, 22 | 500–2000 | 1.3 | Low vs high load |
| 2 — Alpha sweep | run_alpha_sweep.ps1 | 10 | 500–1000 | 1.1, 1.3, 1.5, 2.0, 3.0 | Heavy-tail parameter effect |
| 3 — Size dist sweep | run_experiments.ps1 | 10 | 1000 | 1.3 | Effect of x variability |
| 4 — Saturation stress | run_experiments.ps1 | 25, 30 | 2000 | 1.3 | System overload |
| 5 - Bottleneck | run_bottleneck_sweep.ps1 | 40–147 | 2000 | 1.3 | Find saturation point |

Total: **125 runs**. Theoretical system capacity: ~147 req/s (3 × ~49 req/s per server, derived from mean service time ~20ms at low load).

---

## Configuration

Key parameters in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `INITIAL_SEED` | 42 | Random seed — **do not change** between experiments |
| `ALPHA` | 1.3 | Pareto shape for server-side multiplier |
| `X_MIN` | 1.0 | Minimum request size |
| `SERVER_PORTS` | 5001–5003 | HTTP ports for the 3 servers |
| `SERVER_CORES` | [1, 2, 3] | CPU cores for server processes |
| `DISPATCHER_CORE` | 0 | CPU core for dispatcher |

> `ALPHA` is read at server boot time. The alpha sweep script (`run_alpha_sweep.ps1`) edits this value automatically and restarts servers between groups.

---

## Output

- **CSVs** → `data/<policy>_lam<lam>_alpha<alpha>[_tag].csv`
- **Plots** → `notebooks/figures/sweep{N}_*/` (4 PNG figures per sweep: percentiles, ccdf, per_request, load_split)

CSV columns: `request_id, policy, lam, alpha, size_dist, x, arrival_time, dispatch_time, completion_time, response_time, wait_time, service_time, server_port, server_pid`
