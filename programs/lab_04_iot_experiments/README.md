# Lab 4: IoT IDS experiments and results

Reproducible benchmarks, raw measurements, report figures and the 12-slide defense presentation for the IoT IDS project. The scripts use the sibling `lab_03_iot_ml_integration/` project. The ToN_IoT dataset, reports, credentials and dependency directories are not included.

## Requirements

- Python 3.14, Node.js 22 and npm.
- Install Python requirements with `python -m pip install -r code/requirements.txt`.
- Install Lab 3 Node dependencies with `npm ci` from `../lab_03_iot_ml_integration/`.
- For model retraining, obtain the course ToN_IoT CSV and place it at `../lab_03_iot_ml_integration/data/raw/ton_iot_network.csv`.

## Reproduce local experiments

From this project directory:

```bash
python code/run_ml_experiments.py
```

From `../lab_03_iot_ml_integration/` run:

```bash
npm ci
npm exec hardhat -- run ../lab_04_iot_experiments/code/benchmark_local.cjs --network hardhat
npm exec hardhat -- run ../lab_04_iot_experiments/code/security_contract_checks.cjs --network hardhat
```

Then from the repository root:

```bash
python programs/lab_04_iot_experiments/code/run_system_experiments.py
python programs/lab_04_iot_experiments/code/security_api_checks.py
python programs/lab_04_iot_experiments/code/render_system_plots.py
python programs/lab_04_iot_experiments/code/build_presentation.py
```

The load scenario sends ten gateway checks for each of 10, 50 and 100 concurrent users. It also performs 1000 sequential checks for NFR-06. ML experiments require the ToN_IoT CSV; the other local benchmarks use the checked-in model artifact and demo flows.

## Optional Sepolia measurements

The Sepolia benchmark writes five real testnet decisions to the existing Lab 2 proxy and registers model v2 once if needed. Use only a testnet signer with administrator and oracle roles. From the repository root, compile Lab 3 artifacts, create an untracked `.env` from the Lab 4 example, then run:

```bash
cd programs/lab_03_iot_ml_integration
npm run compile
cd ../lab_04_iot_experiments
cp -n code/.env.example .env
# Fill SEPOLIA_RPC_URL and DEPLOYER_PRIVATE_KEY in the untracked .env
python code/benchmark_sepolia.py --env-file .env --repeats 5
```

This consumes Sepolia test ETH and changes testnet state. The script checks chain ID, account roles, device state and model hash before sending. Never put a mainnet private key or secret in a tracked file.

## Results and limitations

`artifacts/` contains the raw JSON/CSV results used by the report. `images/` contains generated experiment graphs. `artifacts/defense_presentation.pptx` is the 12-slide presentation. The fee snapshot uses public RPC gas prices and ETH/EUR at run time; Layer 2 execution-only values and raw calldata sensitivity are not full rollup fee quotes.
