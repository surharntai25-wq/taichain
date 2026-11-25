#!/usr/bin/env python3
"""
TaiSpace — Tai (TAI) Mempool.space / Litecoin.space-Style Block Explorer (`explorer-v3.py`)

Features:
* Mempool.space / Litecoin.space dark navy theme (`#11131f` / `#1d2030`) with top navbar & universal search
* 3D Isometric Mempool Block (left of dashed divider) vs. Mined 3D Blocks stream (right of divider)
  with live fee-rate spread, total TAI fees/rewards, tx count, age, and miner/validator badge
* Reward Stats card (Total Block Rewards, Avg Block Fees, Avg Tx Fee)
* Difficulty & Halving Countdown card (Blocks to Retarget, PoW/PoS Slot Split, Next Halving Countdown)
* Producers / Validators Donut Chart (SVG) + Difficulty & Block Cadence Dual-Line Chart (SVG)
* Live Latest Transactions table (with newest Mempool `PENDING` transactions at the very top!)
* Full Block, Transaction, and Address detail views + TaiMask (`127.0.0.1:18095`) wallet link

Usage
-----
  python explorer-v3.py --node http://127.0.0.1:8001 --port 8080
"""
import argparse
import hashlib
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TAI.SPACE — Tai Mainnet Explorer</title>
  <style>
    :root {
      --bg: #11131f;
      --nav: #181b2a;
      --card: #1d2030;
      --card-2: #24283b;
      --border: #2c3148;
      --text: #f3f4f6;
      --muted: #8b92a8;
      --blue: #3b82f6;
      --cyan: #38bdf8;
      --green: #10b981;
      --amber: #f59e0b;
      --purple: #a855f7;
      --pink: #ec4899;
      --red: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.45;
    }
    a { color: var(--cyan); text-decoration: none; cursor: pointer; }
    a:hover { text-decoration: underline; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }

    /* Top Litecoin.space-style Navbar */
    .navbar {
      background: var(--nav);
      border-bottom: 1px solid var(--border);
      padding: 0 24px;
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 30;
    }
    .nav-left {
      display: flex;
      align-items: center;
      height: 100%;
      gap: 6px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 900;
      font-size: 1.15rem;
      letter-spacing: 0.04em;
      color: var(--cyan);
      margin-right: 12px;
      cursor: pointer;
    }
    .cube-logo {
      width: 28px;
      height: 28px;
      background: linear-gradient(135deg, #38bdf8, #2563eb);
      clip-path: polygon(50% 0%, 95% 25%, 95% 75%, 50% 100%, 5% 75%, 5% 25%);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      font-size: 0.8rem;
      font-weight: 900;
    }
    .net-badge {
      background: var(--card-2);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 5px 11px;
      border-radius: 8px;
      font-size: 0.78rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 6px;
      margin-right: 8px;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 8px var(--green);
    }
    .dot.offline { background: var(--red); box-shadow: 0 0 8px var(--red); }

    .nav-tab {
      height: 100%;
      padding: 0 15px;
      display: flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      border-bottom: 3px solid transparent;
      transition: all 0.15s;
    }
    .nav-tab:hover { color: var(--text); background: rgba(255,255,255,0.03); }
    .nav-tab.active {
      background: #2563eb;
      color: #ffffff;
    }
    .nav-tab svg { width: 17px; height: 17px; }

    .search-form {
      display: flex;
      align-items: center;
      width: 380px;
      max-width: 100%;
    }
    .search-form input {
      flex: 1;
      background: #121420;
      border: 1px solid var(--border);
      border-right: none;
      color: var(--text);
      padding: 8px 13px;
      border-radius: 6px 0 0 6px;
      font-size: 0.84rem;
      outline: none;
    }
    .search-form input:focus { border-color: var(--blue); }
    .search-form button {
      background: #2563eb;
      border: 1px solid #2563eb;
      color: #fff;
      padding: 8px 14px;
      border-radius: 0 6px 6px 0;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .search-form button:hover { background: #1d4ed8; }

    /* Main Container */
    .container {
      max-width: 1380px;
      margin: 0 auto;
      padding: 24px 22px 48px;
    }
    .alert {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.45);
      color: #fca5a5;
      padding: 10px 16px;
      border-radius: 8px;
      margin-bottom: 18px;
      display: none;
      font-size: 0.86rem;
    }

    /* 3D Isometric Block Ribbon (Litecoin.space signature strip) */
    .ribbon-wrap {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 22px;
      padding: 18px 10px 26px;
      overflow-x: auto;
    }
    .mempool-side {
      display: flex;
      align-items: center;
      gap: 18px;
      flex-shrink: 0;
    }
    .divider-line {
      width: 2px;
      height: 175px;
      border-left: 2px dashed #4b5563;
      position: relative;
      flex-shrink: 0;
    }
    .divider-line::before, .divider-line::after {
      content: "⇅";
      position: absolute;
      left: -8px;
      font-size: 0.78rem;
      color: var(--muted);
      background: var(--bg);
      padding: 2px 0;
    }
    .divider-line::before { top: -18px; }
    .divider-line::after { bottom: -18px; }

    .blocks-stream {
      display: flex;
      align-items: flex-start;
      gap: 24px;
      overflow-x: auto;
      padding-bottom: 6px;
    }

    .block-col {
      display: flex;
      flex-direction: column;
      align-items: center;
      width: 146px;
      flex-shrink: 0;
      cursor: pointer;
      transition: transform 0.15s ease;
    }
    .block-col:hover { transform: translateY(-4px); }
    .block-num-top {
      font-size: 0.92rem;
      font-weight: 700;
      color: var(--cyan);
      margin-bottom: 10px;
      height: 20px;
    }
    .block-num-top.mem { color: #fbbf24; }

    /* 3D Cube Box */
    .cube-box {
      position: relative;
      width: 132px;
      height: 132px;
      background: linear-gradient(180deg, #32364a 0%, #242838 100%);
      border: 1px solid #3f455e;
      border-radius: 4px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: space-between;
      padding: 10px 8px 0;
      box-shadow: -10px -8px 0 #1c1f2e, -10px -8px 0 1px #2f3449;
      margin-left: 10px;
      margin-top: 8px;
      text-align: center;
    }
    .cube-box.mempool-cube {
      background: linear-gradient(180deg, #1b3b36 0%, #162a2c 100%);
      border-color: #10b981;
      box-shadow: -10px -8px 0 #122926, -10px -8px 0 1px #0f766e;
    }
    .cube-box.pos-cube {
      border-top: 3px solid var(--green);
    }
    .cube-box.pow-cube {
      border-top: 3px solid var(--amber);
    }
    .cube-fee-rate {
      font-size: 0.72rem;
      color: #cbd5e1;
    }
    .cube-spread {
      font-size: 0.68rem;
      color: #facc15;
      font-weight: 600;
    }
    .cube-reward {
      font-size: 0.98rem;
      font-weight: 800;
      color: #ffffff;
    }
    .cube-txs {
      font-size: 0.72rem;
      color: #cbd5e1;
    }
    .cube-footer-bar {
      width: calc(100% + 16px);
      margin-left: -8px;
      margin-right: -8px;
      background: #2563eb;
      color: #ffffff;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 4px 4px;
      border-radius: 0 0 3px 3px;
    }
    .cube-footer-bar.mem-bar {
      background: #059669;
    }
    .producer-tag {
      margin-top: 9px;
      font-size: 0.74rem;
      font-weight: 700;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      gap: 5px;
      max-width: 140px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .slot-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    /* 2x2 Dashboard Cards */
    .dash-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 22px;
    }
    @media (max-width: 960px) {
      .dash-grid { grid-template-columns: 1fr; }
      .search-form { width: 220px; }
    }
    .panel {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 22px;
    }
    .panel-title {
      text-align: center;
      font-size: 0.74rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: var(--muted);
      text-transform: uppercase;
      margin-bottom: 16px;
    }
    .stats-3 {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      text-align: center;
    }
    .st-lbl {
      font-size: 0.82rem;
      color: #cbd5e1;
      margin-bottom: 6px;
    }
    .st-val {
      font-size: 1.45rem;
      font-weight: 800;
      color: #ffffff;
    }
    .st-unit {
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--muted);
      margin-left: 3px;
    }
    .st-sub {
      font-size: 0.76rem;
      color: var(--green);
      margin-top: 4px;
      font-weight: 600;
    }
    .st-sub.muted { color: var(--muted); font-weight: 400; }

    /* Charts Grid */
    .chart-box {
      display: flex;
      align-items: center;
      justify-content: space-around;
      gap: 16px;
      min-height: 195px;
    }
    .legend-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-size: 0.8rem;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .legend-swatch {
      width: 11px;
      height: 11px;
      border-radius: 3px;
      flex-shrink: 0;
    }

    /* Transactions Table Card */
    .table-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 20px;
    }
    .table-header {
      padding: 14px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-weight: 700;
      font-size: 0.92rem;
    }
    .table-wrap { padding: 8px 18px 14px; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--border); }
    th { color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255,255,255,0.02); }

    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 5px;
      font-size: 0.71rem;
      font-weight: 700;
    }
    .badge-POW { background: rgba(245, 158, 11, 0.16); color: var(--amber); border: 1px solid rgba(245, 158, 11, 0.4); }
    .badge-POS { background: rgba(16, 185, 129, 0.16); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.4); }
    .badge-GENESIS { background: rgba(168, 85, 247, 0.16); color: var(--purple); border: 1px solid rgba(168, 85, 247, 0.4); }
    .badge-TX { background: rgba(56, 189, 248, 0.14); color: var(--cyan); border: 1px solid rgba(56, 189, 248, 0.35); }
    .badge-PENDING { background: rgba(250, 204, 21, 0.16); color: #facc15; border: 1px solid rgba(250, 204, 21, 0.4); margin-left: 5px; }

    .detail-row {
      display: grid;
      grid-template-columns: 185px 1fr;
      padding: 10px 0;
      border-bottom: 1px solid var(--border);
      gap: 12px;
      font-size: 0.88rem;
      word-break: break-all;
    }
    .detail-row:last-child { border-bottom: none; }
    .detail-key { color: var(--muted); font-weight: 600; }
    .btn-back {
      background: var(--card-2);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 6px 12px;
      border-radius: 7px;
      cursor: pointer;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .btn-back:hover { border-color: var(--cyan); color: var(--cyan); }
  </style>
</head>
<body>
  <!-- Top Navbar -->
  <header class="navbar">
    <div class="nav-left">
      <div class="brand" onclick="showHome()">
        <div class="cube-logo">T</div>
        <span>TAI.SPACE</span>
      </div>
      <div class="net-badge">
        <span id="connDot" class="dot"></span>
        <span id="connText">Mainnet</span>
      </div>
      <div class="nav-tab active" id="tabMining" onclick="showHome()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
        <span>Mining &amp; PoS</span>
      </div>
      <div class="nav-tab" id="tabValidators" onclick="showValidators()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        <span>Validators</span>
      </div>
      <div class="nav-tab" id="tabSpecs" onclick="showSpecs()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
        <span>Specs</span>
      </div>
    </div>

    <form class="search-form" onsubmit="handleSearch(event)">
      <input id="searchInput" type="text" placeholder="Your Gateway to Explore Tai (Block, TxID, Address)" />
      <button type="submit" title="Search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      </button>
    </form>
  </header>

  <div class="container">
    <div id="alertBox" class="alert"></div>

    <!-- 3D Isometric Mempool & Confirmed Blocks Ribbon -->
    <section class="ribbon-wrap" id="blockRibbon">
      <div class="mempool-side" id="mempoolCubeSlot"></div>
      <div class="divider-line"></div>
      <div class="blocks-stream" id="confirmedCubesSlot"></div>
    </section>

    <!-- Dynamic Inspector View -->
    <div id="detailView" style="display:none;"></div>

    <!-- Main Mining & Consensus Dashboard -->
    <div id="homeView">
      <!-- Top Row: Reward Stats + Difficulty & Halving -->
      <div class="dash-grid">
        <div class="panel">
          <div class="panel-title">Reward Stats (<span id="statWindowLabel">All Blocks</span>)</div>
          <div class="stats-3">
            <div>
              <div class="st-lbl">Circulating Supply</div>
              <div class="st-val"><span id="statSupply">0</span><span class="st-unit">TAI</span></div>
              <div class="st-sub">Cap: 21,000,000 TAI</div>
            </div>
            <div>
              <div class="st-lbl">Avg Block Fees</div>
              <div class="st-val"><span id="statAvgBlockFee">0.0000</span><span class="st-unit">TAI/blk</span></div>
              <div class="st-sub muted">Base: 50 TAI / block</div>
            </div>
            <div>
              <div class="st-lbl">Total Staked (PoS)</div>
              <div class="st-val"><span id="statStaked">0</span><span class="st-unit">TAI</span></div>
              <div class="st-sub" id="statStakedPct">0.0% of supply</div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-title">Difficulty &amp; Hybrid Consensus</div>
          <div class="stats-3">
            <div>
              <div class="st-lbl">PoW / PoS Blocks</div>
              <div class="st-val"><span id="statPowCount">0</span><span class="st-unit">/</span><span id="statPosCount">0</span></div>
              <div class="st-sub" id="statAvgTime">Avg ~20.0s / block</div>
            </div>
            <div>
              <div class="st-lbl">PoW Difficulty</div>
              <div class="st-val"><span id="statBits">6</span><span class="st-unit">bits</span></div>
              <div class="st-sub muted">Argon2id (16 MiB)</div>
            </div>
            <div>
              <div class="st-lbl">Next Halving</div>
              <div class="st-val" id="statHalvingBlocks">210,000</div>
              <div class="st-sub muted" id="statHalvingEta">blocks remaining</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Bottom Row: Producers Donut + Difficulty & Throughput Chart -->
      <div class="dash-grid">
        <div class="panel">
          <div class="stats-3" style="margin-bottom:14px;">
            <div>
              <div class="st-lbl">Active Producers</div>
              <div class="st-val" id="statProducerCount">0</div>
            </div>
            <div>
              <div class="st-lbl">Total Blocks</div>
              <div class="st-val" id="statTotalBlocks">0</div>
            </div>
            <div>
              <div class="st-lbl">Total Transactions</div>
              <div class="st-val" id="statTotalTxs">0</div>
            </div>
          </div>
          <div class="chart-box">
            <svg id="donutSvg" width="165" height="165" viewBox="0 0 165 165"></svg>
            <div class="legend-list" id="donutLegend"></div>
          </div>
        </div>

        <div class="panel">
          <div class="stats-3" style="margin-bottom:14px;">
            <div>
              <div class="st-lbl">Target Block Time</div>
              <div class="st-val">20.0<span class="st-unit">s</span></div>
            </div>
            <div>
              <div class="st-lbl">Mempool Queue</div>
              <div class="st-val" id="statMempoolCount">0<span class="st-unit">txs</span></div>
            </div>
            <div>
              <div class="st-lbl">Signature Algo</div>
              <div class="st-val" style="font-size:1.15rem; padding-top:4px;">ML-DSA-65</div>
            </div>
          </div>
          <div style="width:100%; height:165px;">
            <svg id="diffChartSvg" viewBox="0 0 540 165" style="width:100%; height:100%; overflow:visible;"></svg>
          </div>
        </div>
      </div>

      <!-- Live Transactions Feed (Newest Pending Mempool Txs First!) -->
      <div class="table-card">
        <div class="table-header">
          <span>Latest Transactions (Mempool &amp; Confirmed)</span>
          <span style="font-size:0.78rem; color:var(--muted);">Auto-refresh 3s</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Txn Hash</th>
                <th>Type</th>
                <th>Block</th>
                <th>From</th>
                <th>To</th>
                <th>Value</th>
                <th>Fee</th>
              </tr>
            </thead>
            <tbody id="txsTable"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <script>
    const DECIMALS = 1e8;
    const PALETTE = ["#ec4899", "#3b82f6", "#10b981", "#f59e0b", "#a855f7", "#06b6d4"];
    let cachedBlocks = [];
    let cachedMempool = [];
    let cachedStats = {};
    let txIndex = {};

    function fmtTai(units, maxDec = 4) {
      return (Number(units) / DECIMALS).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: maxDec
      }) + " TAI";
    }

    function shortHex(h, n = 7) {
      if (!h) return "-";
      if (h.startsWith("COINBASE:")) return "COINBASE";
      return h.length > n * 2 ? h.slice(0, n) + "…" + h.slice(-5) : h;
    }

    function timeAgo(ts) {
      const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts);
      if (diff < 10) return "Just now";
      if (diff < 60) return diff + "s ago";
      if (diff < 3600) return Math.floor(diff / 60) + "m ago";
      if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
      return Math.floor(diff / 86400) + "d ago";
    }

    function setActiveTab(id) {
      document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
      const el = document.getElementById(id);
      if (el) el.classList.add("active");
    }

    function showAlert(msg) {
      const box = document.getElementById("alertBox");
      if (!msg) { box.style.display = "none"; return; }
      box.textContent = msg;
      box.style.display = "block";
    }

    function showHome() {
      showAlert("");
      setActiveTab("tabMining");
      document.getElementById("detailView").style.display = "none";
      document.getElementById("homeView").style.display = "block";
    }

    function render3DRibbon() {
      // Left side: Pending Mempool Block Cube
      const memSlot = document.getElementById("mempoolCubeSlot");
      const memFees = cachedMempool.reduce((acc, t) => acc + Number(t.fee || 0), 0);
      const minFee = cachedMempool.length ? Math.min(...cachedMempool.map(t => Number(t.fee || 0) / 1e8)) : 0.00001;
      const maxFee = cachedMempool.length ? Math.max(...cachedMempool.map(t => Number(t.fee || 0) / 1e8)) : 0.00001;
      const nextHeight = cachedBlocks.length;
      const nextSlot = nextHeight % 2 === 1 ? "PoW" : "PoS";

      memSlot.innerHTML = `
        <div class="block-col" onclick="showHome()">
          <div class="block-num-top mem">Next #${nextHeight} (${nextSlot})</div>
          <div class="cube-box mempool-cube">
            <div class="cube-fee-rate">~${minFee.toFixed(5)} TAI/tx</div>
            <div class="cube-spread">${minFee.toFixed(5)} - ${maxFee.toFixed(5)}</div>
            <div class="cube-reward">${(memFees / 1e8).toFixed(4)} TAI</div>
            <div class="cube-txs">${cachedMempool.length} pending txs</div>
            <div class="cube-footer-bar mem-bar">In ~20 seconds</div>
          </div>
          <div class="producer-tag"><span class="slot-dot" style="background:#10b981;"></span>Mempool Queue</div>
        </div>
      `;

      // Right side: Latest 6 Confirmed 3D Block Cubes
      const confSlot = document.getElementById("confirmedCubesSlot");
      const recent = cachedBlocks.slice(-6).reverse();
      confSlot.innerHTML = recent.map(b => {
        const totalAmt = (b.txs || []).reduce((s, t) => s + Number(t.amount || 0), 0);
        const totalFee = (b.txs || []).reduce((s, t) => s + Number(t.fee || 0), 0);
        const isPos = b.kind === "POS";
        const dotColor = isPos ? "#10b981" : b.kind === "POW" ? "#f59e0b" : "#a855f7";
        return `
          <div class="block-col" onclick="inspectBlock(${b.height})">
            <div class="block-num-top">${b.height}</div>
            <div class="cube-box ${isPos ? "pos-cube" : "pow-cube"}">
              <div class="cube-fee-rate">Bits: ${b.bits} • ${b.kind}</div>
              <div class="cube-spread">Fees: ${(totalFee / 1e8).toFixed(5)} TAI</div>
              <div class="cube-reward">${(totalAmt / 1e8).toFixed(2)} TAI</div>
              <div class="cube-txs">${b.txs.length} transaction${b.txs.length === 1 ? "" : "s"}</div>
              <div class="cube-footer-bar">${timeAgo(b.ts)}</div>
            </div>
            <div class="producer-tag">
              <span class="slot-dot" style="background:${dotColor};"></span>
              <span>${b.producer ? shortHex(b.producer, 5) : "GENESIS"}</span>
            </div>
          </div>
        `;
      }).join("");
    }

    function renderDonutChart() {
      const counts = {};
      for (const b of cachedBlocks) {
        const key = b.producer ? shortHex(b.producer, 6) : "GENESIS";
        counts[key] = (counts[key] || 0) + 1;
      }
      const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6);
      const total = entries.reduce((s, [, c]) => s + c, 0) || 1;
      document.getElementById("statProducerCount").textContent = Object.keys(counts).length;

      const svg = document.getElementById("donutSvg");
      const legend = document.getElementById("donutLegend");
      const cx = 82, cy = 82, r = 58, strokeW = 24;
      const circ = 2 * Math.PI * r;
      let offset = 0;

      svg.innerHTML = entries.map(([label, count], i) => {
        const frac = count / total;
        const dash = frac * circ;
        const color = PALETTE[i % PALETTE.length];
        const seg = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="transparent" stroke="${color}" stroke-width="${strokeW}" stroke-dasharray="${dash.toFixed(2)} ${circ.toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"></circle>`;
        offset += dash;
        return seg;
      }).join("");

      legend.innerHTML = entries.map(([label, count], i) => {
        const pct = ((count / total) * 100).toFixed(1);
        const color = PALETTE[i % PALETTE.length];
        return `
          <div class="legend-item">
            <span class="legend-swatch" style="background:${color};"></span>
            <span class="mono">${label}</span>
            <span style="color:var(--muted);">(${pct}%)</span>
          </div>
        `;
      }).join("");
    }

    function renderDifficultyChart() {
      const svg = document.getElementById("diffChartSvg");
      const recent = cachedBlocks.slice(-30);
      if (recent.length < 2) { svg.innerHTML = ""; return; }

      const w = 540, h = 155, pad = 16;
      const bitsArr = recent.map(b => Number(b.bits || 6));
      const txsArr = recent.map(b => (b.txs || []).length);

      const minB = Math.min(...bitsArr) - 1;
      const maxB = Math.max(...bitsArr) + 1;
      const maxT = Math.max(...txsArr, 2);

      const diffPts = bitsArr.map((v, i) => {
        const x = (i / (recent.length - 1)) * w;
        const y = h - pad - ((v - minB) / Math.max(1, maxB - minB)) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");

      const txPts = txsArr.map((v, i) => {
        const x = (i / (recent.length - 1)) * w;
        const y = h - pad - (v / maxT) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");

      svg.innerHTML = `
        <line x1="0" y1="${h - pad}" x2="${w}" y2="${h - pad}" stroke="#2c3148" stroke-width="1"/>
        <line x1="0" y1="${pad}" x2="${w}" y2="${pad}" stroke="#2c3148" stroke-dasharray="4 4" stroke-width="1"/>
        <polyline fill="none" stroke="#10b981" stroke-width="2.4" points="${diffPts}" />
        <polyline fill="none" stroke="#f59e0b" stroke-width="2" points="${txPts}" />
        <text x="4" y="12" fill="#10b981" font-size="11" font-weight="700">● PoW Difficulty (${bitsArr[bitsArr.length - 1]} bits)</text>
        <text x="195" y="12" fill="#f59e0b" font-size="11" font-weight="700">● Txs per Block</text>
      `;
    }

    function renderTxTable() {
      const tbody = document.getElementById("txsTable");
      const rows = [];

      // Newest pending mempool transactions FIRST!
      for (const tx of cachedMempool.slice().reverse()) {
        rows.push({ tx, status: "PENDING", height: null });
      }
      // Followed by newest confirmed transactions
      for (let i = cachedBlocks.length - 1; i >= 0 && rows.length < 18; i--) {
        const b = cachedBlocks[i];
        for (let j = b.txs.length - 1; j >= 0 && rows.length < 18; j--) {
          rows.push({ tx: b.txs[j], status: "CONFIRMED", height: b.height });
        }
      }

      tbody.innerHTML = rows.map(item => {
        const t = item.tx;
        const fromHtml = t.sender.startsWith("COINBASE:")
          ? `<span style="color:var(--muted)">COINBASE</span>`
          : `<a onclick="inspectAddress('${t.sender}')">${shortHex(t.sender, 6)}</a>`;
        const toHtml = t.recipient
          ? `<a onclick="inspectAddress('${t.recipient}')">${shortHex(t.recipient, 6)}</a>`
          : `<span style="color:var(--muted)">Staking Pool</span>`;
        const blkHtml = item.height !== null
          ? `<a onclick="inspectBlock(${item.height})">#${item.height}</a>`
          : `<span style="color:#facc15;">Mempool</span>`;

        return `
          <tr>
            <td class="mono"><a onclick="inspectTx('${t._txid}')">${shortHex(t._txid, 8)}</a></td>
            <td>
              <span class="badge badge-TX">${t.kind}</span>
              ${item.status === "PENDING" ? `<span class="badge badge-PENDING">PENDING</span>` : ""}
            </td>
            <td>${blkHtml}</td>
            <td class="mono">${fromHtml}</td>
            <td class="mono">${toHtml}</td>
            <td><strong>${fmtTai(t.amount, 4)}</strong></td>
            <td style="color:var(--muted)">${fmtTai(t.fee, 5)}</td>
          </tr>
        `;
      }).join("");
    }

    async function refreshData() {
      try {
        const res = await fetch("/api/overview");
        if (!res.ok) throw new Error("Node offline");
        const data = await res.json();

        document.getElementById("connDot").className = "dot";
        document.getElementById("connText").textContent = "Mainnet";

        cachedStats = data.stats || {};
        cachedBlocks = data.blocks || [];
        cachedMempool = data.mempool || [];
        txIndex = data.tx_index || {};

        const supplyUnits = Number(cachedStats.supply || 0);
        const stakedUnits = Number(cachedStats.staked || 0);
        const totalBlocks = cachedBlocks.length;
        const totalTxs = Object.keys(txIndex).length;

        let totalFees = 0;
        for (const b of cachedBlocks) {
          for (const t of (b.txs || [])) totalFees += Number(t.fee || 0);
        }
        const avgBlockFee = totalBlocks > 0 ? (totalFees / totalBlocks) / 1e8 : 0;

        let avgTime = "20.0s";
        if (cachedBlocks.length >= 2) {
          const sl = cachedBlocks.slice(-21);
          const span = sl[sl.length - 1].ts - sl[0].ts;
          avgTime = Math.max(0.1, span / (sl.length - 1)).toFixed(1) + "s";
        }

        const height = Number(cachedStats.height || 0);
        const halvingRem = 210000 - (height % 210000);

        document.getElementById("statSupply").textContent = (supplyUnits / 1e8).toLocaleString(undefined, { maximumFractionDigits: 2 });
        document.getElementById("statAvgBlockFee").textContent = avgBlockFee.toFixed(5);
        document.getElementById("statStaked").textContent = (stakedUnits / 1e8).toLocaleString(undefined, { maximumFractionDigits: 2 });
        document.getElementById("statStakedPct").textContent = supplyUnits > 0 ? ((stakedUnits / supplyUnits) * 100).toFixed(1) + "% of supply" : "0.0% of supply";

        document.getElementById("statPowCount").textContent = cachedStats.pow_blocks || 0;
        document.getElementById("statPosCount").textContent = cachedStats.pos_blocks || 0;
        document.getElementById("statAvgTime").textContent = `Avg ${avgTime} / block`;
        document.getElementById("statBits").textContent = cachedStats.bits || 6;
        document.getElementById("statHalvingBlocks").textContent = halvingRem.toLocaleString();

        document.getElementById("statTotalBlocks").textContent = totalBlocks.toLocaleString();
        document.getElementById("statTotalTxs").textContent = totalTxs.toLocaleString();
        document.getElementById("statMempoolCount").innerHTML = `${cachedMempool.length}<span class="st-unit">txs</span>`;

        render3DRibbon();
        renderDonutChart();
        renderDifficultyChart();
        renderTxTable();
      } catch {
        document.getElementById("connDot").className = "dot offline";
        document.getElementById("connText").textContent = "Offline";
      }
    }

    function showValidators() {
      showAlert("");
      setActiveTab("tabValidators");
      const stakes = {};
      const blocksByProd = {};
      for (const b of cachedBlocks) {
        if (b.producer) blocksByProd[b.producer] = (blocksByProd[b.producer] || 0) + 1;
        for (const t of (b.txs || [])) {
          if (t.kind === "STAKE") stakes[t.sender] = (stakes[t.sender] || 0) + Number(t.amount);
          if (t.kind === "UNSTAKE") stakes[t.sender] = Math.max(0, (stakes[t.sender] || 0) - Number(t.amount));
        }
      }
      const rows = Object.entries(stakes).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]);
      document.getElementById("homeView").style.display = "none";
      const dv = document.getElementById("detailView");
      dv.innerHTML = `
        <div class="table-card">
          <div class="table-header">
            <span>PoS Validators &amp; Stakers (Min 100 TAI)</span>
            <button class="btn-back" onclick="showHome()">← Back to Dashboard</button>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Validator Address</th><th>Staked Amount</th><th>Status</th><th>Blocks Produced</th></tr></thead>
              <tbody>
                ${rows.length ? rows.map(([addr, amt]) => `
                  <tr>
                    <td class="mono"><a onclick="inspectAddress('${addr}')">${addr}</a></td>
                    <td><strong>${fmtTai(amt, 4)}</strong></td>
                    <td><span class="badge ${amt >= 100e8 ? "badge-POS" : "badge-POW"}">${amt >= 100e8 ? "ACTIVE VALIDATOR" : "BELOW 100 TAI"}</span></td>
                    <td>${blocksByProd[addr] || 0}</td>
                  </tr>
                `).join("") : "<tr><td colspan='4' style='color:var(--muted)'>No staked validators found.</td></tr>"}
              </tbody>
            </table>
          </div>
        </div>
      `;
      dv.style.display = "block";
    }

    function showSpecs() {
      showAlert("");
      setActiveTab("tabSpecs");
      document.getElementById("homeView").style.display = "none";
      const dv = document.getElementById("detailView");
      dv.innerHTML = `
        <div class="table-card">
          <div class="table-header">
            <span>Tai Mainnet Technical Specifications</span>
            <button class="btn-back" onclick="showHome()">← Back to Dashboard</button>
          </div>
          <div class="table-wrap">
            <div class="detail-row"><div class="detail-key">Chain ID</div><div class="mono">tai-mainnet-v1</div></div>
            <div class="detail-row"><div class="detail-key">Hybrid Consensus</div><div>Alternating Argon2id PoW (Odd Heights) &amp; ML-DSA-65 PoS (Even Heights)</div></div>
            <div class="detail-row"><div class="detail-key">Post-Quantum Signatures</div><div>NIST FIPS 204 ML-DSA-65 (Dilithium3)</div></div>
            <div class="detail-row"><div class="detail-key">Supply &amp; Emission</div><div>21,000,000 TAI max • 50 TAI initial block reward • Halving every 210,000 blocks</div></div>
            <div class="detail-row"><div class="detail-key">Min Validator Stake</div><div>100 TAI (20-block unbonding delay)</div></div>
          </div>
        </div>
      `;
      dv.style.display = "block";
    }

    function inspectBlock(heightOrHash) {
      showAlert("");
      const blk = typeof heightOrHash === "number"
        ? cachedBlocks.find(b => b.height === heightOrHash)
        : cachedBlocks.find(b => b.hash === heightOrHash);
      if (!blk) { showAlert("Block not found: " + heightOrHash); return; }

      const txRows = blk.txs.map(t => `
        <tr>
          <td class="mono"><a onclick="inspectTx('${t._txid}')">${shortHex(t._txid, 10)}</a></td>
          <td><span class="badge badge-TX">${t.kind}</span></td>
          <td class="mono">${t.sender.startsWith("COINBASE:") ? t.sender : `<a onclick="inspectAddress('${t.sender}')">${shortHex(t.sender, 8)}</a>`}</td>
          <td class="mono">${t.recipient ? `<a onclick="inspectAddress('${t.recipient}')">${shortHex(t.recipient, 8)}</a>` : "-"}</td>
          <td>${fmtTai(t.amount)}</td>
          <td>${fmtTai(t.fee, 5)}</td>
        </tr>
      `).join("");

      document.getElementById("homeView").style.display = "none";
      const dv = document.getElementById("detailView");
      dv.innerHTML = `
        <div class="table-card">
          <div class="table-header">
            <span>Block #${blk.height} <span class="badge badge-${blk.kind}" style="margin-left:8px;">${blk.kind}</span></span>
            <button class="btn-back" onclick="showHome()">← Back to Dashboard</button>
          </div>
          <div class="table-wrap">
            <div class="detail-row"><div class="detail-key">Block Hash</div><div class="mono">${blk.hash}</div></div>
            <div class="detail-row"><div class="detail-key">Previous Hash</div><div class="mono">${blk.height > 0 ? `<a onclick="inspectBlock(${blk.height - 1})">${blk.prev}</a>` : blk.prev}</div></div>
            <div class="detail-row"><div class="detail-key">Timestamp</div><div>${new Date(blk.ts * 1000).toUTCString()} (${timeAgo(blk.ts)})</div></div>
            <div class="detail-row"><div class="detail-key">Producer</div><div class="mono">${blk.producer ? `<a onclick="inspectAddress('${blk.producer}')">${blk.producer}</a>` : "GENESIS"}</div></div>
            <div class="detail-row"><div class="detail-key">Difficulty (Bits)</div><div>${blk.bits}</div></div>
            <div class="detail-row"><div class="detail-key">Nonce</div><div class="mono">${blk.nonce}</div></div>
          </div>
        </div>
        <div class="table-card">
          <div class="table-header"><span>Transactions (${blk.txs.length})</span></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Txn Hash</th><th>Type</th><th>From</th><th>To</th><th>Value</th><th>Fee</th></tr></thead>
              <tbody>${txRows}</tbody>
            </table>
          </div>
        </div>
      `;
      dv.style.display = "block";
    }

    function inspectTx(txid) {
      showAlert("");
      const entry = txIndex[txid];
      if (!entry) { showAlert("Transaction not found: " + txid); return; }
      const t = entry.tx;
      document.getElementById("homeView").style.display = "none";
      const dv = document.getElementById("detailView");
      dv.innerHTML = `
        <div class="table-card">
          <div class="table-header">
            <span>Transaction <span class="badge badge-TX" style="margin-left:8px;">${t.kind}</span></span>
            <button class="btn-back" onclick="showHome()">← Back to Dashboard</button>
          </div>
          <div class="table-wrap">
            <div class="detail-row"><div class="detail-key">Transaction Hash</div><div class="mono">${txid}</div></div>
            <div class="detail-row"><div class="detail-key">Status</div><div>${entry.blockHeight !== null ? `Confirmed in <a onclick="inspectBlock(${entry.blockHeight})">Block #${entry.blockHeight}</a>` : `<span class="badge badge-PENDING">PENDING IN MEMPOOL</span>`}</div></div>
            <div class="detail-row"><div class="detail-key">From</div><div class="mono">${t.sender.startsWith("COINBASE:") ? t.sender : `<a onclick="inspectAddress('${t.sender}')">${t.sender}</a>`}</div></div>
            <div class="detail-row"><div class="detail-key">To</div><div class="mono">${t.recipient ? `<a onclick="inspectAddress('${t.recipient}')">${t.recipient}</a>` : "<em>Protocol Staking Contract</em>"}</div></div>
            <div class="detail-row"><div class="detail-key">Value</div><div><strong>${fmtTai(t.amount)}</strong></div></div>
            <div class="detail-row"><div class="detail-key">Fee</div><div>${fmtTai(t.fee, 5)}</div></div>
            <div class="detail-row"><div class="detail-key">Nonce</div><div>${t.nonce}</div></div>
          </div>
        </div>
      `;
      dv.style.display = "block";
    }

    async function inspectAddress(addr) {
      showAlert("");
      try {
        const res = await fetch("/api/address/" + addr);
        if (!res.ok) throw new Error("Failed to fetch address");
        const info = await res.json();
        const historyRows = (info.history || []).map(h => `
          <tr>
            <td class="mono"><a onclick="inspectTx('${h.txid}')">${shortHex(h.txid, 10)}</a></td>
            <td><a onclick="inspectBlock(${h.height})">#${h.height}</a></td>
            <td><span class="badge badge-TX">${h.kind}</span></td>
            <td>${h.role}</td>
            <td>${fmtTai(h.amount)}</td>
          </tr>
        `).join("");

        document.getElementById("homeView").style.display = "none";
        const dv = document.getElementById("detailView");
        dv.innerHTML = `
          <div class="table-card">
            <div class="table-header">
              <span>Address Overview</span>
              <button class="btn-back" onclick="showHome()">← Back to Dashboard</button>
            </div>
            <div class="table-wrap">
              <div class="detail-row"><div class="detail-key">Address</div><div class="mono">${info.address}</div></div>
              <div class="detail-row"><div class="detail-key">Available Balance</div><div><strong>${info.balance_formatted}</strong></div></div>
              <div class="detail-row"><div class="detail-key">Staked Balance</div><div><strong>${info.staked_formatted}</strong></div></div>
              <div class="detail-row"><div class="detail-key">Nonce</div><div>${info.nonce}</div></div>
              <div class="detail-row"><div class="detail-key">Blocks Produced</div><div>${info.blocks_produced}</div></div>
            </div>
          </div>
          <div class="table-card">
            <div class="table-header"><span>Transaction History (${(info.history || []).length})</span></div>
            <div class="table-wrap">
              <table>
                <thead><tr><th>Txn Hash</th><th>Block</th><th>Type</th><th>Direction</th><th>Value</th></tr></thead>
                <tbody>${historyRows || "<tr><td colspan='5' style='color:var(--muted)'>No confirmed transactions yet</td></tr>"}</tbody>
              </table>
            </div>
          </div>
        `;
        dv.style.display = "block";
      } catch (e) {
        showAlert("Error loading address: " + e.message);
      }
    }

    async function handleSearch(e) {
      e.preventDefault();
      const q = document.getElementById("searchInput").value.trim().toLowerCase();
      if (!q) return;
      if (/^\d+$/.test(q)) { inspectBlock(parseInt(q, 10)); return; }
      if (/^[0-9a-f]{64}$/.test(q)) {
        if (cachedBlocks.some(b => b.hash === q)) { inspectBlock(q); return; }
        if (txIndex[q]) { inspectTx(q); return; }
        await inspectAddress(q);
        return;
      }
      showAlert("Enter a valid block height (number) or 64-character hex block hash, TxID, or address.");
    }

    refreshData();
    setInterval(refreshData, 3000);
  </script>
</body>
</html>
"""


def compute_txid(tx: dict) -> str:
    body = {
        "chain_id": tx["chain_id"],
        "kind": tx["kind"],
        "sender": tx["sender"],
        "recipient": tx["recipient"],
        "amount": tx["amount"],
        "fee": tx["fee"],
        "nonce": tx["nonce"],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def fetch_node_json(node_url: str, path: str) -> dict:
    req = urllib.request.Request(f"{node_url}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_explorer(node_url: str, host: str, port: int):
    node_url = node_url.rstrip("/")

    class ExplorerHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt_str, *args):
            pass

        def _send_html(self, html: str):
            raw = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_json(self, code: int, payload: dict):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                if path == "/":
                    self._send_html(HTML_PAGE)

                elif path == "/api/overview":
                    stats = fetch_node_json(node_url, "/stats")
                    blocks = fetch_node_json(node_url, "/chain").get("blocks", [])
                    mempool = fetch_node_json(node_url, "/mempool").get("txs", [])

                    tx_index = {}
                    for b in blocks:
                        for t in b.get("txs", []):
                            tid = compute_txid(t)
                            t["_txid"] = tid
                            tx_index[tid] = {
                                "tx": t,
                                "blockHeight": b["height"],
                                "blockHash": b["hash"],
                                "blockTs": b["ts"],
                            }
                    for t in mempool:
                        tid = compute_txid(t)
                        t["_txid"] = tid
                        tx_index[tid] = {
                            "tx": t,
                            "blockHeight": None,
                            "blockHash": None,
                            "blockTs": None,
                        }

                    self._send_json(
                        200,
                        {
                            "node_url": node_url,
                            "stats": stats,
                            "blocks": blocks,
                            "mempool": mempool,
                            "tx_index": tx_index,
                        },
                    )

                elif path.startswith("/api/address/"):
                    addr = path.split("/api/address/", 1)[1].lower()
                    bal_info = fetch_node_json(node_url, f"/balance/{addr}")
                    blocks = fetch_node_json(node_url, "/chain").get("blocks", [])

                    blocks_produced = 0
                    history = []
                    for b in reversed(blocks):
                        if b.get("producer") == addr:
                            blocks_produced += 1
                        for t in reversed(b.get("txs", [])):
                            tid = compute_txid(t)
                            role = None
                            if t.get("sender") == addr and t.get("recipient") == addr:
                                role = "SELF"
                            elif t.get("sender") == addr:
                                role = "OUT"
                            elif t.get("recipient") == addr:
                                role = "REWARD" if t.get("kind") == "COINBASE" else "IN"
                            if role:
                                history.append(
                                    {
                                        "txid": tid,
                                        "height": b["height"],
                                        "kind": t["kind"],
                                        "role": role,
                                        "amount": t["amount"],
                                    }
                                )

                    bal_info["blocks_produced"] = blocks_produced
                    bal_info["history"] = history[:100]
                    self._send_json(200, bal_info)

                else:
                    self._send_json(404, {"error": "not found"})
            except Exception as e:
                self._send_json(502, {"error": str(e)})

    server = ThreadingHTTPServer((host, port), ExplorerHandler)
    print(f"[TAI.SPACE] Explorer running at http://{host}:{port} -> proxying {node_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Tai.Space explorer...")
    finally:
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="TAI.SPACE — Litecoin.space-style Block Explorer")
    parser.add_argument("--node", default="http://127.0.0.1:8001", help="Running Tai node RPC URL")
    parser.add_argument("--host", default="127.0.0.1", help="Explorer bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Explorer bind port (default: 8080)")
    args = parser.parse_args()
    run_explorer(args.node, args.host, args.port)


if __name__ == "__main__":
    main()
