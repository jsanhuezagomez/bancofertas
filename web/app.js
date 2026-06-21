const DATASETS = [
  "/data/banco_chile_sabores_full.json",
  "/data/banco_falabella_restaurantes_antojos.json",
  "/data/bci_restaurantes.json",
  "/data/banco_estado_sabores.json",
  "/data/santander_sabores.json",
  "/data/itau_ruta_gourmet.json",
  "/data/scotiabank_ruta_gourmet.json"
];

const dayOrder = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"];
const dayLabels = {
  lunes: "Lunes",
  martes: "Martes",
  miercoles: "Miercoles",
  jueves: "Jueves",
  viernes: "Viernes",
  sabado: "Sabado",
  domingo: "Domingo"
};
const dayAliases = {
  lu: "lunes",
  lun: "lunes",
  lunes: "lunes",
  ma: "martes",
  mar: "martes",
  martes: "martes",
  mi: "miercoles",
  mie: "miercoles",
  miercoles: "miercoles",
  miercoles: "miercoles",
  ju: "jueves",
  jue: "jueves",
  jueves: "jueves",
  vi: "viernes",
  vie: "viernes",
  viernes: "viernes",
  sa: "sabado",
  sab: "sabado",
  sabado: "sabado",
  sabado: "sabado",
  do: "domingo",
  dom: "domingo",
  domingo: "domingo"
};

const state = {
  offers: [],
  filtered: [],
  sort: {
    key: "discount",
    direction: "desc"
  }
};

const els = {
  summary: document.querySelector("#summary"),
  refreshButton: document.querySelector("#refreshButton"),
  searchInput: document.querySelector("#searchInput"),
  bankFilter: document.querySelector("#bankFilter"),
  dayFilter: document.querySelector("#dayFilter"),
  discountFilter: document.querySelector("#discountFilter"),
  regionFilter: document.querySelector("#regionFilter"),
  comunaFilter: document.querySelector("#comunaFilter"),
  todayFilter: document.querySelector("#todayFilter"),
  validFilter: document.querySelector("#validFilter"),
  offersBody: document.querySelector("#offersBody"),
  emptyState: document.querySelector("#emptyState"),
  sortButtons: document.querySelectorAll("[data-sort]"),
  dialog: document.querySelector("#offerDialog"),
  closeDialog: document.querySelector("#closeDialog"),
  dialogTitle: document.querySelector("#dialogTitle"),
  dialogSubtitle: document.querySelector("#dialogSubtitle"),
  dialogBody: document.querySelector("#dialogBody")
};

function normalize(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("es-CL")
    .trim();
}

function normalizeKey(value) {
  return normalize(value).replace(/\s+/g, " ");
}

function titleCase(value) {
  return String(value ?? "")
    .toLocaleLowerCase("es-CL")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/(^|\s)(\p{L})/gu, (_, prefix, letter) => `${prefix}${letter.toLocaleUpperCase("es-CL")}`);
}

function displayNameScore(value) {
  const text = String(value ?? "").trim();
  if (!text) return -1;
  const hasAccent = /[áéíóúñÁÉÍÓÚÑ]/.test(text) ? 4 : 0;
  const isAllCaps = text === text.toLocaleUpperCase("es-CL") ? -2 : 0;
  const hasLowercase = /[a-záéíóúñ]/.test(text) ? 2 : 0;
  return hasAccent + isAllCaps + hasLowercase;
}

function buildCanonicalNameMap(values) {
  const grouped = new Map();
  for (const value of values) {
    const key = normalizeKey(value);
    if (!key) continue;

    const current = grouped.get(key);
    if (!current || displayNameScore(value) > displayNameScore(current)) {
      grouped.set(key, String(value).trim());
    }
  }

  const canonical = new Map();
  for (const [key, value] of grouped) {
    canonical.set(key, titleCase(value));
  }
  return canonical;
}

function canonicalName(value, canonicalMap) {
  const key = normalizeKey(value);
  if (!key) return "";
  return canonicalMap.get(key) ?? titleCase(value);
}

function todayIso() {
  const now = new Date();
  const local = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return local.toISOString().slice(0, 10);
}

function todayName() {
  const index = new Date().getDay();
  return ["domingo", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado"][index];
}

function parseDiscount(value, rawText = "") {
  const source = `${value ?? ""} ${rawText ?? ""}`;
  const matches = [...source.matchAll(/(\d{1,3})\s*%/g)].map((match) => Number(match[1]));
  return matches.length ? Math.max(...matches) : 0;
}

function normalizeDiscountLabel(offer) {
  const discount = parseDiscount(offer.discount, offer.raw_title);
  return discount ? `${discount}%` : "N/D";
}

function extractDays(...sources) {
  const text = sources.filter(Boolean).join(" ");
  const normalizedText = normalize(text).replace(/[–—/-]/g, " ");
  if (normalizedText.includes("todos los dias")) {
    return [...dayOrder];
  }

  const matches = normalizedText.match(/\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie|sab|dom|lu|ma|mi|ju|vi|sa|do)\b/g) ?? [];
  const days = [];
  for (const match of matches) {
    const day = dayAliases[match];
    if (day && !days.includes(day)) {
      days.push(day);
    }
  }
  return days;
}

function getLocations(offer) {
  return Array.isArray(offer.addresses) ? offer.addresses : [];
}

function getRegions(offer) {
  return [...new Set(getLocations(offer).map((location) => location.region).filter(Boolean))];
}

function getComunas(offer) {
  return [...new Set(getLocations(offer).map((location) => location.comuna).filter(Boolean))];
}

function isValid(offer) {
  if (!offer.valid_until) {
    return null;
  }
  return offer.valid_until >= todayIso();
}

function locationStatus(offer) {
  if (offer.location_status) return offer.location_status;
  return getLocations(offer).length ? "specific" : "missing";
}

function locationFallbackLabel(offer) {
  const status = locationStatus(offer);
  if (status === "multiple") return "Cadena";
  if (status === "missing") return "Sin direccion";
  return "N/D";
}

function canonicalizeOfferLocations(offer, canonicalMaps) {
  return {
    ...offer,
    addresses: getLocations(offer).map((location) => ({
      ...location,
      region: canonicalName(location.region, canonicalMaps.regions),
      comuna: canonicalName(location.comuna, canonicalMaps.comunas)
    }))
  };
}

function enrichOffer(offer, canonicalMaps) {
  const canonicalOffer = canonicalizeOfferLocations(offer, canonicalMaps);
  const rawSearch = [
    canonicalOffer.promotion_day,
    canonicalOffer.raw_title,
    canonicalOffer.raw_info,
    canonicalOffer.conditions
  ].filter(Boolean).join(" ");
  const days = extractDays(canonicalOffer.promotion_day, rawSearch);
  const discountPercent = parseDiscount(canonicalOffer.discount, canonicalOffer.raw_title);
  const regions = getRegions(canonicalOffer);
  const comunas = getComunas(canonicalOffer);

  return {
    ...canonicalOffer,
    _days: days,
    _discountPercent: discountPercent,
    _discountLabel: normalizeDiscountLabel(canonicalOffer),
    _regions: regions,
    _comunas: comunas,
    _locationStatus: locationStatus(canonicalOffer),
    _valid: isValid(canonicalOffer),
    _search: normalize([
      canonicalOffer.merchant,
      canonicalOffer.bank,
      canonicalOffer.channel,
      canonicalOffer.discount,
      canonicalOffer.promotion_day,
      canonicalOffer.valid_until,
      locationFallbackLabel(canonicalOffer),
      regions.join(" "),
      comunas.join(" ")
    ].join(" "))
  };
}

async function loadDataset(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`No se pudo cargar ${url}`);
  }
  return response.json();
}

async function loadData() {
  els.summary.textContent = "Cargando beneficios...";
  const results = await Promise.allSettled(DATASETS.map(loadDataset));
  const rawOffers = [];
  const seen = new Set();

  for (const result of results) {
    if (result.status !== "fulfilled") {
      console.warn(result.reason);
      continue;
    }

    for (const offer of result.value) {
      const key = offer.source_url || `${offer.bank}:${offer.merchant}`;
      if (!seen.has(key)) {
        seen.add(key);
        rawOffers.push(offer);
      }
    }
  }

  const canonicalMaps = {
    regions: buildCanonicalNameMap(rawOffers.flatMap(getRegions)),
    comunas: buildCanonicalNameMap(rawOffers.flatMap(getComunas))
  };

  state.offers = rawOffers.map((offer) => enrichOffer(offer, canonicalMaps));
  populateFilters();
  applyFilters();
}

function populateFilters() {
  const selectedBank = els.bankFilter.value;
  const selectedRegion = els.regionFilter.value;
  const selectedComuna = els.comunaFilter.value;
  const banks = [...new Set(state.offers.map((offer) => offer.bank).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "es"));
  const regions = [...new Set(state.offers.flatMap((offer) => offer._regions))]
    .sort((a, b) => a.localeCompare(b, "es"));
  const comunas = [...new Set(state.offers.flatMap((offer) => offer._comunas))]
    .sort((a, b) => a.localeCompare(b, "es"));

  fillSelect(els.bankFilter, banks, "Todos");
  fillSelect(els.regionFilter, regions, "Todas");
  fillSelect(els.comunaFilter, comunas, "Todas");

  els.bankFilter.value = banks.includes(selectedBank) ? selectedBank : "";
  els.regionFilter.value = regions.includes(selectedRegion) ? selectedRegion : "";
  els.comunaFilter.value = comunas.includes(selectedComuna) ? selectedComuna : "";
}

function fillSelect(select, values, emptyLabel) {
  select.innerHTML = "";
  select.append(new Option(emptyLabel, ""));
  for (const value of values) {
    select.append(new Option(value, value));
  }
}

function applyFilters() {
  const query = normalize(els.searchInput.value);
  const bank = els.bankFilter.value;
  const day = els.todayFilter.checked ? todayName() : els.dayFilter.value;
  const minDiscount = Number(els.discountFilter.value);
  const region = els.regionFilter.value;
  const comuna = els.comunaFilter.value;
  const onlyValid = els.validFilter.checked;

  state.filtered = state.offers.filter((offer) => {
    if (query && !offer._search.includes(query)) return false;
    if (bank && offer.bank !== bank) return false;
    if (day && !offer._days.includes(day)) return false;
    if (offer._discountPercent < minDiscount) return false;
    if (region && !offer._regions.includes(region)) return false;
    if (comuna && !offer._comunas.includes(comuna)) return false;
    if (onlyValid && offer._valid === false) return false;
    return true;
  });

  sortFiltered();
  renderTable();
}

function sortValue(offer, key) {
  const first = (values) => values[0] || "";
  const values = {
    merchant: offer.merchant || "",
    bank: offer.bank || "",
    discount: offer._discountPercent,
    days: first(offer._days),
    channel: offer.channel || "",
    region: first(offer._regions),
    comuna: first(offer._comunas),
    validUntil: offer.valid_until || ""
  };
  return values[key] ?? "";
}

function compareOffers(a, b, key) {
  const aValue = sortValue(a, key);
  const bValue = sortValue(b, key);

  if (typeof aValue === "number" || typeof bValue === "number") {
    return Number(aValue) - Number(bValue);
  }
  return String(aValue).localeCompare(String(bValue), "es", { numeric: true, sensitivity: "base" });
}

function sortFiltered() {
  const multiplier = state.sort.direction === "asc" ? 1 : -1;
  state.filtered.sort((a, b) => {
    const result = compareOffers(a, b, state.sort.key);
    if (result !== 0) return result * multiplier;
    return a.merchant.localeCompare(b.merchant, "es", { sensitivity: "base" });
  });
}

function updateSortButtons() {
  for (const button of els.sortButtons) {
    const isActive = button.dataset.sort === state.sort.key;
    button.classList.toggle("active", isActive);
    button.dataset.direction = isActive ? state.sort.direction : "";
    button.setAttribute("aria-sort", isActive ? (state.sort.direction === "asc" ? "ascending" : "descending") : "none");
  }
}

function validLabel(offer) {
  if (offer._valid === true) return `<span class="valid">Vigente</span>`;
  if (offer._valid === false) return `<span class="expired">Vencido</span>`;
  return `<span class="unknown">Sin fecha</span>`;
}

function dayText(days) {
  return days.length ? days.map((day) => dayLabels[day] ?? day).join(", ") : "N/D";
}

function renderTable() {
  updateSortButtons();
  const rows = state.filtered.slice(0, 600).map((offer, index) => {
    const fallback = locationFallbackLabel(offer);
    const region = offer._regions[0] || fallback;
    const comuna = offer._comunas[0] || fallback;
    const days = dayText(offer._days);
    const validUntil = offer.valid_until ?? "N/D";
    return `
      <tr data-index="${index}">
        <td>
          <div class="merchant">
            <strong>${escapeHtml(offer.merchant)}</strong>
            <span class="subtle">${escapeHtml(offer.source_url || "")}</span>
          </div>
        </td>
        <td><span class="badge">${escapeHtml(offer.bank)}</span></td>
        <td class="discount">${escapeHtml(offer._discountLabel)}</td>
        <td>${escapeHtml(days)}</td>
        <td>${escapeHtml(offer.channel || "N/D")}</td>
        <td>${escapeHtml(region)}</td>
        <td>${escapeHtml(comuna)}</td>
        <td>${validLabel(offer)} <span class="subtle">${escapeHtml(validUntil)}</span></td>
      </tr>
    `;
  });

  els.offersBody.innerHTML = rows.join("");
  els.emptyState.hidden = state.filtered.length > 0;
  els.summary.textContent = `${state.filtered.length} de ${state.offers.length} beneficios`;

  els.offersBody.querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", () => {
      openOffer(state.filtered[Number(row.dataset.index)]);
    });
  });
}

function renderCardRequirements(requirements) {
  if (!requirements) return "N/D";
  const values = [
    ...(requirements.banks ?? []),
    ...(requirements.products ?? []),
    ...(requirements.brands ?? []),
    ...(requirements.tiers ?? []),
    ...(requirements.types ?? [])
  ];
  return values.length ? [...new Set(values)].join(", ") : "N/D";
}

function openOffer(offer) {
  els.dialogTitle.textContent = offer.merchant;
  els.dialogSubtitle.textContent = `${offer.bank} - ${offer._discountLabel} - ${offer.channel || "N/D"}`;

  const addresses = getLocations(offer)
    .map((location) => `
      <div>
        <strong>${escapeHtml(location.address || location.raw || "Direccion")}</strong>
        <p class="subtle">${escapeHtml([location.comuna, location.region].filter(Boolean).join(" - "))}</p>
      </div>
    `)
    .join("");
  const emptyAddressLabel = locationStatus(offer) === "multiple"
    ? "Cadena/franquicia: hay multiples direcciones, no se muestran individualmente."
    : "Sin direcciones detectadas.";

  els.dialogBody.innerHTML = `
    <div class="detailGrid">
      <div class="detailItem"><span>Descuento</span>${escapeHtml(offer._discountLabel)}</div>
      <div class="detailItem"><span>Dias</span>${escapeHtml(dayText(offer._days))}</div>
      <div class="detailItem"><span>Vigencia</span>${validLabel(offer)} ${escapeHtml(offer.valid_until || "N/D")}</div>
      <div class="detailItem"><span>Canal</span>${escapeHtml(offer.channel || "N/D")}</div>
      <div class="detailItem"><span>Tarjetas</span>${escapeHtml(renderCardRequirements(offer.card_requirements))}</div>
      <div class="detailItem"><span>Banco</span>${escapeHtml(offer.bank)}</div>
    </div>

    <section>
      <div class="sectionTitle">Direcciones</div>
      <div class="addressList">${addresses || `<div class="subtle">${escapeHtml(emptyAddressLabel)}</div>`}</div>
    </section>

    <section>
      <div class="sectionTitle">Condiciones</div>
      <div class="textBlock">${escapeHtml(offer.conditions || "Sin condiciones capturadas.")}</div>
    </section>

    <section>
      <div class="sectionTitle">Detalle fuente</div>
      <div class="textBlock">${escapeHtml(offer.raw_title || "Sin detalle.")}</div>
    </section>

    <section>
      <div class="sectionTitle">Link original</div>
      <a href="${escapeAttribute(offer.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(offer.source_url)}</a>
    </section>
  `;

  els.dialog.showModal();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

for (const input of [
  els.searchInput,
  els.bankFilter,
  els.dayFilter,
  els.discountFilter,
  els.regionFilter,
  els.comunaFilter,
  els.todayFilter,
  els.validFilter
]) {
  input.addEventListener("input", applyFilters);
  input.addEventListener("change", applyFilters);
}

for (const button of els.sortButtons) {
  button.addEventListener("click", () => {
    const key = button.dataset.sort;
    if (state.sort.key === key) {
      state.sort.direction = state.sort.direction === "asc" ? "desc" : "asc";
    } else {
      state.sort.key = key;
      state.sort.direction = key === "discount" || key === "validUntil" ? "desc" : "asc";
    }
    sortFiltered();
    renderTable();
  });
}

els.todayFilter.addEventListener("change", () => {
  els.dayFilter.disabled = els.todayFilter.checked;
});

els.refreshButton.addEventListener("click", loadData);
els.closeDialog.addEventListener("click", () => els.dialog.close());
els.dialog.addEventListener("click", (event) => {
  if (event.target === els.dialog) {
    els.dialog.close();
  }
});

loadData().catch((error) => {
  console.error(error);
  els.summary.textContent = "No se pudieron cargar los beneficios.";
});
