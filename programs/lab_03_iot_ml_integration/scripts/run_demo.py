"""Start a local Hardhat chain, deploy contracts and serve the browser application."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RPC_URL = os.getenv("WEB3_PROVIDER_URL", "http://127.0.0.1:8545")


def rpc_ready() -> bool:
    request = Request(
        RPC_URL,
        data=b'{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}',
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=1) as response:
            return b'"result"' in response.read()
    except (URLError, TimeoutError, OSError):
        return False


def run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete local IoT IDS browser demonstration.")
    parser.add_argument("--retrain", action="store_true", help="Retrain models and regenerate evidence before deployment.")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    env = os.environ.copy()
    env["WEB3_PROVIDER_URL"] = RPC_URL
    env.setdefault("MODEL_VERSION", "2")
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if "DATABASE_PATH" not in os.environ:
        default_db = ROOT / "artifacts" / "iot_ids.sqlite3"
        for stale_file in (default_db, Path(str(default_db) + "-wal"), Path(str(default_db) + "-shm")):
            stale_file.unlink(missing_ok=True)
        env["DATABASE_PATH"] = "artifacts/iot_ids.sqlite3"

    model_path = ROOT / "models" / "random_forest_v2.joblib"
    card_path = ROOT / "models" / "model_card.json"
    if args.retrain or not model_path.exists() or not card_path.exists():
        run([sys.executable, "-m", "app.train", "--data", "data/raw/ton_iot_network.csv"], env)

    if not (ROOT / "node_modules" / ".bin" / "hardhat").exists():
        raise SystemExit("Node dependencies are missing. Run `npm ci` in the code directory first.")

    run(["node_modules/.bin/hardhat", "compile"], env)
    node_log_path = ROOT / "artifacts" / "hardhat-node.log"
    node_log_path.parent.mkdir(parents=True, exist_ok=True)
    with node_log_path.open("w", encoding="utf-8") as node_log:
        node = subprocess.Popen(
            ["node_modules/.bin/hardhat", "node", "--hostname", "127.0.0.1", "--port", "8545"],
            cwd=ROOT,
            env=env,
            stdout=node_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and node.poll() is None:
                if rpc_ready():
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"Hardhat RPC did not start. See {node_log_path}.")

            run(["node_modules/.bin/hardhat", "run", "scripts/deploy-local.js", "--network", "localhost"], env)
            env["DATABASE_PATH"] = env.get("DATABASE_PATH", "artifacts/iot_ids.sqlite3")
            env["MODEL_PATH"] = env.get("MODEL_PATH", "models/random_forest_v2.joblib")
            env["MODEL_CARD_PATH"] = env.get("MODEL_CARD_PATH", "models/model_card.json")
            env["DEPLOYMENT_PATH"] = env.get("DEPLOYMENT_PATH", "deployments/localhost.json")

            import uvicorn
            print(f"IoT IDS is ready at http://127.0.0.1:{args.port}")
            print("Hardhat local network: chain ID 31337. Connect MetaMask to this network.")
            uvicorn.run("app.api:app", host="127.0.0.1", port=args.port, reload=False)
        except KeyboardInterrupt:
            pass
        finally:
            if node.poll() is None:
                try:
                    os.killpg(node.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    node.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    node.kill()


if __name__ == "__main__":
    main()
