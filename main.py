import subprocess
import time
import psutil
import config
import os

def start_server(port, core_id):
    """
    Starts a seer process and pins it to a specific CPU core.
    """

    #NOTE FOR MACOS USERS: Use "python3" instead of "python"
    cmd = ["python3", "-m", "src.server", str(port)]
    process = subprocess.Popen(cmd)
    
    #CPU Pinning: Bind the process to a specific physical core
    #! WINDOWS/LINUX: Uncomment the following 2 lines to enable strict core affinity.
    #! MACOS: Keep these lines commented. macOS (Darwin) does not support standard 
    #! process.cpu_affinity() due to kernel-level scheduling restrictions.
    #p = psutil.Process(process.pid)
    #p.cpu_affinity([core_id])

    print(f"Server started on Port: {port} | Pinned to Core: {core_id} | PID: {process.pid}")
    return process

if __name__ == "__main__":
    print("--- Initializing Load Balancing System ---")

    server_processes = []

    #Start 3 servers based on configuration
    try:
        for server_id, port in config.SERVER_PORTS.items():
            #Match server ID to corressponding CPU core
            core = config.SERVER_CORES[server_id - 1]
            proc = start_server(port, core)
            server_processes.append(proc)

        print("\n Infrastructure is ready. Servers are listening for requests.")
        print("Dispatcher can now be started. Press Ctrl+C to stop servers.")

        #Keep the main process alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n Shutting down servers...")
        for p in server_processes:
            p.terminate()
        print("All processes terminated.")