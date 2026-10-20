# Practical Work 1: educational blockchain

Python 3.12 or newer is required. Install dependencies from this directory:

```sh
python -m pip install -r requirements.txt
PYTHONPATH=code python -m unittest discover -s tests -v
```

Run the attack checks with `python code/demo_attacks.py`. To start three HTTP nodes, run `python run_three_nodes.py` from `code/` and stop with Ctrl+C. The network-fork scenario is `python network_demo.py` from `code/`. For the Proof-of-Work experiment, install matplotlib and run `python experiment.py` from `code/`.
