const tbody = document.querySelector("#standings");
const main = document.querySelector("main");
const topBar = document.querySelector(".top-bar");
const leagueName = document.querySelector("#league-name");
const status = document.querySelector("#status");
const refreshButton = document.querySelector("#refresh");
const lastUpdated = document.querySelector("#last-updated");
const pairsViewButton = document.querySelector("#pairs-view");
const teamsViewButton = document.querySelector("#teams-view");
const standingsCard = document.querySelector(".table-wrap");
const teamDetail = document.querySelector("#team-detail");
const ownershipPanel = document.querySelector(".ownership-panel");
const playerOwnership = document.querySelector("#player-ownership");
const duoImportanceSelect = document.querySelector("#duo-importance-select");
const importancePagination = document.querySelector("#importance-pagination");
const importancePrevious = document.querySelector("#importance-previous");
const importanceNext = document.querySelector("#importance-next");
const importancePageStatus = document.querySelector("#importance-page-status");
const importanceDialog = document.querySelector("#importance-dialog");
const importanceDialogTitle = document.querySelector("#importance-dialog-title");
const importanceDialogBody = document.querySelector("#importance-dialog-body");
const importanceDialogClose = document.querySelector("#importance-dialog-close");
const transferDialog = document.createElement("div");
const transferDialogBody = document.createElement("div");
let standingsData;
let activeView = "pairs";
let activeTeamId;
let activeDuoImportanceName = "";
let updatedAt;
let activeImportanceAnchor;
let activeTransferAnchor;
let importancePage = 0;
let headerBaseFontSizes = [];
let headerScaleFrame;
let transferCloseTimer;
const desktopLayout = window.matchMedia("(min-width: 901px)");
const mobileLayout = window.matchMedia("(max-width: 700px)");
const lastViewedTeamKey = "fpl:lastViewedTeamId";
const importancePageSize = 15;
let teamStatsFitFrame;

transferDialog.id = "transfer-dialog";
transferDialog.className = "importance-dialog transfer-dialog";
transferDialog.hidden = true;
transferDialog.setAttribute("role", "tooltip");
transferDialogBody.className = "importance-dialog-body";
transferDialog.append(transferDialogBody);
document.body.append(transferDialog);

function measureHeaderFontSizes() {
  if (!topBar) return;

  const textElements = topBar.querySelectorAll(".eyebrow, h1, #status");
  textElements.forEach((element) => element.style.removeProperty("font-size"));
  headerBaseFontSizes = Array.from(textElements, (element) => ({
    element,
    fontSize: parseFloat(getComputedStyle(element).fontSize),
  }));
}

function getHeaderScale(scrollPosition) {
  const scrollRange = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  const progress = scrollRange ? Math.min(1, Math.max(0, scrollPosition / scrollRange)) : 0;
  return 1 - Math.min(progress, 0.5);
}

function applyHeaderFontScale(scale) {
  if (!headerBaseFontSizes.length) measureHeaderFontSizes();

  headerBaseFontSizes.forEach(({ element, fontSize }) => {
    element.style.fontSize = `${fontSize * scale}px`;
  });
}

function updateHeaderFontSizes() {
  headerScaleFrame = undefined;
  applyHeaderFontScale(getHeaderScale(window.scrollY));
}

function scheduleHeaderFontScale() {
  if (headerScaleFrame !== undefined) return;
  headerScaleFrame = requestAnimationFrame(updateHeaderFontSizes);
}

function resetHeaderFontScale() {
  headerBaseFontSizes = [];
  scheduleHeaderFontScale();
}

function scrollToTeamDetail() {
  if (!teamDetail || !topBar) {
    teamDetail?.scrollIntoView({ behavior: "smooth", block: "end" });
    return;
  }

  const currentScrollPosition = window.scrollY;
  let destination = currentScrollPosition + teamDetail.getBoundingClientRect().bottom - window.innerHeight;

  // The sticky header changes height while scrolling, so measure the layout at
  // the projected destination until the required offset settles.
  for (let iteration = 0; iteration < 4; iteration += 1) {
    applyHeaderFontScale(getHeaderScale(destination));
    const detailBottom = window.scrollY + teamDetail.getBoundingClientRect().bottom;
    const maximumScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const nextDestination = Math.min(
      maximumScroll,
      Math.max(0, detailBottom - window.innerHeight),
    );

    if (Math.abs(nextDestination - destination) < 0.5) {
      destination = nextDestination;
      break;
    }
    destination = nextDestination;
  }

  applyHeaderFontScale(getHeaderScale(currentScrollPosition));
  window.scrollTo({ top: destination, behavior: "smooth" });
}

const POINT_DETAIL_LABELS = {
  minutes: ({ value }) => `Played ${value} min`,
  goals_scored: ({ value }) => `${value} ${pluralize("goal", value)}`,
  assists: ({ value }) => `${value} ${pluralize("assist", value)}`,
  clean_sheets: () => "Clean sheet",
  goals_conceded: ({ value }) => `${value} ${pluralize("goal conceded", value, "goals conceded")}`,
  own_goals: ({ value }) => `${value} ${pluralize("own goal", value)}`,
  penalties_saved: ({ value }) => `${value} ${pluralize("penalty save", value)}`,
  penalties_missed: ({ value }) => `${value} ${pluralize("penalty miss", value, "penalty misses")}`,
  yellow_cards: ({ value }) => value === 1 ? "Yellow card" : `${value} yellow cards`,
  red_cards: ({ value }) => value === 1 ? "Red card" : `${value} red cards`,
  saves: ({ value }) => `${value} ${pluralize("save", value)}`,
  defensive_contribution: ({ value }) => `${value} def. ${pluralize("contribution", value)}`,
  bonus: ({ bps = 0 }) => `Bonus (${bps} bps)`,
};

function pluralize(singular, count, plural = `${singular}s`) {
  return count === 1 ? singular : plural;
}

function teamStatsFit(stats) {
  const statsRect = stats.getBoundingClientRect();
  const statRects = Array.from(stats.children, (stat) => stat.getBoundingClientRect());
  if (!statRects.length || !statsRect.width) return true;

  const left = Math.min(...statRects.map((rect) => rect.left));
  const right = Math.max(...statRects.map((rect) => rect.right));
  return left >= statsRect.left - 0.5 && right <= statsRect.right + 0.5;
}

function maximizeTeamStatsFont(stats) {
  const minimumFontSize = 1;
  const maximumFontSize = parseFloat(getComputedStyle(stats.firstElementChild).fontSize);
  let low = minimumFontSize;
  let high = maximumFontSize;

  stats.style.setProperty("--team-detail-stats-font-size", `${minimumFontSize}px`);

  for (let iteration = 0; iteration < 8; iteration += 1) {
    const candidate = (low + high) / 2;
    stats.style.setProperty("--team-detail-stats-font-size", `${candidate}px`);
    if (teamStatsFit(stats)) low = candidate;
    else high = candidate;
  }

  stats.style.setProperty("--team-detail-stats-font-size", `${low}px`);
}

function fitTeamDetailStats() {
  const stats = teamDetail?.querySelector(".team-detail-stats");
  if (!stats) return;

  stats.style.removeProperty("--team-detail-stats-font-size");
  maximizeTeamStatsFont(stats);
}

function scheduleTeamStatsFit() {
  cancelAnimationFrame(teamStatsFitFrame);
  teamStatsFitFrame = requestAnimationFrame(fitTeamDetailStats);
}

function getSavedTeamId() {
  try {
    const value = localStorage.getItem(lastViewedTeamKey);
    return value ? Number(value) : undefined;
  } catch {
    return undefined;
  }
}

function saveTeamId(teamId) {
  try {
    localStorage.setItem(lastViewedTeamKey, String(teamId));
  } catch {
    // Ignore storage failures so private browsing/settings do not break the page.
  }
}

function setDefaultActiveTeam() {
  const standings = standingsData?.standings || [];
  if (!standings.length) return;

  const savedTeamId = getSavedTeamId();
  const activeStillExists = standings.some((team) => team.id === activeTeamId);
  const savedTeamExists = standings.some((team) => team.id === savedTeamId);

  if (activeStillExists) return;

  activeTeamId = savedTeamExists ? savedTeamId : standings[0].id;
  saveTeamId(activeTeamId);
}

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
  if (!standingsCard || !ownershipPanel || !teamDetail) return;

  if (mobileLayout.matches) {
    teamDetail.style.maxHeight = "";
    teamDetail.style.height = "";
    ownershipPanel.style.maxHeight = "";
    ownershipPanel.style.height = "";
    ownershipPanel.classList.remove("ownership-panel-scrollable");
    return;
  }

  if (!desktopLayout.matches) {
    ownershipPanel.style.maxHeight = "";
    ownershipPanel.style.height = "";
    teamDetail.style.maxHeight = "";
    teamDetail.style.height = "";
    ownershipPanel.classList.remove("ownership-panel-scrollable");
    return;
  }

  const standingsHeight = `${standingsCard.getBoundingClientRect().height}px`;
  ownershipPanel.style.maxHeight = standingsHeight;
  ownershipPanel.style.height = activeTeamId === undefined ? "" : standingsHeight;
  teamDetail.style.maxHeight = activeTeamId === undefined ? "" : standingsHeight;
  teamDetail.style.height = activeTeamId === undefined ? "" : standingsHeight;
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

function createTeamBadge(team) {
  if (team.badgeUrl) {
    const badge = document.createElement("img");
    badge.src = team.badgeUrl;
    badge.alt = `${team.team} badge`;
    badge.className = "team-badge";
    badge.loading = "lazy";
    return badge;
  }

  return createFallbackBadge(team.team);
}

function createTeamLink(team) {
  const link = document.createElement("button");

  link.type = "button";
  link.className = "team-link";
  link.addEventListener("click", () => openTeamDetail(team.id));
  link.append(createTeamBadge(team));

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

function formatTeamValue(value) {
  return Number.isFinite(value) ? `${value.toFixed(1)}m` : "—";
}

function formatTeamValueWithBank(value, bank) {
  const teamValue = formatTeamValue(value);
  if (!Number.isFinite(bank)) return teamValue;
  return `${teamValue} (${formatTeamValue(bank)} bank)`;
}

function formatStatValue(value) {
  return Number.isFinite(value) ? value.toLocaleString() : value;
}

function formatChipName(chip) {
  const chipNames = {
    BB: "Bench Boost",
    WC: "Wildcard",
    FH: "Free Hit",
    TC: "Triple Captain",
  };
  return chipNames[chip] || chip || "-";
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
    createPointDetails(player.pointDetails),
  );

  if (!importanceDialog.open) {
    importanceDialog.showModal();
  }
  positionImportanceDialog(anchor);
}

function createPointDetails(pointDetails) {
  const section = document.createElement("section");
  section.className = "importance-points";
  if (!pointDetails) {
    section.hidden = true;
    return section;
  }

  const table = document.createElement("table");
  const body = document.createElement("tbody");
  for (const detail of pointDetails.rows) {
    const labelTemplate = POINT_DETAIL_LABELS[detail.identifier];
    if (!labelTemplate) continue;

    const row = document.createElement("tr");
    const label = document.createElement("td");
    const points = document.createElement("td");
    label.textContent = `${labelTemplate(detail)}:`;
    points.textContent = detail.points;
    row.append(label, points);
    body.append(row);
  }

  const totalRow = document.createElement("tr");
  const totalLabel = document.createElement("th");
  const total = document.createElement("th");
  totalRow.className = "importance-points-total";
  totalLabel.scope = "row";
  totalLabel.textContent = "Total Points:";
  total.textContent = pointDetails.total;
  totalRow.append(totalLabel, total);
  body.append(totalRow);
  table.append(body);
  section.append(table);
  return section;
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

function findImportancePlayer(playerId) {
  return (standingsData?.duoImportance || [])
    .flatMap((duo) => duo.players || [])
    .find((player) => player.id === playerId);
}

function playerWithImportanceTeams(player) {
  const importancePlayer = findImportancePlayer(player.id);
  return {
    ...importancePlayer,
    ...player,
    teams: player.teams || importancePlayer?.teams || { started: [], benched: [] },
  };
}

function playerDisplayName(player) {
  if (player.isCaptain) return `${player.name} (C)`;
  if (player.isViceCaptain) return `${player.name} (VC)`;
  return player.name;
}

function createTeamPlayerRow(player) {
  const row = document.createElement("div");
  const name = document.createElement("button");
  const opponent = document.createElement("span");
  const fixtureTime = document.createElement("span");
  const points = document.createElement("span");

  row.className = "ownership-row team-player-row";
  if (player.isBenched) row.classList.add("team-player-row-benched");
  name.className = "importance-player-button team-player-name";
  name.type = "button";
  name.textContent = playerDisplayName(player);
  opponent.textContent = player.opponent;
  fixtureTime.textContent = player.fixtureTime || "-";
  points.textContent = player.points;
  const openPlayerTeams = () => {
    openImportanceDialog(playerWithImportanceTeams(player), name);
  };
  row.addEventListener("click", openPlayerTeams);
  name.addEventListener("click", (event) => {
    event.stopPropagation();
    openPlayerTeams();
  });
  row.append(name, opponent, fixtureTime, points);
  return row;
}

function createTeamStat(label, value) {
  const stat = document.createElement("div");
  const statLabel = document.createElement("span");
  const statValue = document.createElement("strong");

  stat.className = "team-detail-stat";
  statLabel.textContent = label;
  statValue.textContent = formatStatValue(value);
  stat.append(statLabel, statValue);
  return stat;
}

function createTransferStat(detail) {
  const stat = createTeamStat(
    "Transfers",
    formatTransfers(detail.transfersMade, detail.transferCost),
  );
  const open = () => openTransferDialog(detail, stat);
  const close = () => scheduleCloseTransferDialog();

  stat.classList.add("team-transfer-stat");
  stat.tabIndex = 0;
  stat.setAttribute("aria-describedby", transferDialog.id);
  stat.addEventListener("mouseenter", open);
  stat.addEventListener("focus", open);
  stat.addEventListener("mouseleave", close);
  stat.addEventListener("blur", close);
  stat.addEventListener("click", () => {
    if (activeTransferAnchor === stat && !transferDialog.hidden) {
      closeTransferDialog();
    } else {
      open();
    }
  });
  return stat;
}

function createGameweekScore(points) {
  const score = document.createElement("div");
  const label = document.createElement("span");
  const value = document.createElement("strong");

  score.className = "team-detail-gw-score";
  label.textContent = "GW";
  value.textContent = formatStatValue(points);
  score.append(label, value);
  return score;
}

function findTeamDetail(teamId) {
  return (standingsData?.teamDetails || []).find((team) => team.id === teamId);
}

function findStandingsTeam(teamId) {
  return (standingsData?.standings || []).find((team) => team.id === teamId);
}

function formatTransfers(transfersMade, transferCost) {
  const transfers = formatStatValue(transfersMade);
  return transferCost > 0 ? `${transfers} (-${transferCost})` : transfers;
}

function createTransferList(detail) {
  const section = document.createElement("section");
  const transfers = detail.transfers || [];

  if (!transfers.length) {
    const empty = document.createElement("p");
    empty.textContent = detail.transfersMade > 0
      ? "Transfer details unavailable"
      : "No transfers made";
    section.append(empty);
    return section;
  }

  const list = document.createElement("ul");
  for (const transfer of transfers) {
    const item = document.createElement("li");
    item.textContent = `${transfer.out} -> ${transfer.in}`;
    list.append(item);
  }
  section.append(list);
  return section;
}

function positionTransferDialog(anchor) {
  if (transferDialog.hidden || !anchor) return;

  const spacing = 8;
  const viewportPadding = 12;
  const anchorRect = anchor.getBoundingClientRect();
  const dialogWidth = transferDialog.offsetWidth;
  const dialogHeight = transferDialog.offsetHeight;
  const maxLeft = window.innerWidth - dialogWidth - viewportPadding;
  const belowTop = anchorRect.bottom + spacing;
  const aboveTop = anchorRect.top - dialogHeight - spacing;
  const left = Math.max(
    viewportPadding,
    Math.min(anchorRect.left + (anchorRect.width - dialogWidth) / 2, maxLeft),
  );
  const top = belowTop + dialogHeight <= window.innerHeight - viewportPadding
    ? belowTop
    : Math.max(viewportPadding, aboveTop);

  transferDialog.style.left = `${left}px`;
  transferDialog.style.top = `${top}px`;
}

function openTransferDialog(detail, anchor) {
  clearTimeout(transferCloseTimer);
  activeTransferAnchor = anchor;
  transferDialogBody.replaceChildren(createTransferList(detail));
  transferDialog.hidden = false;
  positionTransferDialog(anchor);
}

function scheduleCloseTransferDialog() {
  clearTimeout(transferCloseTimer);
  transferCloseTimer = setTimeout(closeTransferDialog, 120);
}

function closeTransferDialog() {
  clearTimeout(transferCloseTimer);
  transferDialog.hidden = true;
  activeTransferAnchor = undefined;
}

function renderTeamDetail() {
  if (!teamDetail || activeTeamId === undefined) return;

  const detail = findTeamDetail(activeTeamId);
  const standingsTeam = findStandingsTeam(activeTeamId);
  if (!detail || !standingsTeam) {
    closeTransferDialog();
    teamDetail.replaceChildren();
    return;
  }

  closeTransferDialog();

  const header = document.createElement("div");
  const titleGroup = document.createElement("div");
  const titleText = document.createElement("div");
  const teamName = document.createElement("h2");
  const gameweekScore = createGameweekScore(detail.gameweekPoints);
  const stats = document.createElement("div");
  const players = document.createElement("div");

  header.className = "team-detail-header";

  titleGroup.className = "team-detail-title";
  titleText.className = "team-detail-title-text";
  teamName.textContent = detail.team;

  stats.className = "team-detail-stats";
  stats.append(
    createTeamStat("Total Pts", detail.totalPoints),
    createTransferStat(detail),
    createTeamStat("Chip", formatChipName(detail.chip)),
    createTeamStat("Value", formatTeamValueWithBank(detail.teamValue, detail.bank)),
  );

  titleText.append(teamName, stats);
  titleGroup.append(createTeamBadge(standingsTeam), titleText);

  header.append(titleGroup, gameweekScore);

  players.className = "ownership-list team-player-list";
  players.replaceChildren(
    createTeamPlayerHeader(),
    ...detail.players.map(createTeamPlayerRow),
  );

  teamDetail.replaceChildren(header, players);
  scheduleTeamStatsFit();
  syncOwnershipHeight();
}

function openTeamDetail(teamId) {
  activeTeamId = teamId;
  saveTeamId(teamId);
  closeImportanceDialog();
  closeTransferDialog();
  renderActiveView();
  renderOwnership();
  requestAnimationFrame(scrollToTeamDetail);
}

function renderActiveView() {
  if (!standingsData) return;
  setDefaultActiveTeam();
  const hasActiveTeam = activeTeamId !== undefined;
  main?.classList.toggle("team-detail-active", hasActiveTeam);
  if (teamDetail) teamDetail.hidden = !hasActiveTeam;
  if (hasActiveTeam) {
    renderTeamDetail();
  }

  const isPairs = activeView === "pairs";
  pairsViewButton.setAttribute("aria-pressed", String(isPairs));
  teamsViewButton.setAttribute("aria-pressed", String(!isPairs));
  tbody.replaceChildren(
    ...(isPairs ? standingsData.pairs.map(createPairRow) : standingsData.standings.map(createTeamRow)),
  );
  syncOwnershipHeight();
  scheduleHeaderFontScale();
}

function renderOwnership() {
  if (!standingsData) return;
  closeImportanceDialog();
  const duoImportance = standingsData.duoImportance || [];
  if (!duoImportance.length) {
    duoImportanceSelect.replaceChildren();
    playerOwnership.replaceChildren();
    importancePagination.hidden = true;
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
      Math.sign(a.importance) - Math.sign(b.importance) ||
      a.name.localeCompare(b.name),
  );
  const pageCount = mobileLayout.matches
    ? Math.max(1, Math.ceil(players.length / importancePageSize))
    : 1;
  importancePage = Math.min(importancePage, pageCount - 1);
  const visiblePlayers = mobileLayout.matches
    ? players.slice(
        importancePage * importancePageSize,
        (importancePage + 1) * importancePageSize,
      )
    : players;
  playerOwnership.replaceChildren(
    createImportanceHeader(),
    ...visiblePlayers.map(createImportanceRow),
  );
  importancePagination.hidden = pageCount === 1;
  importancePrevious.disabled = importancePage === 0;
  importanceNext.disabled = importancePage === pageCount - 1;
  importancePageStatus.textContent = `${importancePage + 1} / ${pageCount}`;
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

function createTeamPlayerHeader() {
  const row = document.createElement("div");
  row.className = "ownership-row ownership-header";
  for (const label of ["Player", "Opp", "Status", "Pts"]) {
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
  setDefaultActiveTeam();
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
  renderOwnership();
});
teamsViewButton.addEventListener("click", () => {
  activeView = "teams";
  renderActiveView();
  renderOwnership();
});
duoImportanceSelect.addEventListener("change", () => {
  activeDuoImportanceName = duoImportanceSelect.value;
  importancePage = 0;
  renderOwnership();
});
importancePrevious.addEventListener("click", () => {
  if (importancePage === 0) return;
  importancePage -= 1;
  renderOwnership();
});
importanceNext.addEventListener("click", () => {
  importancePage += 1;
  renderOwnership();
});
importanceDialogClose.addEventListener("click", closeImportanceDialog);
importanceDialog.addEventListener("click", (event) => {
  if (event.target === importanceDialog) closeImportanceDialog();
});
importanceDialog.addEventListener("close", () => {
  activeImportanceAnchor = undefined;
});
transferDialog.addEventListener("mouseenter", () => clearTimeout(transferCloseTimer));
transferDialog.addEventListener("mouseleave", scheduleCloseTransferDialog);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeTransferDialog();
});
window.addEventListener("scroll", () => {
  scheduleHeaderFontScale();
  positionTransferDialog(activeTransferAnchor);
}, { passive: true });
window.addEventListener("resize", () => {
  positionImportanceDialog(activeImportanceAnchor);
  positionTransferDialog(activeTransferAnchor);
  resetHeaderFontScale();
});
desktopLayout.addEventListener("change", syncOwnershipHeight);
mobileLayout.addEventListener("change", () => {
  importancePage = 0;
  renderOwnership();
});
if (standingsCard) {
  new ResizeObserver(syncOwnershipHeight).observe(standingsCard);
}
if (teamDetail) {
  new ResizeObserver(() => {
    scheduleTeamStatsFit();
    syncOwnershipHeight();
  }).observe(teamDetail);
}
document.fonts?.ready.then(() => {
  scheduleTeamStatsFit();
  resetHeaderFontScale();
});
setInterval(renderLastUpdated, 30_000);
scheduleHeaderFontScale();
loadStandings();
