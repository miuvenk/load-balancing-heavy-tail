# Shared Configuration File

# The Initial Seed ensures that each users generate the same job sequences.
# DO NOT CHANGE THIS during experiments!
INITIAL_SEED = 42  #it must be the same.

# Pareto Distribution Parameters
ALPHA = 1.3  # Default value.
X_MIN = 1.0  # Minimum job size.

# Networking - Ports for Servers
SERVER_PORTS = {
    1: 5001,
    2: 5002,
    3: 5003
}

# Dispatcher Core
DISPATCHER_CORE = 0  # Dispatcher runs on Core 0
SERVER_CORES = [1, 2, 3]  # Servers run on Core 1, 2, and 3