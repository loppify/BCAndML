"""Educational account-based blockchain with Ed25519, PoW and HTTP peers."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

REWARD = 50
MAX_BLOCK_BYTES = 16_384


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Wallet:
    secret: str
    public_key: str
    address: str

    @classmethod
    def create(cls) -> "Wallet":
        private = Ed25519PrivateKey.generate()
        secret = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()).hex()
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        return cls(secret, public, sha(bytes.fromhex(public)))

    def sign(self, payload: bytes) -> str:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.secret)).sign(payload).hex()


@dataclass
class Transaction:
    sender: str
    recipient: str
    amount: int
    fee: int
    nonce: int
    public_key: str
    signature: str = ""

    def body(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if k != "signature"}

    def signing_bytes(self) -> bytes:
        return canonical(self.body())

    @property
    def txid(self) -> str:
        return sha(canonical(asdict(self)))

    @classmethod
    def create(cls, wallet: Wallet, recipient: str, amount: int, fee: int, nonce: int) -> "Transaction":
        tx = cls(wallet.address, recipient, amount, fee, nonce, wallet.public_key)
        tx.signature = wallet.sign(tx.signing_bytes())
        return tx

    def verify_signature(self) -> bool:
        if self.sender != sha(bytes.fromhex(self.public_key)) or self.amount <= 0 or self.fee < 0 or self.nonce < 0:
            return False
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key)).verify(bytes.fromhex(self.signature), self.signing_bytes())
            return True
        except (ValueError, InvalidSignature):
            return False


def merkle_root(transactions: list[Transaction]) -> str:
    if not transactions:
        return sha(b"")
    level = [bytes.fromhex(tx.txid) for tx in transactions]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_proof(transactions: list[Transaction], index: int) -> list[tuple[str, str]]:
    if not 0 <= index < len(transactions):
        raise IndexError(index)
    level = [bytes.fromhex(tx.txid) for tx in transactions]
    proof: list[tuple[str, str]] = []
    pos = index
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sibling = pos ^ 1
        proof.append(("left" if sibling < pos else "right", level[sibling].hex()))
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
        pos //= 2
    return proof


def verify_merkle(txid: str, proof: list[tuple[str, str]], root: str) -> bool:
    current = bytes.fromhex(txid)
    for side, sibling in proof:
        other = bytes.fromhex(sibling)
        current = hashlib.sha256(other + current if side == "left" else current + other).digest()
    return current.hex() == root


@dataclass
class Block:
    index: int
    timestamp: float
    previous_hash: str
    merkle_root: str
    difficulty: int
    nonce: int
    transactions: list[Transaction]

    def header(self) -> dict[str, Any]:
        return {"index": self.index, "timestamp": self.timestamp, "previous_hash": self.previous_hash,
                "merkle_root": self.merkle_root, "difficulty": self.difficulty, "nonce": self.nonce}

    @property
    def hash(self) -> str:
        return sha(canonical(self.header()))

    @classmethod
    def mine(cls, index: int, previous: str, txs: list[Transaction], difficulty: int, timestamp: float | None = None) -> "Block":
        block = cls(index, timestamp if timestamp is not None else time.time(), previous, merkle_root(txs), difficulty, 0, txs)
        target = "0" * difficulty
        while not block.hash.startswith(target):
            block.nonce += 1
        return block


class Blockchain:
    """Chain validation, account nonces, fee-priority selection, retargeting."""
    RETARGET_INTERVAL = 3
    TARGET_BLOCK_SECONDS = 0.25

    def __init__(self) -> None:
        self.chain = [Block.mine(0, "0" * 64, [], 1, timestamp=1.0)]
        self.mempool: list[Transaction] = []

    @staticmethod
    def balances(chain: list[Block]) -> dict[str, int]:
        result: dict[str, int] = {}
        for block in chain:
            for tx in block.transactions:
                if tx.sender != "COINBASE":
                    result[tx.sender] = result.get(tx.sender, 0) - tx.amount - tx.fee
                result[tx.recipient] = result.get(tx.recipient, 0) + tx.amount
        return result

    @staticmethod
    def nonces(chain: list[Block]) -> dict[str, int]:
        out: dict[str, int] = {}
        for block in chain:
            for tx in block.transactions:
                if tx.sender != "COINBASE":
                    out[tx.sender] = max(out.get(tx.sender, 0), tx.nonce + 1)
        return out

    def expected_difficulty(self, chain: list[Block] | None = None) -> int:
        c = chain or self.chain
        mined_blocks = len(c) - 1
        if mined_blocks < self.RETARGET_INTERVAL or mined_blocks % self.RETARGET_INTERVAL:
            return c[-1].difficulty
        elapsed = c[-1].timestamp - c[-self.RETARGET_INTERVAL].timestamp
        expected = self.TARGET_BLOCK_SECONDS * (self.RETARGET_INTERVAL - 1)
        if elapsed < expected / 2:
            return min(5, c[-1].difficulty + 1)
        if elapsed > expected * 2:
            return max(1, c[-1].difficulty - 1)
        return c[-1].difficulty

    def add_transaction(self, tx: Transaction) -> None:
        if not tx.verify_signature():
            raise ValueError("invalid_signature")
        known = {t.txid for b in self.chain for t in b.transactions} | {t.txid for t in self.mempool}
        if tx.txid in known:
            raise ValueError("duplicate_transaction")
        expected = self.nonces(self.chain).get(tx.sender, 0) + sum(t.sender == tx.sender for t in self.mempool)
        if tx.nonce != expected:
            raise ValueError("invalid_nonce")
        funds = self.balances(self.chain).get(tx.sender, 0) - sum(t.amount + t.fee for t in self.mempool if t.sender == tx.sender)
        if funds < tx.amount + tx.fee:
            raise ValueError("insufficient_balance")
        self.mempool.append(tx)

    def mine_block(self, miner: str, difficulty: int | None = None) -> Block:
        ordered = sorted(self.mempool, key=lambda t: (-t.fee, t.txid))
        chosen: list[Transaction] = []
        size = 0
        next_nonce = self.nonces(self.chain)
        remaining = ordered[:]
        while remaining:
            progressed = False
            for tx in remaining[:]:
                if tx.nonce != next_nonce.get(tx.sender, 0):
                    continue
                n = len(canonical(asdict(tx)))
                remaining.remove(tx)
                if size + n <= MAX_BLOCK_BYTES:
                    chosen.append(tx)
                    size += n
                    next_nonce[tx.sender] = tx.nonce + 1
                    progressed = True
            if not progressed:
                break
        reward = Transaction("COINBASE", miner, REWARD + sum(t.fee for t in chosen), 0, len(self.chain), "", "")
        txs = [reward] + chosen
        block = Block.mine(len(self.chain), self.chain[-1].hash, txs, difficulty if difficulty is not None else self.expected_difficulty())
        self.chain.append(block)
        ids = {t.txid for t in chosen}
        self.mempool = [t for t in self.mempool if t.txid not in ids]
        return block

    def validate(self, chain: list[Block] | None = None) -> bool:
        c = chain or self.chain
        if not c or c[0].previous_hash != "0" * 64 or c[0].index != 0:
            return False
        expected_genesis = Block.mine(0, "0" * 64, [], 1, timestamp=1.0)
        if c[0].hash != expected_genesis.hash:
            return False
        balances: dict[str, int] = {}
        expected_nonces: dict[str, int] = {}
        for i, block in enumerate(c):
            if block.index != i or block.hash[:block.difficulty] != "0" * block.difficulty:
                return False
            if i and block.previous_hash != c[i - 1].hash:
                return False
            if i > 1:
                expected = self.expected_difficulty(c[:i])
                if block.difficulty != expected:
                    return False
            if block.merkle_root != merkle_root(block.transactions):
                return False
            if block.difficulty < 1 or block.difficulty > 5:
                return False
            if i == 0 and not block.transactions:
                continue
            if not block.transactions or block.transactions[0].sender != "COINBASE":
                return False
            fees = 0
            seen_coinbase = 0
            for j, tx in enumerate(block.transactions):
                if tx.sender == "COINBASE":
                    seen_coinbase += 1
                    if j != 0:
                        return False
                    balances[tx.recipient] = balances.get(tx.recipient, 0) + tx.amount
                    continue
                if not tx.verify_signature() or tx.nonce != expected_nonces.get(tx.sender, 0):
                    return False
                if balances.get(tx.sender, 0) < tx.amount + tx.fee:
                    return False
                balances[tx.sender] = balances.get(tx.sender, 0) - tx.amount - tx.fee
                balances[tx.recipient] = balances.get(tx.recipient, 0) + tx.amount
                expected_nonces[tx.sender] = tx.nonce + 1
                fees += tx.fee
            if seen_coinbase != 1 or block.transactions[0].amount > REWARD + fees:
                return False
        return True

    def replace_chain(self, candidate: list[Block]) -> bool:
        def work(c: list[Block]) -> int:
            return sum(16 ** b.difficulty for b in c)
        if work(candidate) <= work(self.chain):
            return False
        old = {tx.txid: tx for b in self.chain for tx in b.transactions if tx.sender != "COINBASE"}
        new_ids = {tx.txid for b in candidate for tx in b.transactions}
        orphaned = [tx for txid, tx in old.items() if txid not in new_ids]
        if not self.validate(candidate):
            return False
        self.chain = candidate
        self.mempool = []
        for tx in orphaned:
            try:
                self.add_transaction(tx)
            except ValueError:
                pass
        return True

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"header": b.header(), "transactions": [asdict(t) for t in b.transactions]} for b in self.chain], f, sort_keys=True)

    @classmethod
    def load(cls, path: str) -> "Blockchain":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        obj = cls.__new__(cls)
        obj.chain = [Block(**entry["header"], transactions=[Transaction(**t) for t in entry["transactions"]]) for entry in data]
        obj.mempool = []
        if not obj.validate():
            raise ValueError("invalid_chain_file")
        return obj


class Node:
    def __init__(self, port: int):
        self.port = port
        self.blockchain = Blockchain()
        self.peers: set[str] = set()

    def broadcast(self, path: str, payload: dict[str, Any]) -> None:
        data = canonical(payload)
        for peer in sorted(self.peers):
            try:
                req = urllib.request.Request(peer + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=1).read()
            except Exception:
                continue
