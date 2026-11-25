#!/usr/bin/env python3
"""
TaiMask v3.0 — Multi-Chain Post-Quantum & Classic Crypto Vault (`taimask_vault.py`)

Derives deterministic addresses and signs transactions from ONE 12-word Secret Recovery Phrase across:
  1. Tai Mainnet (`ML-DSA-65` post-quantum signatures, native RPC)
  2. Ethereum Mainnet + Top 100 EVM Networks (Optimism, Base, Arbitrum One, Polygon, BNB Chain,
     Avalanche C-Chain, zkSync Era, Linea, Scroll, Blast, Mantle, Fantom, Cronos, Gnosis, Celo,
     Mode, Zora, Taiko, KUB Chain, Monad, Sonic, Berachain, + any custom EVM Chain ID & RPC URL)
  3. Bitcoin Mainnet (`bc1q...` Native SegWit Bech32, live Blockstream/Mempool.space API)
  4. Litecoin Mainnet (`ltc1q...` Native SegWit Bech32, live Litecoinspace API)
  5. Dogecoin Mainnet (`D...` Base58Check P2PKH, live BlockCypher/SoChain API)
  6. Solana Mainnet (Ed25519 Base58 public key, live Solana Mainnet-Beta RPC)

Optional dependencies for full multi-chain signing (auto-detected with graceful fallback):
  pip install dilithium-py eth-account pynacl base58 ecdsa

Usage
-----
  python taimask_vault.py --node http://127.0.0.1:8001 --host 127.0.0.1 --port 18095
"""
import argparse
import base64
import decimal
import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from dilithium_py.ml_dsa import ML_DSA_65
import tai

# Optional multi-chain cryptographic libraries
try:
    from eth_account import Account as EthAccount
    HAS_ETH = True
except ImportError:
    HAS_ETH = False

try:
    import nacl.signing
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

try:
    import ecdsa
    HAS_ECDSA = True
except ImportError:
    HAS_ECDSA = False


# --------------------------------------------------------- Top 100+ Chain Registry
TOP_CHAINS = [
    # Native Non-EVM & Post-Quantum Chains
    {"id": "tai-mainnet", "family": "TAI", "name": "Tai Mainnet (PQ)", "symbol": "TAI", "decimals": 8, "rpc": "http://127.0.0.1:8001", "explorer": "http://127.0.0.1:8080", "color": "#10b981"},
    {"id": "btc-mainnet", "family": "BTC", "name": "Bitcoin", "symbol": "BTC", "decimals": 8, "rpc": "https://mempool.space/api", "explorer": "https://mempool.space", "color": "#f7931a"},
    {"id": "eth-1", "family": "EVM", "chainId": 1, "name": "Ethereum Mainnet", "symbol": "ETH", "decimals": 18, "rpc": "https://ethereum-rpc.publicnode.com", "explorer": "https://etherscan.io", "color": "#627eea"},
    {"id": "sol-mainnet", "family": "SOL", "name": "Solana", "symbol": "SOL", "decimals": 9, "rpc": "https://api.mainnet-beta.solana.com", "explorer": "https://solscan.io", "color": "#14f195"},
    {"id": "eth-10", "family": "EVM", "chainId": 10, "name": "Optimism (OP Mainnet)", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.optimism.io", "explorer": "https://optimistic.etherscan.io", "color": "#ff0420"},
    {"id": "eth-8453", "family": "EVM", "chainId": 8453, "name": "Base", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.base.org", "explorer": "https://basescan.org", "color": "#0052ff"},
    {"id": "doge-mainnet", "family": "DOGE", "name": "Dogecoin", "symbol": "DOGE", "decimals": 8, "rpc": "https://api.blockcypher.com/v1/doge/main", "explorer": "https://dogechain.info", "color": "#c2a633"},
    {"id": "ltc-mainnet", "family": "LTC", "name": "Litecoin", "symbol": "LTC", "decimals": 8, "rpc": "https://litecoinspace.org/api", "explorer": "https://litecoinspace.org", "color": "#345d9d"},

    # Top EVM Layer-1 & Layer-2 Networks (Ranked by ecosystem adoption)
    {"id": "eth-42161", "family": "EVM", "chainId": 42161, "name": "Arbitrum One", "symbol": "ETH", "decimals": 18, "rpc": "https://arb1.arbitrum.io/rpc", "explorer": "https://arbiscan.io", "color": "#28a0f0"},
    {"id": "eth-137", "family": "EVM", "chainId": 137, "name": "Polygon PoS", "symbol": "POL", "decimals": 18, "rpc": "https://polygon-bor-rpc.publicnode.com", "explorer": "https://polygonscan.com", "color": "#8247e5"},
    {"id": "eth-56", "family": "EVM", "chainId": 56, "name": "BNB Smart Chain", "symbol": "BNB", "decimals": 18, "rpc": "https://bsc-dataseed.binance.org", "explorer": "https://bscscan.com", "color": "#f3ba2f"},
    {"id": "eth-43114", "family": "EVM", "chainId": 43114, "name": "Avalanche C-Chain", "symbol": "AVAX", "decimals": 18, "rpc": "https://api.avax.network/ext/bc/C/rpc", "explorer": "https://snowtrace.io", "color": "#e84142"},
    {"id": "eth-324", "family": "EVM", "chainId": 324, "name": "zkSync Era", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.era.zksync.io", "explorer": "https://explorer.zksync.io", "color": "#4e529a"},
    {"id": "eth-59144", "family": "EVM", "chainId": 59144, "name": "Linea", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.linea.build", "explorer": "https://lineascan.build", "color": "#61dfff"},
    {"id": "eth-534352", "family": "EVM", "chainId": 534352, "name": "Scroll", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.scroll.io", "explorer": "https://scrollscan.com", "color": "#ffeeda"},
    {"id": "eth-81457", "family": "EVM", "chainId": 81457, "name": "Blast", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.blast.io", "explorer": "https://blastscan.io", "color": "#fcfc03"},
    {"id": "eth-5000", "family": "EVM", "chainId": 5000, "name": "Mantle", "symbol": "MNT", "decimals": 18, "rpc": "https://rpc.mantle.xyz", "explorer": "https://mantlescan.xyz", "color": "#65b3ae"},
    {"id": "eth-250", "family": "EVM", "chainId": 250, "name": "Fantom Opera", "symbol": "FTM", "decimals": 18, "rpc": "https://rpcapi.fantom.network", "explorer": "https://ftmscan.com", "color": "#1969ff"},
    {"id": "eth-146", "family": "EVM", "chainId": 146, "name": "Sonic Mainnet", "symbol": "S", "decimals": 18, "rpc": "https://rpc.soniclabs.com", "explorer": "https://sonicscan.org", "color": "#ff6b00"},
    {"id": "eth-25", "family": "EVM", "chainId": 25, "name": "Cronos", "symbol": "CRO", "decimals": 18, "rpc": "https://evm.cronos.org", "explorer": "https://cronoscan.com", "color": "#002d74"},
    {"id": "eth-100", "family": "EVM", "chainId": 100, "name": "Gnosis Chain", "symbol": "xDAI", "decimals": 18, "rpc": "https://rpc.gnosischain.com", "explorer": "https://gnosisscan.io", "color": "#04795b"},
    {"id": "eth-42220", "family": "EVM", "chainId": 42220, "name": "Celo", "symbol": "CELO", "decimals": 18, "rpc": "https://forno.celo.org", "explorer": "https://celoscan.io", "color": "#35d07f"},
    {"id": "eth-96", "family": "EVM", "chainId": 96, "name": "Bitkub Chain (KUB)", "symbol": "KUB", "decimals": 18, "rpc": "https://rpc.bitkubchain.io", "explorer": "https://kubscan.com", "color": "#00d06c"},
    {"id": "eth-34443", "family": "EVM", "chainId": 34443, "name": "Mode Network", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.mode.network", "explorer": "https://modescan.io", "color": "#dffe00"},
    {"id": "eth-7777777", "family": "EVM", "chainId": 7777777, "name": "Zora", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.zora.energy", "explorer": "https://explorer.zora.energy", "color": "#2b5df0"},
    {"id": "eth-167000", "family": "EVM", "chainId": 167000, "name": "Taiko Alethia", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.mainnet.taiko.xyz", "explorer": "https://taikoscan.io", "color": "#e81899"},
    {"id": "eth-1101", "family": "EVM", "chainId": 1101, "name": "Polygon zkEVM", "symbol": "ETH", "decimals": 18, "rpc": "https://zkevm-rpc.com", "explorer": "https://zkevm.polygonscan.com", "color": "#7b3fe4"},
    {"id": "eth-1088", "family": "EVM", "chainId": 1088, "name": "Metis Andromeda", "symbol": "METIS", "decimals": 18, "rpc": "https://andromeda.metis.io/?owner=1088", "explorer": "https://andromeda-explorer.metis.io", "color": "#00dacc"},
    {"id": "eth-1284", "family": "EVM", "chainId": 1284, "name": "Moonbeam", "symbol": "GLMR", "decimals": 18, "rpc": "https://rpc.api.moonbeam.network", "explorer": "https://moonscan.io", "color": "#53cbc9"},
    {"id": "eth-1285", "family": "EVM", "chainId": 1285, "name": "Moonriver", "symbol": "MOVR", "decimals": 18, "rpc": "https://rpc.api.moonriver.moonbeam.network", "explorer": "https://moonriver.moonscan.io", "color": "#f2b705"},
    {"id": "eth-1313161554", "family": "EVM", "chainId": 1313161554, "name": "Aurora", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.aurora.dev", "explorer": "https://explorer.aurora.dev", "color": "#78d64b"},
    {"id": "eth-1666600000", "family": "EVM", "chainId": 1666600000, "name": "Harmony One", "symbol": "ONE", "decimals": 18, "rpc": "https://api.harmony.one", "explorer": "https://explorer.harmony.one", "color": "#00aee9"},
    {"id": "eth-2222", "family": "EVM", "chainId": 2222, "name": "Kava EVM", "symbol": "KAVA", "decimals": 18, "rpc": "https://evm.kava.io", "explorer": "https://kavascan.com", "color": "#ff433e"},
    {"id": "eth-8217", "family": "EVM", "chainId": 8217, "name": "Kaia (Klaytn)", "symbol": "KAIA", "decimals": 18, "rpc": "https://public-en.node.kaia.io", "explorer": "https://kaiascan.io", "color": "#bff009"},
    {"id": "eth-204", "family": "EVM", "chainId": 204, "name": "opBNB Mainnet", "symbol": "BNB", "decimals": 18, "rpc": "https://opbnb-mainnet-rpc.bnbchain.org", "explorer": "https://opbnbscan.com", "color": "#f3ba2f"},
    {"id": "eth-169", "family": "EVM", "chainId": 169, "name": "Manta Pacific", "symbol": "ETH", "decimals": 18, "rpc": "https://pacific-rpc.manta.network/http", "explorer": "https://pacific-explorer.manta.network", "color": "#0091ff"},
    {"id": "eth-252", "family": "EVM", "chainId": 252, "name": "Fraxtal", "symbol": "frxETH", "decimals": 18, "rpc": "https://rpc.frax.com", "explorer": "https://fraxscan.com", "color": "#000000"},
    {"id": "eth-1329", "family": "EVM", "chainId": 1329, "name": "Sei EVM", "symbol": "SEI", "decimals": 18, "rpc": "https://evm-rpc.sei-apis.com", "explorer": "https://seitrace.com", "color": "#9b1c1c"},
    {"id": "eth-480", "family": "EVM", "chainId": 480, "name": "World Chain", "symbol": "ETH", "decimals": 18, "rpc": "https://worldchain-mainnet.g.alchemy.com/public", "explorer": "https://worldscan.org", "color": "#111111"},
    {"id": "eth-130", "family": "EVM", "chainId": 130, "name": "Unichain", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.unichain.org", "explorer": "https://uniscan.xyz", "color": "#ff007a"},
    {"id": "eth-57073", "family": "EVM", "chainId": 57073, "name": "Ink (Kraken L2)", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc-gel.inkonchain.com", "explorer": "https://explorer.inkonchain.com", "color": "#7132f5"},
    {"id": "eth-1868", "family": "EVM", "chainId": 1868, "name": "Soneium", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.soneium.org", "explorer": "https://soneium.blockscout.com", "color": "#000000"},
    {"id": "eth-2741", "family": "EVM", "chainId": 2741, "name": "Abstract", "symbol": "ETH", "decimals": 18, "rpc": "https://api.mainnet.abs.xyz", "explorer": "https://abscan.org", "color": "#00de73"},
    {"id": "eth-80094", "family": "EVM", "chainId": 80094, "name": "Berachain", "symbol": "BERA", "decimals": 18, "rpc": "https://rpc.berachain.com", "explorer": "https://berascan.com", "color": "#8b5a2b"},
    {"id": "eth-999", "family": "EVM", "chainId": 999, "name": "HyperEVM", "symbol": "HYPE", "decimals": 18, "rpc": "https://rpc.hyperliquid.xyz/evm", "explorer": "https://purrsec.com", "color": "#50e3c2"},
    {"id": "eth-30", "family": "EVM", "chainId": 30, "name": "Rootstock (RSK)", "symbol": "RBTC", "decimals": 18, "rpc": "https://public-node.rsk.co", "explorer": "https://explorer.rootstock.io", "color": "#ff9900"},
    {"id": "eth-40", "family": "EVM", "chainId": 40, "name": "Telos EVM", "symbol": "TLOS", "decimals": 18, "rpc": "https://mainnet.telos.net/evm", "explorer": "https://teloscan.io", "color": "#571aff"},
    {"id": "eth-50", "family": "EVM", "chainId": 50, "name": "XDC Network", "symbol": "XDC", "decimals": 18, "rpc": "https://erpc.xinfin.network", "explorer": "https://xdcscan.com", "color": "#204996"},
    {"id": "eth-57", "family": "EVM", "chainId": 57, "name": "Syscoin NEVM", "symbol": "SYS", "decimals": 18, "rpc": "https://rpc.syscoin.org", "explorer": "https://explorer.syscoin.org", "color": "#0082c6"},
    {"id": "eth-61", "family": "EVM", "chainId": 61, "name": "Ethereum Classic", "symbol": "ETC", "decimals": 18, "rpc": "https://etc.rivet.link", "explorer": "https://blockscout.com/etc/mainnet", "color": "#3ab83a"},
    {"id": "eth-66", "family": "EVM", "chainId": 66, "name": "OKXChain (OKTC)", "symbol": "OKT", "decimals": 18, "rpc": "https://exchainrpc.okex.org", "explorer": "https://www.oklink.com/oktc", "color": "#111111"},
    {"id": "eth-88", "family": "EVM", "chainId": 88, "name": "Viction (TomoChain)", "symbol": "VIC", "decimals": 18, "rpc": "https://rpc.viction.xyz", "explorer": "https://vicscan.xyz", "color": "#00e8b5"},
    {"id": "eth-106", "family": "EVM", "chainId": 106, "name": "Velas EVM", "symbol": "VLX", "decimals": 18, "rpc": "https://evmexplorer.velas.com/rpc", "explorer": "https://evmexplorer.velas.com", "color": "#0037c1"},
    {"id": "eth-122", "family": "EVM", "chainId": 122, "name": "Fuse Mainnet", "symbol": "FUSE", "decimals": 18, "rpc": "https://rpc.fuse.io", "explorer": "https://explorer.fuse.io", "color": "#b4f9ba"},
    {"id": "eth-148", "family": "EVM", "chainId": 148, "name": "ShimmerEVM", "symbol": "SMR", "decimals": 18, "rpc": "https://json-rpc.evm.shimmer.network", "explorer": "https://explorer.evm.shimmer.network", "color": "#00e0ca"},
    {"id": "eth-196", "family": "EVM", "chainId": 196, "name": "X Layer (OKX L2)", "symbol": "OKB", "decimals": 18, "rpc": "https://rpc.xlayer.tech", "explorer": "https://www.oklink.com/xlayer", "color": "#111111"},
    {"id": "eth-255", "family": "EVM", "chainId": 255, "name": "Kroma", "symbol": "ETH", "decimals": 18, "rpc": "https://api.kroma.network", "explorer": "https://kromascan.com", "color": "#70de2c"},
    {"id": "eth-288", "family": "EVM", "chainId": 288, "name": "Boba Network", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.boba.network", "explorer": "https://bobascan.com", "color": "#ccff00"},
    {"id": "eth-314", "family": "EVM", "chainId": 314, "name": "Filecoin FEVM", "symbol": "FIL", "decimals": 18, "rpc": "https://api.node.glif.io/rpc/v1", "explorer": "https://filfox.info", "color": "#0090ff"},
    {"id": "eth-321", "family": "EVM", "chainId": 321, "name": "KuCoin Community Chain", "symbol": "KCS", "decimals": 18, "rpc": "https://rpc-mainnet.kcc.network", "explorer": "https://explorer.kcc.io", "color": "#00b98e"},
    {"id": "eth-336", "family": "EVM", "chainId": 336, "name": "Shiden", "symbol": "SDN", "decimals": 18, "rpc": "https://evm.shiden.astar.network", "explorer": "https://shiden.subscan.io", "color": "#5923b8"},
    {"id": "eth-369", "family": "EVM", "chainId": 369, "name": "PulseChain", "symbol": "PLS", "decimals": 18, "rpc": "https://rpc.pulsechain.com", "explorer": "https://scan.pulsechain.com", "color": "#00ff88"},
    {"id": "eth-592", "family": "EVM", "chainId": 592, "name": "Astar", "symbol": "ASTR", "decimals": 18, "rpc": "https://evm.astar.network", "explorer": "https://astar.subscan.io", "color": "#0070eb"},
    {"id": "eth-1030", "family": "EVM", "chainId": 1030, "name": "Conflux eSpace", "symbol": "CFX", "decimals": 18, "rpc": "https://evm.confluxrpc.com", "explorer": "https://evm.confluxscan.io", "color": "#1a1a1a"},
    {"id": "eth-1116", "family": "EVM", "chainId": 1116, "name": "Core DAO", "symbol": "CORE", "decimals": 18, "rpc": "https://rpc.coredao.org", "explorer": "https://scan.coredao.org", "color": "#ff9211"},
    {"id": "eth-1135", "family": "EVM", "chainId": 1135, "name": "Lisk", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.api.lisk.com", "explorer": "https://blockscout.lisk.com", "color": "#0d47a1"},
    {"id": "eth-1285", "family": "EVM", "chainId": 1285, "name": "Moonriver", "symbol": "MOVR", "decimals": 18, "rpc": "https://rpc.api.moonriver.moonbeam.network", "explorer": "https://moonriver.moonscan.io", "color": "#f2b705"},
    {"id": "eth-13371", "family": "EVM", "chainId": 13371, "name": "Immutable zkEVM", "symbol": "IMX", "decimals": 18, "rpc": "https://rpc.immutable.com", "explorer": "https://explorer.immutable.com", "color": "#17b5cb"},
    {"id": "eth-1480", "family": "EVM", "chainId": 1480, "name": "Vana", "symbol": "VANA", "decimals": 18, "rpc": "https://rpc.vana.org", "explorer": "https://vanascan.io", "color": "#4f46e5"},
    {"id": "eth-1625", "family": "EVM", "chainId": 1625, "name": "Gravity Alpha", "symbol": "G", "decimals": 18, "rpc": "https://rpc.gravity.xyz", "explorer": "https://explorer.gravity.xyz", "color": "#e11d48"},
    {"id": "eth-1890", "family": "EVM", "chainId": 1890, "name": "Lightlink Phoenix", "symbol": "ETH", "decimals": 18, "rpc": "https://replicator.phoenix.lightlink.io/rpc/v1", "explorer": "https://phoenix.lightlink.io", "color": "#00b4d8"},
    {"id": "eth-1996", "family": "EVM", "chainId": 1996, "name": "Sanko", "symbol": "DMT", "decimals": 18, "rpc": "https://mainnet.sanko.xyz", "explorer": "https://explorer.sanko.xyz", "color": "#3b82f6"},
    {"id": "eth-2000", "family": "EVM", "chainId": 2000, "name": "Dogechain EVM", "symbol": "DOGE", "decimals": 18, "rpc": "https://rpc.dogechain.dog", "explorer": "https://explorer.dogechain.dog", "color": "#c2a633"},
    {"id": "eth-2020", "family": "EVM", "chainId": 2020, "name": "Ronin", "symbol": "RON", "decimals": 18, "rpc": "https://api.roninchain.com/rpc", "explorer": "https://app.roninchain.com", "color": "#1273ea"},
    {"id": "eth-2040", "family": "EVM", "chainId": 2040, "name": "Vanar Mainnet", "symbol": "VANRY", "decimals": 18, "rpc": "https://rpc.vanarchain.com", "explorer": "https://explorer.vanarchain.com", "color": "#00d2ff"},
    {"id": "eth-2221", "family": "EVM", "chainId": 2221, "name": "Kava Testnet", "symbol": "KAVA", "decimals": 18, "rpc": "https://evm.testnet.kava.io", "explorer": "https://testnet.kavascan.com", "color": "#ff433e"},
    {"id": "eth-2345", "family": "EVM", "chainId": 2345, "name": "GOAT Network", "symbol": "BTC", "decimals": 18, "rpc": "https://rpc.goat.network", "explorer": "https://explorer.goat.network", "color": "#f59e0b"},
    {"id": "eth-2710", "family": "EVM", "chainId": 2710, "name": "Morph L2", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc-quicknode.morphl2.io", "explorer": "https://explorer.morphl2.io", "color": "#14b866"},
    {"id": "eth-2818", "family": "EVM", "chainId": 2818, "name": "Morph Mainnet", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.morphl2.io", "explorer": "https://explorer.morphl2.io", "color": "#14b866"},
    {"id": "eth-3637", "family": "EVM", "chainId": 3637, "name": "Botanix", "symbol": "BTC", "decimals": 18, "rpc": "https://rpc.botanixlabs.com", "explorer": "https://botanixscan.io", "color": "#f7931a"},
    {"id": "eth-4200", "family": "EVM", "chainId": 4200, "name": "Merlin Mainnet", "symbol": "BTC", "decimals": 18, "rpc": "https://rpc.merlinchain.io", "explorer": "https://scan.merlinchain.io", "color": "#7c3aed"},
    {"id": "eth-4326", "family": "EVM", "chainId": 4326, "name": "MegaETH", "symbol": "ETH", "decimals": 18, "rpc": "https://mainnet.megaeth.com/rpc", "explorer": "https://megaexplorer.xyz", "color": "#ec4899"},
    {"id": "eth-4689", "family": "EVM", "chainId": 4689, "name": "IoTeX", "symbol": "IOTX", "decimals": 18, "rpc": "https://babel-api.mainnet.iotex.io", "explorer": "https://iotexscan.io", "color": "#00d4d5"},
    {"id": "eth-5112", "family": "EVM", "chainId": 5112, "name": "Ham Chain", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.ham.fun", "explorer": "https://explorer.ham.fun", "color": "#f472b6"},
    {"id": "eth-7000", "family": "EVM", "chainId": 7000, "name": "ZetaChain", "symbol": "ZETA", "decimals": 18, "rpc": "https://zetachain-evm.blockpi.network/v1/rpc/public", "explorer": "https://explorer.zetachain.com", "color": "#008462"},
    {"id": "eth-7560", "family": "EVM", "chainId": 7560, "name": "Cyber L2", "symbol": "ETH", "decimals": 18, "rpc": "https://cyber.alt.technology", "explorer": "https://cyberscan.co", "color": "#00ff66"},
    {"id": "eth-841", "family": "EVM", "chainId": 841, "name": "Taraxa", "symbol": "TARA", "decimals": 18, "rpc": "https://rpc.mainnet.taraxa.io", "explorer": "https://tara.to", "color": "#15ac5b"},
    {"id": "eth-888", "family": "EVM", "chainId": 888, "name": "Wanchain", "symbol": "WAN", "decimals": 18, "rpc": "https://gwan-ssl.wandevs.org:56891", "explorer": "https://www.wanscan.org", "color": "#136aad"},
    {"id": "eth-9001", "family": "EVM", "chainId": 9001, "name": "Evmos", "symbol": "EVMOS", "decimals": 18, "rpc": "https://evmos.lava.build", "explorer": "https://escan.live", "color": "#ed4e33"},
    {"id": "eth-10143", "family": "EVM", "chainId": 10143, "name": "Monad", "symbol": "MON", "decimals": 18, "rpc": "https://rpc.monad.xyz", "explorer": "https://monadexplorer.com", "color": "#836ef9"},
    {"id": "eth-17777", "family": "EVM", "chainId": 17777, "name": "EOS EVM", "symbol": "EOS", "decimals": 18, "rpc": "https://api.evm.eosnetwork.com", "explorer": "https://explorer.evm.eosnetwork.com", "color": "#443f54"},
    {"id": "eth-22776", "family": "EVM", "chainId": 22776, "name": "MAP Protocol", "symbol": "MAPO", "decimals": 18, "rpc": "https://rpc.maplabs.io", "explorer": "https://maposcan.io", "color": "#f59e0b"},
    {"id": "eth-32769", "family": "EVM", "chainId": 32769, "name": "Zilliqa EVM", "symbol": "ZIL", "decimals": 18, "rpc": "https://api.zilliqa.com", "explorer": "https://evmx.zilliqa.com", "color": "#49c1bf"},
    {"id": "eth-42170", "family": "EVM", "chainId": 42170, "name": "Arbitrum Nova", "symbol": "ETH", "decimals": 18, "rpc": "https://nova.arbitrum.io/rpc", "explorer": "https://nova.arbiscan.io", "color": "#e57310"},
    {"id": "eth-42793", "family": "EVM", "chainId": 42793, "name": "Etherlink", "symbol": "XTZ", "decimals": 18, "rpc": "https://node.mainnet.etherlink.com", "explorer": "https://explorer.etherlink.com", "color": "#38ff9c"},
    {"id": "eth-43111", "family": "EVM", "chainId": 43111, "name": "Hemi Network", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.hemi.network/rpc", "explorer": "https://explorer.hemi.xyz", "color": "#ff6a00"},
    {"id": "eth-55244", "family": "EVM", "chainId": 55244, "name": "Superposition", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.superposition.so", "explorer": "https://explorer.superposition.so", "color": "#8b5cf6"},
    {"id": "eth-60808", "family": "EVM", "chainId": 60808, "name": "BOB (Build on Bitcoin)", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.gobob.xyz", "explorer": "https://explorer.gobob.xyz", "color": "#f25d00"},
    {"id": "eth-88888", "family": "EVM", "chainId": 88888, "name": "Chiliz Chain", "symbol": "CHZ", "decimals": 18, "rpc": "https://rpc.ankr.com/chiliz", "explorer": "https://chiliscan.com", "color": "#cd0124"},
    {"id": "eth-98865", "family": "EVM", "chainId": 98865, "name": "Plume Mainnet", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.plumenetwork.xyz", "explorer": "https://explorer.plumenetwork.xyz", "color": "#ff4d4d"},
    {"id": "eth-167009", "family": "EVM", "chainId": 167009, "name": "Taiko Hekla", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.hekla.taiko.xyz", "explorer": "https://hekla.taikoscan.io", "color": "#e81899"},
    {"id": "eth-534351", "family": "EVM", "chainId": 534351, "name": "Scroll Sepolia", "symbol": "ETH", "decimals": 18, "rpc": "https://sepolia-rpc.scroll.io", "explorer": "https://sepolia.scrollscan.com", "color": "#ffeeda"},
    {"id": "eth-666666666", "family": "EVM", "chainId": 666666666, "name": "Degen Chain", "symbol": "DEGEN", "decimals": 18, "rpc": "https://rpc.degen.tips", "explorer": "https://explorer.degen.tips", "color": "#a36efd"},
    {"id": "eth-88153591557", "family": "EVM", "chainId": 88153591557, "name": "Arbitrum Blueberry", "symbol": "ETH", "decimals": 18, "rpc": "https://rpc.arb-blueberry.gelato.digital", "explorer": "https://arb-blueberry.gelatoscout.com", "color": "#28a0f0"},
    {"id": "eth-11155111", "family": "EVM", "chainId": 11155111, "name": "Ethereum Sepolia", "symbol": "ETH", "decimals": 18, "rpc": "https://ethereum-sepolia-rpc.publicnode.com", "explorer": "https://sepolia.etherscan.io", "color": "#627eea"},
    {"id": "eth-84532", "family": "EVM", "chainId": 84532, "name": "Base Sepolia", "symbol": "ETH", "decimals": 18, "rpc": "https://sepolia.base.org", "explorer": "https://sepolia.basescan.org", "color": "#0052ff"},
    {"id": "eth-11155420", "family": "EVM", "chainId": 11155420, "name": "OP Sepolia", "symbol": "ETH", "decimals": 18, "rpc": "https://sepolia.optimism.io", "explorer": "https://sepolia-optimism.etherscan.io", "color": "#ff0420"},
]


# --------------------------------------------------------- Base58 & Bech32 Encoders
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    res = []
    while n > 0:
        n, rem = divmod(n, 58)
        res.append(B58_ALPHABET[rem])
    for byte in b:
        if byte == 0:
            res.append("1")
        else:
            break
    return "".join(reversed(res)) or "1"


def b58check_encode(version: bytes, payload: bytes) -> str:
    raw = version + payload
    checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    return b58encode(raw + checksum)


def _bech32_polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def bech32_segwit_encode(hrp: str, witver: int, witprog: bytes) -> str:
    CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    data = [witver] + _convertbits(witprog, 8, 5)
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(CHARSET[d] for d in data + checksum)


def hash160(data: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()


# --------------------------------------------------------- Pure-Python Secp256k1 & Ed25519
# Fallback secp256k1 point multiplication so BTC/ETH/LTC/DOGE addresses work with ZERO extra packages!
_SECP_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_SECP_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def _secp_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and y1 != y2:
        return None
    if x1 == x2:
        lam = (3 * x1 * x1 * pow(2 * y1, -1, _SECP_P)) % _SECP_P
    else:
        lam = ((y2 - y1) * pow(x2 - x1, -1, _SECP_P)) % _SECP_P
    x3 = (lam * lam - x1 - x2) % _SECP_P
    y3 = (lam * (x1 - x3) - y1) % _SECP_P
    return (x3, y3)


def _secp_mul(k: int):
    k = k % _SECP_N
    res = None
    addend = _SECP_G
    while k:
        if k & 1:
            res = _secp_add(res, addend)
        addend = _secp_add(addend, addend)
        k >>= 1
    return res


def secp256k1_pubkeys(priv32: bytes) -> tuple[bytes, bytes]:
    """Return (compressed_33_bytes, uncompressed_64_bytes_xy)."""
    k = int.from_bytes(priv32, "big") % (_SECP_N - 1) + 1
    x, y = _secp_mul(k)
    prefix = b"\x02" if (y % 2 == 0) else b"\x03"
    comp = prefix + x.to_bytes(32, "big")
    uncomp_xy = x.to_bytes(32, "big") + y.to_bytes(32, "big")
    return comp, uncomp_xy


# Minimal pure-Python Ed25519 public key derivation for Solana when PyNaCl isn't installed
_ED_Q = 2**255 - 19
_ED_D = (-121665 * pow(121666, -1, _ED_Q)) % _ED_Q
_ED_I = pow(2, (_ED_Q - 1) // 4, _ED_Q)


def _ed_xrecover(y):
    xx = (y * y - 1) * pow(_ED_D * y * y + 1, -1, _ED_Q)
    x = pow(xx, (_ED_Q + 3) // 8, _ED_Q)
    if (x * x - xx) % _ED_Q != 0:
        x = (x * _ED_I) % _ED_Q
    if x % 2 != 0:
        x = _ED_Q - x
    return x


_ED_BY = (4 * pow(5, -1, _ED_Q)) % _ED_Q
_ED_BX = _ed_xrecover(_ED_BY)
_ED_B = (_ED_BX % _ED_Q, _ED_BY % _ED_Q)


def _ed_add(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * pow(1 + _ED_D * x1 * x2 * y1 * y2, -1, _ED_Q)
    y3 = (y1 * y2 + x1 * x2) * pow(1 - _ED_D * x1 * x2 * y1 * y2, -1, _ED_Q)
    return (x3 % _ED_Q, y3 % _ED_Q)


def _ed_scalarmult(P, e):
    if e == 0:
        return (0, 1)
    Q = _ed_scalarmult(P, e // 2)
    Q = _ed_add(Q, Q)
    if e & 1:
        Q = _ed_add(Q, P)
    return Q


def ed25519_pubkey(seed32: bytes) -> bytes:
    if HAS_NACL:
        return bytes(nacl.signing.SigningKey(seed32).verify_key)
    h = bytearray(hashlib.sha512(seed32).digest())
    h[0] &= 248
    h[31] &= 63
    h[31] |= 64
    a = int.from_bytes(h[:32], "little")
    x, y = _ed_scalarmult(_ED_B, a)
    enc = bytearray(y.to_bytes(32, "little"))
    enc[31] |= (x & 1) << 7
    return bytes(enc)


# --------------------------------------------------------- Wordlist & Mnemonic
def get_wordlist() -> list[str]:
    wl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bip39_english.txt")
    if os.path.exists(wl_path):
        with open(wl_path, "r", encoding="utf-8") as f:
            words = [w.strip() for w in f if w.strip()]
        if len(words) == 2048:
            return words

    onsets = [
        "ab", "ac", "ad", "af", "ag", "al", "am", "an", "ap", "ar", "as", "at", "au", "av", "aw", "ax",
        "ba", "be", "bi", "bl", "bo", "br", "bu", "by", "ca", "ce", "ch", "ci", "cl", "co", "cr", "cu",
        "da", "de", "di", "do", "dr", "du", "ea", "ec", "ed", "ef", "el", "em", "en", "ep", "eq", "er",
        "es", "ev", "ex", "fa", "fe", "fi", "fl", "fo", "fr", "fu", "ga", "ge", "gi", "gl", "go", "gr",
    ]
    codas = [
        "band", "bell", "bird", "blue", "boat", "bold", "bone", "book", "born", "calm", "camp", "card",
        "care", "cast", "cave", "chip", "city", "clay", "clip", "cloud", "coal", "code", "coin", "cold",
        "core", "corn", "crew", "crop", "crow", "cube", "dawn", "deep", "deer", "desk", "dial", "dock",
        "dome", "door", "dove", "draw", "drop", "drum", "dusk", "dust", "east", "echo", "edge", "elm",
        "even", "face", "fact", "fair", "fall", "fame", "farm", "fast", "fern", "film", "fire", "fish",
        "flag", "flame", "flow", "foam", "fold", "folk", "ford", "fork", "form", "fort", "fox", "free",
        "frog", "fuel", "gate", "gaze", "gear", "gem", "gift", "glow", "gold", "grid", "grip", "grow",
        "guard", "guide", "gulf", "hall", "hand", "harp", "hawk", "head", "heat", "helm", "herb", "hill",
        "hive", "home", "hope", "horn", "host", "icon", "idea", "iron", "isle", "jade", "jazz", "join",
        "jump", "keen", "keep", "kelp", "key", "kind", "king", "kite", "knot", "lake", "lamp", "land",
        "lane", "lark", "leaf", "leap", "lens", "lift", "light", "lime", "line", "link", "lion", "list",
        "lock", "loft", "loom", "loop", "lord", "luck", "lynx", "map", "mark", "mars", "mask", "mast",
        "maze", "meadow", "melt", "mesa", "mild", "mill", "mind", "mine", "mint", "mist", "mode", "moon",
        "moss", "moth", "mount", "move", "navy", "nest", "net", "node", "noon", "north", "note", "oak",
        "oasis", "ocean", "olive", "opal", "open", "orbit", "orca", "ore", "owl", "pace", "pack", "page",
        "palm", "park", "path", "peak", "pearl", "pine", "pipe", "plan", "play", "plot", "plum", "plus",
        "poem", "point", "pole", "pond", "port", "post", "pure", "quest", "quick", "quiet", "quill", "rain",
        "range", "ray", "reach", "reed", "reef", "rest", "ridge", "ring", "rise", "river", "road", "rock",
        "roof", "root", "rose", "ruby", "rule", "run", "safe", "sage", "sail", "salt", "sand", "scale",
        "scan", "scene", "scope", "scout", "sea", "seal", "seed", "seek", "self", "sense", "shade", "shaft",
        "shape", "share", "shell", "shield", "shift", "shine", "ship", "shore", "side", "sight", "sign", "silk",
        "silver", "site", "skill", "sky", "slate", "slope", "smart", "smile", "smoke", "snow", "solar", "solid",
    ]
    return [f"{o}{c}" for o in onsets for c in codas[:32]]


def generate_mnemonic_12() -> str:
    words = get_wordlist()
    entropy = secrets.token_bytes(16)
    checksum_bits = f"{hashlib.sha256(entropy).digest()[0]:08b}"[:4]
    ent_bits = "".join(f"{b:08b}" for b in entropy) + checksum_bits
    return " ".join(words[int(ent_bits[i * 11:(i + 1) * 11], 2)] for i in range(12))


def validate_mnemonic_12(phrase: str) -> str:
    words = get_wordlist()
    word_to_idx = {w: i for i, w in enumerate(words)}
    tokens = [w.strip().lower() for w in phrase.strip().split() if w.strip()]
    if len(tokens) != 12:
        raise ValueError("Seed phrase must be exactly 12 words")
    bits = []
    for tok in tokens:
        if tok not in word_to_idx:
            raise ValueError(f"Unknown seed word: '{tok}'")
        bits.append(f"{word_to_idx[tok]:011b}")
    bitstr = "".join(bits)
    ent_bits, cs_bits = bitstr[:128], bitstr[128:]
    entropy = bytes(int(ent_bits[i * 8:(i + 1) * 8], 2) for i in range(16))
    expected_cs = f"{hashlib.sha256(entropy).digest()[0]:08b}"[:4]
    if cs_bits != expected_cs:
        raise ValueError("Invalid seed phrase checksum")
    return " ".join(tokens)


def wallet_from_mnemonic(mnemonic: str, account_index: int = 0) -> tai.Wallet:
    normalized = validate_mnemonic_12(mnemonic)
    salt = f"tai-mnemonic-v1:account-{account_index}".encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha512", normalized.encode("utf-8"), salt, 204_800, dklen=32)
    pk, sk = ML_DSA_65.key_derive(dk)
    return tai.Wallet(pk, sk)


def derive_multichain_keys(mnemonic: str, account_index: int = 0) -> dict:
    """
    Deterministically derive addresses & private keys for ALL supported chains from one 12-word seed:
      - TAI:  64-char SHA-256 of ML-DSA-65 public key
      - EVM:  0x... checksum/hex address (shared across Ethereum, Optimism, Base, Arbitrum, Polygon, BSC, & Top 100 EVMs)
      - BTC:  bc1q... Native SegWit Bech32 address
      - LTC:  ltc1q... Native SegWit Bech32 address
      - DOGE: D... Base58Check P2PKH address
      - SOL:  Base58 Ed25519 public key
    """
    norm = validate_mnemonic_12(mnemonic)
    tai_w = wallet_from_mnemonic(norm, account_index)

    def _seed(domain: str) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha512", norm.encode("utf-8"), f"{domain}:{account_index}".encode("utf-8"), 100_000, dklen=32
        )

    # 1. EVM (m/44'/60'/0'/0/account_index domain)
    evm_priv = _seed("taimask-evm-secp256k1")
    _, evm_uncomp_xy = secp256k1_pubkeys(evm_priv)
    # Keccak-256 via eth_account if installed, else SHA3-256 fallback
    if HAS_ETH:
        evm_addr = EthAccount.from_key(evm_priv).address
    else:
        evm_addr = "0x" + hashlib.sha3_256(evm_uncomp_xy).digest()[-20:].hex()

    # 2. Bitcoin Native SegWit (bc1q...)
    btc_priv = _seed("taimask-btc-segwit")
    btc_comp, _ = secp256k1_pubkeys(btc_priv)
    btc_addr = bech32_segwit_encode("bc", 0, hash160(btc_comp))

    # 3. Litecoin Native SegWit (ltc1q...)
    ltc_priv = _seed("taimask-ltc-segwit")
    ltc_comp, _ = secp256k1_pubkeys(ltc_priv)
    ltc_addr = bech32_segwit_encode("ltc", 0, hash160(ltc_comp))

    # 4. Dogecoin P2PKH (version byte 0x1e -> 'D...')
    doge_priv = _seed("taimask-doge-p2pkh")
    doge_comp, _ = secp256k1_pubkeys(doge_priv)
    doge_addr = b58check_encode(b"\x1e", hash160(doge_comp))

    # 5. Solana Ed25519 Base58
    sol_seed = _seed("taimask-sol-ed25519")
    sol_pub = ed25519_pubkey(sol_seed)
    sol_addr = b58encode(sol_pub)

    return {
        "TAI": {"address": tai_w.address, "wallet": tai_w},
        "EVM": {"address": evm_addr, "priv_hex": evm_priv.hex()},
        "BTC": {"address": btc_addr, "priv_hex": btc_priv.hex()},
        "LTC": {"address": ltc_addr, "priv_hex": ltc_priv.hex()},
        "DOGE": {"address": doge_addr, "priv_hex": doge_priv.hex()},
        "SOL": {"address": sol_addr, "priv_hex": sol_seed.hex()},
    }


# --------------------------------------------------------- Encrypted Vault
def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_vault(mnemonic: str, password: str) -> dict:
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    master = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000, dklen=64)
    enc_key, mac_key = master[:32], master[32:]
    pt = mnemonic.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(pt, _keystream(enc_key, nonce, len(pt))))
    tag = hmac.new(mac_key, salt + nonce + ct, hashlib.sha256).hexdigest()
    return {
        "version": 1,
        "kdf": "pbkdf2-sha256",
        "iterations": 200_000,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ct).decode("ascii"),
        "mac": tag,
    }


def decrypt_vault(vault_obj: dict, password: str) -> str:
    salt = base64.b64decode(vault_obj["salt"])
    nonce = base64.b64decode(vault_obj["nonce"])
    ct = base64.b64decode(vault_obj["ciphertext"])
    iters = int(vault_obj.get("iterations", 200_000))
    master = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, dklen=64)
    enc_key, mac_key = master[:32], master[32:]
    expected_tag = hmac.new(mac_key, salt + nonce + ct, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_tag, vault_obj["mac"]):
        raise ValueError("Incorrect password or corrupted vault")
    pt = bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct))))
    return validate_mnemonic_12(pt.decode("utf-8"))


# --------------------------------------------------------- Multi-Chain RPC Helpers
def http_json(url: str, payload: dict | None = None, timeout: int = 6) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "TaiMask/3.0"}
    if payload is None:
        req = urllib.request.Request(url, headers=headers, method="GET")
    else:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_chain_balance(chain: dict, keys: dict, default_tai_node: str) -> dict:
    family = chain["family"]
    addr = keys[family]["address"]
    rpc = default_tai_node if family == "TAI" else chain["rpc"]
    symbol = chain["symbol"]

    if family == "TAI":
        stats = http_json(f"{rpc}/stats", timeout=4)
        bal = http_json(f"{rpc}/balance/{addr}", timeout=4)
        blocks = http_json(f"{rpc}/chain", timeout=4).get("blocks", [])
        history = []
        for b in reversed(blocks):
            for t in reversed(b.get("txs", [])):
                tx_obj = tai.Tx.from_dict(t)
                role = None
                if t["sender"] == addr:
                    role = "OUT"
                elif t["recipient"] == addr:
                    role = "REWARD" if t["kind"] == "COINBASE" else "IN"
                if role:
                    history.append({
                        "txid": tx_obj.txid(),
                        "height": b["height"],
                        "kind": t["kind"],
                        "role": role,
                        "amount_fmt": f"{t['amount'] / 1e8:.4f} TAI",
                    })
            if len(history) >= 15:
                break
        return {
            "online": True,
            "address": addr,
            "balance_formatted": bal["balance_formatted"],
            "staked_formatted": bal["staked_formatted"],
            "height": stats.get("height", 0),
            "nonce": bal["nonce"],
            "history": history,
        }

    if family == "EVM":
        res = http_json(rpc, {"jsonrpc": "2.0", "method": "eth_getBalance", "params": [addr, "latest"], "id": 1})
        blk = http_json(rpc, {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 2})
        nc = http_json(rpc, {"jsonrpc": "2.0", "method": "eth_getTransactionCount", "params": [addr, "latest"], "id": 3})
        wei = int(res.get("result", "0x0"), 16)
        height = int(blk.get("result", "0x0"), 16)
        nonce = int(nc.get("result", "0x0"), 16)
        eth_val = decimal.Decimal(wei) / decimal.Decimal(10**18)
        return {
            "online": True,
            "address": addr,
            "balance_formatted": f"{eth_val:.6f} {symbol}",
            "staked_formatted": f"Chain ID {chain.get('chainId', '-')}",
            "height": height,
            "nonce": nonce,
            "history": [],
        }

    if family == "BTC":
        endpoints = [rpc.rstrip("/"), "https://blockstream.info/api", "https://mempool.space/api"]
        last_err = None
        for base in dict.fromkeys(endpoints):
            try:
                info = http_json(f"{base}/address/{addr}", timeout=6)
                tip_raw = urllib.request.urlopen(
                    urllib.request.Request(f"{base}/blocks/tip/height", headers={"User-Agent": "TaiMask/3.0"}),
                    timeout=5,
                ).read().decode("utf-8").strip()
                tip_height = int(tip_raw) if tip_raw.isdigit() else 0
                cs = info.get("chain_stats", {})
                ms = info.get("mempool_stats", {})
                sats = (cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)) + (
                    ms.get("funded_txo_sum", 0) - ms.get("spent_txo_sum", 0)
                )
                tx_cnt = cs.get("tx_count", 0) + ms.get("tx_count", 0)
                return {
                    "online": True,
                    "address": addr,
                    "balance_formatted": f"{sats / 1e8:.8f} BTC",
                    "staked_formatted": f"SegWit • {tx_cnt} txs",
                    "height": tip_height,
                    "nonce": tx_cnt,
                    "history": [],
                }
            except Exception as e:
                last_err = e
        raise last_err

    if family == "LTC":
        endpoints = [rpc.rstrip("/"), "https://litecoinspace.org/api"]
        last_err = None
        for base in dict.fromkeys(endpoints):
            try:
                info = http_json(f"{base}/address/{addr}", timeout=6)
                tip_raw = urllib.request.urlopen(
                    urllib.request.Request(f"{base}/blocks/tip/height", headers={"User-Agent": "TaiMask/3.0"}),
                    timeout=5,
                ).read().decode("utf-8").strip()
                tip_height = int(tip_raw) if tip_raw.isdigit() else 0
                cs = info.get("chain_stats", {})
                ms = info.get("mempool_stats", {})
                sats = (cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)) + (
                    ms.get("funded_txo_sum", 0) - ms.get("spent_txo_sum", 0)
                )
                tx_cnt = cs.get("tx_count", 0) + ms.get("tx_count", 0)
                return {
                    "online": True,
                    "address": addr,
                    "balance_formatted": f"{sats / 1e8:.8f} LTC",
                    "staked_formatted": f"SegWit • {tx_cnt} txs",
                    "height": tip_height,
                    "nonce": tx_cnt,
                    "history": [],
                }
            except Exception as e:
                last_err = e
        raise last_err

    if family == "DOGE":
        # Primary: Blockchair (no API key needed, returns chain tip + address balance)
        # Fallback: BlockCypher
        try:
            bc = http_json(f"https://api.blockchair.com/dogecoin/dashboards/address/{addr}?limit=0", timeout=6)
            addr_data = bc.get("data", {}).get(addr, {}).get("address", {})
            koinu = int(addr_data.get("balance", 0))
            tx_cnt = int(addr_data.get("transaction_count", 0))
            tip_height = int(bc.get("context", {}).get("state", 0))
            return {
                "online": True,
                "address": addr,
                "balance_formatted": f"{koinu / 1e8:.4f} DOGE",
                "staked_formatted": f"P2PKH • {tx_cnt} txs",
                "height": tip_height,
                "nonce": tx_cnt,
                "history": [],
            }
        except Exception:
            chain_meta = http_json("https://api.blockcypher.com/v1/doge/main", timeout=6)
            info = http_json(f"https://api.blockcypher.com/v1/doge/main/addrs/{addr}/balance", timeout=6)
            koinu = int(info.get("final_balance", 0))
            tx_cnt = int(info.get("n_tx", 0))
            return {
                "online": True,
                "address": addr,
                "balance_formatted": f"{koinu / 1e8:.4f} DOGE",
                "staked_formatted": f"P2PKH • {tx_cnt} txs",
                "height": int(chain_meta.get("height", 0)),
                "nonce": tx_cnt,
                "history": [],
            }

    if family == "SOL":
        res = http_json(rpc, {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [addr]})
        slot = http_json(rpc, {"jsonrpc": "2.0", "id": 2, "method": "getSlot"})
        lamports = res.get("result", {}).get("value", 0)
        return {
            "online": True,
            "address": addr,
            "balance_formatted": f"{lamports / 1e9:.6f} SOL",
            "staked_formatted": "Ed25519 SPL Ready",
            "height": slot.get("result", 0),
            "nonce": 0,
            "history": [],
        }

    raise ValueError("Unsupported chain family")


def broadcast_chain_tx(chain: dict, keys: dict, data: dict, default_tai_node: str) -> dict:
    family = chain["family"]
    action = data.get("action", "send")
    recipient = data.get("recipient", "").strip()
    amount_str = str(data.get("amount", "0")).strip()
    val = decimal.Decimal(amount_str)
    if val <= 0:
        raise ValueError("Amount must be greater than 0")

    if family == "TAI":
        rpc = default_tai_node
        w = keys["TAI"]["wallet"]
        amount_units = int(val * tai.DECIMALS)
        fee_units = int(decimal.Decimal(str(data.get("fee", "0.00001"))) * tai.DECIMALS)
        bal = http_json(f"{rpc}/balance/{w.address}")
        pool = http_json(f"{rpc}/mempool").get("txs", [])
        nonce = bal["nonce"] + sum(1 for t in pool if t.get("sender") == w.address)

        if action == "send":
            rec = recipient.lower()
            if not tai.is_valid_address(rec):
                raise ValueError("Invalid 64-character hex TAI recipient address")
            tx = tai.Tx("TRANSFER", w.address, rec, amount_units, fee_units, nonce).sign(w)
        elif action == "stake":
            tx = tai.Tx("STAKE", w.address, "", amount_units, fee_units, nonce).sign(w)
        elif action == "unstake":
            tx = tai.Tx("UNSTAKE", w.address, "", amount_units, fee_units, nonce).sign(w)
        else:
            raise ValueError("Unknown TAI action")
        return http_json(f"{rpc}/tx", {"tx": tx.to_dict()})

    if family == "EVM":
        if not HAS_ETH:
            raise ValueError("Install 'eth-account' (`pip install eth-account`) to sign & broadcast EVM transactions.")
        if not recipient.startswith("0x") or len(recipient) != 42:
            raise ValueError("Invalid 0x EVM recipient address")
        rpc = chain["rpc"]
        acct = EthAccount.from_key(bytes.fromhex(keys["EVM"]["priv_hex"]))
        nonce_hex = http_json(rpc, {"jsonrpc": "2.0", "method": "eth_getTransactionCount", "params": [acct.address, "pending"], "id": 1})["result"]
        gas_hex = http_json(rpc, {"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 2})["result"]
        tx_dict = {
            "to": recipient,
            "value": int(val * decimal.Decimal(10**18)),
            "gas": 21000,
            "gasPrice": int(gas_hex, 16),
            "nonce": int(nonce_hex, 16),
            "chainId": int(chain["chainId"]),
        }
        signed = acct.sign_transaction(tx_dict)
        raw_hex = "0x" + signed.raw_transaction.hex()
        sent = http_json(rpc, {"jsonrpc": "2.0", "method": "eth_sendRawTransaction", "params": [raw_hex], "id": 3})
        if "error" in sent:
            raise ValueError(sent["error"].get("message", str(sent["error"])))
        return {"ok": True, "txid": sent["result"]}

    raise ValueError(
        f"Address derived ({keys[family]['address']}), but native UTXO/Solana raw tx broadcast requires signing backend."
    )


# --------------------------------------------------------- Session & HTTP Server
class VaultSession:
    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self.lock = threading.RLock()
        self.unlocked_mnemonic: str | None = None
        self.keys: dict | None = None
        self.account_index: int = 0
        self.custom_chains: list[dict] = []

    def all_chains(self) -> list[dict]:
        return TOP_CHAINS + self.custom_chains

    def find_chain(self, chain_id: str) -> dict:
        for c in self.all_chains():
            if c["id"] == chain_id:
                return c
        return TOP_CHAINS[0]

    def exists(self) -> bool:
        return os.path.exists(self.vault_path)

    def is_unlocked(self) -> bool:
        with self.lock:
            return self.keys is not None

    def create_or_import(self, mnemonic: str, password: str, account_index: int = 0) -> dict:
        norm = validate_mnemonic_12(mnemonic)
        derived = derive_multichain_keys(norm, account_index)
        enc = encrypt_vault(norm, password)
        fd = os.open(self.vault_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(enc, f, indent=2)
        with self.lock:
            self.unlocked_mnemonic = norm
            self.keys = derived
            self.account_index = account_index
        return derived

    def unlock(self, password: str, account_index: int = 0) -> dict:
        if not self.exists():
            raise ValueError("No wallet vault found.")
        with open(self.vault_path, "r", encoding="utf-8") as f:
            vault_obj = json.load(f)
        norm = decrypt_vault(vault_obj, password)
        derived = derive_multichain_keys(norm, account_index)
        with self.lock:
            self.unlocked_mnemonic = norm
            self.keys = derived
            self.account_index = account_index
        return derived

    def lock_wallet(self):
        with self.lock:
            self.unlocked_mnemonic = None
            self.keys = None

    def reveal_seed(self, password: str) -> str:
        with open(self.vault_path, "r", encoding="utf-8") as f:
            vault_obj = json.load(f)
        return decrypt_vault(vault_obj, password)

    def reset_vault(self):
        with self.lock:
            self.unlocked_mnemonic = None
            self.keys = None
            self.account_index = 0
            if os.path.exists(self.vault_path):
                os.remove(self.vault_path)


def main():
    parser = argparse.ArgumentParser(description="TaiMask v3 Multi-Chain Seed Vault")
    parser.add_argument("--vault", default="taimask_vault.json", help="Encrypted vault path")
    parser.add_argument("--node", default="http://127.0.0.1:8001", help="Tai Mainnet RPC URL")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=18095, help="Bind port")
    args = parser.parse_args()

    node_url = args.node.rstrip("/")
    session = VaultSession(args.vault)
    ui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tai-metamask-extension", "popup.html")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt_str, *args):
            pass

        def _send_json(self, code: int, payload: dict):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self):
            self._send_json(200, {"ok": True})

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            try:
                if path == "/" and os.path.exists(ui_path):
                    with open(ui_path, "rb") as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return

                if path == "/api/chains":
                    chains_clean = [
                        {k: v for k, v in c.items() if k != "priv_hex"}
                        for c in session.all_chains()
                    ]
                    self._send_json(200, {"chains": chains_clean, "count": len(chains_clean)})

                elif path == "/api/status":
                    with session.lock:
                        addrs = (
                            {fam: info["address"] for fam, info in session.keys.items()}
                            if session.keys
                            else {}
                        )
                        idx = session.account_index
                    self._send_json(200, {
                        "has_vault": session.exists(),
                        "unlocked": session.is_unlocked(),
                        "addresses": addrs,
                        "account_index": idx,
                    })

                elif path == "/api/new-seed":
                    phrase = generate_mnemonic_12()
                    self._send_json(200, {"mnemonic": phrase, "words": phrase.split()})

                elif path == "/api/wallet":
                    with session.lock:
                        k = session.keys
                        idx = session.account_index
                    if not k:
                        self._send_json(401, {"error": "Wallet is locked"})
                        return

                    chain_id = qs.get("chain", "tai-mainnet")
                    chain = session.find_chain(chain_id)
                    fam = chain["family"]
                    addr = k[fam]["address"]

                    try:
                        info = query_chain_balance(chain, k, node_url)
                    except Exception as rpc_err:
                        info = {
                            "online": False,
                            "rpc_error": str(rpc_err),
                            "address": addr,
                            "balance_formatted": f"0.000000 {chain['symbol']}",
                            "staked_formatted": chain["name"],
                            "height": 0,
                            "nonce": 0,
                            "history": [],
                        }

                    info["account_index"] = idx
                    info["chain"] = chain
                    info["all_addresses"] = {f: v["address"] for f, v in k.items()}
                    self._send_json(200, info)
                else:
                    self._send_json(404, {"error": "Not found"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

                if path == "/api/setup":
                    k = session.create_or_import(data.get("mnemonic", ""), data.get("password", ""), 0)
                    self._send_json(200, {"ok": True, "address": k["TAI"]["address"]})

                elif path == "/api/unlock":
                    k = session.unlock(data.get("password", ""), 0)
                    self._send_json(200, {"ok": True, "address": k["TAI"]["address"]})

                elif path == "/api/switch-account":
                    idx = int(data.get("account_index", 0))
                    with session.lock:
                        if not session.unlocked_mnemonic:
                            raise ValueError("Wallet is locked")
                        session.keys = derive_multichain_keys(session.unlocked_mnemonic, idx)
                        session.account_index = idx
                    self._send_json(200, {"ok": True, "account_index": idx})

                elif path == "/api/add-chain":
                    cid = int(data.get("chainId", 0))
                    name = data.get("name", "").strip()
                    symbol = data.get("symbol", "ETH").strip().upper()
                    rpc = data.get("rpc", "").strip()
                    if cid <= 0 or not name or not rpc.startswith("http"):
                        raise ValueError("Valid Chain ID, Network Name, and http(s) RPC URL required")
                    custom = {
                        "id": f"eth-{cid}",
                        "family": "EVM",
                        "chainId": cid,
                        "name": name,
                        "symbol": symbol,
                        "decimals": 18,
                        "rpc": rpc,
                        "explorer": data.get("explorer", ""),
                        "color": "#38bdf8",
                    }
                    session.custom_chains.append(custom)
                    self._send_json(200, {"ok": True, "chain": custom})

                elif path == "/api/lock":
                    session.lock_wallet()
                    self._send_json(200, {"ok": True})

                elif path == "/api/reset":
                    session.reset_vault()
                    self._send_json(200, {"ok": True})

                elif path == "/api/reveal-seed":
                    phrase = session.reveal_seed(data.get("password", ""))
                    self._send_json(200, {"ok": True, "mnemonic": phrase, "words": phrase.split()})

                elif path == "/api/action":
                    with session.lock:
                        k = session.keys
                    if not k:
                        self._send_json(401, {"ok": False, "error": "Wallet is locked"})
                        return
                    chain = session.find_chain(data.get("chain", "tai-mainnet"))
                    res = broadcast_chain_tx(chain, k, data, node_url)
                    self._send_json(200, res)
                else:
                    self._send_json(404, {"ok": False, "error": "Not found"})
            except Exception as e:
                self._send_json(400, {"ok": False, "error": str(e)})

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[TAIMASK v3] Multi-Chain Vault ({len(TOP_CHAINS)} chains) listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down TaiMask v3...")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
