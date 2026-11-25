#!/usr/bin/env python3
"""
Tai (TAI) Mobile-Friendly Lite Wallet Web App (`mobile_wallet.py`)

A self-contained, touch-friendly Progressive Web App (PWA) & mobile wallet server
designed for Android phones/tablets. Connects directly to your running `node.py`
RPC endpoint to check balances, copy/share addresses, and sign/broadcast
`TRANSFER`, `STAKE`, and `UNSTAKE` transactions using ML-DSA-65 post-quantum keys.

Usage (PC on same Wi-Fi OR directly inside Termux on Android):
  python mobile_wallet.py --node http://127.0.0.1:8001 --wallet alice.key --host 0.0.0.0 --port 8090
  Then open http://<YOUR_PC_LAN_IP>:8090 on your Android browser (or http://127.0.0.1:8090 in Termux)
  and tap "Add to Home screen" to install as an Android app!
"""
import argparse
import decimal
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import tai

MANIFEST_JSON = json.dumps({
    "name": "Tai Lite Wallet",
    "short_name": "TaiWallet",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#090d16",
    "theme_color": "#0f172a",
    "description": "Post-Quantum ML-DSA-65 Lite Wallet for Tai (TAI)",
    "icons": [
        {
            "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'%3E%3Crect width='128' height='128' rx='28' fill='%2338bdf8'/%3E%3Ctext x='64' y='84' font-family='sans-serif' font-size='64' font-weight='bold' text-anchor='middle' fill='%23090d16'%3ET%3C/text%3E%3C/svg%3E",
            "sizes": "128x128",
            "type": "image/svg+xml"
        }
    ]
})

MOBILE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <meta name="theme-color" content="#0f172a" />
  <meta name="mobile-web-app-capable" content="yes" />
  <link rel="manifest" href="/manifest.json" />
  <title>Tai Lite Wallet</title>
  <style>
    :root {
      --bg: #090d16;
      --card: #131b2e;
      --card-2: #1a243b;
      --border: #26334d;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --green: #10b981;
      --amber: #f59e0b;
      --red: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      max-width: 480px;
      margin: 0 auto;
      padding: 16px 16px 84px;
      min-height: 100vh;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }
    .title { font-size: 1.2rem; font-weight: 800; display: flex; align-items: center; gap: 8px; }
    .pill {
      font-size: 0.72rem;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 999px;
      background: rgba(56, 189, 248, 0.16);
      color: var(--accent);
      border: 1px solid rgba(56, 189, 248, 0.35);
    }
    .status {
      font-size: 0.78rem;
      color: var(--muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); }
    .dot.off { background: var(--red); }
    .balance-card {
      background: linear-gradient(145deg, #16223b, #0f172a);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 16px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.35);
    }
    .bal-label { font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
    .bal-main { font-size: 2rem; font-weight: 800; margin: 6px 0 12px; letter-spacing: -0.02em; }
    .bal-sub {
      display: flex;
      justify-content: space-between;
      font-size: 0.85rem;
      color: var(--muted);
      padding-top: 12px;
      border-top: 1px solid rgba(255,255,255,0.08);
    }
    .addr-box {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 16px;
    }
    .addr-text {
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .btn-sm {
      background: var(--card-2);
      color: var(--accent);
      border: 1px solid var(--border);
      padding: 7px 12px;
      border-radius: 10px;
      font-weight: 700;
      font-size: 0.8rem;
      cursor: pointer;
      white-space: nowrap;
    }
    .tabs {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      background: var(--card);
      padding: 6px;
      border-radius: 14px;
      border: 1px solid var(--border);
      margin-bottom: 16px;
    }
    .tab {
      background: transparent;
      border: none;
      color: var(--muted);
      padding: 10px 6px;
      border-radius: 10px;
      font-weight: 700;
      font-size: 0.88rem;
      cursor: pointer;
    }
    .tab.active {
      background: var(--accent);
      color: #08101e;
    }
    .panel {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      margin-bottom: 16px;
    }
    .field { margin-bottom: 14px; }
    .field label { display: block; font-size: 0.8rem; color: var(--muted); margin-bottom: 6px; font-weight: 600; }
    .field input {
      width: 100%;
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 13px 14px;
      border-radius: 12px;
      font-size: 1rem;
      outline: none;
    }
    .field input:focus { border-color: var(--accent); }
    .btn-primary {
      width: 100%;
      background: var(--accent);
      color: #08101e;
      border: none;
      padding: 14px;
      border-radius: 12px;
      font-size: 1rem;
      font-weight: 800;
      cursor: pointer;
    }
    .btn-primary:disabled { opacity: 0.5; }
    .toast {
      padding: 12px 14px;
      border-radius: 12px;
      font-size: 0.85rem;
      margin-bottom: 14px;
      display: none;
      word-break: break-all;
    }
    .toast.ok { background: rgba(16,185,129,0.16); border: 1px solid rgba(16,185,129,0.45); color: #6ee7b7; }
    .toast.err { background: rgba(239,68,68,0.16); border: 1px solid rgba(239,68,68,0.45); color: #fca5a5; }
    .tx-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 11px 0;
      border-bottom: 1px solid var(--border);
      font-size: 0.86rem;
    }
    .tx-item:last-child { border-bottom: none; }
    .tx-kind { font-weight: 700; }
    .tx-meta { font-size: 0.75rem; color: var(--muted); font-family: ui-monospace, monospace; }
    .amt-in { color: var(--green); font-weight: 700; }
    .amt-out { color: var(--amber); font-weight: 700; }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="title">Tai Wallet <span class="pill">ML-DSA-65</span></div>
    <div class="status"><span id="dot" class="dot"></span><span id="heightLabel">Syncing...</span></div>
  </div>

  <div class="balance-card">
    <div class="bal-label">Available Balance</div>
    <div class="bal-main" id="balMain">0.00 TAI</div>
    <div class="bal-sub">
      <span>Staked: <strong id="balStaked" style="color:var(--green)">0.00 TAI</strong></span>
      <span>Nonce: <strong id="balNonce">0</strong></span>
    </div>
  </div>

  <div class="addr-box">
    <div class="addr-text" id="myAddr">Loading address...</div>
    <button class="btn-sm" onclick="copyAddr()">Copy</button>
  </div>

  <div id="toast" class="toast"></div>

  <div class="tabs">
    <button class="tab active" id="tabSend" onclick="switchTab('send')">Send</button>
    <button class="tab" id="tabStake" onclick="switchTab('stake')">Stake</button>
    <button class="tab" id="tabUnstake" onclick="switchTab('unstake')">Unstake</button>
  </div>

  <div class="panel" id="formPanel">
    <div class="field" id="recipientField">
      <label>Recipient Address (64-char hex)</label>
      <input id="recipientInput" type="text" placeholder="Paste destination TAI address..." autocomplete="off" />
    </div>
    <div class="field">
      <label id="amountLabel">Amount (TAI)</label>
      <input id="amountInput" type="number" step="0.00000001" min="0.00000001" placeholder="0.00" />
    </div>
    <div class="field">
      <label>Network Fee (TAI)</label>
      <input id="feeInput" type="number" step="0.00000001" min="0.00001" value="0.00001" />
    </div>
    <button class="btn-primary" id="submitBtn" onclick="submitAction()">Send TAI</button>
  </div>

  <div class="panel">
    <div style="font-weight:700; margin-bottom:8px; font-size:0.92rem;">Recent Activity</div>
    <div id="txList"><div style="color:var(--muted); font-size:0.84rem;">Loading...</div></div>
  </div>

  <script>
    let activeTab = "send";
    let fullAddress = "";

    function showToast(msg, ok = true) {
      const t = document.getElementById("toast");
      t.textContent = msg;
      t.className = "toast " + (ok ? "ok" : "err");
      t.style.display = "block";
    }

    function switchTab(tab) {
      activeTab = tab;
      document.getElementById("tabSend").className = "tab" + (tab === "send" ? " active" : "");
      document.getElementById("tabStake").className = "tab" + (tab === "stake" ? " active" : "");
      document.getElementById("tabUnstake").className = "tab" + (tab === "unstake" ? " active" : "");

      const recField = document.getElementById("recipientField");
      const btn = document.getElementById("submitBtn");
      const lbl = document.getElementById("amountLabel");

      if (tab === "send") {
        recField.style.display = "block";
        lbl.textContent = "Amount to Send (TAI)";
        btn.textContent = "Send TAI";
      } else if (tab === "stake") {
        recField.style.display = "none";
        lbl.textContent = "Amount to Stake (Min 100 TAI for PoS)";
        btn.textContent = "Stake TAI";
      } else {
        recField.style.display = "none";
        lbl.textContent = "Amount to Unstake (20-block delay)";
        btn.textContent = "Unstake TAI";
      }
    }

    async function copyAddr() {
      if (!fullAddress) return;
      try {
        await navigator.clipboard.writeText(fullAddress);
        showToast("Address copied to clipboard!");
      } catch {
        showToast("Address: " + fullAddress, true);
      }
    }

    async function refreshWallet() {
      try {
        const res = await fetch("/api/wallet");
        if (!res.ok) throw new Error("offline");
        const d = await res.json();

        fullAddress = d.address;
        document.getElementById("myAddr").textContent = d.address;
        document.getElementById("balMain").textContent = d.balance_formatted;
        document.getElementById("balStaked").textContent = d.staked_formatted;
        document.getElementById("balNonce").textContent = d.nonce;
        document.getElementById("dot").className = "dot";
        document.getElementById("heightLabel").textContent = "Block #" + d.height;

        const list = document.getElementById("txList");
        if (!d.history || d.history.length === 0) {
          list.innerHTML = '<div style="color:var(--muted); font-size:0.84rem;">No transactions yet</div>';
        } else {
          list.innerHTML = d.history.map(item => {
            const isIn = item.role === "IN" || item.role === "REWARD";
            const sign = isIn ? "+" : "-";
            const cls = isIn ? "amt-in" : "amt-out";
            const amt = (item.amount / 1e8).toLocaleString(undefined, { maximumFractionDigits: 6 });
            return `
              <div class="tx-item">
                <div>
                  <div class="tx-kind">${item.kind} <span style="color:var(--muted); font-weight:400;">#${item.height}</span></div>
                  <div class="tx-meta">${item.txid.slice(0, 14)}…</div>
                </div>
                <div class="${cls}">${sign}${amt} TAI</div>
              </div>
            `;
          }).join("");
        }
      } catch {
        document.getElementById("dot").className = "dot off";
        document.getElementById("heightLabel").textContent = "Node Offline";
      }
    }

    async function submitAction() {
      const btn = document.getElementById("submitBtn");
      const amount = document.getElementById("amountInput").value.trim();
      const fee = document.getElementById("feeInput").value.trim();
      const recipient = document.getElementById("recipientInput").value.trim();

      if (!amount || Number(amount) <= 0) {
        showToast("Enter a valid TAI amount.", false);
        return;
      }

      btn.disabled = true;
      try {
        const res = await fetch("/api/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: activeTab, recipient, amount, fee })
        });
        const out = await res.json();
        if (!res.ok || !out.ok) {
          throw new Error(out.error || "Transaction failed");
        }
        showToast("Broadcasted! TxID: " + out.txid);
        document.getElementById("amountInput").value = "";
        refreshWallet();
      } catch (e) {
        showToast(e.message, false);
      } finally {
        btn.disabled = false;
      }
    }

    refreshWallet();
    setInterval(refreshWallet, 3000);
  </script>
</body>
</html>
"""


def parse_units(amount_str: str) -> int:
    val = decimal.Decimal(str(amount_str))
    if val <= 0:
        raise ValueError("amount must be greater than 0")
    scaled = val * tai.DECIMALS
    if scaled != int(scaled):
        raise ValueError("TAI supports at most 8 decimal places")
    return int(scaled)


def node_get(node_url: str, path: str) -> dict:
    req = urllib.request.Request(f"{node_url}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def node_post(node_url: str, path: str, payload: dict) -> dict:
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{node_url}{path}", data=raw, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(e.read().decode("utf-8", errors="replace"))


def main():
    parser = argparse.ArgumentParser(description="Tai (TAI) Android/Mobile Lite Wallet PWA")
    parser.add_argument("--wallet", default="mobile.key", help="Wallet keyfile path (auto-created if missing)")
    parser.add_argument("--node", default="http://127.0.0.1:8001", help="Running Tai node RPC URL")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (0.0.0.0 allows Android LAN access)")
    parser.add_argument("--port", type=int, default=8090, help="Bind port (default: 8090)")
    args = parser.parse_args()

    node_url = args.node.rstrip("/")
    if os.path.exists(args.wallet):
        wallet = tai.Wallet.load(args.wallet)
    else:
        wallet = tai.Wallet.new()
        wallet.save(args.wallet)
        print(f"[WALLET] Created new ML-DSA-65 mobile wallet -> {args.wallet}")

    print(f"[WALLET] Address: {wallet.address}")

    class MobileWalletHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt_str, *args):
            pass

        def _send(self, code: int, content_type: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            try:
                if path == "/":
                    self._send(200, "text/html; charset=utf-8", MOBILE_HTML.encode("utf-8"))
                elif path == "/manifest.json":
                    self._send(200, "application/manifest+json", MANIFEST_JSON.encode("utf-8"))
                elif path == "/api/wallet":
                    stats = node_get(node_url, "/stats")
                    bal = node_get(node_url, f"/balance/{wallet.address}")
                    blocks = node_get(node_url, "/chain").get("blocks", [])

                    history = []
                    for b in reversed(blocks):
                        for t in reversed(b.get("txs", [])):
                            tx_obj = tai.Tx.from_dict(t)
                            role = None
                            if t["sender"] == wallet.address:
                                role = "OUT"
                            elif t["recipient"] == wallet.address:
                                role = "REWARD" if t["kind"] == "COINBASE" else "IN"
                            if role:
                                history.append({
                                    "txid": tx_obj.txid(),
                                    "height": b["height"],
                                    "kind": t["kind"],
                                    "role": role,
                                    "amount": t["amount"],
                                })
                        if len(history) >= 20:
                            break

                    payload = {
                        "address": wallet.address,
                        "height": stats.get("height", 0),
                        "balance": bal["balance"],
                        "balance_formatted": bal["balance_formatted"],
                        "staked": bal["staked"],
                        "staked_formatted": bal["staked_formatted"],
                        "nonce": bal["nonce"],
                        "history": history[:20],
                    }
                    self._send(200, "application/json", json.dumps(payload).encode("utf-8"))
                else:
                    self._send(404, "application/json", b'{"error":"not found"}')
            except Exception as e:
                self._send(502, "application/json", json.dumps({"error": str(e)}).encode("utf-8"))

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/")
            if path != "/api/action":
                self._send(404, "application/json", b'{"error":"not found"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                action = data.get("action")
                amount_units = parse_units(data.get("amount", "0"))
                fee_units = parse_units(data.get("fee", "0.00001"))

                bal = node_get(node_url, f"/balance/{wallet.address}")
                pool = node_get(node_url, "/mempool").get("txs", [])
                queued = sum(1 for t in pool if t.get("sender") == wallet.address)
                nonce = bal["nonce"] + queued

                if action == "send":
                    recipient = data.get("recipient", "").strip().lower()
                    if not tai.is_valid_address(recipient):
                        raise ValueError("Invalid 64-character hex recipient address")
                    tx = tai.Tx("TRANSFER", wallet.address, recipient, amount_units, fee_units, nonce).sign(wallet)
                elif action == "stake":
                    tx = tai.Tx("STAKE", wallet.address, "", amount_units, fee_units, nonce).sign(wallet)
                elif action == "unstake":
                    tx = tai.Tx("UNSTAKE", wallet.address, "", amount_units, fee_units, nonce).sign(wallet)
                else:
                    raise ValueError("Unknown action")

                res = node_post(node_url, "/tx", {"tx": tx.to_dict()})
                self._send(200, "application/json", json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._send(400, "application/json", json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))

    server = ThreadingHTTPServer((args.host, args.port), MobileWalletHandler)
    print(f"[MOBILE] Tai Lite Wallet running on http://{args.host}:{args.port} (node={node_url})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down mobile wallet...")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
