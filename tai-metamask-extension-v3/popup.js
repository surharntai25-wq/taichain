const API_BASE = "http://127.0.0.1:18095";
let generatedWords = [];
let currentAction = "send";
let fullAddress = "";
let activeChainId = "tai-mainnet";
let allChains = [];
let activeFamilyFilter = "ALL";
let cachedWalletData = null;

function showToast(msg, ok = true) {
  const el = document.getElementById("toast");
  if (!msg) { el.style.display = "none"; return; }
  el.textContent = msg;
  el.className = "toast " + (ok ? "ok" : "err");
  el.style.display = "block";
}

function showView(viewId) {
  showToast("");
  document.getElementById("menuDrawer").classList.remove("open");
  document.getElementById("netModal").classList.remove("open");
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById(viewId).classList.add("active");
  if (viewId === "viewUnlock") setTimeout(() => document.getElementById("unlockPass").focus(), 50);
}

function renderSeedGrid(containerId, words) {
  document.getElementById(containerId).innerHTML = words.map((w, idx) =>
    `<div class="seed-word"><span class="seed-num">${idx + 1}.</span><span>${w}</span></div>`
  ).join("");
}

async function apiGet(path) {
  const res = await fetch(API_BASE + path);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

async function apiPost(path, body) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || "Action failed");
  return data;
}

async function loadChains() {
  try {
    const res = await apiGet("/api/chains");
    allChains = res.chains || [];
    document.getElementById("chainCountLabel").textContent = allChains.length;
    renderNetworkList();
  } catch {}
}

function renderNetworkList() {
  const q = document.getElementById("netSearchInput").value.trim().toLowerCase();
  const filtered = allChains.filter(c => {
    const famMatch = activeFamilyFilter === "ALL" || c.family === activeFamilyFilter;
    const textMatch = !q || c.name.toLowerCase().includes(q) || c.symbol.toLowerCase().includes(q) || String(c.chainId || "").includes(q);
    return famMatch && textMatch;
  });

  document.getElementById("netList").innerHTML = filtered.map(c => `
    <div class="net-item ${c.id === activeChainId ? "selected" : ""}" data-cid="${c.id}">
      <div class="net-left">
        <span class="net-dot" style="background:${c.color || "#38bdf8"};"></span>
        <div>
          <div style="font-size:0.82rem; font-weight:700;">${c.name}</div>
          <div style="font-size:0.68rem; color:var(--muted);">${c.family}${c.chainId ? " • ID " + c.chainId : ""}</div>
        </div>
      </div>
      <span class="net-sym">${c.symbol}</span>
    </div>
  `).join("");

  document.querySelectorAll(".net-item").forEach(el => {
    el.onclick = () => {
      activeChainId = el.getAttribute("data-cid");
      document.getElementById("netModal").classList.remove("open");
      renderNetworkList();
      refreshDashboard();
    };
  });
}

async function refreshDashboard() {
  try {
    const d = await apiGet("/api/wallet?chain=" + encodeURIComponent(activeChainId));
    cachedWalletData = d;
    fullAddress = d.address;
    const chain = d.chain || { name: "Tai Mainnet", symbol: "TAI", family: "TAI", color: "#10b981" };

    if (typeof d.account_index === "number") {
      document.getElementById("accountSelect").value = String(d.account_index);
      document.getElementById("addrAcctIdx").textContent = d.account_index;
    }

    document.getElementById("curNetName").textContent = chain.name;
    document.getElementById("curNetDot").style.background = chain.color || "#10b981";
    document.getElementById("addrText").textContent = d.address.slice(0, 6) + "…" + d.address.slice(-4);
    document.getElementById("chainEmblem").textContent = chain.symbol.slice(0, 4);
    document.getElementById("chainEmblem").style.color = chain.color || "#fff";
    document.getElementById("mainBal").textContent = d.balance_formatted;
    document.getElementById("chainSubLabel").textContent = chain.name;
    document.getElementById("mainHeight").textContent = Number(d.height || 0).toLocaleString();
    document.getElementById("mainStaked").textContent = d.staked_formatted;

    const isTai = chain.family === "TAI";
    document.getElementById("qaStake").style.opacity = isTai ? "1" : "0.45";
    document.getElementById("qaUnstake").style.opacity = isTai ? "1" : "0.45";
    document.getElementById("bannerLabel").textContent = isTai ? "PoS Staking" : "Network Standard";
    document.getElementById("bannerBadge").textContent = isTai ? "50 TAI / block" : chain.family;
    document.getElementById("btnSendTx").textContent =
      currentAction === "send" ? `Send ${chain.symbol}` : currentAction === "stake" ? "Stake TAI" : "Unstake TAI";

    const online = d.online !== false;
    document.getElementById("statusDot").className = online ? "status-badge" : "status-badge off";
    document.getElementById("netStatusText").textContent = online ? `${chain.symbol} RPC Online` : "RPC Offline";
    document.getElementById("netStatusText").style.color = online ? "var(--green)" : "var(--red)";

    const list = document.getElementById("activityList");
    if (!d.history || d.history.length === 0) {
      list.textContent = isTai ? "No transactions yet" : `View full ${chain.name} history in Explorer`;
    } else {
      list.innerHTML = d.history.slice(0, 10).map(item => {
        const isIn = item.role === "IN" || item.role === "REWARD";
        return `<div class="tx-row">
          <span><strong>${item.kind}</strong> <span style="color:var(--muted)">#${item.height}</span></span>
          <span style="font-weight:700; color:${isIn ? "var(--green)" : "var(--accent)"}">${isIn ? "+" : "-"}${item.amount_fmt}</span>
        </div>`;
      }).join("");
    }
  } catch {
    document.getElementById("statusDot").className = "status-badge off";
  }
}

async function boot() {
  await loadChains();
  try {
    const st = await apiGet("/api/status");
    if (!st.has_vault) {
      document.getElementById("addrText").textContent = "No Wallet";
      showView("viewWelcome");
    } else if (!st.unlocked) {
      document.getElementById("addrText").textContent = "Locked";
      showView("viewUnlock");
    } else {
      showView("viewMain");
      refreshDashboard();
    }
  } catch {
    document.getElementById("statusDot").className = "status-badge off";
    showView("viewWelcome");
    showToast("Start taimask_vault.py on port 18095 first.", false);
  }
}

// Network Modal Events
document.getElementById("btnNetSelect").onclick = () => {
  document.getElementById("netModal").classList.toggle("open");
  document.getElementById("netSearchInput").focus();
};
document.getElementById("btnCloseNet").onclick = () => document.getElementById("netModal").classList.remove("open");
document.getElementById("netSearchInput").oninput = renderNetworkList;

document.querySelectorAll(".f-chip").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll(".f-chip").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeFamilyFilter = btn.getAttribute("data-fam");
    renderNetworkList();
  };
});

document.getElementById("btnShowAddCustom").onclick = () => {
  const f = document.getElementById("formCustomChain");
  f.style.display = f.style.display === "none" ? "block" : "none";
};

document.getElementById("formCustomChain").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const res = await apiPost("/api/add-chain", {
      name: document.getElementById("custName").value,
      chainId: document.getElementById("custChainId").value,
      symbol: document.getElementById("custSymbol").value,
      rpc: document.getElementById("custRpc").value
    });
    activeChainId = res.chain.id;
    await loadChains();
    document.getElementById("netModal").classList.remove("open");
    showToast("Added " + res.chain.name);
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

// Menu & Copy
document.getElementById("btnMenuToggle").onclick = () => document.getElementById("menuDrawer").classList.toggle("open");
document.getElementById("addrPill").onclick = async () => {
  if (!fullAddress) return;
  await navigator.clipboard.writeText(fullAddress);
  showToast("Copied address: " + fullAddress);
};
document.getElementById("btnCopyFullAddr").onclick = async () => {
  if (!fullAddress) return;
  await navigator.clipboard.writeText(fullAddress);
  showToast("Copied address: " + fullAddress);
};

document.getElementById("btnExplorerChain").onclick = () => {
  const c = cachedWalletData && cachedWalletData.chain;
  if (c && c.explorer) {
    const url = c.family === "TAI" ? c.explorer : `${c.explorer}/address/${fullAddress}`;
    window.open(url, "_blank");
  }
};

// All Addresses View
function openAllAddresses() {
  if (!cachedWalletData || !cachedWalletData.all_addresses) return;
  const addrs = cachedWalletData.all_addresses;
  const labels = {
    TAI: "Tai Mainnet (ML-DSA-65 PQ)",
    EVM: "Ethereum, Optimism, Base, Arbitrum, Polygon, BSC & Top 100 EVMs",
    BTC: "Bitcoin Native SegWit (Bech32)",
    SOL: "Solana Mainnet (Ed25519)",
    DOGE: "Dogecoin Mainnet (P2PKH)",
    LTC: "Litecoin Native SegWit (Bech32)"
  };
  document.getElementById("allAddrsCard").innerHTML = Object.entries(labels).map(([fam, desc]) => `
    <div style="padding:10px 0; border-bottom:1px solid var(--border);">
      <div style="font-size:0.76rem; font-weight:700; color:var(--accent);">${fam} — <span style="color:var(--muted); font-weight:400;">${desc}</span></div>
      <div style="font-family:ui-monospace, monospace; font-size:0.75rem; word-break:break-all; margin-top:4px; cursor:pointer;" onclick="navigator.clipboard.writeText('${addrs[fam]}'); showToast('Copied ${fam} address!')">${addrs[fam]} ❐</div>
    </div>
  `).join("");
  showView("viewAddresses");
}

document.getElementById("btnAllAddrs").onclick = openAllAddresses;
document.getElementById("bnavAddrs").onclick = openAllAddresses;
document.getElementById("btnBackFromAddrs").onclick = () => showView("viewMain");

// Onboarding & Auth
document.getElementById("btnStartCreate").onclick = async () => {
  showView("viewCreate");
  const data = await apiGet("/api/new-seed");
  generatedWords = data.words;
  renderSeedGrid("seedGrid", generatedWords);
};
document.getElementById("btnStartImport").onclick = () => showView("viewImport");
document.getElementById("btnResetImport").onclick = () => showView("viewImport");
document.getElementById("btnBackWelcome1").onclick = () => showView("viewWelcome");
document.getElementById("btnBackWelcome2").onclick = () => showView("viewWelcome");
document.getElementById("btnRegenSeed").onclick = async () => {
  const data = await apiGet("/api/new-seed");
  generatedWords = data.words;
  renderSeedGrid("seedGrid", generatedWords);
};
document.getElementById("btnCopySeed").onclick = async () => {
  await navigator.clipboard.writeText(generatedWords.join(" "));
  showToast("12-word seed phrase copied!");
};

document.getElementById("formCreate").onsubmit = async (e) => {
  e.preventDefault();
  if (
    document.getElementById("confirmWord3").value.trim().toLowerCase() !== generatedWords[2] ||
    document.getElementById("confirmWord12").value.trim().toLowerCase() !== generatedWords[11]
  ) {
    showToast("Word #3 or Word #12 does not match!", false);
    return;
  }
  try {
    await apiPost("/api/setup", { mnemonic: generatedWords.join(" "), password: document.getElementById("createPass").value });
    showView("viewMain");
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

document.getElementById("formImport").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await apiPost("/api/setup", {
      mnemonic: document.getElementById("importSeedInput").value.trim(),
      password: document.getElementById("importPass").value
    });
    showView("viewMain");
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

document.getElementById("formUnlock").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await apiPost("/api/unlock", { password: document.getElementById("unlockPass").value });
    document.getElementById("unlockPass").value = "";
    showView("viewMain");
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

document.getElementById("btnLock").onclick = async () => {
  await apiPost("/api/lock", {});
  document.getElementById("addrText").textContent = "Locked";
  showView("viewUnlock");
};

// Actions
function setActionMode(mode) {
  const chain = (cachedWalletData && cachedWalletData.chain) || { family: "TAI", symbol: "TAI" };
  if ((mode === "stake" || mode === "unstake") && chain.family !== "TAI") {
    showToast("Native PoS staking is available on Tai Mainnet.", false);
    return;
  }
  currentAction = mode;
  ["qaStake", "qaUnstake", "qaSend", "qaReceive"].forEach(id => document.getElementById(id).classList.remove("active"));
  if (mode === "receive") {
    document.getElementById("qaReceive").classList.add("active");
    if (fullAddress) {
      navigator.clipboard.writeText(fullAddress);
      showToast("Receive Address copied: " + fullAddress);
    }
    return;
  }
  const map = { stake: "qaStake", unstake: "qaUnstake", send: "qaSend" };
  document.getElementById(map[mode]).classList.add("active");
  document.getElementById("recGroup").style.display = mode === "send" ? "block" : "none";
  document.getElementById("btnSendTx").textContent =
    mode === "send" ? `Send ${chain.symbol}` : mode === "stake" ? "Stake TAI" : "Unstake TAI";
}

document.getElementById("qaStake").onclick = () => setActionMode("stake");
document.getElementById("qaUnstake").onclick = () => setActionMode("unstake");
document.getElementById("qaSend").onclick = () => setActionMode("send");
document.getElementById("qaReceive").onclick = () => setActionMode("receive");

document.getElementById("formTx").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const res = await apiPost("/api/action", {
      chain: activeChainId,
      action: currentAction,
      recipient: document.getElementById("txRecipient").value.trim(),
      amount: document.getElementById("txAmount").value.trim(),
      fee: "0.00001"
    });
    showToast("Broadcasted! TxID: " + res.txid);
    document.getElementById("txAmount").value = "";
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

// Seed Backup
document.getElementById("btnRevealSeed").onclick = () => {
  document.getElementById("revealedGrid").style.display = "none";
  document.getElementById("revealPass").value = "";
  showView("viewReveal");
  setTimeout(() => document.getElementById("revealPass").focus(), 50);
};
document.getElementById("formReveal").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const res = await apiPost("/api/reveal-seed", { password: document.getElementById("revealPass").value });
    renderSeedGrid("revealedGrid", res.words);
    document.getElementById("revealedGrid").style.display = "grid";
  } catch (err) {
    showToast(err.message, false);
  }
};
document.getElementById("btnBackMain").onclick = () => showView("viewMain");

// Account Switcher
document.getElementById("accountSelect").onchange = async (e) => {
  const idx = parseInt(e.target.value, 10);
  try {
    await apiPost("/api/switch-account", { account_index: idx });
    showToast("Switched to Account " + idx);
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

// Bottom Nav
document.getElementById("bnavHome").onclick = () => {
  showView("viewMain");
  document.querySelector(".scroll-body").scrollTo({ top: 0, behavior: "smooth" });
};
document.getElementById("bnavNetworks").onclick = () => {
  showView("viewMain");
  document.getElementById("netModal").classList.add("open");
  document.getElementById("netSearchInput").focus();
};
document.getElementById("bnavActivity").onclick = () => {
  showView("viewMain");
  document.getElementById("activitySection").scrollIntoView({ behavior: "smooth" });
};

boot();
setInterval(() => {
  if (document.getElementById("viewMain").classList.contains("active")) {
    refreshDashboard();
  }
}, 5000);

async function handleFullReset() {
  if (!confirm("Reset TaiMask? Make sure you backed up your 12-word seed phrase first. This deletes taimask_vault.json so you can create or import a new wallet.")) {
    return;
  }
  try {
    await apiPost("/api/reset", {});
    fullAddress = "";
    cachedWalletData = null;
    document.getElementById("addrText").textContent = "No Wallet";
    showView("viewWelcome");
    showToast("Vault reset! Create a new wallet or import a 12-word seed.");
  } catch (err) {
    showToast(err.message, false);
  }
}

document.getElementById("btnFullResetUnlock").onclick = handleFullReset;
document.getElementById("btnFullResetMenu").onclick = handleFullReset;
