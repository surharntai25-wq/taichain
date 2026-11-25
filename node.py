#!/usr/bin/env python3
"""
Tai (TAI) Multi-Node P2P & RPC Network Node (`node.py`)

Wraps the hardened `tai.py` consensus engine in a zero-dependency HTTP/JSON RPC
server with P2P peer discovery, block/transaction gossip, initial chain sync,
fork reorganization (`can_reorg_to`), and background mining/forging.

Usage
-----
  # Terminal 1 (Seed Node + Miner/Validator Alice):
  python tai.py new-wallet alice.key
  python node.py --port 8001 --db node1_chain.json --wallet alice.key --mine

  # Terminal 2 (Peer Node + Miner/Validator Bob):
  python tai.py new-wallet bob.key
  python node.py --port 8002 --db node2_chain.json --wallet bob.key --peers http://127.0.0.1:8001 --mine

  # Query or submit via RPC:
  curl http://127.0.0.1:8001/stats
  curl http://127.0.0.1:8001/balance/<address>
"""
import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import tai

MAX_RPC_BODY_BYTES = 2_000_000  # Slightly above MAX_BLOCK_BYTES (1.5 MB)
SYNC_INTERVAL_SECONDS = 5
PEER_TIMEOUT_SECONDS = 4


def http_json(url: str, payload: dict = None, timeout: int = PEER_TIMEOUT_SECONDS) -> dict:
    """Send a GET (if payload is None) or POST JSON request to a peer."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_RPC_BODY_BYTES + 1)
        if len(raw) > MAX_RPC_BODY_BYTES:
            raise ValueError("peer response exceeded max payload size")
        return json.loads(raw.decode("utf-8"))


class TaiNode:
    def __init__(self, host: str, port: int, db_path: str, wallet: tai.Wallet = None,
                 peers: list[str] = None, auto_mine: bool = False):
        self.host = host
        self.port = port
        self.self_url = f"http://{host}:{port}"
        self.db_path = db_path
        self.wallet = wallet
        self.auto_mine = auto_mine
        self.lock = threading.RLock()
        self.chain = tai.Chain.load(db_path)
        self.peers = set()
        self._stop_event = threading.Event()

        for p in peers or []:
            norm = p.rstrip("/")
            if norm and norm != self.self_url:
                self.peers.add(norm)

    # -- peer & gossip management -------------------------------------------
    def register_peer(self, peer_url: str) -> bool:
        norm = peer_url.strip().rstrip("/")
        if not norm.startswith(("http://", "https://")) or norm == self.self_url:
            return False
        with self.lock:
            is_new = norm not in self.peers
            self.peers.add(norm)
        return is_new

    def snapshot_peers(self) -> list[str]:
        with self.lock:
            return sorted(self.peers)

    def broadcast(self, path: str, payload: dict, exclude: str = None):
        """Gossip a block, transaction, or peer announcement asynchronously."""
        for peer in self.snapshot_peers():
            if exclude and peer == exclude:
                continue
            threading.Thread(
                target=self._send_quietly,
                args=(f"{peer}{path}", payload),
                daemon=True,
            ).start()

    @staticmethod
    def _send_quietly(url: str, payload: dict):
        try:
            http_json(url, payload)
        except Exception:
            pass

    # -- chain & mempool ingestion ------------------------------------------
    def receive_tx(self, tx_dict: dict, source_peer: str = None) -> dict:
        tx = tai.Tx.from_dict(tx_dict)
        with self.lock:
            self.chain.submit_tx(tx)
        self.broadcast("/tx", {"tx": tx.to_dict(), "from": self.self_url}, exclude=source_peer)
        return {"ok": True, "txid": tx.txid()}

    def receive_block(self, blk_dict: dict, source_peer: str = None) -> dict:
        blk = tai.Block.from_dict(blk_dict)
        with self.lock:
            tip = self.chain.tip
            if blk.hash == tip.hash:
                return {"ok": True, "status": "already_known", "height": tip.height}

            if blk.height == tip.height + 1 and blk.prev == tip.hash:
                self.chain.add_block(blk)
                self.chain.save(self.db_path)
                accepted = True
                status = "appended"
            elif blk.height > tip.height or (blk.height == tip.height and blk.prev != tip.hash):
                accepted = False
                status = "sync_triggered"
            else:
                return {"ok": False, "error": "stale or lower-height block"}

        if accepted:
            self.broadcast("/block", {"block": blk.to_dict(), "from": self.self_url}, exclude=source_peer)
            return {"ok": True, "status": status, "height": blk.height}

        if source_peer:
            self.sync_from_peer(source_peer)
        return {"ok": True, "status": status}

    def sync_from_peer(self, peer_url: str) -> bool:
        """Fetch full chain from a peer and reorganize if heavier & valid."""
        try:
            remote_stats = http_json(f"{peer_url}/stats")
            with self.lock:
                local_height = self.chain.tip.height
            if remote_stats.get("height", 0) < local_height:
                return False

            data = http_json(f"{peer_url}/chain")
            raw_blocks = data.get("blocks", [])
            if not raw_blocks:
                return False
            candidate = [tai.Block.from_dict(b) for b in raw_blocks]

            with self.lock:
                if self.chain.can_reorg_to(candidate):
                    self.chain.save(self.db_path)
                    print(f"[SYNC] Reorganized to {peer_url} at height #{self.chain.tip.height}")
                    return True
        except Exception as e:
            print(f"[SYNC] Peer {peer_url} sync failed: {e}")
        return False

    def sync_all_peers(self):
        for peer in self.snapshot_peers():
            self.register_peer_remotely(peer)
            self.sync_from_peer(peer)

    def register_peer_remotely(self, peer_url: str):
        try:
            resp = http_json(f"{peer_url}/peers", {"peer": self.self_url})
            for p in resp.get("peers", []):
                self.register_peer(p)
        except Exception:
            pass

    # -- background loops ---------------------------------------------------
    def _sync_loop(self):
        while not self._stop_event.is_set():
            self.sync_all_peers()
            self._stop_event.wait(SYNC_INTERVAL_SECONDS)

    def _mine_loop(self):
        if not self.wallet:
            return
        print(f"[MINER] Active as {self.wallet.address[:16]}…")
        while not self._stop_event.is_set():
            with self.lock:
                ts = max(int(time.time()), self.chain.median_time_past() + 1)
                blk = self.chain.build_block(self.wallet.address, ts=ts)
                tip_hash = self.chain.tip.hash

            if blk.kind == tai.POW:
                target = 1 << (256 - blk.bits)
                n = 0
                aborted = False
                while not self._stop_event.is_set():
                    blk.nonce = n
                    if int(tai.pow_hash(blk.header()), 16) < target:
                        blk.hash = blk.compute_hash()
                        break
                    n += 1
                    if n % 32 == 0:
                        with self.lock:
                            if self.chain.tip.hash != tip_hash:
                                aborted = True
                                break
                if aborted or self._stop_event.is_set():
                    continue
            else:
                with self.lock:
                    turn = tai.pos_turn_for_timestamp(blk.ts, self.chain.tip.ts)
                    elected = tai.select_proposer(
                        self.chain.state, self.chain.seed_for(blk.height), blk.height, turn
                    )
                    if elected != self.wallet.address:
                        blk = None
                    else:
                        self.chain.forge_pos(blk, self.wallet)
                if blk is None:
                    self._stop_event.wait(1)
                    continue

            committed = False
            with self.lock:
                if self.chain.tip.hash == tip_hash:
                    try:
                        self.chain.add_block(blk)
                        self.chain.save(self.db_path)
                        committed = True
                    except ValueError as e:
                        print(f"[MINER] Rejected own block: {e}")

            if committed:
                print(
                    f"[BLOCK] #{blk.height} {blk.kind} {blk.hash[:12]}… "
                    f"txs={len(blk.txs)} reward={tai.fmt(blk.txs[0].amount)}"
                )
                self.broadcast("/block", {"block": blk.to_dict(), "from": self.self_url})

    def start(self):
        self.sync_all_peers()
        threading.Thread(target=self._sync_loop, daemon=True).start()
        if self.auto_mine:
            threading.Thread(target=self._mine_loop, daemon=True).start()

        node_ref = self

        class RPCHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt_str, *args):
                pass

            def _send_json(self, code: int, body: dict):
                raw = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_RPC_BODY_BYTES:
                    raise ValueError("invalid Content-Length")
                raw = self.rfile.read(length)
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object")
                return data

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                try:
                    if path == "/stats":
                        with node_ref.lock:
                            st = node_ref.chain.stats()
                            st["tip_hash"] = node_ref.chain.tip.hash
                            st["mempool_size"] = len(node_ref.chain.mempool)
                            st["peers"] = node_ref.snapshot_peers()
                        self._send_json(200, st)

                    elif path == "/chain":
                        with node_ref.lock:
                            blocks = [b.to_dict() for b in node_ref.chain.blocks]
                        self._send_json(200, {"blocks": blocks})

                    elif path == "/mempool":
                        with node_ref.lock:
                            txs = [t.to_dict() for t in node_ref.chain.mempool]
                        self._send_json(200, {"txs": txs})

                    elif path == "/peers":
                        self._send_json(200, {"peers": node_ref.snapshot_peers()})

                    elif path.startswith("/balance/"):
                        addr = path.split("/balance/", 1)[1]
                        if not tai.is_valid_address(addr):
                            self._send_json(400, {"error": "invalid address"})
                            return
                        with node_ref.lock:
                            bal = node_ref.chain.state.bal.get(addr, 0)
                            stk = node_ref.chain.state.stake.get(addr, 0)
                            nonce = node_ref.chain.state.nonce.get(addr, 0)
                        self._send_json(
                            200,
                            {
                                "address": addr,
                                "balance": bal,
                                "balance_formatted": tai.fmt(bal),
                                "staked": stk,
                                "staked_formatted": tai.fmt(stk),
                                "nonce": nonce,
                            },
                        )
                    else:
                        self._send_json(404, {"error": "not found"})
                except Exception as e:
                    self._send_json(500, {"error": str(e)})

            def do_POST(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")
                try:
                    payload = self._read_json()
                    if path == "/tx":
                        tx_obj = payload.get("tx", payload)
                        res = node_ref.receive_tx(tx_obj, source_peer=payload.get("from"))
                        self._send_json(200, res)

                    elif path == "/block":
                        blk_obj = payload.get("block", payload)
                        res = node_ref.receive_block(blk_obj, source_peer=payload.get("from"))
                        self._send_json(200, res)

                    elif path == "/peers":
                        peer_url = payload.get("peer", "")
                        if node_ref.register_peer(peer_url):
                            node_ref.broadcast("/peers", {"peer": peer_url}, exclude=peer_url)
                        self._send_json(200, {"ok": True, "peers": node_ref.snapshot_peers()})

                    else:
                        self._send_json(404, {"error": "not found"})
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                except Exception as e:
                    self._send_json(500, {"error": str(e)})

        server = ThreadingHTTPServer((self.host, self.port), RPCHandler)
        print(f"[RPC] Listening on {self.self_url} (db={self.db_path})")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down node...")
        finally:
            self._stop_event.set()
            server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Tai (TAI) P2P & RPC Blockchain Node")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8001, help="Bind port (default: 8001)")
    parser.add_argument("--db", default="tai_chain.json", help="Chain persistence file path")
    parser.add_argument("--wallet", default=None, help="Path to ML-DSA-65 wallet keyfile")
    parser.add_argument("--peers", nargs="*", default=[], help="Bootstrap peer URLs (e.g. http://127.0.0.1:8001)")
    parser.add_argument("--mine", action="store_true", help="Enable background PoW mining & PoS forging")
    args = parser.parse_args()

    wallet = tai.Wallet.load(args.wallet) if args.wallet else None
    node = TaiNode(
        host=args.host,
        port=args.port,
        db_path=args.db,
        wallet=wallet,
        peers=args.peers,
        auto_mine=args.mine,
    )
    node.start()


if __name__ == "__main__":
    main()
