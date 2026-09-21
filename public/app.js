const tbody = document.querySelector("#standings");
const main = document.querySelector("main");
const topBar = document.querySelector(".top-bar");
const leagueName = document.querySelector("#league-name");
const status = document.querySelector("#status");
const refreshButton = document.querySelector("#refresh");
const refreshIcon = refreshButton?.querySelector(".refresh-icon");
const lastUpdated = document.querySelector("#last-updated");
const gameweekPreviousButtons = [...document.querySelectorAll("[data-gameweek-previous]")];
const gameweekNextButtons = [...document.querySelectorAll("[data-gameweek-next]")];
const gameweekValues = [...document.querySelectorAll("[data-gameweek-value]")];
const pairsViewButton = document.querySelector("#pairs-view");
const teamsViewButton = document.querySelector("#teams-view");
const standingsCard = document.querySelector(".table-wrap");
const chipsList = document.querySelector("#chips-list");
const transfersList = document.querySelector("#transfers-list");
const teamDetail = document.querySelector("#team-detail");
const teamSummaryPanel = document.querySelector("#team-summary-panel");
const ownershipPanel = document.querySelector(".ownership-panel");
const playerOwnership = document.querySelector("#player-ownership");
const duoImportanceSelect = document.querySelector("#duo-importance-select");
const liveOnlyFilter = document.querySelector("#live-only-filter");
const importancePagination = document.querySelector("#importance-pagination");
const importancePrevious = document.querySelector("#importance-previous");
const importanceNext = document.querySelector("#importance-next");
const importancePageStatus = document.querySelector("#importance-page-status");
const importanceDialog = document.querySelector("#importance-dialog");
const importanceDialogTitle = document.querySelector("#importance-dialog-title");
const importanceDialogBody = document.querySelector("#importance-dialog-body");
const importanceDialogClose = document.querySelector("#importance-dialog-close");
const themeToggle = document.querySelector("#theme-toggle");
const mobileTabButtons = [...document.querySelectorAll(".mobile-tab")];
let standingsData;
let currentGameweekData;
let activeView = "pairs";
let activeTeamId;
let activeDuoImportanceName = "";
let liveOnlyImportance = false;
let liveOnlyImportanceContext = "";
let liveOnlyImportanceManuallySet = false;
let updatedAt;
let activeImportanceAnchor;
let activeImportanceMode = "modal";
let importancePage = 0;
const importancePageSize = 14;
let standingsRefreshTimer;
let lastFetchAt = 0;
let isLoadingStandings = false;
let selectedGameweekId;
let availableGameweeks = [];
let headerBaseFontSizes = [];
let headerScaleFrame;
let teamColumnFitFrame;
const desktopLayout = window.matchMedia("(min-width: 901px)");
const mobileLayout = window.matchMedia("(max-width: 700px)");
const hoverLayout = window.matchMedia("(hover: hover) and (pointer: fine)");
const preferredDarkTheme = window.matchMedia("(prefers-color-scheme: dark)");
const lastViewedTeamKey = "fpl:lastViewedTeamId";
const themeStorageKey = "fpl:theme";
const standingsStorageKey = "fpl:standingsSnapshot:v2";
const themeTransitionDuration = 1120;
let themeTransitionTimer;
let activeMobileTab = "league";

function getStoredTheme() {
  try {
    const theme = localStorage.getItem(themeStorageKey);
    return theme === "dark" || theme === "light" ? theme : undefined;
  } catch {
    return undefined;
  }
}

function saveTheme(theme) {
  try {
    localStorage.setItem(themeStorageKey, theme);
  } catch {
    // Theme switching should keep working even when storage is unavailable.
  }
}

function getStandingsSnapshot() {
  try {
    const snapshot = JSON.parse(localStorage.getItem(standingsStorageKey) || "null");
    return snapshot?.league && snapshot?.gameweek && snapshot?.updatedAt ? snapshot : undefined;
  } catch {
    return undefined;
  }
}

function saveStandingsSnapshot(data) {
  try {
    localStorage.setItem(standingsStorageKey, JSON.stringify(data));
  } catch {
    // The live view still works if the browser refuses or evicts stored snapshots.
  }
}

function isRecentStandingsSnapshot(data) {
  const updatedAtMs = new Date(data?.updatedAt).getTime();
  return Number.isFinite(updatedAtMs) && Date.now() - updatedAtMs < 30 * 60 * 1000;
}

function canUseFrozenSnapshot(data) {
  return (
    data?.refreshPolicy?.mode === "frozen"
    && data?.gameweek?.id === data?.currentGameweek?.id
    && isRecentStandingsSnapshot(data)
  );
}

function getPreferredTheme() {
  return preferredDarkTheme.matches ? "dark" : "light";
}

function updateThemeToggle(theme) {
  if (!themeToggle) return;

  const nextTheme = theme === "dark" ? "light" : "dark";
  themeToggle.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
  themeToggle.title = `Switch to ${nextTheme} mode`;
}

function applyTheme(theme, animate = false) {
  const root = document.documentElement;
  const currentTheme = root.dataset.theme === "dark" ? "dark" : "light";

  if (animate && currentTheme !== theme && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    window.clearTimeout(themeTransitionTimer);
    root.dataset.themeTransition = "active";
    // Make sure transition styles are active before the theme variables change.
    root.getBoundingClientRect();
    root.dataset.theme = theme;

    themeTransitionTimer = window.setTimeout(() => {
      delete root.dataset.themeTransition;
    }, themeTransitionDuration);
  } else {
    delete root.dataset.themeTransition;
    root.dataset.theme = theme;
  }

  updateThemeToggle(theme);
}

function setTheme(theme) {
  applyTheme(theme, true);
  saveTheme(theme);
}

function toggleTheme() {
  const currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  setTheme(currentTheme === "dark" ? "light" : "dark");
}

applyTheme("dark");

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
  return 0.75 - Math.min(progress, 0.5) * 0.5;
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

function fitStandingsColumns() {
  teamColumnFitFrame = undefined;
  const table = document.querySelector(".standings-table");
  if (!table || !tbody) return;

  const canvas = fitStandingsColumns.canvas || document.createElement("canvas");
  fitStandingsColumns.canvas = canvas;
  const context = canvas.getContext("2d");
  const teamCells = [...tbody.querySelectorAll("td:nth-child(2)")];
  const rankCells = [...tbody.querySelectorAll("td:nth-child(1)")];
  const widestRankCell = rankCells.reduce((widest, cell) => {
    const style = getComputedStyle(cell);
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    const contentWidth = [...cell.children].reduce((total, child) => {
      const childStyle = getComputedStyle(child);
      return total
        + child.getBoundingClientRect().width
        + parseFloat(childStyle.marginLeft)
        + parseFloat(childStyle.marginRight);
    }, 0);
    context.font = style.font;
    return Math.max(
      widest,
      Math.ceil(contentWidth + padding),
      Math.ceil(context.measureText(cell.textContent.trim()).width + padding),
    );
  }, 0);
  const widestTeamCell = teamCells.reduce((widest, cell) => {
    const style = getComputedStyle(cell);
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    const linkWidth = Math.max(
      0,
      ...[...cell.querySelectorAll(".team-link")].map((link) => link.scrollWidth),
    );
    return Math.max(widest, Math.ceil(linkWidth + padding));
  }, 0);

  if (widestRankCell > 0) {
    table.style.setProperty("--rank-col-width", `${widestRankCell}px`);
  }

  if (widestTeamCell > 0) {
    const desktopTeamWidth = Math.ceil(widestTeamCell * 1.2);
    table.style.setProperty("--team-col-width", `${desktopLayout.matches ? desktopTeamWidth : widestTeamCell}px`);
  }
}

function scheduleStandingsColumnFit() {
  if (teamColumnFitFrame !== undefined) return;
  teamColumnFitFrame = requestAnimationFrame(fitStandingsColumns);
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
  if (!lastUpdated) return;
  lastUpdated.textContent = updatedAt ? `Last updated ${formatTimeAgo(updatedAt)}` : "";
}

function getStandingsPollMs() {
  const pollMs = (currentGameweekData || standingsData)?.refreshPolicy?.pollMs;
  return Number.isFinite(pollMs) && pollMs > 0 ? pollMs : undefined;
}

function clearStandingsRefresh() {
  clearTimeout(standingsRefreshTimer);
  standingsRefreshTimer = undefined;
}

function scheduleStandingsRefresh() {
  clearStandingsRefresh();
  const pollMs = getStandingsPollMs();
  if (!pollMs || document.visibilityState === "hidden") return;

  standingsRefreshTimer = setTimeout(() => {
    loadStandings(false, { quiet: true });
  }, pollMs);
}

function animateRefreshIcon() {
  if (!refreshIcon) return;

  refreshIcon.classList.remove("refresh-icon-spin");
  refreshIcon.getBoundingClientRect();
  refreshIcon.classList.add("refresh-icon-spin");
}

function updateGameweekControls() {
  const selectedIndex = availableGameweeks.findIndex(
    (gameweek) => gameweek.id === selectedGameweekId,
  );

  gameweekValues.forEach((input) => {
    input.value = Number.isFinite(selectedGameweekId) ? String(selectedGameweekId) : "";
    input.disabled = isLoadingStandings || !availableGameweeks.length;
  });
  gameweekPreviousButtons.forEach((button) => {
    button.disabled = isLoadingStandings || selectedIndex <= 0;
  });
  gameweekNextButtons.forEach((button) => {
    button.disabled = isLoadingStandings
      || selectedIndex < 0
      || selectedIndex >= availableGameweeks.length - 1;
  });
}

function renderGameweekControls(data) {
  const gameweeks = Array.isArray(data.availableGameweeks) && data.availableGameweeks.length
    ? data.availableGameweeks
    : [data.gameweek];

  availableGameweeks = [...gameweeks].sort((a, b) => a.id - b.id);
  selectedGameweekId = data.gameweek.id;
  updateGameweekControls();
}

function stepGameweek(offset) {
  const selectedIndex = availableGameweeks.findIndex(
    (gameweek) => gameweek.id === selectedGameweekId,
  );
  const gameweek = availableGameweeks[selectedIndex + offset];
  if (!gameweek || isLoadingStandings) return;

  selectedGameweekId = gameweek.id;
  updateGameweekControls();
  loadStandings(false);
}

function selectGameweek(input) {
  const gameweekId = Number(input.value);
  const gameweek = availableGameweeks.find((item) => item.id === gameweekId);
  if (!gameweek || isLoadingStandings || gameweek.id === selectedGameweekId) {
    updateGameweekControls();
    return;
  }

  selectedGameweekId = gameweek.id;
  updateGameweekControls();
  loadStandings(false);
}

function refreshStandingsAfterResume() {
  if (document.visibilityState === "hidden") {
    clearStandingsRefresh();
    return;
  }

  renderLastUpdated();
  const pollMs = getStandingsPollMs();
  if (!pollMs) {
    scheduleStandingsRefresh();
    return;
  }

  if (!lastFetchAt || Date.now() - lastFetchAt >= pollMs) {
    loadStandings(false, { quiet: true });
    return;
  }

  scheduleStandingsRefresh();
}

function syncOwnershipHeight() {
  if (!standingsCard || !ownershipPanel || !teamDetail) return;

  ownershipPanel.style.maxHeight = "";
  ownershipPanel.style.height = "";
  ownershipPanel.classList.remove("ownership-panel-scrollable");

  if (mobileLayout.matches) {
    teamDetail.style.maxHeight = "";
    teamDetail.style.height = "";
    return;
  }

  if (!desktopLayout.matches) {
    teamDetail.style.maxHeight = "";
    teamDetail.style.height = "";
    return;
  }

  teamDetail.style.maxHeight = "";
  teamDetail.style.height = "";
}

function createCell(value, className, label) {
  const element = document.createElement("td");
  element.textContent = value;
  if (className) element.className = className;
  if (label) element.dataset.label = label;
  return element;
}

function createRankCell(rank, movement) {
  const element = createCell("", "rank-cell", "Rank");
  const value = document.createElement("span");
  value.className = "rank-value";
  value.textContent = rank;

  if (["increase", "decrease", "same"].includes(movement?.direction)) {
    const indicator = document.createElement("span");
    indicator.className = `rank-movement rank-movement-${movement.direction}`;
    indicator.setAttribute("aria-hidden", "true");
    element.title = movement.direction === "same"
      ? `Rank unchanged at ${movement.currentRank}`
      : `Rank ${movement.direction}d from ${movement.previousRank} to ${movement.currentRank}`;
    element.setAttribute(
      "aria-label",
      movement.direction === "same"
        ? `Rank ${rank}, unchanged from last gameweek`
        : `Rank ${rank}, ${movement.direction}d from ${movement.previousRank}`,
    );
    element.append(indicator);
  }

  element.append(value);
  return element;
}

function createStackedCell(values, className, label) {
  const element = createCell("", ["stacked-number", className].filter(Boolean).join(" "), label);
  element.replaceChildren(
    ...values.map((value) => {
      const item = document.createElement("span");
      item.textContent = value;
      return item;
    }),
  );
  return element;
}

function createStatusCountContent(value, hasCaptain) {
  const content = document.createElement("span");
  const count = document.createElement("span");
  content.className = "status-count";
  count.textContent = value;
  content.append(count);
  if (hasCaptain) content.append(createCaptainPill("C"));
  return content;
}

function createStatusCell(value, label, hasCaptain) {
  const element = createCell("", "number status-cell", label);
  element.replaceChildren(createStatusCountContent(value, hasCaptain));
  return element;
}

function createStackedStatusCell(members, field, label) {
  const element = createCell("", "stacked-number number status-cell", label);
  element.replaceChildren(
    ...members.map((member) => {
      const item = document.createElement("span");
      item.append(createStatusCountContent(
        member[field] ?? 0,
        member.captainStatus === field,
      ));
      return item;
    }),
  );
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

function createTeamCardImage(team) {
  if (standingsData?.teamCardImage === "headshot" && team.headshotUrl) {
    const headshot = document.createElement("img");
    headshot.src = team.headshotUrl;
    headshot.alt = "";
    headshot.className = "team-card-headshot";
    headshot.loading = "lazy";
    return headshot;
  }

  return createTeamBadge(team);
}

function createManagerHeadshot(team, className = "manager-headshot") {
  if (!team.headshotUrl) return undefined;

  const headshot = document.createElement("img");
  headshot.src = team.headshotUrl;
  headshot.alt = "";
  headshot.className = className;
  headshot.loading = "lazy";
  return headshot;
}

function createTeamLink(team) {
  const link = document.createElement("button");

  link.type = "button";
  link.className = "team-link";
  link.addEventListener("click", (event) => {
    event.stopPropagation();
    openTeamDetail(team.id);
  });
  const headshot = createManagerHeadshot(team, "manager-headshot team-link-headshot");
  if (headshot) link.append(headshot);

  const teamNameGroup = document.createElement("span");
  const teamNameLine = document.createElement("span");
  const teamName = document.createElement("span");
  teamNameGroup.className = "team-name";
  teamNameLine.className = "team-name-line";
  teamName.textContent = team.team;
  teamNameLine.append(teamName);

  if (team.chip) {
    const chip = document.createElement("span");
    chip.className = "chip-pill";
    chip.textContent = team.chip;
    teamNameLine.append(chip);
  }

  teamNameGroup.append(teamNameLine);

  const teamDetail = standingsData?.teamDetails?.find((detail) => detail.id === team.id);
  const captain = teamDetail?.players?.find((player) => player.isCaptain);
  if (captain || team.manager) {
    const captainName = document.createElement("span");
    captainName.className = "team-captain";
    captainName.textContent = [captain?.name, team.manager].filter(Boolean).join(" · ");
    teamNameGroup.append(captainName);
  }

  link.append(teamNameGroup);
  return link;
}

function addTeamRowInteraction(row, teamId, label) {
  row.classList.add("standings-row-clickable");
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-label", `Open ${label}`);
  row.addEventListener("click", () => openTeamDetail(teamId));
  row.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openTeamDetail(teamId);
  });
}

function addPairRowInteraction(row, members) {
  const selectableMembers = members.filter(
    (member, index, list) => list.findIndex((candidate) => candidate.id === member.id) === index,
  );
  if (!selectableMembers.length) return;

  row.classList.add("standings-row-clickable");
  row.addEventListener("click", (event) => {
    const rect = row.getBoundingClientRect();
    const rowRatio = rect.height ? (event.clientY - rect.top) / rect.height : 0;
    const memberIndex = Math.min(
      selectableMembers.length - 1,
      Math.max(0, Math.floor(rowRatio * selectableMembers.length)),
    );
    openTeamDetail(selectableMembers[memberIndex].id);
  });
}

function createTeamRow(team) {
  const row = document.createElement("tr");
  const teamCell = document.createElement("td");
  teamCell.dataset.label = "Team";
  teamCell.append(createTeamLink(team));
  row.append(
    createRankCell(team.rank, team.rankMovement),
    teamCell,
    createStatusCell(team.toStart ?? 0, "To Start", team.captainStatus === "toStart"),
    createStatusCell(team.inPlay ?? 0, "In Play", team.captainStatus === "inPlay"),
    createCell(team.gameweekPoints, "number", "GW Indiv"),
    createCell(team.gameweekPoints, "number", "GW Total"),
    createCell(team.totalPoints, "number", "Total"),
  );
  addTeamRowInteraction(row, team.id, team.team);
  return row;
}

function createPairMemberPlaceholder() {
  const placeholder = document.createElement("span");
  placeholder.className = "pair-member-placeholder";
  placeholder.setAttribute("aria-hidden", "true");
  return placeholder;
}

function getPairMembersInPointsOrder(pair) {
  return [...(pair.members || [])].sort((a, b) => {
    const aPoints = Number.isFinite(a.totalPoints) ? a.totalPoints : -Infinity;
    const bPoints = Number.isFinite(b.totalPoints) ? b.totalPoints : -Infinity;
    return bPoints - aPoints;
  });
}

function createPairRow(pair) {
  const row = document.createElement("tr");
  const teamCell = document.createElement("td");
  const teamsById = new Map((standingsData?.standings || []).map((team) => [team.id, team]));
  const members = getPairMembersInPointsOrder(pair);
  const seenMemberIds = new Set();
  const hasDuplicateMembers = new Set(members.map((member) => member.id)).size < members.length;

  teamCell.className = "pair-members";
  if (hasDuplicateMembers) {
    teamCell.classList.add("pair-members-centered");
  }
  teamCell.dataset.label = "Teams";
  for (const member of members) {
    if (seenMemberIds.has(member.id)) {
      teamCell.append(createPairMemberPlaceholder());
      continue;
    }

    seenMemberIds.add(member.id);
    const team = { ...member, ...teamsById.get(member.id) };
    teamCell.append(createTeamLink(team));
  }

  row.append(
    createRankCell(pair.rank, pair.rankMovement),
    teamCell,
    createStackedStatusCell(members, "toStart", "To Start"),
    createStackedStatusCell(members, "inPlay", "In Play"),
    createStackedCell(members.map((member) => member.gameweekPoints), "number", "GW Indiv"),
    createCell(pair.gameweekPoints, "number", "GW Total"),
    createCell(pair.totalPoints, "number", "Total"),
  );
  addPairRowInteraction(row, members);
  return row;
}

function formatPercent(value) {
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

function formatTeamValue(value) {
  return Number.isFinite(value) ? `${value.toFixed(1)}m` : "—";
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

const availableChips = ["BB", "FH", "TC", "WC"];

function createChipsRow(team, { showTeamName = true, data = standingsData } = {}) {
  const row = document.createElement("div");
  const name = document.createElement("span");
  const chips = document.createElement("span");
  const detail = (data?.teamDetails || []).find((item) => item.id === team.id);
  const chipHistory = Array.isArray(detail?.chipsPlayed)
    ? detail.chipsPlayed
    : (detail?.chip ? [{ chip: detail.chip }] : []);
  const playedChips = new Set(chipHistory.map((item) => item.chip));

  row.className = "chips-row";
  name.className = "chips-team-name";
  name.textContent = team.team;
  chips.className = "chips-pills";

  for (const chipName of availableChips) {
    const chip = document.createElement("span");
    const hasPlayed = playedChips.has(chipName);
    const isActive = detail?.chip === chipName
      && data?.gameweek?.id === data?.currentGameweek?.id;
    const stateClass = isActive
      ? " chips-pill-active"
      : (hasPlayed ? " chips-pill-played" : "");
    chip.className = `chip-pill chips-pill${stateClass}`;
    chip.textContent = chipName;
    chip.title = `${formatChipName(chipName)} — ${isActive ? "active" : hasPlayed ? "played" : "not played"}`;
    chip.setAttribute("aria-label", chip.title);
    chips.append(chip);
  }

  if (showTeamName) {
    row.append(name, chips);
  } else {
    row.classList.add("chips-row-centered");
    row.append(chips);
  }
  return row;
}

function getTeamsInDuoLeagueOrder(data = standingsData) {
  const standings = data?.standings || [];
  const teamsById = new Map(standings.map((team) => [team.id, team]));
  const orderedTeams = [];
  const addedTeamIds = new Set();

  for (const pair of data?.pairs || []) {
    for (const member of getPairMembersInPointsOrder(pair)) {
      if (addedTeamIds.has(member.id)) continue;

      const team = teamsById.get(member.id);
      if (!team) continue;
      orderedTeams.push(team);
      addedTeamIds.add(member.id);
    }
  }

  for (const team of standings) {
    if (addedTeamIds.has(team.id)) continue;
    orderedTeams.push(team);
  }

  return orderedTeams;
}

function renderChips() {
  const data = currentGameweekData || standingsData;
  if (!chipsList || !data) return;
  chipsList.replaceChildren(
    ...getTeamsInDuoLeagueOrder(data).map((team) => createChipsRow(team, { data })),
  );
}

function createTransfersHeader() {
  const row = document.createElement("div");
  const labels = [
    ["Team"],
    ["Xfers", "Made"],
    ["FTs", "Left"],
    ["Net", "Diff"],
    ["Details"],
  ];

  row.className = "chips-row stats-transfers-row stats-transfers-header";
  for (const lines of labels) {
    const cell = document.createElement("span");
    lines.forEach((line, index) => {
      if (index) cell.append(document.createElement("br"));
      cell.append(line);
    });
    row.append(cell);
  }
  return row;
}

function formatNetDiff(transfers) {
  if (!transfers.length) return "0";
  if (transfers.some((transfer) => (
    !Number.isFinite(transfer.pointsIn) || !Number.isFinite(transfer.pointsOut)
  ))) return "—";

  const net = transfers.reduce(
    (total, transfer) => total + transfer.pointsIn - transfer.pointsOut,
    0,
  );
  return `${net > 0 ? "+" : ""}${net}`;
}

function createTransfersRow(team, data = standingsData) {
  const row = document.createElement("div");
  const name = document.createElement("span");
  const made = document.createElement("span");
  const banked = document.createElement("span");
  const net = document.createElement("span");
  const details = document.createElement("span");
  const detail = (data?.teamDetails || []).find((item) => item.id === team.id);
  const transfers = detail?.transfers || [];
  const chipLabel = detail?.chip === "WC"
    ? "Wildcard"
    : detail?.chip === "FH" ? "Free Hit" : undefined;

  row.className = "chips-row stats-transfers-row";
  name.className = "chips-team-name";
  name.textContent = team.team;
  made.className = "stats-transfer-number";
  made.textContent = chipLabel ? "—" : formatStatValue(detail?.transfersMade ?? 0);
  banked.className = "stats-transfer-number";
  banked.textContent = formatStatValue(detail?.bankedFTs ?? "—");
  net.className = "stats-transfer-number";
  net.textContent = chipLabel ? "—" : formatNetDiff(transfers);
  details.className = "stats-transfer-value";
  if (chipLabel) {
    details.textContent = chipLabel;
  } else if (transfers.length) {
    details.replaceChildren(...transfers.map((transfer) => {
      const line = document.createElement("span");
      const pointsOut = Number.isFinite(transfer.pointsOut) ? ` (${transfer.pointsOut})` : "";
      const pointsIn = Number.isFinite(transfer.pointsIn) ? ` (${transfer.pointsIn})` : "";
      line.className = "stats-transfer-line";
      line.textContent = `${transfer.out}${pointsOut} → ${transfer.in}${pointsIn}`;
      return line;
    }));
  } else {
    details.textContent = "—";
  }
  row.append(name, made, banked, net, details);
  return row;
}

function renderTransfers() {
  const data = currentGameweekData || standingsData;
  if (!transfersList || !data) return;
  transfersList.replaceChildren(
    createTransfersHeader(),
    ...getTeamsInDuoLeagueOrder(data).map((team) => createTransfersRow(team, data)),
  );
}

function createCaptainPill(label) {
  const pill = document.createElement("span");
  pill.className = `captain-pill captain-pill-${label.toLowerCase()}`;
  pill.textContent = label;
  pill.setAttribute("aria-label", label === "C" ? "Captain" : "Vice captain");
  return pill;
}

function createTeamPickContent(team) {
  const fragment = document.createDocumentFragment();
  const name = document.createElement("span");
  name.textContent = team.name;
  fragment.append(name);

  if (team.captain) {
    fragment.append(createCaptainPill("C"));
  }

  return fragment;
}

function createTeamPickSection(title, teams) {
  const section = document.createElement("section");
  const heading = document.createElement("h4");
  heading.textContent = `${title} (${teams.length})`;
  section.append(heading);

  if (!teams.length) {
    const empty = document.createElement("p");
    empty.textContent = "-";
    section.append(empty);
    return section;
  }

  const list = document.createElement("ul");
  for (const team of teams) {
    const item = document.createElement("li");
    item.className = "team-pick-item";
    item.replaceChildren(createTeamPickContent(team));
    list.append(item);
  }
  section.append(list);
  return section;
}

function usesDesktopPlayerPopover() {
  return desktopLayout.matches && hoverLayout.matches;
}

function importanceDialogRow(anchor) {
  return anchor?.closest(".ownership-row") || anchor;
}

function importanceDialogContainer(anchor) {
  return anchor?.closest(".team-player-row") ? teamDetail : ownershipPanel;
}

function positionImportanceDialog(anchor) {
  if (!importanceDialog?.open || !anchor) return;

  const isPopover = activeImportanceMode === "popover";
  const spacing = isPopover ? 12 : 8;
  const rightPopoverInsetRatio = 0.6;
  const viewportPadding = 12;
  const anchorRect = anchor.getBoundingClientRect();
  const dialogWidth = importanceDialog.offsetWidth;
  const dialogHeight = importanceDialog.offsetHeight;
  const maxLeft = window.innerWidth - dialogWidth - viewportPadding;
  const maxTop = window.innerHeight - dialogHeight - viewportPadding;
  let left;
  let top;

  if (isPopover) {
    const rowRect = importanceDialogRow(anchor).getBoundingClientRect();
    const containerRect = importanceDialogContainer(anchor)?.getBoundingClientRect() || anchorRect;
    left = containerRect.right + spacing - (dialogWidth * rightPopoverInsetRatio);
    top = rowRect.top;
  } else {
    const nameRect = anchor.querySelector(".player-name-text")?.getBoundingClientRect();
    const anchorRight = mobileLayout.matches && nameRect
      ? nameRect.right
      : anchorRect.right;
    left = anchorRight + spacing;
    top = anchorRect.top - spacing;
  }

  left = Math.max(viewportPadding, Math.min(left, maxLeft));
  top = isPopover
    ? Math.max(viewportPadding, top)
    : Math.max(viewportPadding, Math.min(top, maxTop));

  importanceDialog.style.left = `${left}px`;
  importanceDialog.style.top = `${top}px`;
}

function openImportanceDialog(player, anchor) {
  const usePopover = usesDesktopPlayerPopover();
  const mode = usePopover ? "popover" : "modal";
  const teams = player.teams || {};
  const startedTeams = teams.started || [];
  const benchedTeams = teams.benched || [];
  if (importanceDialog.open && activeImportanceMode !== mode) {
    closeImportanceDialog();
  }
  activeImportanceAnchor = anchor;
  activeImportanceMode = mode;
  importanceDialog.classList.toggle("importance-dialog-hover", usePopover);
  importanceDialogTitle.textContent = player.name;
  importanceDialogBody.replaceChildren(
    createTeamPickSection("Started", startedTeams),
    createTeamPickSection("Benched", benchedTeams),
    createPointDetails(player.pointDetails),
  );

  if (!importanceDialog.open) {
    if (usePopover) {
      importanceDialog.show();
    } else {
      importanceDialog.showModal();
    }
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
  activeImportanceMode = "modal";
  importanceDialog?.classList.remove("importance-dialog-hover");
}

function addPlayerDialogInteractions(row, button, getPlayer) {
  const openPlayerDialog = (event) => {
    if (usesDesktopPlayerPopover()) {
      event.preventDefault();
      if (activeImportanceAnchor === button && importanceDialog.open) {
        closeImportanceDialog();
        return;
      }
      openImportanceDialog(getPlayer(), button);
      return;
    }
    openImportanceDialog(getPlayer(), button);
  };

  row.addEventListener("click", openPlayerDialog);
}

function playerCrestUrl(player) {
  if (!player.teamCode) return "";
  return `https://resources.premierleague.com/premierleague/badges/t${player.teamCode}.png`;
}

function createPlayerNameContent(player, label, captainLabel = "") {
  const fragment = document.createDocumentFragment();
  const crestUrl = playerCrestUrl(player);

  if (crestUrl) {
    const isLiverpool = String(player.teamCode) === "14";
    const crest = document.createElement(isLiverpool ? "span" : "img");
    crest.className = "player-crest";
    if (isLiverpool) {
      crest.classList.add("player-crest-liverpool");
      crest.setAttribute("aria-hidden", "true");
    } else {
      crest.src = crestUrl;
      crest.alt = "";
      crest.loading = "lazy";
      crest.decoding = "async";
    }
    fragment.append(crest);
  }

  const text = document.createElement("span");
  text.className = "player-name-text";
  text.textContent = label;
  fragment.append(text);

  if (captainLabel) {
    fragment.append(createCaptainPill(captainLabel));
  }

  return fragment;
}

function createImportanceRow(player) {
  const row = document.createElement("div");
  const name = document.createElement("button");
  const opponent = document.createElement("span");
  const fixtureTime = document.createElement("span");
  const points = document.createElement("span");
  const importance = document.createElement("strong");

  row.className = "ownership-row";
  if (player.isLive) row.classList.add("player-live");
  name.className = "importance-player-button";
  name.type = "button";
  fixtureTime.className = "player-match-status";
  points.className = "player-points";
  name.replaceChildren(createPlayerNameContent(player, player.name));
  opponent.textContent = player.opponent;
  fixtureTime.textContent = player.matchStatus || player.fixtureTime || "-";
  points.textContent = player.points;
  importance.textContent = formatPercent(player.importance);
  if (player.importance < 0) {
    name.classList.add("negative-importance");
    importance.classList.add("negative-importance");
  }
  addPlayerDialogInteractions(row, name, () => player);
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

function playerCaptainLabel(player) {
  if (player.isCaptain) return "C";
  if (player.isViceCaptain) return "VC";
  return "";
}

function teamPlayerPoints(player, chip) {
  if (player.isCaptain && Number.isFinite(player.points)) {
    return player.points * (chip === "TC" ? 3 : 2);
  }
  return player.points;
}

function createTeamPlayerRow(player, chip) {
  const row = document.createElement("div");
  const name = document.createElement("button");
  const opponent = document.createElement("span");
  const fixtureTime = document.createElement("span");
  const points = document.createElement("span");

  row.className = "ownership-row team-player-row";
  if (player.isBenched) row.classList.add("team-player-row-benched");
  if (player.isLive) row.classList.add("player-live");
  name.className = "importance-player-button team-player-name";
  name.type = "button";
  fixtureTime.className = "player-match-status";
  points.className = "player-points";
  name.replaceChildren(createPlayerNameContent(player, player.name, playerCaptainLabel(player)));
  opponent.textContent = player.opponent;
  fixtureTime.textContent = player.matchStatus || player.fixtureTime || "-";
  points.textContent = teamPlayerPoints(player, chip);
  addPlayerDialogInteractions(row, name, () => playerWithImportanceTeams(player));
  row.append(name, opponent, fixtureTime, points);
  return row;
}

function createTeamValueSummary(detail) {
  const values = document.createElement("div");
  values.className = "team-summary-values";

  const squadValue = Number.isFinite(detail.teamValue) && Number.isFinite(detail.bank)
    ? detail.teamValue - detail.bank
    : undefined;

  for (const [label, value, formatter] of [
    ["Squad Value", squadValue, formatTeamValue],
    ["Bank", detail.bank, formatTeamValue],
    ["Total Value", detail.teamValue, formatTeamValue],
    ["Total Pts", detail.totalPoints, formatStatValue],
    ["Banked FTs", detail.bankedFTs, formatStatValue],
  ]) {
    const item = document.createElement("div");
    const itemLabel = document.createElement("span");
    const itemValue = document.createElement("strong");
    item.className = "team-summary-value";
    itemLabel.textContent = label;
    itemValue.textContent = formatter(value);
    item.append(itemLabel, itemValue);
    values.append(item);
  }

  return values;
}

function renderTeamSummary(detail, standingsTeam) {
  if (!teamSummaryPanel) return;
  teamSummaryPanel.hidden = false;
  teamSummaryPanel.replaceChildren(
    createTeamValueSummary(detail),
    createChipsRow(standingsTeam, { showTeamName: false }),
  );
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

function createTeamDetailTeamSelect(detail) {
  const control = document.createElement("div");
  const select = document.createElement("select");
  const chevron = document.createElement("span");
  const teams = standingsData?.standings || standingsData?.teamDetails || [];

  control.className = "team-detail-team-control";
  select.className = "team-detail-team-select";
  select.setAttribute("aria-label", "Select team");
  select.title = "Select team";
  select.replaceChildren(
    ...teams.map((team) => {
      const option = document.createElement("option");
      option.value = String(team.id);
      option.textContent = team.team || team.manager || `Team ${team.id}`;
      return option;
    }),
  );
  select.value = String(detail.id);
  select.addEventListener("change", () => {
    const teamId = Number(select.value);
    if (!Number.isFinite(teamId) || teamId === activeTeamId) return;

    openTeamDetail(teamId, { scroll: false });
  });

  chevron.className = "team-detail-team-chevron";
  chevron.setAttribute("aria-hidden", "true");

  control.append(select, chevron);
  return control;
}

function findTeamDetail(teamId) {
  return (standingsData?.teamDetails || []).find((team) => team.id === teamId);
}

function findStandingsTeam(teamId) {
  return (standingsData?.standings || []).find((team) => team.id === teamId);
}

function renderTeamDetail() {
  if (!teamDetail || activeTeamId === undefined) return;

  teamDetail.classList.remove("team-detail-loading");
  teamDetail.removeAttribute("aria-busy");

  const detail = findTeamDetail(activeTeamId);
  const standingsTeam = findStandingsTeam(activeTeamId);
  if (!detail || !standingsTeam) {
    teamDetail.replaceChildren();
    if (teamSummaryPanel) {
      teamSummaryPanel.hidden = true;
      teamSummaryPanel.replaceChildren();
    }
    return;
  }

  const header = document.createElement("div");
  const titleGroup = document.createElement("div");
  const titleText = document.createElement("div");
  const teamName = createTeamDetailTeamSelect(detail);
  const gameweekScore = createGameweekScore(detail.gameweekPoints);
  const players = document.createElement("div");

  header.className = "team-detail-header";

  titleGroup.className = "team-detail-title";
  titleText.className = "team-detail-title-text";

  titleText.append(teamName);
  titleGroup.append(createTeamCardImage(standingsTeam), titleText);

  header.append(titleGroup, gameweekScore);

  players.className = "ownership-list team-player-list";
  players.replaceChildren(
    createTeamPlayerHeader(),
    ...detail.players.map((p) => createTeamPlayerRow(p, detail.chip)),
  );

  teamDetail.replaceChildren(header, players);
  renderTeamSummary(detail, standingsTeam);
  syncOwnershipHeight();
}

function openTeamDetail(teamId, { scroll = true } = {}) {
  activeTeamId = teamId;
  saveTeamId(teamId);
  if (mobileLayout.matches) setMobileTab("team", { scroll: false });
  closeImportanceDialog();
  renderActiveView();
  renderOwnership();
  if (scroll) {
    requestAnimationFrame(() => {
      if (mobileLayout.matches) {
        window.scrollTo({ top: 0, behavior: "smooth" });
      } else {
        scrollToTeamDetail();
      }
    });
  }
}

function setMobileTab(tab, { scroll = true } = {}) {
  if (!["league", "team", "importance", "stats"].includes(tab)) return;
  activeMobileTab = tab;
  main.dataset.mobileTab = tab;
  mobileTabButtons.forEach((button) => {
    const isActive = button.dataset.mobileTab === tab;
    button.classList.toggle("is-active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
  closeImportanceDialog();
  if (scroll && mobileLayout.matches) window.scrollTo({ top: 0, behavior: "smooth" });
  requestAnimationFrame(() => {
    scheduleStandingsColumnFit();
    syncOwnershipHeight();
  });
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
  standingsCard.classList.toggle("view-individual", !isPairs);
  tbody.replaceChildren(
    ...(isPairs ? standingsData.pairs.map(createPairRow) : standingsData.standings.map(createTeamRow)),
  );
  scheduleStandingsColumnFit();
  syncOwnershipHeight();
  scheduleHeaderFontScale();
}

function renderOwnership() {
  const data = currentGameweekData || standingsData;
  if (!data) return;
  closeImportanceDialog();
  const duoImportance = data.duoImportance || [];
  if (!duoImportance.length) {
    duoImportanceSelect.replaceChildren();
    playerOwnership.replaceChildren();
    importancePagination.hidden = true;
    liveOnlyFilter.hidden = true;
    liveOnlyImportance = false;
    liveOnlyImportanceContext = "";
    liveOnlyImportanceManuallySet = false;
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

  const livePlayerCount = selectedDuo.players.filter((player) => player.isLive).length;
  const hasLivePlayers = livePlayerCount > 0;
  const liveOnlyContext = `${data.gameweek?.id ?? ""}:${selectedDuo.name}`;
  if (liveOnlyImportanceContext !== liveOnlyContext) {
    liveOnlyImportanceContext = liveOnlyContext;
    liveOnlyImportanceManuallySet = false;
  }
  if (!liveOnlyImportanceManuallySet) liveOnlyImportance = livePlayerCount > 0;
  liveOnlyFilter.hidden = !hasLivePlayers;
  if (!hasLivePlayers) {
    liveOnlyImportance = false;
    liveOnlyImportanceManuallySet = false;
  }
  liveOnlyFilter.setAttribute("aria-pressed", String(liveOnlyImportance));

  const players = selectedDuo.players.filter(
    (player) => !liveOnlyImportance || player.isLive,
  ).sort(
    (a, b) =>
      Math.abs(b.importance) - Math.abs(a.importance) ||
      Math.sign(a.importance) - Math.sign(b.importance) ||
      a.name.localeCompare(b.name),
  );
  const showAllPlayers = mobileLayout.matches;
  const pageCount = showAllPlayers
    ? 1
    : Math.max(1, Math.ceil(players.length / importancePageSize));
  if (showAllPlayers) importancePage = 0;
  importancePage = Math.min(importancePage, pageCount - 1);
  const visiblePlayers = showAllPlayers
    ? players
    : players.slice(
      importancePage * importancePageSize,
      (importancePage + 1) * importancePageSize,
    );
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

function renderStandings(data, { saveSnapshot = true, animateRefresh = false } = {}) {
  if (animateRefresh) animateRefreshIcon();
  standingsData = data;
  if (data.gameweek?.id === data.currentGameweek?.id) currentGameweekData = data;
  leagueName.textContent = data.league.name;
  status.textContent = data.gameweek.name;
  updatedAt = new Date(data.updatedAt);
  renderGameweekControls(data);
  if (saveSnapshot) saveStandingsSnapshot(data);
  setDefaultActiveTeam();
  renderLastUpdated();
  renderActiveView();
  renderOwnership();
  renderTransfers();
  renderChips();
  scheduleStandingsRefresh();
}

async function loadStandings(force = false, { quiet = false } = {}) {
  if (isLoadingStandings) return;
  isLoadingStandings = true;
  updateGameweekControls();
  clearStandingsRefresh();

  if (!quiet) {
    refreshButton.disabled = true;
    refreshButton.setAttribute("aria-label", "Refreshing standings");
    status.textContent = "Loading standings…";
  }

  try {
    const params = new URLSearchParams();
    if (force) params.set("refresh", "1");
    if (selectedGameweekId) params.set("event", String(selectedGameweekId));
    const url = params.toString() ? `/api/standings?${params}` : "/api/standings";
    const responsePromise = fetch(url, { cache: "no-store" });
    const currentParams = new URLSearchParams();
    if (force) currentParams.set("refresh", "1");
    const currentUrl = currentParams.toString()
      ? `/api/standings?${currentParams}`
      : "/api/standings";
    const currentResponsePromise = selectedGameweekId
      && standingsData?.currentGameweek?.id
      && selectedGameweekId !== standingsData.currentGameweek.id
      ? fetch(currentUrl, { cache: "no-store" })
      : undefined;
    const [response, currentResponse] = await Promise.all([
      responsePromise,
      currentResponsePromise,
    ]);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Standings are unavailable");
    if (currentResponse) {
      const currentData = await currentResponse.json();
      if (!currentResponse.ok) {
        throw new Error(currentData.error || "Current gameweek stats are unavailable");
      }
      currentGameweekData = currentData;
    }
    lastFetchAt = Date.now();
    renderStandings(data, { animateRefresh: quiet && !force });
  } catch (error) {
    if (!quiet || !standingsData) {
      status.textContent = error instanceof Error ? error.message : "Standings are unavailable";
    }
    if (teamDetail && !standingsData) {
      teamDetail.hidden = true;
      teamDetail.classList.remove("team-detail-loading");
      teamDetail.removeAttribute("aria-busy");
    }
    scheduleStandingsRefresh();
  } finally {
    isLoadingStandings = false;
    updateGameweekControls();
    if (!quiet) {
      refreshButton.disabled = false;
      refreshButton.setAttribute("aria-label", "Refresh standings");
    }
  }
}

refreshButton.addEventListener("click", () => loadStandings(true));
gameweekPreviousButtons.forEach((button) => {
  button.addEventListener("click", () => stepGameweek(-1));
});
gameweekNextButtons.forEach((button) => {
  button.addEventListener("click", () => stepGameweek(1));
});
gameweekValues.forEach((input) => {
  input.addEventListener("focus", () => input.select());
  input.addEventListener("change", () => selectGameweek(input));
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    selectGameweek(input);
    input.blur();
  });
});
document.addEventListener("visibilitychange", refreshStandingsAfterResume);
window.addEventListener("pageshow", refreshStandingsAfterResume);
window.addEventListener("focus", refreshStandingsAfterResume);
mobileTabButtons.forEach((button) => {
  button.addEventListener("click", () => setMobileTab(button.dataset.mobileTab));
});
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
liveOnlyFilter.addEventListener("click", () => {
  liveOnlyImportance = !liveOnlyImportance;
  liveOnlyImportanceManuallySet = true;
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
document.addEventListener("click", (event) => {
  if (activeImportanceMode !== "popover" || !importanceDialog.open) return;
  const activeRow = importanceDialogRow(activeImportanceAnchor);
  if (importanceDialog.contains(event.target) || activeRow?.contains(event.target)) {
    return;
  }
  closeImportanceDialog();
});
importanceDialog.addEventListener("close", () => {
  activeImportanceAnchor = undefined;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeImportanceDialog();
});
window.addEventListener("scroll", () => {
  scheduleHeaderFontScale();
  positionImportanceDialog(activeImportanceAnchor);
}, { passive: true });
window.addEventListener("resize", () => {
  positionImportanceDialog(activeImportanceAnchor);
  scheduleStandingsColumnFit();
  resetHeaderFontScale();
});
desktopLayout.addEventListener("change", syncOwnershipHeight);
hoverLayout.addEventListener("change", closeImportanceDialog);
mobileLayout.addEventListener("change", () => {
  importancePage = 0;
  setMobileTab(activeMobileTab, { scroll: false });
  renderOwnership();
});
ownershipPanel?.addEventListener("scroll", () => {
  positionImportanceDialog(activeImportanceAnchor);
}, { passive: true });
teamDetail?.addEventListener("scroll", () => {
  positionImportanceDialog(activeImportanceAnchor);
}, { passive: true });
if (standingsCard) {
  new ResizeObserver(syncOwnershipHeight).observe(standingsCard);
}
if (teamDetail) {
  new ResizeObserver(() => {
    syncOwnershipHeight();
  }).observe(teamDetail);
}
document.fonts?.ready.then(() => {
  scheduleStandingsColumnFit();
  resetHeaderFontScale();
});
setInterval(renderLastUpdated, 30_000);
scheduleHeaderFontScale();
scheduleStandingsColumnFit();
setMobileTab(activeMobileTab, { scroll: false });
const initialStandingsSnapshot = getStandingsSnapshot();
if (canUseFrozenSnapshot(initialStandingsSnapshot)) {
  renderStandings(initialStandingsSnapshot, { saveSnapshot: false });
  loadStandings(true, { quiet: true });
} else {
  loadStandings(true);
}
