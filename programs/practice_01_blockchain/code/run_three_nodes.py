"""Launch three isolated local node processes, then connect them as peers."""
import json
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ports = (8101, 8102, 8103)
processes = [subprocess.Popen([sys.executable, "node_server.py", str(port)]) for port in ports]
base = [f"http://127.0.0.1:{port}" for port in ports]

def post(url, data=None):
    request = Request(url, json.dumps(data or {}).encode(), {"Content-Type": "application/json"}, method="POST")
    return json.loads(urlopen(request, timeout=2).read())

try:
    time.sleep(0.5)
    for i, url in enumerate(base):
        for j, peer in enumerate(base):
            if i != j:
                post(url + "/peers", {"peer": peer})
    for url in base:
        print(url, json.loads(urlopen(url + "/status").read()))
    print("All three independent node processes are running. Press Ctrl+C to stop.")
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        process.terminate()
    for process in processes:
        process.wait()
