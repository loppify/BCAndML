"""Minimal REST node process used by the three-peer demonstration."""
import json
import sys
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from blockchain import Block, Blockchain, Node, Transaction, Wallet

node = Node(int(sys.argv[1]))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, code, data):
        raw = json.dumps(data, default=lambda x: asdict(x), sort_keys=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path)
        if path.path == "/chain":
            return self.respond(200, [{"header": b.header(), "transactions": [asdict(t) for t in b.transactions]} for b in node.blockchain.chain])
        if path.path == "/status":
            return self.respond(200, {"port": node.port, "height": len(node.blockchain.chain)-1, "peers": sorted(node.peers), "valid": node.blockchain.validate(), "mempool": len(node.blockchain.mempool)})
        if path.path == "/validate":
            return self.respond(200, {"valid": node.blockchain.validate()})
        if path.path == "/balance":
            address = parse_qs(path.query).get("address", [""])[0]
            return self.respond(200, {"address": address, "balance": Blockchain.balances(node.blockchain.chain).get(address, 0)})
        self.respond(404, {"error": "not_found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/wallet":
                return self.respond(201, asdict(Wallet.create()))
            if self.path == "/peers":
                node.peers.add(body["peer"].rstrip("/"))
                return self.respond(200, {"peers": sorted(node.peers)})
            if self.path == "/transaction":
                tx = Transaction(**body)
                node.blockchain.add_transaction(tx)
                node.broadcast("/transaction", asdict(tx))
                return self.respond(200, {"accepted": tx.txid})
            if self.path == "/mine":
                block = node.blockchain.mine_block(body["miner"])
                node.broadcast("/block", {"header": block.header(), "transactions": [asdict(t) for t in block.transactions]})
                return self.respond(200, {"hash": block.hash, "height": block.index})
            if self.path == "/block":
                block = Block(**body["header"], transactions=[Transaction(**t) for t in body["transactions"]])
                current = node.blockchain.chain
                parent_index = next((i for i, b in enumerate(current) if b.hash == block.previous_hash), None)
                if parent_index is not None:
                    candidate = current[:parent_index + 1] + [block]
                else:
                    candidate = current + [block]
                if parent_index == len(current) - 1 and node.blockchain.validate(candidate):
                    node.blockchain.chain.append(block)
                    included = {tx.txid for tx in block.transactions}
                    node.blockchain.mempool = [tx for tx in node.blockchain.mempool if tx.txid not in included]
                    return self.respond(200, {"accepted": block.hash})
                if parent_index is not None and node.blockchain.replace_chain(candidate):
                    return self.respond(200, {"reorganized": True, "height": len(candidate)-1})
                return self.respond(409, {"error": "invalid_or_forked_block"})
            if self.path == "/sync":
                for peer in sorted(node.peers):
                    try:
                        from urllib.request import urlopen
                        raw = urlopen(peer + "/chain", timeout=2).read()
                        entries = json.loads(raw)
                        candidate = [Block(**e["header"], transactions=[Transaction(**t) for t in e["transactions"]]) for e in entries]
                        if node.blockchain.replace_chain(candidate):
                            return self.respond(200, {"replaced": True, "height": len(candidate)-1})
                    except Exception:
                        continue
                return self.respond(200, {"replaced": False, "height": len(node.blockchain.chain)-1})
        except (ValueError, KeyError, TypeError) as exc:
            return self.respond(400, {"error": str(exc)})
        self.respond(404, {"error": "not_found"})

    def do_DELETE(self):
        if self.path == "/peers":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            node.peers.discard(body["peer"].rstrip("/"))
            return self.respond(200, {"peers": sorted(node.peers)})
        self.respond(404, {"error": "not_found"})


ThreadingHTTPServer(("127.0.0.1", node.port), Handler).serve_forever()
