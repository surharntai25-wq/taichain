#!/usr/bin/env python3
"""
Tai (TAI) - a hardened hybrid Proof-of-Work / Proof-of-Stake blockchain.

Consensus rules
---------------
* Max supply : 21,000,000 TAI (8 decimals, 1 TAI = 10**8 units)
* Block slots: strictly alternate  -> odd heights = PoW, even heights = PoS
               => 50% of blocks (and 50% of all new coins) come from each.
* Reward     : 50 TAI per block, halving every 210,000 blocks (any type).
               50 * 210,000 * 2 = 21,000,000 -> the cap is hit by design and
               is also enforced in code (reward is clipped to remaining supply).
* PoW slot   : Argon2id(header) (16 MiB, CPU/ARM64 friendly) must have `bits`
               leading zero bits. Block IDs are still sha256(header).
* PoS slot   : proposer chosen by stake-weighted deterministic lottery seeded
               from the hash of a block 20 heights back (anti-grinding);
               proposer signs the block (ML-DSA-65).
               Minimum stake 100 TAI, unstake delayed by 20 blocks.
               Includes time-based slot rotation & PoW fallback to prevent stalls.
* Fallback   : if no address has the minimum stake, or if elected PoS proposers
               fail to produce a block within the grace window, a PoS slot can
               rotate to backup proposers and ultimately fall back to PoW.
* Fees       : go to the block producer (minimum relay fee enforced).
* Signatures : ML-DSA-65 (post-quantum, NIST FIPS 204). Address = sha256(public key);
               the public key is revealed only when the address first signs something.

Usage
-----
  pip install argon2-cffi dilithium-py
  python tai.py demo                 # run a full simulation + self-checks
  python tai.py new-wallet alice.key # create a wallet
  python tai.py run alice.key 50     # produce 50 blocks with that wallet
  python tai.py balance <address>    # show balance/stake from saved chain
"""
import hashlib
import heapq
import json
import os
import statistics
import sys
import tempfile
import time

from argon2.low_level import Type, hash_secret_raw
from dilithium_py.ml_dsa import ML_DSA_65  # NIST FIPS 204, post-quantum signatures

# ----------------------------------------------------------------- parameters
NAME = "Tai"
TICKER = "TAI"
CHAIN_ID = "tai-mainnet-v1"
DECIMALS = 10 ** 8
MAX_SUPPLY = 21_000_000 * DECIMALS
INITIAL_REWARD = 50 * DECIMALS
HALVING_INTERVAL = 210_000
MIN_STAKE = 100 * DECIMALS
UNSTAKE_DELAY = 20
SEED_LOOKBACK = 20  # PoS lottery seed comes from a block this many heights back
MAX_REORG_DEPTH = SEED_LOOKBACK  # Finality horizon: reject reorgs deeper than lookback
INITIAL_BITS = 6  # Argon2id is slow per hash, so far fewer bits than SHA-256
MIN_BITS = 4
MAX_BITS = 240
# PoW: Argon2id, 16 MiB, 1 pass, 1 lane -> CPU/phone (ARM64) friendly, ASIC-resistant
ARGON_MEMORY_KIB = 16 * 1024
ARGON_TIME_COST = 1
ARGON_LANES = 1
ARGON_SALT = b"tai-pow-v1-salt!"
ADJUST_INTERVAL = 10
TARGET_BLOCK_SECONDS = 20
POS_SLOT_WINDOW = 30  # Seconds per backup proposer turn before rotating
POS_FALLBACK_AFTER_TURNS = 3  # Fall back to PoW if top N elected proposers are offline
MTP_WINDOW = 11  # Median-Time-Past window to prevent timestamp manipulation
MAX_TX_PER_BLOCK = 200
MAX_BLOCK_BYTES = 1_500_000  # ~1.5 MB byte cap to bound ML-DSA-65 signature bloat
MAX_MEMPOOL_SIZE = 2_000
MIN_RELAY_FEE = 1_000  # 0.00001000 TAI anti-spam floor
MAX_FUTURE_SECONDS = 15 * 60  # Tightened from 2h to 15m to curb difficulty spoofing
GENESIS_TIME = 1763510400  # 2025-11-19
CHAIN_FILE = "tai_chain.json"

HEX_CHARS = frozenset("0123456789abcdef")
POW, POS, GENESIS = "POW", "POS", "GENESIS"


def is_strict_int(v) -> bool:
    """True only for exact int (excludes bool, which subclasses int in Python)."""
    return type(v) is int


def is_valid_address(addr: str) -> bool:
    """Addresses must be 64-character lowercase SHA-256 hex strings."""
    return isinstance(addr, str) and len(addr) == 64 and all(c in HEX_CHARS for c in addr)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def pow_hash(header: str) -> str:
    """Argon2id proof-of-work hash of a block header (hex)."""
    return hash_secret_raw(
        header.encode("utf-8"),
        ARGON_SALT,
        ARGON_TIME_COST,
        ARGON_MEMORY_KIB,
        ARGON_LANES,
        32,
        Type.ID,
    ).hex()


def fmt(units: int) -> str:
    return f"{units / DECIMALS:,.8f} {TICKER}"


def block_reward(height: int) -> int:
    return INITIAL_REWARD >> (height // HALVING_INTERVAL)


# --------------------------------------------------------------------- wallet
class Wallet:
    """Post-quantum wallet (ML-DSA-65). Address = sha256(public key)."""

    def __init__(self, pk: bytes, sk: bytes):
        self.pk, self.sk = pk, sk
        self.pubkey = pk.hex()
        self.address = hashlib.sha256(pk).hexdigest()

    @classmethod
    def new(cls):
        pk, sk = ML_DSA_65.keygen()
        return cls(pk, sk)

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls(bytes.fromhex(d["pk"]), bytes.fromhex(d["sk"]))

    def save(self, path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pk": self.pk.hex(), "sk": self.sk.hex()}, f)

    def sign(self, msg_hex: str) -> str:
        return ML_DSA_65.sign(self.sk, bytes.fromhex(msg_hex)).hex()


def verify_sig(address: str, msg_hex: str, sig_hex: str, pubkey_hex: str) -> bool:
    """Valid only if the public key hashes to `address` AND the signature checks out."""
    if not is_valid_address(address):
        return False
    if not (isinstance(msg_hex, str) and isinstance(sig_hex, str) and isinstance(pubkey_hex, str)):
        return False
    if len(pubkey_hex) > 8192 or len(sig_hex) > 16384 or len(msg_hex) != 64:
        return False
    try:
        pk = bytes.fromhex(pubkey_hex)
        if hashlib.sha256(pk).hexdigest() != address:
            return False
        return bool(ML_DSA_65.verify(pk, bytes.fromhex(msg_hex), bytes.fromhex(sig_hex)))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- transaction
class Tx:
    KINDS = ("TRANSFER", "STAKE", "UNSTAKE", "COINBASE")

    def __init__(self, kind, sender, recipient, amount, fee=0, nonce=0, sig="", pubkey="", chain_id=CHAIN_ID):
        if kind not in self.KINDS:
            raise ValueError(f"invalid tx kind: {kind}")
        if not (is_strict_int(amount) and is_strict_int(fee) and is_strict_int(nonce)):
            raise ValueError("amount, fee, and nonce must be strict integers")
        if not (isinstance(sender, str) and isinstance(recipient, str)):
            raise ValueError("sender and recipient must be strings")
        if not (isinstance(sig, str) and isinstance(pubkey, str) and isinstance(chain_id, str)):
            raise ValueError("sig, pubkey, and chain_id must be strings")

        self.kind = kind
        self.sender = sender
        self.recipient = recipient
        self.amount = amount
        self.fee = fee
        self.nonce = nonce
        self.sig = sig
        self.pubkey = pubkey
        self.chain_id = chain_id

    def body(self):
        return dict(
            chain_id=self.chain_id,
            kind=self.kind,
            sender=self.sender,
            recipient=self.recipient,
            amount=self.amount,
            fee=self.fee,
            nonce=self.nonce,
        )

    def txid(self):
        return sha256(json.dumps(self.body(), sort_keys=True))

    def byte_size(self) -> int:
        return len(json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8"))

    def sign(self, wallet: Wallet):
        self.sig = wallet.sign(self.txid())
        self.pubkey = wallet.pubkey
        return self

    def to_dict(self):
        d = self.body()
        d["sig"] = self.sig
        d["pubkey"] = self.pubkey
        return d

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise ValueError("tx payload must be a dict")
        return cls(
            d["kind"],
            d["sender"],
            d["recipient"],
            d["amount"],
            d["fee"],
            d["nonce"],
            d.get("sig", ""),
            d.get("pubkey", ""),
            d.get("chain_id", CHAIN_ID),
        )


# ---------------------------------------------------------------------- state
class State:
    def __init__(self):
        self.bal = {}
        self.nonce = {}
        self.stake = {}
        self.pending = []  # list of [unlock_height, address, amount]
        self.supply = 0

    def snapshot(self):
        s = State()
        s.bal = self.bal.copy()
        s.nonce = self.nonce.copy()
        s.stake = self.stake.copy()
        s.pending = [item[:] for item in self.pending]
        s.supply = self.supply
        return s

    def validators(self):
        return sorted((a, s) for a, s in self.stake.items() if s >= MIN_STAKE)


def select_proposer(state: State, seed_hash: str, height: int, turn: int = 0):
    vals = state.validators()
    if not vals:
        return None
    total = sum(s for _, s in vals)
    r = int(sha256(f"{CHAIN_ID}:{seed_hash}:{height}:{turn}"), 16) % total
    for addr, s in vals:
        if r < s:
            return addr
        r -= s
    return vals[-1][0]


def pos_turn_for_timestamp(blk_ts: int, tip_ts: int) -> int:
    elapsed = max(0, blk_ts - tip_ts)
    return elapsed // POS_SLOT_WINDOW


def expected_slot_kind(height: int, state: State, blk_ts: int, tip_ts: int) -> str:
    if height % 2 == 1:
        return POW
    if not state.validators():
        return POW
    if pos_turn_for_timestamp(blk_ts, tip_ts) >= POS_FALLBACK_AFTER_TURNS:
        return POW
    return POS


def apply_tx(state: State, tx: Tx, min_fee: int = 0):
    """Validate and apply a non-coinbase transaction. Raises ValueError."""
    if tx.chain_id != CHAIN_ID:
        raise ValueError("wrong chain_id")
    if tx.kind not in ("TRANSFER", "STAKE", "UNSTAKE"):
        raise ValueError("bad tx kind")
    if not is_valid_address(tx.sender):
        raise ValueError("invalid sender address")
    if tx.amount <= 0 or tx.fee < min_fee:
        raise ValueError("bad amount/fee")
    if tx.amount > MAX_SUPPLY or tx.fee > MAX_SUPPLY:
        raise ValueError("amount/fee exceeds max supply")
    if not verify_sig(tx.sender, tx.txid(), tx.sig, tx.pubkey):
        raise ValueError("bad signature")
    if tx.nonce != state.nonce.get(tx.sender, 0):
        raise ValueError("bad nonce")

    bal = state.bal.get(tx.sender, 0)
    if tx.kind == "TRANSFER":
        if not is_valid_address(tx.recipient):
            raise ValueError("invalid recipient address")
        if bal < tx.amount + tx.fee:
            raise ValueError("insufficient balance")
        state.bal[tx.sender] = bal - tx.amount - tx.fee
        state.bal[tx.recipient] = state.bal.get(tx.recipient, 0) + tx.amount
    elif tx.kind == "STAKE":
        if tx.recipient != "":
            raise ValueError("STAKE recipient must be empty")
        if bal < tx.amount + tx.fee:
            raise ValueError("insufficient balance")
        state.bal[tx.sender] = bal - tx.amount - tx.fee
        state.stake[tx.sender] = state.stake.get(tx.sender, 0) + tx.amount
    else:  # UNSTAKE
        if tx.recipient != "":
            raise ValueError("UNSTAKE recipient must be empty")
        if state.stake.get(tx.sender, 0) < tx.amount or bal < tx.fee:
            raise ValueError("insufficient stake/fee")
        state.bal[tx.sender] = bal - tx.fee
        state.stake[tx.sender] -= tx.amount
        if state.stake[tx.sender] == 0:
            del state.stake[tx.sender]
        state.pending.append([None, tx.sender, tx.amount])

    state.nonce[tx.sender] = tx.nonce + 1


# ---------------------------------------------------------------------- block
class Block:
    def __init__(self, height, prev, ts, txs, kind, producer, bits, nonce=0, sig="", hash_="", pubkey="", chain_id=CHAIN_ID):
        if not (is_strict_int(height) and is_strict_int(ts) and is_strict_int(bits) and is_strict_int(nonce)):
            raise ValueError("height, ts, bits, and nonce must be strict integers")
        if kind not in (POW, POS, GENESIS):
            raise ValueError("invalid block kind")
        if not (isinstance(prev, str) and isinstance(producer, str) and isinstance(sig, str)
                and isinstance(hash_, str) and isinstance(pubkey, str) and isinstance(chain_id, str)):
            raise ValueError("block header string fields must be strings")

        self.height = height
        self.prev = prev
        self.ts = ts
        self.txs = txs
        self.kind = kind
        self.producer = producer
        self.bits = bits
        self.nonce = nonce
        self.sig = sig
        self.hash = hash_
        self.pubkey = pubkey
        self.chain_id = chain_id

    def merkle(self):
        """
        Domain-separated Merkle root without odd-leaf duplication
        (prevents CVE-2012-2459 duplicate-tail second-preimage malleability).
        """
        if not self.txs:
            return sha256("empty-merkle")
        layer = [sha256("leaf:" + t.txid()) for t in self.txs]
        while len(layer) > 1:
            next_layer = []
            for i in range(0, len(layer) - 1, 2):
                next_layer.append(sha256("node:" + layer[i] + layer[i + 1]))
            if len(layer) % 2 == 1:
                next_layer.append(layer[-1])  # Promote odd node without duplicating
            layer = next_layer
        return layer[0]

    def header(self):
        return json.dumps(
            dict(
                cid=self.chain_id,
                h=self.height,
                p=self.prev,
                t=self.ts,
                m=self.merkle(),
                k=self.kind,
                pr=self.producer,
                b=self.bits,
                n=self.nonce,
            ),
            sort_keys=True,
        )

    def compute_hash(self):
        return sha256(self.header())

    def byte_size(self) -> int:
        return len(json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8"))

    def to_dict(self):
        return dict(
            chain_id=self.chain_id,
            height=self.height,
            prev=self.prev,
            ts=self.ts,
            kind=self.kind,
            producer=self.producer,
            bits=self.bits,
            nonce=self.nonce,
            sig=self.sig,
            hash=self.hash,
            pubkey=self.pubkey,
            txs=[t.to_dict() for t in self.txs],
        )

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or not isinstance(d.get("txs"), list):
            raise ValueError("invalid block payload")
        return cls(
            d["height"],
            d["prev"],
            d["ts"],
            [Tx.from_dict(t) for t in d["txs"]],
            d["kind"],
            d["producer"],
            d["bits"],
            d["nonce"],
            d.get("sig", ""),
            d.get("hash", ""),
            d.get("pubkey", ""),
            d.get("chain_id", CHAIN_ID),
        )


# ---------------------------------------------------------------------- chain
class Chain:
    def __init__(self):
        g = Block(0, "0" * 64, GENESIS_TIME, [], GENESIS, "", INITIAL_BITS)
        g.hash = g.compute_hash()
        self.blocks = [g]
        self.state = State()
        self.mempool = []

    @property
    def tip(self):
        return self.blocks[-1]

    def median_time_past(self) -> int:
        recent = [b.ts for b in self.blocks[-MTP_WINDOW:]]
        return int(statistics.median_low(recent))

    def seed_for(self, height: int) -> str:
        """Randomness for the PoS election at `height`: the hash of a block
        SEED_LOOKBACK heights earlier (genesis for the first few blocks)."""
        return self.blocks[max(0, height - SEED_LOOKBACK)].hash

    # -- difficulty ---------------------------------------------------------
    def next_bits(self):
        h = len(self.blocks)
        bits = self.tip.bits
        if h % ADJUST_INTERVAL == 0:
            span = self.blocks[h - 1].ts - self.blocks[h - ADJUST_INTERVAL].ts
            expected = (ADJUST_INTERVAL - 1) * TARGET_BLOCK_SECONDS
            span = max(expected // 4, min(expected * 4, span))
            if span < expected / 2:
                bits = min(MAX_BITS, bits + 1)
            elif span > expected * 2:
                bits = max(MIN_BITS, bits - 1)
        return bits

    # -- building -----------------------------------------------------------
    def build_block(self, producer: str, ts: int = None) -> Block:
        if not is_valid_address(producer):
            raise ValueError("invalid producer address")
        h = len(self.blocks)
        mtp = self.median_time_past()
        if ts is None:
            ts = max(int(time.time()), mtp + 1)

        scratch = self.state.snapshot()
        self._release_pending(scratch, h)
        kind = expected_slot_kind(h, self.state, ts, self.tip.ts)

        # Group mempool transactions per sender in strict nonce order, then use a max-heap
        # over each sender's next ready transaction so higher-fee child txs never invert nonces.
        by_sender = {}
        for tx in self.mempool:
            by_sender.setdefault(tx.sender, []).append(tx)
        for sender in by_sender:
            by_sender[sender].sort(key=lambda t: t.nonce)

        heap = []
        for sender, txs in by_sender.items():
            avg_fee = sum(t.fee for t in txs) / len(txs)
            heapq.heappush(heap, (-txs[0].fee, -avg_fee, sender, 0))

        picked, fees = [], 0
        running_bytes = 1024

        while heap and len(picked) < MAX_TX_PER_BLOCK - 1:
            _, _, sender, idx = heapq.heappop(heap)
            txs = by_sender[sender]
            tx = txs[idx]
            tx_bytes = tx.byte_size()
            if running_bytes + tx_bytes > MAX_BLOCK_BYTES:
                continue
            trial = scratch.snapshot()
            try:
                apply_tx(trial, tx, min_fee=MIN_RELAY_FEE)
                self._fix_unstake_height(trial, tx, h)
                scratch = trial
                picked.append(tx)
                fees += tx.fee
                running_bytes += tx_bytes
                if idx + 1 < len(txs):
                    rem = txs[idx + 1 :]
                    avg_fee = sum(t.fee for t in rem) / len(rem)
                    heapq.heappush(heap, (-rem[0].fee, -avg_fee, sender, idx + 1))
            except ValueError:
                continue

        reward = min(block_reward(h), MAX_SUPPLY - self.state.supply)
        cb = Tx("COINBASE", f"COINBASE:{self.tip.hash[:16]}", producer, reward + fees, 0, h)
        return Block(h, self.tip.hash, ts, [cb] + picked, kind, producer, self.next_bits())

    @staticmethod
    def _fix_unstake_height(state, tx, h):
        if tx.kind == "UNSTAKE":
            state.pending[-1][0] = h + UNSTAKE_DELAY

    @staticmethod
    def _release_pending(state, h):
        keep = []
        for unlock, addr, amt in state.pending:
            if unlock <= h:
                state.bal[addr] = state.bal.get(addr, 0) + amt
            else:
                keep.append([unlock, addr, amt])
        state.pending = keep

    def mine_pow(self, blk: Block):
        target = 1 << (256 - blk.bits)
        n = 0
        while True:
            blk.nonce = n
            if int(pow_hash(blk.header()), 16) < target:
                blk.hash = blk.compute_hash()  # sha256 block id
                return blk
            n += 1

    def forge_pos(self, blk: Block, wallet: Wallet):
        blk.hash = blk.compute_hash()
        blk.sig = wallet.sign(blk.hash)
        blk.pubkey = wallet.pubkey
        return blk

    def produce(self, wallet: Wallet, ts: int = None):
        """Produce the next block if this wallet is allowed to. Returns block or None."""
        blk = self.build_block(wallet.address, ts=ts)
        if blk.kind == POW:
            self.mine_pow(blk)
        else:
            turn = pos_turn_for_timestamp(blk.ts, self.tip.ts)
            if select_proposer(self.state, self.seed_for(blk.height), blk.height, turn) != wallet.address:
                return None
            self.forge_pos(blk, wallet)
        self.add_block(blk)
        return blk

    # -- validation ---------------------------------------------------------
    def validate(self, blk: Block) -> State:
        tip, h = self.tip, blk.height
        if blk.chain_id != CHAIN_ID:
            raise ValueError("wrong chain_id")
        if h != tip.height + 1 or blk.prev != tip.hash:
            raise ValueError("does not extend tip")
        if not is_valid_address(blk.producer):
            raise ValueError("invalid producer address")
        if blk.ts <= self.median_time_past() or blk.ts > time.time() + MAX_FUTURE_SECONDS:
            raise ValueError("bad timestamp")
        if blk.kind != expected_slot_kind(h, self.state, blk.ts, tip.ts):
            raise ValueError("wrong consensus type for this slot")
        if blk.bits != self.next_bits():
            raise ValueError("wrong difficulty")
        if blk.byte_size() > MAX_BLOCK_BYTES:
            raise ValueError("block exceeds max byte size")
        if blk.hash != blk.compute_hash():
            raise ValueError("hash mismatch")

        if blk.kind == POW:
            if blk.sig != "" or blk.pubkey != "":
                raise ValueError("PoW block must not carry PoS signature fields")
            if int(pow_hash(blk.header()), 16) >= (1 << (256 - blk.bits)):
                raise ValueError("insufficient proof of work")
        else:
            if blk.nonce != 0:
                raise ValueError("PoS block nonce must be 0")
            turn = pos_turn_for_timestamp(blk.ts, tip.ts)
            if blk.producer != select_proposer(self.state, self.seed_for(h), h, turn):
                raise ValueError("not the elected proposer")
            if not verify_sig(blk.producer, blk.hash, blk.sig, blk.pubkey):
                raise ValueError("bad proposer signature")

        if not blk.txs or len(blk.txs) > MAX_TX_PER_BLOCK:
            raise ValueError("bad tx count")
        cb, rest = blk.txs[0], blk.txs[1:]
        expected_cb_sender = f"COINBASE:{tip.hash[:16]}"
        if (
            cb.kind != "COINBASE"
            or cb.sender != expected_cb_sender
            or cb.fee != 0
            or cb.nonce != h
            or cb.sig != ""
            or cb.pubkey != ""
            or cb.chain_id != CHAIN_ID
            or any(t.kind == "COINBASE" for t in rest)
        ):
            raise ValueError("invalid coinbase transaction")

        st = self.state.snapshot()
        self._release_pending(st, h)
        fees = 0
        seen_txids = set()
        for tx in rest:
            tid = tx.txid()
            if tid in seen_txids:
                raise ValueError("duplicate transaction in block")
            seen_txids.add(tid)
            apply_tx(st, tx, min_fee=MIN_RELAY_FEE)
            self._fix_unstake_height(st, tx, h)
            fees += tx.fee

        reward = min(block_reward(h), MAX_SUPPLY - st.supply)
        if cb.recipient != blk.producer or cb.amount != reward + fees:
            raise ValueError("bad coinbase amount")
        st.bal[cb.recipient] = st.bal.get(cb.recipient, 0) + cb.amount
        st.supply += reward
        if st.supply > MAX_SUPPLY:
            raise ValueError("max supply exceeded")
        return st

    def prune_mempool(self):
        """Evict confirmed, stale-nonce, or unpayable transactions from the mempool."""
        valid = []
        sim = self.state.snapshot()
        for tx in sorted(self.mempool, key=lambda t: (t.sender, t.nonce)):
            try:
                apply_tx(sim, tx, min_fee=MIN_RELAY_FEE)
                valid.append(tx)
            except ValueError:
                continue
        self.mempool = valid

    def add_block(self, blk: Block):
        self.state = self.validate(blk)
        self.blocks.append(blk)
        used = {t.txid() for t in blk.txs}
        self.mempool = [t for t in self.mempool if t.txid() not in used]
        self.prune_mempool()

    def submit_tx(self, tx: Tx):
        if len(self.mempool) >= MAX_MEMPOOL_SIZE:
            raise ValueError("mempool full")
        tid = tx.txid()
        if any(t.txid() == tid for t in self.mempool):
            raise ValueError("duplicate transaction in mempool")

        trial = self.state.snapshot()
        sender_queued = sorted((t for t in self.mempool if t.sender == tx.sender), key=lambda t: t.nonce)
        for qtx in sender_queued:
            apply_tx(trial, qtx, min_fee=MIN_RELAY_FEE)
        apply_tx(trial, tx, min_fee=MIN_RELAY_FEE)
        self.mempool.append(tx)

    @staticmethod
    def chain_weight(blocks: list[Block]) -> tuple[int, int]:
        """
        Fork-choice weight tuple: (cumulative_work_and_pos_weight, block_count).
        PoW blocks contribute 2**bits work; canonical PoS blocks contribute
        the current tip PoW equivalent (2**bits) so valid PoS slots cannot be
        undercut by low-difficulty fallback forks.
        """
        score = 0
        for b in blocks[1:]:
            if b.kind == POW:
                score += 1 << b.bits
            elif b.kind == POS:
                score += (1 << b.bits) + 1
        return (score, len(blocks))

    def can_reorg_to(self, candidate_blocks: list[Block]) -> bool:
        """
        Bounded fork-choice rule:
        1. Rejects reorganizations deeper than MAX_REORG_DEPTH (SEED_LOOKBACK).
        2. Requires strictly heavier cumulative chain weight (not raw height).
        3. Re-validates the candidate branch from genesis.
        """
        if not candidate_blocks:
            return False
        if self.chain_weight(candidate_blocks) <= self.chain_weight(self.blocks):
            return False

        common = 0
        limit = min(len(self.blocks), len(candidate_blocks))
        while common < limit and self.blocks[common].hash == candidate_blocks[common].hash:
            common += 1
        fork_height = common - 1
        if fork_height < 0:
            return False
        reorg_depth = (len(self.blocks) - 1) - fork_height
        if reorg_depth > MAX_REORG_DEPTH:
            return False

        rebuilt = Chain()
        if candidate_blocks[0].to_dict() != rebuilt.blocks[0].to_dict():
            return False
        for blk in candidate_blocks[1:]:
            rebuilt.add_block(blk)

        self.blocks = rebuilt.blocks
        self.state = rebuilt.state
        self.prune_mempool()
        return True

    # -- persistence --------------------------------------------------------
    def save(self, path=CHAIN_FILE):
        directory = os.path.dirname(os.path.abspath(path))
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tai_chain_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([b.to_dict() for b in self.blocks], f)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    @classmethod
    def load(cls, path=CHAIN_FILE):
        c = cls()
        if not os.path.exists(path):
            return c
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            raise ValueError("corrupt chain file")
        if data[0] != c.blocks[0].to_dict():
            raise ValueError("genesis block mismatch")
        for d in data[1:]:  # fully re-validates every block
            c.add_block(Block.from_dict(d))
        return c

    def stats(self):
        pow_n = sum(1 for b in self.blocks if b.kind == POW)
        pos_n = sum(1 for b in self.blocks if b.kind == POS)
        return dict(
            height=self.tip.height,
            pow_blocks=pow_n,
            pos_blocks=pos_n,
            supply=self.state.supply,
            staked=sum(self.state.stake.values()),
            bits=self.tip.bits,
        )


# ------------------------------------------------------------------------ CLI
def demo():
    print(f"=== {NAME} ({TICKER}) hardened hybrid PoW/PoS demo ===\n")
    chain = Chain()
    alice, bob = Wallet.new(), Wallet.new()
    pending_stake = False

    for _ in range(30):
        for w, label in ((alice, "alice"), (bob, "bob")):
            blk = chain.produce(w)
            if blk:
                print(
                    f"#{blk.height:<3} {blk.kind}  by {label:<5} hash {blk.hash[:12]}…  "
                    f"bits={blk.bits}  txs={len(blk.txs)}"
                )
                break

        if not pending_stake and chain.state.bal.get(alice.address, 0) >= MIN_STAKE + DECIMALS:
            chain.submit_tx(
                Tx(
                    "STAKE",
                    alice.address,
                    "",
                    MIN_STAKE,
                    DECIMALS // 100,
                    chain.state.nonce.get(alice.address, 0),
                ).sign(alice)
            )
            pending_stake = True
            print("      -> alice stakes 100 TAI")

        if pending_stake and chain.tip.height == 12:
            base_nonce = chain.state.nonce.get(alice.address, 0) + sum(
                1 for t in chain.mempool if t.sender == alice.address
            )
            chain.submit_tx(
                Tx("TRANSFER", alice.address, bob.address, 5 * DECIMALS, MIN_RELAY_FEE, base_nonce).sign(alice)
            )
            chain.submit_tx(
                Tx("TRANSFER", alice.address, bob.address, 5 * DECIMALS, DECIMALS // 100, base_nonce + 1).sign(alice)
            )
            print("      -> alice queues 2 sequential transfers (5 TAI + 5 TAI) to bob")

    s = chain.stats()
    print("\n--- stats ---")
    for k, v in s.items():
        print(f"{k:>11}: {fmt(v) if k in ('supply', 'staked') else v}")

    # ---------------------------------------------------------- self checks
    print("\n--- self checks ---")
    kinds = [b.kind for b in chain.blocks[1:]]
    assert all(k == POW for i, k in enumerate(kinds, 1) if i % 2 == 1), "odd slots must be PoW"
    assert POS in kinds, "at least one PoS block expected"
    nxt = len(chain.blocks)
    assert chain.seed_for(nxt) == chain.blocks[nxt - SEED_LOOKBACK].hash
    assert chain.seed_for(nxt) != chain.tip.hash, "seed must not depend on newest block"
    print("ok  PoS seed is taken from an older block (miners can't grind the election)")
    print("ok  alternating slots, PoS blocks produced:", kinds.count(POS))

    # Merkle duplicate-tail resistance check (CVE-2012-2459 defense)
    sample_blk = next(b for b in chain.blocks[1:] if len(b.txs) % 2 == 1)
    mutated_txs = sample_blk.txs + [sample_blk.txs[-1]]
    mutated_blk = Block(
        sample_blk.height,
        sample_blk.prev,
        sample_blk.ts,
        mutated_txs,
        sample_blk.kind,
        sample_blk.producer,
        sample_blk.bits,
        sample_blk.nonce,
    )
    assert mutated_blk.merkle() != sample_blk.merkle()
    print("ok  Merkle tree resists duplicate-tail second-preimage malleability")

    # Verify PoS stall recovery (backup proposer rotation + PoW fallback)
    stall_chain = Chain()
    for b in chain.blocks[1:]:
        stall_chain.add_block(b)
    if len(stall_chain.blocks) % 2 == 0 and stall_chain.state.validators():
        future_ts = stall_chain.tip.ts + (POS_SLOT_WINDOW * POS_FALLBACK_AFTER_TURNS) + 1
        fallback_blk = stall_chain.produce(bob, ts=future_ts)
        assert fallback_blk is not None and fallback_blk.kind == POW
        print("ok  PoS liveness fallback recovers stalled even-height slot via PoW")

    total = (
        sum(block_reward(h) for h in range(0, 33 * HALVING_INTERVAL, HALVING_INTERVAL))
        * HALVING_INTERVAL
    )
    assert total <= MAX_SUPPLY and MAX_SUPPLY - total < 33 * HALVING_INTERVAL, total
    print(f"ok  lifetime issuance by schedule = {fmt(total)} (cap {fmt(MAX_SUPPLY)})")

    assert chain.state.supply == sum(
        b.txs[0].amount - sum(t.fee for t in b.txs[1:]) for b in chain.blocks[1:]
    )
    assert (
        sum(chain.state.bal.values())
        + sum(chain.state.stake.values())
        + sum(p[2] for p in chain.state.pending)
        == chain.state.supply
    )
    print("ok  balances + stakes == minted supply (no coins created from nothing)")

    tmp_file = os.path.join(tempfile.gettempdir(), "_tai_test.json")
    chain.save(tmp_file)
    assert Chain.load(tmp_file).tip.hash == chain.tip.hash
    print("ok  save/load re-validates the whole chain and verifies genesis")

    # Deep reorg rejection check
    deep_fork = Chain()
    assert not chain.can_reorg_to(deep_fork.blocks)
    print("ok  fork choice enforces cumulative work and bounded reorg depth")

    # Tamper rejection check
    bad = Block.from_dict(chain.tip.to_dict())
    bad.txs[0].amount += 1
    try:
        c3 = Chain()
        for b in chain.blocks[1:-1]:
            c3.add_block(b)
        c3.add_block(bad)
        raise SystemExit("FAIL: tampered block accepted")
    except ValueError as e:
        print("ok  tampered block rejected:", e)

    # Cross-chain replay rejection check
    w1, w2 = Wallet.new(), Wallet.new()
    foreign_tx = Tx("TRANSFER", w1.address, w2.address, 100, MIN_RELAY_FEE, 0, chain_id="tai-testnet-v1").sign(w1)
    test_state = State()
    test_state.bal[w1.address] = 10_000
    try:
        apply_tx(test_state, foreign_tx)
        raise SystemExit("FAIL: cross-chain tx accepted")
    except ValueError as e:
        print("ok  cross-chain replay rejected:", e)

    # Post-quantum signature check
    m = sha256("x")
    sg = w1.sign(m)
    assert verify_sig(w1.address, m, sg, w1.pubkey)
    assert not verify_sig(w2.address, m, sg, w2.pubkey)
    assert not verify_sig(w1.address, m, sg, w2.pubkey)
    print("ok  ML-DSA-65 post-quantum signatures verify; forgeries rejected")

    # Halving check
    assert block_reward(0) == 50 * DECIMALS
    assert block_reward(HALVING_INTERVAL) == 25 * DECIMALS
    assert block_reward(HALVING_INTERVAL * 64) == 0
    print("ok  halving schedule 50 -> 25 -> 12.5 ... -> 0")
    print("\nAll checks passed.")


def run(keyfile, n):
    w = Wallet.load(keyfile)
    chain = Chain.load()
    print(f"Producing up to {n} blocks as {w.address[:16]}…  (start height {chain.tip.height})")
    made = 0
    while made < n:
        blk = chain.produce(w)
        if blk:
            made += 1
            print(f"#{blk.height} {blk.kind} {blk.hash[:12]}… reward→{fmt(blk.txs[0].amount)}")
            chain.save()
        else:
            time.sleep(1)
    print(chain.stats())


def main(argv):
    if len(argv) < 2:
        print(__doc__)
    elif argv[1] == "demo":
        demo()
    elif argv[1] == "new-wallet" and len(argv) == 3:
        w = Wallet.new()
        w.save(argv[2])
        print("address:", w.address)
    elif argv[1] == "run" and len(argv) == 4:
        run(argv[2], int(argv[3]))
    elif argv[1] == "balance" and len(argv) == 3:
        c = Chain.load()
        print("balance:", fmt(c.state.bal.get(argv[2], 0)))
        print("staked :", fmt(c.state.stake.get(argv[2], 0)))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)