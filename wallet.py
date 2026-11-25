#!/usr/bin/env python3
"""
Tai (TAI) CLI Wallet Client (`wallet.py`)

Constructs, signs (ML-DSA-65), and broadcasts `TRANSFER`, `STAKE`, and `UNSTAKE`
transactions to a running `node.py` RPC server, and queries live balances.

Usage
-----
  # Check live balance, stake, and nonce from the running node:
  python wallet.py balance alice.key --node http://127.0.0.1:8001

  # Stake 100 TAI to become an active PoS validator on even-height blocks:
  python wallet.py stake alice.key 100 --node http://127.0.0.1:8001

  # Send 25.5 TAI to another address:
  python wallet.py send alice.key <recipient_address> 25.5 --node http://127.0.0.1:8001

  # Unstake 100 TAI (unlocks after 20 blocks):
  python wallet.py unstake alice.key 100 --node http://127.0.0.1:8001
"""
import argparse
import decimal
import json
import sys
import urllib.error
import urllib.request

import tai


def parse_tai_to_units(amount_str: str) -> int:
    """Convert a human-readable TAI decimal string (e.g. '100' or '25.5') into integer base units."""
    try:
        val = decimal.Decimal(amount_str)
    except decimal.InvalidOperation:
        raise ValueError(f"invalid TAI amount: {amount_str}")
    if val <= 0:
        raise ValueError("amount must be greater than 0")
    scaled = val * tai.DECIMALS
    if scaled != int(scaled):
        raise ValueError("TAI supports at most 8 decimal places")
    return int(scaled)


def rpc_get(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rpc_post(url: str, payload: dict) -> dict:
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Node rejected transaction ({e.code}): {err_body}")


def get_account_info(node_url: str, address: str) -> dict:
    return rpc_get(f"{node_url.rstrip('/')}/balance/{address}")


def get_next_nonce(node_url: str, address: str, confirmed_nonce: int) -> int:
    """Account for any transactions already queued in the node's mempool."""
    pool = rpc_get(f"{node_url.rstrip('/')}/mempool").get("txs", [])
    queued = sum(1 for t in pool if t.get("sender") == address)
    return confirmed_nonce + queued


def main():
    parser = argparse.ArgumentParser(description="Tai (TAI) CLI Wallet Client")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bal = sub.add_parser("balance", help="Query live balance and stake from node")
    p_bal.add_argument("keyfile", help="Path to wallet .key file")
    p_bal.add_argument("--node", default="http://127.0.0.1:8001", help="Node RPC URL")

    p_send = sub.add_parser("send", help="Send TAI to another address")
    p_send.add_argument("keyfile", help="Sender wallet .key file")
    p_send.add_argument("recipient", help="64-char hex recipient address")
    p_send.add_argument("amount", help="Amount in TAI (e.g. 10 or 2.5)")
    p_send.add_argument("--fee", default="0.00001", help="Fee in TAI (default: 0.00001)")
    p_send.add_argument("--node", default="http://127.0.0.1:8001", help="Node RPC URL")

    p_stake = sub.add_parser("stake", help="Stake TAI to become a PoS validator (min 100 TAI)")
    p_stake.add_argument("keyfile", help="Validator wallet .key file")
    p_stake.add_argument("amount", help="Amount to stake in TAI (e.g. 100)")
    p_stake.add_argument("--fee", default="0.00001", help="Fee in TAI (default: 0.00001)")
    p_stake.add_argument("--node", default="http://127.0.0.1:8001", help="Node RPC URL")

    p_unstake = sub.add_parser("unstake", help="Unstake TAI (unlocks after 20 blocks)")
    p_unstake.add_argument("keyfile", help="Validator wallet .key file")
    p_unstake.add_argument("amount", help="Amount to unstake in TAI (e.g. 100)")
    p_unstake.add_argument("--fee", default="0.00001", help="Fee in TAI (default: 0.00001)")
    p_unstake.add_argument("--node", default="http://127.0.0.1:8001", help="Node RPC URL")

    args = parser.parse_args()
    w = tai.Wallet.load(args.keyfile)
    node_url = args.node.rstrip("/")

    if args.cmd == "balance":
        info = get_account_info(node_url, w.address)
        print(f"Address : {w.address}")
        print(f"Balance : {info['balance_formatted']}")
        print(f"Staked  : {info['staked_formatted']}")
        print(f"Nonce   : {info['nonce']}")
        return

    amount_units = parse_tai_to_units(args.amount)
    fee_units = parse_tai_to_units(args.fee)
    info = get_account_info(node_url, w.address)
    nonce = get_next_nonce(node_url, w.address, info["nonce"])

    if args.cmd == "send":
        if not tai.is_valid_address(args.recipient):
            raise SystemExit("Error: recipient must be a 64-character lowercase hex address")
        tx = tai.Tx("TRANSFER", w.address, args.recipient, amount_units, fee_units, nonce).sign(w)
    elif args.cmd == "stake":
        if info["staked"] + amount_units < tai.MIN_STAKE:
            print(f"Warning: total stake will be below minimum validator threshold ({tai.fmt(tai.MIN_STAKE)})")
        tx = tai.Tx("STAKE", w.address, "", amount_units, fee_units, nonce).sign(w)
    elif args.cmd == "unstake":
        tx = tai.Tx("UNSTAKE", w.address, "", amount_units, fee_units, nonce).sign(w)

    res = rpc_post(f"{node_url}/tx", {"tx": tx.to_dict()})
    print(f"Submitted {tx.kind} ({tai.fmt(amount_units)}, fee={tai.fmt(fee_units)}, nonce={nonce})")
    print(f"TxID : {res.get('txid')}")
    print(f"Node : {res}")


if __name__ == "__main__":
    main()
