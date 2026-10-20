"""Execute the five required attack cases and print their real outcomes."""
from pathlib import Path
from blockchain import Blockchain, Transaction, Wallet

_RESULTS = []

def result(label, operation):
    try:
        operation()
        message = f"{label}: ACCEPTED (unexpected)"
    except ValueError as exc:
        message = f"{label}: REJECTED ({exc})"
    _RESULTS.append(message)
    print(message)

miner, recipient, other = Wallet.create(), Wallet.create(), Wallet.create()
c = Blockchain()
c.mine_block(miner.address, 1)
tx = Transaction.create(miner, recipient.address, 7, 1, 0)
c.add_transaction(tx)
c.mine_block(miner.address, 1)
c.mine_block(miner.address, 1)
c.chain[2].transactions[1].amount += 1
_RESULTS.append(f"Attack 1, old transaction amount changed: {'DETECTED' if not c.validate() else 'MISSED'}")
print(_RESULTS[-1])

c = Blockchain()
c.mine_block(miner.address, 1)
c.mine_block(miner.address, 1)
c.mine_block(miner.address, 1)
c.chain[1].timestamp += 1
while not c.chain[1].hash.startswith("0" * c.chain[1].difficulty):
    c.chain[1].nonce += 1  # adversary re-mines the altered block; successor link still fails
_RESULTS.append(f"Attack 2, edited block rehashed: {'DETECTED by following previous_hash' if not c.validate() else 'MISSED'}")
print(_RESULTS[-1])

c = Blockchain()
c.mine_block(miner.address, 1)
fake = Transaction.create(miner, recipient.address, 2, 0, 0)
fake.signature = "00" * 64
result("Attack 3, forged signature", lambda: c.add_transaction(fake))

c = Blockchain()
c.mine_block(miner.address, 1)
c.add_transaction(Transaction.create(miner, recipient.address, 40, 1, 0))
result("Attack 4, second conflicting spend", lambda: c.add_transaction(Transaction.create(miner, other.address, 40, 1, 1)))

c = Blockchain()
c.mine_block(miner.address, 1)
confirmed = Transaction.create(miner, recipient.address, 3, 0, 0)
c.add_transaction(confirmed)
c.mine_block(miner.address, 1)
result("Attack 5, replay confirmed transaction", lambda: c.add_transaction(confirmed))

# Preserve the exact stdout transcript as a reproducible test artifact.
output = Path("../artifacts")
output.mkdir(parents=True, exist_ok=True)
(output / "attack_results.txt").write_text("\n".join(_RESULTS) + "\n", encoding="utf-8")
