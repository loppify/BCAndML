"""Reproducibly demonstrate propagation, a partition, and reorganization."""
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from blockchain import Transaction, Wallet

ports = (8101, 8102, 8103)
urls = [f"http://127.0.0.1:{p}" for p in ports]
procs = [subprocess.Popen([sys.executable, "node_server.py", str(p)]) for p in ports]
lines = []

def request(url, method="GET", data=None):
    raw = None if data is None else json.dumps(data).encode()
    req = Request(url, raw, {"Content-Type": "application/json"}, method=method)
    return json.loads(urlopen(req, timeout=3).read())

def post(url, data):
    return request(url, "POST", data)

def log(label, value):
    lines.append(f"{label}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")

try:
    time.sleep(.5)
    # Connect node 1 and 2. Node 3 remains isolated until it synchronizes.
    post(urls[0] + "/peers", {"peer": urls[1]})
    post(urls[1] + "/peers", {"peer": urls[0]})
    miner, receiver = Wallet.create(), Wallet.create()
    post(urls[0] + "/mine", {"miner": miner.address})
    # Bring node 3 to the common prefix before creating the partition.
    post(urls[0] + "/peers", {"peer": urls[2]})
    post(urls[2] + "/peers", {"peer": urls[0]})
    post(urls[2] + "/sync", {})
    request(urls[0] + "/peers", "DELETE", {"peer": urls[2]})
    request(urls[2] + "/peers", "DELETE", {"peer": urls[0]})
    log("Partition created at common height", [request(u + "/status") for u in urls])

    tx = Transaction.create(miner, receiver.address, 5, 1, 0)
    post(urls[0] + "/transaction", tx.__dict__)
    post(urls[0] + "/mine", {"miner": miner.address})
    log("Node 1 branch and transaction propagation to node 2", [request(u + "/status") for u in urls])

    # Isolated node 3 grows a heavier valid branch.
    post(urls[2] + "/mine", {"miner": receiver.address})
    post(urls[2] + "/mine", {"miner": receiver.address})
    post(urls[0] + "/peers", {"peer": urls[2]})
    post(urls[2] + "/peers", {"peer": urls[0]})
    log("Node 1 synchronization", post(urls[0] + "/sync", {}))
    log("Node 2 synchronization", post(urls[1] + "/sync", {}))
    log("After reorganization (node 1, node 2, node 3)", [request(u + "/status") for u in urls])
    output = Path("../artifacts")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "network_demo.txt").open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
finally:
    for proc in procs:
        proc.terminate()
    for proc in procs:
        proc.wait(timeout=3)
