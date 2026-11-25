const API_BASE = "http://127.0.0.1:18095";
let generatedWords = [];
let currentAction = "send";
let fullAddress = "";

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
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById(viewId).classList.add("active");

  if (viewId === "viewUnlock") {
    setTimeout(() => document.getElementById("unlockPass").focus(), 50);
  }
}

function renderSeedGrid(containerId, words) {
  const grid = document.getElementById(containerId);
  grid.innerHTML = words.map((w, idx) =>
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

async function generateNewSeed() {
  const data = await apiGet("/api/new-seed");
  generatedWords = data.words;
  renderSeedGrid("seedGrid", generatedWords);
  document.getElementById("confirmWord3").value = "";
  document.getElementById("confirmWord12").value = "";
}

async function refreshDashboard() {
  try {
    const d = await apiGet("/api/wallet");
    fullAddress = d.address;
    if (typeof d.account_index === "number") {
      document.getElementById("accountSelect").value = String(d.account_index);
    }
    document.getElementById("addrText").textContent = d.address.slice(0, 6) + "…" + d.address.slice(-4);
    document.getElementById("mainBal").textContent = d.balance_formatted;
    document.getElementById("mainStaked").textContent = d.staked_formatted;
    document.getElementById("mainHeight").textContent = d.height;
    document.getElementById("mainNonce").textContent = d.nonce;

    const online = d.node_online !== false;
    document.getElementById("statusDot").className = online ? "status-badge" : "status-badge off";
    document.getElementById("netStatusText").textContent = online ? "Mainnet Online" : "Node Offline";
    document.getElementById("netStatusText").style.color = online ? "var(--green)" : "var(--red)";

    const list = document.getElementById("activityList");
    if (!d.history || d.history.length === 0) {
      list.textContent = "No transactions yet";
    } else {
      list.innerHTML = d.history.slice(0, 10).map(item => {
        const isIn = item.role === "IN" || item.role === "REWARD";
        const amt = (item.amount / 1e8).toLocaleString(undefined, { maximumFractionDigits: 4 });
        return `<div class="tx-row">
          <span><strong>${item.kind}</strong> <span style="color:var(--muted)">#${item.height}</span></span>
          <span style="font-weight:700; color:${isIn ? "var(--green)" : "var(--accent)"}">${isIn ? "+" : "-"}${amt} TAI</span>
        </div>`;
      }).join("");
    }
  } catch {
    document.getElementById("statusDot").className = "status-badge off";
  }
}

async function boot() {
  try {
    const st = await apiGet("/api/status");
    document.getElementById("statusDot").className = "status-badge";
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

// Menu & Top Bar Actions
document.getElementById("btnMenuToggle").onclick = () => {
  document.getElementById("menuDrawer").classList.toggle("open");
};

document.getElementById("btnTopExplorer").onclick = () => {
  window.open("http://127.0.0.1:8080", "_blank");
};

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

// Onboarding Navigation
document.getElementById("btnStartCreate").onclick = async () => {
  showView("viewCreate");
  await generateNewSeed();
};
document.getElementById("btnStartImport").onclick = () => showView("viewImport");
document.getElementById("btnResetImport").onclick = () => showView("viewImport");
document.getElementById("btnBackWelcome1").onclick = () => showView("viewWelcome");
document.getElementById("btnBackWelcome2").onclick = () => showView("viewWelcome");
document.getElementById("btnRegenSeed").onclick = generateNewSeed;

document.getElementById("btnCopySeed").onclick = async () => {
  await navigator.clipboard.writeText(generatedWords.join(" "));
  showToast("12-word seed phrase copied!");
};

// Form Submits (Handles both Button Click AND Enter Key!)
document.getElementById("formCreate").onsubmit = async (e) => {
  e.preventDefault();
  const w3 = document.getElementById("confirmWord3").value.trim().toLowerCase();
  const w12 = document.getElementById("confirmWord12").value.trim().toLowerCase();
  const pass = document.getElementById("createPass").value;

  if (w3 !== generatedWords[2] || w12 !== generatedWords[11]) {
    showToast("Word #3 or Word #12 does not match your seed phrase!", false);
    return;
  }
  try {
    await apiPost("/api/setup", { mnemonic: generatedWords.join(" "), password: pass });
    showView("viewMain");
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

document.getElementById("formImport").onsubmit = async (e) => {
  e.preventDefault();
  const phrase = document.getElementById("importSeedInput").value.trim();
  const pass = document.getElementById("importPass").value;
  try {
    await apiPost("/api/setup", { mnemonic: phrase, password: pass });
    showView("viewMain");
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

document.getElementById("formUnlock").onsubmit = async (e) => {
  e.preventDefault();
  const pass = document.getElementById("unlockPass").value;
  try {
    await apiPost("/api/unlock", { password: pass });
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

// Quick Actions (Stake / Unstake / Send / Receive)
function setActionMode(mode) {
  currentAction = mode;
  ["qaStake", "qaUnstake", "qaSend", "qaReceive"].forEach(id => {
    document.getElementById(id).classList.remove("active");
  });

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
  document.getElementById("amtLabel").textContent =
    mode === "send" ? "Amount (TAI)" : mode === "stake" ? "Stake Amount (Min 100 TAI)" : "Unstake Amount (TAI)";
  document.getElementById("btnSendTx").textContent =
    mode === "send" ? "Send TAI" : mode === "stake" ? "Stake TAI" : "Unstake TAI";
}

document.getElementById("qaStake").onclick = () => setActionMode("stake");
document.getElementById("btnQuickStake").onclick = () => {
  setActionMode("stake");
  document.getElementById("txAmount").focus();
};
document.getElementById("qaUnstake").onclick = () => setActionMode("unstake");
document.getElementById("qaSend").onclick = () => setActionMode("send");
document.getElementById("qaReceive").onclick = () => setActionMode("receive");

document.getElementById("formTx").onsubmit = async (e) => {
  e.preventDefault();
  const recipient = document.getElementById("txRecipient").value.trim();
  const amount = document.getElementById("txAmount").value.trim();
  try {
    const res = await apiPost("/api/action", { action: currentAction, recipient, amount, fee: "0.00001" });
    showToast("Broadcasted! TxID: " + res.txid);
    document.getElementById("txAmount").value = "";
    refreshDashboard();
  } catch (err) {
    showToast(err.message, false);
  }
};

// Seed Reveal with Enter key support
document.getElementById("btnRevealSeed").onclick = () => {
  document.getElementById("revealedGrid").style.display = "none";
  document.getElementById("revealPass").value = "";
  showView("viewReveal");
  setTimeout(() => document.getElementById("revealPass").focus(), 50);
};

document.getElementById("formReveal").onsubmit = async (e) => {
  e.preventDefault();
  const pass = document.getElementById("revealPass").value;
  try {
    const res = await apiPost("/api/reveal-seed", { password: pass });
    renderSeedGrid("revealedGrid", res.words);
    document.getElementById("revealedGrid").style.display = "grid";
  } catch (err) {
    showToast(err.message, false);
  }
};

document.getElementById("btnBackMain").onclick = () => {
  showView("viewMain");
  refreshDashboard();
};

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

// Bottom Navigation Bar
function setBottomNav(activeId) {
  ["bnavHome", "bnavStake", "bnavExplorer", "bnavActivity"].forEach(id => {
    document.getElementById(id).classList.toggle("active", id === activeId);
  });
}

document.getElementById("bnavHome").onclick = () => {
  setBottomNav("bnavHome");
  setActionMode("send");
  document.querySelector(".scroll-body").scrollTo({ top: 0, behavior: "smooth" });
};

document.getElementById("bnavStake").onclick = () => {
  setBottomNav("bnavStake");
  setActionMode("stake");
  document.getElementById("txAmount").focus();
};

document.getElementById("bnavExplorer").onclick = () => {
  window.open("http://127.0.0.1:8080", "_blank");
};

document.getElementById("bnavActivity").onclick = () => {
  setBottomNav("bnavActivity");
  document.getElementById("activitySection").scrollIntoView({ behavior: "smooth" });
};

boot();
setInterval(() => {
  if (document.getElementById("viewMain").classList.contains("active")) {
    refreshDashboard();
  }
}, 4000);
