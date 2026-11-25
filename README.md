# TaiChain (TAI) — Post-Quantum Hybrid PoW/PoS Blockchain

**TaiChain** is a quantum-resistant Layer-1 cryptocurrency combining memory-hard **Argon2id Proof-of-Work** with **NIST FIPS 204 ML-DSA-65 (Dilithium3) Proof-of-Stake**, accompanied by the **TAI.SPACE** real-time block explorer and the **TaiMask v3** multi-chain browser wallet.

---

## Core Protocol Specifications

| Parameter | Specification |
| :--- | :--- |
| **Chain ID** | `tai-mainnet-v1` |
| **Consensus Mechanism** | Hybrid Alternating **PoW** (Odd Heights) & **PoS** (Even Heights) |
| **PoW Hash Algorithm** | Argon2id (`16 MiB` memory cost) |
| **Post-Quantum Signatures** | NIST FIPS 204 **ML-DSA-65** (`dilithium-py`) |
| **Max Supply** | `21,000,000 TAI` (`1 TAI = 10^8` base units) |
| **Initial Block Reward** | `50.00 TAI` (Halving every `210,000` blocks) |
| **Target Block Time** | `~20.0 seconds` |
| **Minimum PoS Validator Stake** | `100.00 TAI` (`20-block` unbonding delay) |

---

## Project Structure

* **`tai.py`** — Core consensus engine, Argon2id PoW verification, ML-DSA-65 post-quantum wallet & transaction signing, and UTXO/account state ledger.
* **`node.py`** — Peer-to-peer HTTP/JSON full node, mempool manager, and hybrid PoW/PoS block producer.
* **`wallet.py`** — CLI wallet utility for generating `.key` pairs, checking balances, sending `TRANSFER` transactions, and managing `STAKE` / `UNSTAKE` operations.
* **`explorer-v3.py`** — **TAI.SPACE** block explorer featuring 3D isometric mempool/block cubes, live fee-rate spreads, validator distribution charts, and mempool/confirmed transaction feeds.
* **`taimask_vault.py`** — Local encrypted seed vault & multi-chain RPC signer (`127.0.0.1:18095`) deriving deterministic addresses from a single 12-word recovery phrase across **Tai Mainnet**, **Bitcoin**, **Ethereum**, **Optimism**, **Base**, **Solana**, **Dogecoin**, **Litecoin**, and **90+ EVM chains**.
* **`tai-metamask-extension-v3/`** — Chrome/Edge/Kiwi right-sidebar browser extension UI for TaiMask v3.
* **`mobile_wallet.py`** — Lightweight mobile wallet server optimized for Android Termux.
* **`render.yaml`** — Cloud deployment blueprint for running a 24/7 public seed node.

---

## Quick Start (Desktop: Windows / Linux / macOS)

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/surharntai25-wq/taichain.git
cd taichain
pip install -r requirements.txt
```
*(Optional: install `eth-account` via `pip install eth-account` to enable raw EVM transaction broadcasting in TaiMask v3.)*

### 2. Create a Validator / Miner Key & Start Your Node
```bash
# Generate a post-quantum ML-DSA-65 keypair
python wallet.py new alice.key

# Start the node and begin hybrid PoW/PoS block production
python node.py --port 8001 --db tai_chain.json --wallet alice.key --mine
```

### 3. Launch the TAI.SPACE Block Explorer
Open a second terminal in the same directory:
```bash
python explorer-v3.py --node http://127.0.0.1:8001 --port 8080
```
Open **`http://127.0.0.1:8080`** in your browser.

### 4. Launch TaiMask v3 Vault & Browser Extension
Open a third terminal:
```bash
python taimask_vault.py --node http://127.0.0.1:8001 --host 127.0.0.1 --port 18095
```
1. Open Chrome or Edge and navigate to `chrome://extensions`.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `tai-metamask-extension-v3` folder.
4. Pin **TaiMask** and click its icon to open the right-sidebar multi-chain wallet.

---

## Running a Node & Miner on Android (ARM64 via Termux)

1. Install **Termux** (`arm64-v8a`) and run:
   ```bash
   pkg update && pkg upgrade -y
   pkg install -y python clang libffi openssl git
   pip install -U pip setuptools wheel
   ARGON2_CFFI_USE_SSE2=0 pip install argon2-cffi dilithium-py
   ```
2. Clone the repository and start mining:
   ```bash
   git clone https://github.com/surharntai25-wq/taichain.git
   cd taichain
   python wallet.py new mobile.key
   termux-wake-lock
   python node.py --host 0.0.0.0 --port 8001 --db mobile_chain.json --wallet mobile.key --mine
   ```

---

## CLI Wallet Commands (`wallet.py`)

```bash
# Check balance, staked amount, and nonce
python wallet.py balance <ADDRESS_OR_KEYFILE>

# Send TAI to another address
python wallet.py send alice.key <RECIPIENT_64_HEX> 100

# Stake TAI (minimum 100 TAI to activate PoS slot eligibility)
python wallet.py stake alice.key 100

# Unstake TAI (releases to available balance after a 20-block unbonding delay)
python wallet.py unstake alice.key 100
```

---

## Security Notice

Never commit `*.key` files, `taimask_vault.json`, or `*_chain.json` databases to version control. Always back up your `.key` files and your 12-word Secret Recovery Phrase offline.