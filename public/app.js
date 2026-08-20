const tbody = document.querySelector("#standings");
const leagueName = document.querySelector("#league-name");
const status = document.querySelector("#status");
const refreshButton = document.querySelector("#refresh");
const lastUpdated = document.querySelector("#last-updated");
const pairsViewButton = document.querySelector("#pairs-view");
const teamsViewButton = document.querySelector("#teams-view");
let standingsData;
let activeView = "teams";
let updatedAt;

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

  const teamName = document.createElement("span");
  teamName.textContent = team.team;
  link.append(teamName);
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

function createPairRow(pair) {
  const row = document.createElement("tr");
  const teamCell = document.createElement("td");
  const managerCell = document.createElement("td");

  teamCell.className = "pair-members";
  managerCell.className = "pair-members";
  teamCell.dataset.label = "Teams";
  managerCell.dataset.label = "Managers";
  for (const member of pair.members) {
    teamCell.append(createTeamLink(member));
    managerCell.append(createManager(member));
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

function renderActiveView() {
  if (!standingsData) return;
  const isPairs = activeView === "pairs";
  pairsViewButton.setAttribute("aria-pressed", String(isPairs));
  teamsViewButton.setAttribute("aria-pressed", String(!isPairs));
  tbody.replaceChildren(
    ...(isPairs ? standingsData.pairs.map(createPairRow) : standingsData.standings.map(createTeamRow)),
  );
}

function renderStandings(data) {
  standingsData = data;
  leagueName.textContent = data.league.name;
  status.textContent = data.gameweek.name;
  updatedAt = new Date(data.updatedAt);
  renderLastUpdated();
  renderActiveView();
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
setInterval(renderLastUpdated, 30_000);
loadStandings();
