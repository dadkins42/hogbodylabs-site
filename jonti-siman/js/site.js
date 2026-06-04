// Musician site — loads JSON manifests and renders the page.
// The companion app writes these JSON files; this script just displays them.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Parse "YYYY-MM-DD" as a LOCAL date (avoids the UTC shift of new Date("...")).
function parseDate(str) {
  if (!str) return null;
  const [y, m, d] = str.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

function todayStr() {
  const t = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`;
}

async function loadJSON(path, fallback) {
  try {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.json();
  } catch (e) {
    return fallback;
  }
}

function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

function escapeHTML(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// ---- Shows -------------------------------------------------------------

function renderShows(shows) {
  const list = document.getElementById("shows-list");
  const hero = document.getElementById("next-show");
  if (!list) return;

  const today = todayStr();
  const upcoming = (shows || [])
    .filter((s) => s.date && s.date >= today)
    .sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")));

  // Hero "next show" highlight = first confirmed upcoming show.
  const next = upcoming.find((s) => (s.status || "confirmed") !== "cancelled");
  if (hero) {
    if (next) {
      const d = parseDate(next.date);
      hero.innerHTML =
        `<span class="next-label">Next show</span>` +
        `<span class="next-date">${WEEKDAYS[d.getDay()]} ${MONTHS[d.getMonth()]} ${d.getDate()}</span>` +
        `<span class="next-venue">${escapeHTML(next.venue)} · ${escapeHTML(next.city)}</span>`;
      hero.href = "#shows";
      hero.style.display = "";
    } else {
      hero.style.display = "none";
    }
  }

  list.innerHTML = "";
  if (upcoming.length === 0) {
    list.appendChild(el("p", "empty-state", "No shows on the calendar right now — check back soon."));
    return;
  }

  let currentMonth = "";
  for (const s of upcoming) {
    const d = parseDate(s.date);
    const monthKey = `${MONTHS_LONG[d.getMonth()]} ${d.getFullYear()}`;
    if (monthKey !== currentMonth) {
      currentMonth = monthKey;
      list.appendChild(el("h3", "month-header", monthKey));
    }

    const cancelled = (s.status || "confirmed") === "cancelled";
    const row = el("div", "show-row" + (cancelled ? " cancelled" : ""));

    const dateBlock =
      `<div class="show-date">` +
        `<span class="dow">${WEEKDAYS[d.getDay()]}</span>` +
        `<span class="day">${d.getDate()}</span>` +
        `<span class="mon">${MONTHS[d.getMonth()]}</span>` +
      `</div>`;

    const meta = [];
    if (s.time) meta.push(escapeHTML(s.time));
    if (s.band) meta.push(escapeHTML(s.band));
    if (s.notes) meta.push(escapeHTML(s.notes));

    const details =
      `<div class="show-details">` +
        `<span class="show-venue">${escapeHTML(s.venue)}</span>` +
        `<span class="show-city">${escapeHTML(s.city)}</span>` +
        (meta.length ? `<span class="show-meta">${meta.join(" · ")}</span>` : "") +
      `</div>`;

    let action = "";
    if (cancelled) {
      action = `<span class="show-action cancelled-tag">Cancelled</span>`;
    } else if (s.ticketURL) {
      action = `<a class="show-action tickets" href="${escapeHTML(s.ticketURL)}" target="_blank" rel="noopener">Tickets</a>`;
    }

    row.innerHTML = dateBlock + details + action;
    list.appendChild(row);
  }
}

// ---- Bands -------------------------------------------------------------

function renderBands(bands) {
  const wrap = document.getElementById("bands-list");
  if (!wrap) return;
  wrap.innerHTML = "";
  for (const b of bands || []) {
    const card = el("div", "band-card");
    const links = (b.links || [])
      .map((l) => `<a href="${escapeHTML(l.url)}" target="_blank" rel="noopener">${escapeHTML(l.label)}</a>`)
      .join("");
    card.innerHTML =
      (b.photo ? `<img class="band-photo" src="${escapeHTML(b.photo)}" alt="${escapeHTML(b.name)}">` : "") +
      `<h3>${escapeHTML(b.name)}</h3>` +
      `<p>${escapeHTML(b.blurb)}</p>` +
      (links ? `<div class="band-links">${links}</div>` : "");
    wrap.appendChild(card);
  }
}

// ---- Music -------------------------------------------------------------

function renderMusic(tracks) {
  const wrap = document.getElementById("music-list");
  if (!wrap) return;

  // Hide the whole Music section (and its nav link) until there are tracks to show.
  const section = document.getElementById("music");
  const navLink = document.querySelector('#site-nav a[href="#music"]');
  if (!tracks || tracks.length === 0) {
    if (section) section.style.display = "none";
    if (navLink) navLink.style.display = "none";
    return;
  }
  if (section) section.style.display = "";
  if (navLink) navLink.style.display = "";

  wrap.innerHTML = "";
  for (const t of tracks || []) {
    const card = el("div", "music-card");
    if (t.embedURL) {
      card.innerHTML =
        `<div class="embed"><iframe src="${escapeHTML(t.embedURL)}" loading="lazy" ` +
        `frameborder="0" allow="encrypted-media; clipboard-write; fullscreen" allowfullscreen></iframe></div>` +
        `<span class="music-title">${escapeHTML(t.title)}</span>`;
    } else {
      card.innerHTML =
        `<div class="embed embed-empty">${escapeHTML((t.source || "").toUpperCase())}</div>` +
        `<span class="music-title">${escapeHTML(t.title)}</span>`;
    }
    wrap.appendChild(card);
  }
}

// ---- Profile -----------------------------------------------------------

function renderProfile(p) {
  if (!p) return;
  const set = (id, val) => { const n = document.getElementById(id); if (n) n.textContent = val || ""; };

  set("artist-name", p.name);
  set("artist-name-hero", p.name);
  set("artist-name-footer", p.name);
  set("artist-tagline", p.tagline);
  if (p.name) document.title = p.name;

  const bioEl = document.getElementById("artist-bio");
  if (bioEl && p.bio) {
    bioEl.innerHTML = p.bio.split("\n").filter(Boolean)
      .map((para) => `<p>${escapeHTML(para)}</p>`).join("");
  }

  const hero = document.getElementById("hero-img");
  if (hero && p.photo) hero.style.backgroundImage = `url('${p.photo}')`;

  const about = document.getElementById("about-img");
  const aboutSrc = p.aboutPhoto || p.photo; // fall back to the hero photo
  if (about) {
    if (aboutSrc) about.src = aboutSrc;
    else about.style.display = "none"; // no photo yet — hide the broken-image slot
  }

  const book = document.getElementById("booking-link");
  if (book && p.bookingEmail) {
    book.href = `mailto:${p.bookingEmail}`;
    book.textContent = p.bookingEmail;
  }

  const socials = document.getElementById("socials");
  if (socials) {
    socials.innerHTML = (p.socials || [])
      .map((s) => `<a href="${escapeHTML(s.url)}" target="_blank" rel="noopener">${escapeHTML(s.label)}</a>`)
      .join("");
  }

  const year = document.getElementById("year");
  if (year) year.textContent = new Date().getFullYear();
}

// ---- Boot --------------------------------------------------------------

async function boot() {
  const [profile, shows, bands, music] = await Promise.all([
    loadJSON("data/profile.json", {}),
    loadJSON("data/shows.json", { shows: [] }),
    loadJSON("data/bands.json", { bands: [] }),
    loadJSON("data/music.json", { tracks: [] }),
  ]);

  renderProfile(profile);
  renderShows(shows.shows || []);
  renderBands(bands.bands || []);
  renderMusic(music.tracks || []);

  // Mobile nav toggle
  const toggle = document.getElementById("nav-toggle");
  const nav = document.getElementById("site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => nav.classList.toggle("open"));
    nav.querySelectorAll("a").forEach((a) =>
      a.addEventListener("click", () => nav.classList.remove("open")));
  }
}

document.addEventListener("DOMContentLoaded", boot);
