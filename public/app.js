const tbody = document.querySelector("#standings");
const leagueName = document.querySelector("#league-name");
const status = document.querySelector("#status");
const refreshButton = document.querySelector("#refresh");
const lastUpdated = document.querySelector("#last-updated");
const pairsViewButton = document.querySelector("#pairs-view");
const teamsViewButton = document.querySelector("#teams-view");
const standingsCard = document.querySelector(".table-wrap");
const ownershipPanel = document.querySelector(".ownership-panel");
const playerOwnership = document.querySelector("#player-ownership");
const duoImportanceSelect = document.querySelector("#duo-importance-select");
const importanceDialog = document.querySelector("#importance-dialog");
const importanceDialogTitle = document.querySelector("#importance-dialog-title");
const importanceDialogBody = document.querySelector("#importance-dialog-body");
const importanceDialogClose = document.querySelector("#importance-dialog-close");
let standingsData;
let activeView = "pairs";
let activeDuoImportanceName = "";
let updatedAt;
let activeImportanceAnchor;
const desktopLayout = window.matchMedia("(min-width: 901px)");

function formatTimeAgo(date) {
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (elapsedSeconds < 60) return "just now";

  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) return `${elapsedMinutes}m ago`;

  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours}h ago`;

  return `${Math.floor(elapsedHours / 24)}d ago`;
}

function renderLastUpdated() {
  lastUpdated.textContent = updatedAt ? `Last updated ${formatTimeAgo(updatedAt)}` : "";
}

function syncOwnershipHeight() {
  if (!standingsCard || !ownershipPanel) return;

  if (!desktopLayout.matches) {
    ownershipPanel.style.maxHeight = "";
    ownershipPanel.classList.remove("ownership-panel-scrollable");
    return;
  }

  ownershipPanel.style.maxHeight = `${standingsCard.getBoundingClientRect().height}px`;
  ownershipPanel.classList.toggle(
    "ownership-panel-scrollable",
    ownershipPanel.scrollHeight > ownershipPanel.clientHeight + 1,
  );
}

function createCell(value, className, label) {
  const element = document.createElement("td");
  element.textContent = value;
  if (className) element.className = className;
  if (label) element.dataset.label = label;
  return element;
}

function createFallbackBadge(teamName) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");

  svg.setAttribute("viewBox", "0 0 253.22 296.1");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${teamName} badge`);
  svg.classList.add("team-badge", "team-badge-fallback");
  path.setAttribute("d", "M126.61,296.1c-40.5,0-75.27-19.85-100.55-57.41C7.47,211.08.59,183.72.31,182.57l-.31-2.52V46.04L126.61,0l126.61,46.04-.31,136.53c-.28,1.15-7.16,28.51-25.75,56.12-25.28,37.56-60.05,57.41-100.55,57.41Z");
  svg.append(path);
  return svg;
}

function createTeamLink(team) {
  const link = document.createElement("a");

  link.href = team.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.className = "team-link";

  if (team.badgeUrl) {
    const badge = document.createElement("img");
    badge.src = team.badgeUrl;
    badge.alt = `${team.team} badge`;
    badge.className = "team-badge";
    badge.loading = "lazy";
    link.append(badge);
  } else {
    link.append(createFallbackBadge(team.team));
  }

  const teamNameGroup = document.createElement("span");
  const teamName = document.createElement("span");
  teamNameGroup.className = "team-name";
  teamName.textContent = team.team;
  teamNameGroup.append(teamName);

  if (team.chip) {
    const chip = document.createElement("span");
    chip.className = "chip-pill";
    chip.textContent = team.chip;
    teamNameGroup.append(chip);
  }

  link.append(teamNameGroup);
  return link;
}

function createManager(team) {
  const manager = document.createElement("span");
  manager.className = "manager";

  if (team.headshotUrl) {
    const headshot = document.createElement("img");
    headshot.src = team.headshotUrl;
    headshot.alt = "";
    headshot.className = "manager-headshot";
    headshot.loading = "lazy";
    manager.append(headshot);
  }

  const managerName = document.createElement("span");
  managerName.textContent = team.manager;
  manager.append(managerName);
  return manager;
}

function createTeamRow(team) {
  const row = document.createElement("tr");
  const teamCell = document.createElement("td");
  const managerCell = document.createElement("td");
  teamCell.dataset.label = "Team";
  managerCell.dataset.label = "Manager";
  teamCell.append(createTeamLink(team));
  managerCell.append(createManager(team));
  row.append(
    createCell(team.rank, "", "Rank"),
    teamCell,
    managerCell,
    createCell(team.gameweekPoints, "number", "GW"),
    createCell(team.totalPoints, "number", "Total"),
  );
  return row;
}

function createPairMemberPlaceholder() {
  const placeholder = document.createElement("span");
  placeholder.className = "pair-member-placeholder";
  placeholder.setAttribute("aria-hidden", "true");
  return placeholder;
}

function createPairRow(pair) {
  const row = document.createElement("tr");
  const teamCell = document.createElement("td");
  const managerCell = document.createElement("td");
  const teamsById = new Map((standingsData?.standings || []).map((team) => [team.id, team]));
  const seenMemberIds = new Set();
  const hasDuplicateMembers = new Set(pair.members.map((member) => member.id)).size < pair.members.length;

  teamCell.className = "pair-members";
  managerCell.className = "pair-members";
  if (hasDuplicateMembers) {
    teamCell.classList.add("pair-members-centered");
  }
  teamCell.dataset.label = "Teams";
  managerCell.dataset.label = "Managers";
  for (const member of pair.members) {
    if (seenMemberIds.has(member.id)) {
      teamCell.append(createPairMemberPlaceholder());
      continue;
    }

    seenMemberIds.add(member.id);
    const team = { ...member, ...teamsById.get(member.id) };
    teamCell.append(createTeamLink(team));
  }

  if (hasDuplicateMembers) {
    managerCell.classList.add("pair-members-centered");
  }
  seenMemberIds.clear();
  for (const member of pair.members) {
    if (seenMemberIds.has(member.id)) {
      managerCell.append(createPairMemberPlaceholder());
      continue;
    }

    seenMemberIds.add(member.id);
    const team = { ...member, ...teamsById.get(member.id) };
    managerCell.append(createManager(team));
  }

  row.append(
    createCell(pair.rank, "", "Rank"),
    teamCell,
    managerCell,
    createCell(pair.gameweekPoints, "number", "GW"),
    createCell(pair.totalPoints, "number", "Total"),
  );
  return row;
}

function formatPercent(value) {
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

function formatTeamPick(team) {
  return `${team.name}${team.captain ? " (C)" : ""}`;
}

function createTeamPickSection(title, teams) {
  const section = document.createElement("section");
  const heading = document.createElement("h4");
  heading.textContent = title;
  section.append(heading);

  if (!teams.length) {
    const empty = document.createElement("p");
    empty.textContent = "None";
    section.append(empty);
    return section;
  }

  const list = document.createElement("ul");
  for (const team of teams) {
    const item = document.createElement("li");
    item.textContent = formatTeamPick(team);
    list.append(item);
  }
  section.append(list);
  return section;
}

function positionImportanceDialog(anchor) {
  if (!importanceDialog?.open || !anchor) return;

  const spacing = 8;
  const viewportPadding = 12;
  const anchorRect = anchor.getBoundingClientRect();
  const dialogWidth = importanceDialog.offsetWidth;
  const dialogHeight = importanceDialog.offsetHeight;
  const maxLeft = window.innerWidth - dialogWidth - viewportPadding;
  const maxTop = window.innerHeight - dialogHeight - viewportPadding;
  const left = Math.max(
    viewportPadding,
    Math.min(anchorRect.right + spacing, maxLeft),
  );
  const top = Math.max(
    viewportPadding,
    Math.min(anchorRect.top - spacing, maxTop),
  );

  importanceDialog.style.left = `${left}px`;
  importanceDialog.style.top = `${top}px`;
}

function openImportanceDialog(player, anchor) {
  const teams = player.teams || {};
  activeImportanceAnchor = anchor;
  importanceDialogTitle.textContent = player.name;
  importanceDialogBody.replaceChildren(
    createTeamPickSection("Started", teams.started || []),
    createTeamPickSection("Benched", teams.benched || []),
  );

  if (!importanceDialog.open) {
    importanceDialog.showModal();
  }
  positionImportanceDialog(anchor);
}

function closeImportanceDialog() {
  if (importanceDialog?.open) importanceDialog.close();
  activeImportanceAnchor = undefined;
}

function createImportanceRow(player) {
  const row = document.createElement("div");
  const name = document.createElement("button");
  const opponent = document.createElement("span");
  const fixtureTime = document.createElement("span");
  const points = document.createElement("span");
  const importance = document.createElement("strong");

  row.className = "ownership-row";
  name.className = "importance-player-button";
  name.type = "button";
  name.textContent = player.name;
  opponent.textContent = player.opponent;
  fixtureTime.textContent = player.fixtureTime || "-";
  points.textContent = player.points;
  importance.textContent = formatPercent(player.importance);
  if (player.importance < 0) {
    name.classList.add("negative-importance");
    importance.classList.add("negative-importance");
  }
  name.addEventListener("click", () => openImportanceDialog(player, name));
  row.append(name, opponent, fixtureTime, points, importance);
  return row;
}

function renderActiveView() {
  if (!standingsData) return;
  const isPairs = activeView === "pairs";
  pairsViewButton.setAttribute("aria-pressed", String(isPairs));
  teamsViewButton.setAttribute("aria-pressed", String(!isPairs));
  tbody.replaceChildren(
    ...(isPairs ? standingsData.pairs.map(createPairRow) : standingsData.standings.map(createTeamRow)),
  );
  syncOwnershipHeight();
}

function renderOwnership() {
  if (!standingsData) return;
  closeImportanceDialog();
  const duoImportance = standingsData.duoImportance || [];
  if (!duoImportance.length) {
    duoImportanceSelect.replaceChildren();
    playerOwnership.replaceChildren();
    return;
  }

  const selectedDuo =
    duoImportance.find((duo) => duo.name === activeDuoImportanceName) || duoImportance[0];
  activeDuoImportanceName = selectedDuo.name;
  duoImportanceSelect.replaceChildren(
    ...duoImportance.map((duo) => {
      const option = document.createElement("option");
      option.value = duo.name;
      option.textContent = duo.name;
      return option;
    }),
  );
  duoImportanceSelect.value = activeDuoImportanceName;

  const players = selectedDuo.players.slice().sort(
    (a, b) =>
      Math.abs(b.importance) - Math.abs(a.importance) ||
      Math.sign(b.importance) - Math.sign(a.importance) ||
      a.name.localeCompare(b.name),
  );
  playerOwnership.replaceChildren(
    createImportanceHeader(),
    ...players.map(createImportanceRow),
  );
  syncOwnershipHeight();
}

function createImportanceHeader() {
  const row = document.createElement("div");
  row.className = "ownership-row ownership-header";
  for (const label of ["Player", "Opp", "Status", "Pts", "Importance"]) {
    const cell = document.createElement("span");
    cell.textContent = label;
    row.append(cell);
  }
  return row;
}

function renderStandings(data) {
  standingsData = data;
  leagueName.textContent = data.league.name;
  status.textContent = data.gameweek.name;
  updatedAt = new Date(data.updatedAt);
  renderLastUpdated();
  renderActiveView();
  renderOwnership();
}

async function loadStandings(force = false) {
  refreshButton.disabled = true;
  refreshButton.setAttribute("aria-label", "Refreshing standings");
  status.textContent = "Loading latest standings…";

  try {
    const url = force ? "/api/standings?refresh=1" : "/api/standings";
    const response = await fetch(url, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Standings are unavailable");
    renderStandings(data);
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "Standings are unavailable";
  } finally {
    refreshButton.disabled = false;
    refreshButton.setAttribute("aria-label", "Refresh standings");
  }
}

refreshButton.addEventListener("click", () => loadStandings(true));
pairsViewButton.addEventListener("click", () => {
  activeView = "pairs";
  renderActiveView();
});
teamsViewButton.addEventListener("click", () => {
  activeView = "teams";
  renderActiveView();
});
duoImportanceSelect.addEventListener("change", () => {
  activeDuoImportanceName = duoImportanceSelect.value;
  renderOwnership();
});
importanceDialogClose.addEventListener("click", closeImportanceDialog);
importanceDialog.addEventListener("click", (event) => {
  if (event.target === importanceDialog) closeImportanceDialog();
});
importanceDialog.addEventListener("close", () => {
  activeImportanceAnchor = undefined;
});
window.addEventListener("resize", () => positionImportanceDialog(activeImportanceAnchor));
desktopLayout.addEventListener("change", syncOwnershipHeight);
if (standingsCard) {
  new ResizeObserver(syncOwnershipHeight).observe(standingsCard);
}
setInterval(renderLastUpdated, 30_000);
loadStandings();
