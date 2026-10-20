import json
import os
import tempfile
import unittest

import blockchain as blockchain_module
from blockchain import Blockchain, Block, Transaction, Wallet, merkle_proof, merkle_root, verify_merkle


class BlockchainTests(unittest.TestCase):
    def setUp(self):
        self.chain = Blockchain()
        self.miner = Wallet.create()
        self.receiver = Wallet.create()
        self.chain.mine_block(self.miner.address, difficulty=1)

    def tx(self, nonce=0, amount=10, fee=1):
        return Transaction.create(self.miner, self.receiver.address, amount, fee, nonce)

    def test_wallet_address_derived_from_public_key(self):
        w = Wallet.create()
        self.assertEqual(w.address, __import__("hashlib").sha256(bytes.fromhex(w.public_key)).hexdigest())

    def test_signature_valid(self):
        self.assertTrue(self.tx().verify_signature())

    def test_signature_tampering_rejected(self):
        tx = self.tx()
        tx.amount += 1
        self.assertFalse(tx.verify_signature())

    def test_deterministic_transaction_encoding(self):
        tx = self.tx()
        self.assertEqual(tx.signing_bytes(), tx.signing_bytes())

    def test_even_merkle_root(self):
        txs = [self.tx(), Transaction.create(self.miner, self.receiver.address, 1, 1, 1)]
        self.assertEqual(len(merkle_root(txs)), 64)

    def test_odd_merkle_root_duplicates_last(self):
        txs = [self.tx(i, 1, 0) for i in range(3)]
        self.assertEqual(merkle_root(txs), merkle_root(txs + [txs[-1]]))

    def test_merkle_inclusion_proof(self):
        txs = [self.tx(i, 1, 0) for i in range(5)]
        self.assertTrue(verify_merkle(txs[3].txid, merkle_proof(txs, 3), merkle_root(txs)))

    def test_merkle_wrong_transaction_rejected(self):
        txs = [self.tx(i, 1, 0) for i in range(2)]
        other = Transaction.create(self.miner, self.receiver.address, 3, 0, 2)
        self.assertFalse(verify_merkle(other.txid, merkle_proof(txs, 0), merkle_root(txs)))

    def test_mempool_accepts_valid_transaction(self):
        self.chain.add_transaction(self.tx())
        self.assertEqual(len(self.chain.mempool), 1)

    def test_mempool_rejects_invalid_signature(self):
        tx = self.tx()
        tx.signature = "00"
        with self.assertRaisesRegex(ValueError, "invalid_signature"):
            self.chain.add_transaction(tx)

    def test_mempool_rejects_overspend(self):
        tx = self.tx(amount=10_000_000)
        with self.assertRaisesRegex(ValueError, "insufficient_balance"):
            self.chain.add_transaction(tx)

    def test_mempool_rejects_wrong_nonce(self):
        with self.assertRaisesRegex(ValueError, "invalid_nonce"):
            self.chain.add_transaction(self.tx(nonce=2))

    def test_mempool_rejects_double_spend(self):
        self.chain.add_transaction(self.tx(amount=30))
        second = Transaction.create(self.miner, self.receiver.address, 30, 1, 1)
        with self.assertRaisesRegex(ValueError, "insufficient_balance"):
            self.chain.add_transaction(second)

    def test_mempool_rejects_duplicate(self):
        tx = self.tx()
        self.chain.add_transaction(tx)
        with self.assertRaisesRegex(ValueError, "duplicate_transaction"):
            self.chain.add_transaction(tx)

    def test_mining_includes_fee_in_reward_and_clears_pool(self):
        self.chain.add_transaction(self.tx())
        before = Blockchain.balances(self.chain.chain).get(self.miner.address, 0)
        block = self.chain.mine_block(self.miner.address, difficulty=1)
        self.assertEqual(block.transactions[0].amount, 51)
        self.assertEqual(Blockchain.balances(self.chain.chain).get(self.miner.address, 0), before + 40)
        self.assertFalse(self.chain.mempool)

    def test_full_chain_validation_and_mutation_detection(self):
        self.chain.add_transaction(self.tx())
        self.chain.mine_block(self.miner.address, difficulty=1)
        self.assertTrue(self.chain.validate())
        self.chain.chain[1].transactions[0].amount += 1
        self.assertFalse(self.chain.validate())

    def test_json_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "chain.json")
            self.chain.save(path)
            loaded = Blockchain.load(path)
            self.assertTrue(loaded.validate())
            self.assertEqual(loaded.chain[-1].hash, self.chain.chain[-1].hash)

    def test_hash_recalculation_breaks_next_link(self):
        self.chain.mine_block(self.miner.address, difficulty=1)
        self.chain.chain[1].timestamp += 1
        self.assertFalse(self.chain.validate())

    def test_longer_working_chain_is_accepted(self):
        peer = Blockchain()
        peer.mine_block(self.miner.address)
        peer.mine_block(self.miner.address)
        self.assertTrue(self.chain.replace_chain(peer.chain))

    def test_fee_priority_respects_sender_nonce_order(self):
        txs = [Transaction.create(self.miner, self.receiver.address, 1, fee, nonce)
               for nonce, fee in enumerate((0, 1, 2))]
        for tx in txs:
            self.chain.add_transaction(tx)
        block = self.chain.mine_block(self.miner.address, difficulty=1)
        self.assertEqual([tx.nonce for tx in block.transactions[1:]], [0, 1, 2])

    def test_block_size_limit_leaves_unselected_tx_in_mempool(self):
        self.chain.add_transaction(self.tx(amount=1, fee=0))
        original = blockchain_module.MAX_BLOCK_BYTES
        try:
            blockchain_module.MAX_BLOCK_BYTES = 1
            block = self.chain.mine_block(self.miner.address, difficulty=1)
        finally:
            blockchain_module.MAX_BLOCK_BYTES = original
        self.assertEqual(len(block.transactions), 1)
        self.assertEqual(len(self.chain.mempool), 1)

    def test_retarget_raises_difficulty_after_fast_epoch(self):
        chain = Blockchain()
        coinbase = Transaction("COINBASE", self.miner.address, 50, 0, 1, "", "")
        b1 = Block.mine(1, chain.chain[-1].hash, [coinbase], 1, timestamp=1.01)
        b2 = Block.mine(2, b1.hash, [coinbase], 1, timestamp=1.02)
        b3 = Block.mine(3, b2.hash, [coinbase], 1, timestamp=1.03)
        chain.chain.extend([b1, b2, b3])
        self.assertEqual(chain.expected_difficulty(), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
