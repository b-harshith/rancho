// RanchoLabs market research explorer - Frontend controller

function isUnlocked() {
  // Detailed evidence is delivered only after the server validates the signed
  // portal session. Legacy partial-lock call sites therefore stay unlocked.
  return true;
}

function updateUnlockUi() {}
function openUnlockModal() {}
function closeUnlockModal() {}
function submitUnlockCode() {}

function checkMapZoomLock() {
  if (!map) return;
  const canvas = document.getElementById('leaflet-map-canvas');
  if (canvas) canvas.classList.remove('blurred-item');
}

window.openUnlockModal = openUnlockModal;
window.closeUnlockModal = closeUnlockModal;
window.submitUnlockCode = submitUnlockCode;
window.checkMapZoomLock = checkMapZoomLock;
window.isUnlocked = isUnlocked;
window.updateUnlockUi = updateUnlockUi;

let map;
let landingPreviewMap = null;
let baseLayers = {};
let overlayLayers = {};
let layerData = {};
let totalSelectedCityTam = 157073; // Dynamically computed for the selected city, fallback
let rawLocalityRecordCount = 0;
const SIDEBAR_STORAGE_KEY = 'rl_sidebar_width_v2';
const SIDEBAR_MIN_WIDTH = 520;
const SIDEBAR_MAX_WIDTH = 820;
const DEFAULT_SIDEBAR_WIDTH = 640;
const MAP_SEARCH_ZOOM = 14;
const LEGACY_CITY_ORDER = ['delhi_ncr', 'bengaluru', 'hyderabad', 'mumbai'];
const LEGACY_CITY_LABELS = {
  delhi_ncr: 'Delhi NCR',
  bengaluru: 'Bengaluru',
  hyderabad: 'Hyderabad',
  mumbai: 'Mumbai'
};
const LEGACY_CITY_ALIASES = {
  delhi: 'delhi_ncr',
  delhi_ncr: 'delhi_ncr',
  'delhi-ncr': 'delhi_ncr',
  ncr: 'delhi_ncr',
  bangalore: 'bengaluru',
  bengaluru: 'bengaluru',
  hyderabad: 'hyderabad',
  mumbai: 'mumbai'
};
const LEGACY_CITY_CENTERS = {
  delhi_ncr: { lat: 28.6139, lon: 77.2090, zoom: 8 },
  bengaluru: { lat: 12.9716, lon: 77.5946, zoom: 11 },
  hyderabad: { lat: 17.3850, lon: 78.4867, zoom: 10 },
  mumbai: { lat: 19.0760, lon: 72.8777, zoom: 10 }
};
const LEGACY_CITY_SEARCH_VIEWBOXES = {
  delhi_ncr: '76.70,29.05,77.75,28.20',
  bengaluru: '77.25,13.25,77.90,12.70',
  hyderabad: '78.10,17.75,78.85,17.05',
  mumbai: '72.72,19.35,73.15,18.85'
};
const LEGACY_DEFAULT_CATEGORY = 'premium_plus';
const LEGACY_CATEGORY_IDS = [
  'premium_plus',
  'super_premium',
  'premium',
  'affordable_plus',
  'affordable',
  'budget',
  'all_private'
];

// Active state tracking
let activeTab = 'summary';
let activeLegacyCityId = normalizeLegacyCityId(new URLSearchParams(window.location.search).get('city')) || 'bengaluru';
const initialLegacyCategoryId = new URLSearchParams(window.location.search).get('category');
let activeLegacyCategoryId = LEGACY_CATEGORY_IDS.includes(initialLegacyCategoryId)
  ? initialLegacyCategoryId
  : LEGACY_DEFAULT_CATEGORY;
let activeHexCoverageMode = activeLegacyCityId === 'bengaluru' ? 'all' : 'priority';
let selectedZone = null;
let zoneQuickFilter = 'all';
let zoneSearchTerm = '';
let marketSearchTerm = '';
let schoolPartnershipSort = 'reported';
let formulasDrawerReturnFocus = null;
let selectedMarket = null;
let catchmentMarker = null;
let catchmentCircle = null;
let catchmentPolygonLayer = null;
let catchmentIsochroneLayers = {};
let catchmentModeEnabled = false;

// Enhanced Active state tracking and lookup cache
let activePoiMarker = null;
let activeCatchmentData = null;
const SCHOOL_SUBQUARTILES = [
  { key: 'Q4-Sub-Q4', label: 'Ultra Luxury', color: '#7c3aed' },
  { key: 'Q4-Sub-Q3', label: 'Super Luxury', color: '#2563eb' },
  { key: 'Q4-Sub-Q2', label: 'Elite Luxury', color: '#0891b2' },
  { key: 'Q4-Sub-Q1', label: 'Premium Elite', color: '#0f766e' }
];
let schoolMarketState = {
  available: false,
  entities: [],
  campuses: [],
  summary: null,
  audit: null,
  mode: 'q4',
  cutoff: 200000,
  captureRate: 1,
  selectedZone: null,
  selectedMarketIndex: null,
  selectedHexId: null,
  selectedCampusId: null,
  allHeatLayer: null,
  q4ContextLayer: null,
  audienceMarkerLayer: null,
  directoryFocusLayer: null,
  isochroneLayer: null,
  evaluationData: null,
  evaluationMinutes: 30,
  evaluationRequestId: 0,
  portfolioCenters: [],
  portfolioResult: null,
  portfolioLoading: false
};
let schoolDirectoryState = {
  query: '',
  audienceOnly: false,
  sort: 'name',
  page: 1,
  pageSize: 50
};
let schoolEntitiesByCampusLookup = new Map();
let societyLookup = new Map();
let hospitalLookup = new Map();
let landingSlideIndex = 0;
let commercialListings = [];
let rankedCommercialListings = [];
let selectedCommercialListing = null;
let commercialMarkersLayer = null;
let commercialIsochroneLayer = null;
let commercialComparisonSet = new Set();
let commercialCustomCounter = 1;
let commercialSearchMarker = null;
let commercialDraftMarker = null;
let commercialLocationPickMode = false;
let commercialListingFilterTerm = '';
let mapSearchMarker = null;
let mapSearchHalo = null;
let mapSearchSuggestions = [];
let mapSearchActiveSuggestionIndex = -1;
let mapSearchAutocompleteTimer = null;
let mapSearchAutocompleteSequence = 0;
let activeBasemap = 'light';
let boundaryOverlayNeedsRefresh = false;
let overviewLayerControlsInitialized = false;
let activeBoundaryTypeFilter = 'both'; // both, zone, sez
let commuteRouteLayer = null;
const ONBOARDING_STORAGE_KEY = 'rl_onboarding_seen_v2';
const EMPTY_COMMUTE_SCORES = { by_hex: {}, by_zone: {} };
let hexLayerLookup = new Map();
let hexesAreHighlighted = false;
let hexHighlightEnabled = true;
let tooltipsBound = null;
let activeDetailsData = {
  zone: { societies: [], hospitals: [], localities: [], offices: [] },
  market: { societies: [] },
  catchment: { societies: [], hospitals: [] },
  hex: { societies: [], hospitals: [], offices: [] }
};

// Zone Boundaries Polygons and Labels
let CENTRAL_LAT = (LEGACY_CITY_CENTERS[activeLegacyCityId] || LEGACY_CITY_CENTERS.bengaluru).lat;
let CENTRAL_LON = (LEGACY_CITY_CENTERS[activeLegacyCityId] || LEGACY_CITY_CENTERS.bengaluru).lon;
let zonePolygons = {};
let activeZoneLabelMarker = null;
let marketMarkersGroup = null;
let activeMarketLabelMarker = null;
let rolledUpAssetsLayer = null;
let rolledUpAssetsScope = null;
let areaSchoolContextLayer = null;
let areaSchoolContextCampuses = [];
let areaSchoolContextVisible = true;
let summaryQuartileMode = 'Q4';
let projectQuartileAssets = [];
let legacyCityHexLayer = null;
let legacyCityMarkerLayer = null;

let activeHexStyleMode = 'affluence';

// Color mapper for hexes based on Indigo-slate score
function getHexColor(score) {
  if (score >= 70) return '#312e81'; // Premium / Luxury Affluence (70+)
  if (score >= 55) return '#6366f1'; // Upper-Mid / Emerging (55-70)
  if (score >= 40) return '#a5b4fc'; // Mixed / Watchlist (40-55)
  return '#f1f5f9'; // Low Evidence (<40)
}

function getTierColor(tier) {
  switch(tier) {
    case "Premium / Luxury Affluence": return '#312e81';
    case "Upper-Mid / Emerging Affluence": return '#6366f1';
    case "Mixed / Watchlist": return '#a5b4fc';
    default: return '#f1f5f9';
  }
}

// Categorical colors for Louvain communities
function getLouvainColor(cid) {
  const colors = [
    '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', 
    '#14b8a6', '#f43f5e', '#06b6d4', '#6366f1', '#a855f7', 
    '#f97316', '#0ea5e9', '#64748b', '#84cc16', '#059669',
    '#4b5563'
  ];
  if (cid === undefined || cid === null || cid < 0) return '#94a3b8';
  return colors[cid % colors.length];
}

// Single-hue sequential blue gradient for PageRank (scaled x1000)
function getPageRankColor(pr) {
  const val = pr * 1000;
  if (val >= 9.0) return '#1e3a8a'; // Deepest blue
  if (val >= 7.5) return '#2563eb'; // Medium-dark blue
  if (val >= 6.0) return '#3b82f6'; // Notion Blue
  if (val >= 4.5) return '#60a5fa'; // Sky blue
  if (val >= 3.0) return '#93c5fd'; // Light sky blue
  if (val >= 1.5) return '#bfdbfe'; // Very light blue
  if (val >= 0.5) return '#eff6ff'; // Faint ice blue
  return '#f1f5f9'; // Low centrality / gray-white
}

function getHexFeatureStyle(feature) {
  const props = feature.properties;

  // Large feeds can contain more than a thousand occupied cells. Keep the
  // ranked decision surface readable while preserving a complete-view toggle.
  if (activeHexCoverageMode === 'priority') {
    const total = layerData.hexes?.features?.length || 0;
    const limit = Math.min(150, Math.max(40, Math.ceil(total * 0.25)));
    const rank = Number(props.rank || Number.MAX_SAFE_INTEGER);
    if (rank > limit) {
      return {
        fillColor: '#000000',
        color: '#000000',
        weight: 0,
        fillOpacity: 0,
        opacity: 0,
        interactive: false
      };
    }
  }
  
  // Apply Tier Filter
  if (activeHexTierFilter !== 'all') {
    if (props.affluence_tier !== activeHexTierFilter) {
      return {
        fillColor: '#000000',
        color: '#000000',
        weight: 0,
        fillOpacity: 0,
        opacity: 0,
        interactive: false
      };
    }
  }

  // Apply PageRank Filter
  if (activePageRankFilter !== 'all') {
    if (props.pagerank_node_type !== activePageRankFilter) {
      return {
        fillColor: '#000000',
        color: '#000000',
        weight: 0,
        fillOpacity: 0,
        opacity: 0,
        interactive: false
      };
    }
  }
  
  let fillColor = '#94a3b8';
  if (activeHexStyleMode === 'affluence') {
    fillColor = getHexColor(props.final_affluence_score);
  } else if (activeHexStyleMode === 'pagerank') {
    fillColor = getPageRankColor(props.pagerank_personalized);
  }
  
  return {
    fillColor: fillColor,
    color: '#ffffff',
    weight: 1,
    fillOpacity: hexHighlightEnabled ? 0.55 : 0,
    opacity: 1,
    interactive: true
  };
}

function refreshHexLayerStyles() {
  if (!overlayLayers.hexes) return;
  const opacity = parseFloat(document.getElementById('opacity-slider-hexes').value);
  
  overlayLayers.hexes.eachLayer(function (layer) {
    const style = getHexFeatureStyle(layer.feature);
    const finalFillOpacity = style.fillOpacity === 0 ? 0 : (hexHighlightEnabled ? opacity : 0);
    layer.setStyle({
      fillColor: style.fillColor,
      fillOpacity: finalFillOpacity,
      opacity: style.opacity,
      weight: style.weight,
      color: style.color
    });
    
    // Manage tooltips & click handlers dynamically based on visibility
    if (style.weight === 0) {
      layer.unbindTooltip();
      layer.off('click');
    } else {
      if (!layer.getTooltip() && layer._tooltipContent) {
        layer.bindTooltip(layer._tooltipContent, { sticky: true, opacity: 0.9 });
      }
      layer.off('click');
      layer.on('click', function(e) {
        if (commercialLocationPickMode) {
          setCommercialDraftLocation(layer.feature.properties.centroid_lat, layer.feature.properties.centroid_lon, 'Picked from hex center');
        } else if (catchmentModeEnabled) {
          onMapClick({ latlng: L.latLng(layer.feature.properties.centroid_lat, layer.feature.properties.centroid_lon) });
        } else {
          selectHex(layer.feature.properties, layer);
        }
      });
    }
  });
}
window.refreshHexLayerStyles = refreshHexLayerStyles;

function setLegacyHexCoverage(mode) {
  activeHexCoverageMode = mode === 'all' ? 'all' : 'priority';
  const selector = document.getElementById('legacy-hex-coverage-select');
  if (selector) selector.value = activeHexCoverageMode;
  const note = document.getElementById('legacy-hex-coverage-note');
  if (note) {
    const total = layerData.hexes?.features?.length || 0;
    const priority = Math.min(150, Math.max(40, Math.ceil(total * 0.25)));
    note.textContent = activeHexCoverageMode === 'all'
      ? `Showing all ${formatNumber(total)} occupied H3 cells.`
      : `Showing the top ${formatNumber(Math.min(priority, total))} ranked H3 cells; all ${formatNumber(total)} remain available.`;
  }
  refreshHexLayerStyles();
}
window.setLegacyHexCoverage = setLegacyHexCoverage;

function setHexHighlightEnabled(enabled) {
  hexHighlightEnabled = enabled;
  const toggleCatchmentEl = document.getElementById('toggle-hex-highlight-catchment');
  if (toggleCatchmentEl) {
    toggleCatchmentEl.checked = enabled;
  }
  refreshHexLayerStyles();
}
window.setHexHighlightEnabled = setHexHighlightEnabled;

function updateHexColoringMode(mode) {
  activeHexStyleMode = mode;
  refreshHexLayerStyles();
  updateMapLegend();
}

function updateMapLegend() {
  const legendEl = document.getElementById('hex-legend');
  if (!legendEl) return;
  
  if (activeHexStyleMode === 'affluence') {
    legendEl.innerHTML = `
      <div class="legend-title">Catchment context score</div>
      <div class="legend-scale">
        <div class="legend-row"><span class="legend-swatch" style="background: #312e81"></span> Premium / Luxury (70+)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #6366f1"></span> Upper-Mid / Emerging (55-70)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #a5b4fc"></span> Mixed / Watchlist (40-55)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #f1f5f9; border:1px solid #cbd5e1;"></span> Low Evidence (&lt;40)</div>
      </div>
    `;
  } else if (activeHexStyleMode === 'pagerank') {
    legendEl.innerHTML = `
      <div class="legend-title">PageRank Centrality</div>
      <div class="legend-scale">
        <div class="legend-row"><span class="legend-swatch" style="background: #1e3a8a"></span> Core Hub (PR &gt; 9.0)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #2563eb"></span> Gateway Hub (PR 7.5 - 9.0)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #3b82f6"></span> Connected Core (PR 6.0 - 7.5)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #60a5fa"></span> Intermediate Link (PR 4.5 - 6.0)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #93c5fd"></span> Peripheral Link (PR 3.0 - 4.5)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #bfdbfe"></span> Emerging Link (PR 1.5 - 3.0)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #eff6ff"></span> Minor Centrality (PR 0.5 - 1.5)</div>
        <div class="legend-row"><span class="legend-swatch" style="background: #f1f5f9; border:1px solid #cbd5e1;"></span> Isolated (&lt; 0.5)</div>
      </div>
    `;
  }
}

window.updateHexColoringMode = updateHexColoringMode;

function setTextIfExists(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function setHtmlIfExists(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.innerHTML = value;
  }
}

function formatNumberCompact(value, digits = 1) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return '0';
  return numeric.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits === 0 ? 0 : 0
  });
}

function statusClass(status) {
  return String(status || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function getCommuteByHexId(hexId) {
  return layerData.commute_scores?.by_hex?.[hexId] || null;
}

function getCommuteByZone(zoneName) {
  return layerData.commute_scores?.by_zone?.[zoneName] || layerData.client_summary?.commute?.zone_summary?.[zoneName] || null;
}

function getHexPropsById(hexId) {
  return layerData.hexes?.features?.find(feature => feature.properties?.hex_id === hexId)?.properties || null;
}

function sumQ3BelowForHexIds(hexIds = []) {
  return [...new Set(hexIds)].reduce((sum, hexId) => {
    const props = getHexPropsById(hexId);
    return sum + Number(props?.q3_and_below_property_count || 0);
  }, 0);
}

function summarizeCommuteForHexIds(hexIds = []) {
  const rows = [...new Set(hexIds)].map(getCommuteByHexId).filter(Boolean);
  if (!rows.length) return null;
  const avg = rows.reduce((sum, row) => sum + Number(row.score || 0), 0) / rows.length;
  const ranked = rows.slice().sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
  const components = {};
  rows.forEach(row => {
    Object.entries(row.components || {}).forEach(([key, value]) => {
      components[key] = (components[key] || 0) + Number(value || 0);
    });
  });
  Object.keys(components).forEach(key => {
    components[key] = Math.round((components[key] / rows.length) * 10) / 10;
  });
  return {
    score: Math.round(avg * 10) / 10,
    band: avg >= 80 ? 'Excellent commute convenience' : avg >= 65 ? 'Strong commute convenience' : avg >= 50 ? 'Moderate commute convenience' : 'Commute friction risk',
    components,
    evidence: {
      entry_exit_proxy_count: Math.round(rows.reduce((sum, row) => sum + Number(row.evidence?.entry_exit_proxy_count || 0), 0) / rows.length),
      best_hexes: ranked.slice(0, 3).map(row => ({ name: row.name, score: row.score })),
      weak_hexes: ranked.slice(-3).map(row => ({ name: row.name, score: row.score })).reverse(),
      traffic_caveat: 'Free OSM/OSRM-derived proxy; not live traffic.'
    }
  };
}

function renderCommuteSummary(targetId, commute) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!commute) {
    el.innerHTML = '<strong>Commute proxy unavailable.</strong> Run validation or select an area with matched H3 cells.';
    return;
  }
  const components = commute.components || {};
  const evidence = commute.evidence || {};
  const best = evidence.best_hexes || evidence.best_corridors || [];
  const hasComponents = Object.keys(components).length > 0;
  el.innerHTML = `
    <strong>${formatNumber(commute.score || commute.score_tam_weighted || 0, 1)} · ${escapeHTML(commute.band || 'Commute proxy')}</strong>
    <div>${escapeHTML(evidence.traffic_caveat || 'Free OSM/OSRM-derived commute-friction proxy; not live traffic.')}</div>
    ${hasComponents ? `<div class="commute-breakdown">
      <div><span>Directness</span><strong>${formatNumber(components.route_directness || 0, 0)}</strong></div>
      <div><span>Redundancy</span><strong>${formatNumber(components.network_redundancy || 0, 0)}</strong></div>
      <div><span>Chokepoint</span><strong>${formatNumber(components.chokepoint_risk_proxy || 0, 0)}</strong></div>
      <div><span>Transit relief</span><strong>${formatNumber(components.transit_relief || 0, 0)}</strong></div>
    </div>` : ''}
    ${best.length ? `<div style="margin-top:8px;">Best access signals: ${best.map(item => escapeHTML(item.name || item.hex_id || 'Route')).join(', ')}</div>` : ''}
  `;
}

function renderClientSummary() {
  const summary = layerData.client_summary;
  if (!summary) return;
  const hero = document.getElementById('client-summary-hero');
  if (hero) {
    const topHexes = (summary.category_hex_shortlists?.[activeLegacyCategoryId] || summary.top_hexes || [])
      .slice(0, 4)
      .map(item => item.name)
      .filter(Boolean);
    const topZones = (summary.top_zones || []).slice(0, 2).map(item => item.zone || item.name).filter(Boolean);
    const focus = topHexes.length
      ? topHexes.join(', ')
      : topZones.length
        ? topZones.join(' and ')
        : legacyCityLabel();
    const category = activeLegacyCategory();
    const cityScore = activeLegacyCitySummary()?.expansion_scores?.[activeLegacyCategoryId]?.weighted_score;
    const scoreCopy = cityScore == null ? '' : ` City evidence score: ${formatNumber(cityScore, 1)}.`;
    hero.innerHTML = `
      <strong>${escapeHTML(legacyCityLabel())} launch focus: validate ${escapeHTML(focus)} for ${escapeHTML(category.label)} demand, residential depth and live drive-time reach before selecting a center.${escapeHTML(scoreCopy)}</strong>
      <small>${escapeHTML(summary.coverage?.coverage_note || '')}</small>
    `;
  }

  const metrics = document.getElementById('client-summary-metrics');
  if (metrics) {
    const items = [
      ['Total projects', formatNumber(summary.executive_metrics?.total_projects)],
      ['Premium project units', formatNumber(summary.executive_metrics?.q4_total_units)],
      ['Final hexes', formatNumber(summary.coverage?.final_h3_hexes)],
      ['Active hexes', formatNumber(summary.coverage?.active_analysis_hexes)],
      ['Micro-markets', formatNumber(summary.executive_metrics?.micro_markets)]
    ];
    metrics.innerHTML = items.map(([label, value], idx) => {
      const isLocked = !isUnlocked() && idx > 0;
      const blurredClass = isLocked ? ' blurred-item' : '';
      const clickHandler = isLocked ? 'onclick="openUnlockModal()"' : '';
      return `
        <div class="client-summary-metric${blurredClass}" ${clickHandler} style="${isLocked ? 'cursor:pointer;' : ''}">
          <span>${label}</span>
          <strong>${value}</strong>
        </div>
      `;
    }).join('');
  }

  const quartiles = document.getElementById('client-summary-quartiles');
  if (quartiles) {
    const rows = (summary.quartile_breakdown || []).map(item => {
      const avgPrice = item.avg_price_per_sqft != null || item.avg_price != null
        ? `${formatCurrencyShort(item.avg_price_per_sqft ?? item.avg_price)}/sqft`
        : 'NA';
      return `
        <tr>
          <td><strong>${escapeHTML(item.quartile || '-')}</strong></td>
          <td class="num-col">${formatNumber(item.rows || 0)}</td>
          <td class="num-col">${formatNumber(item.units || 0)}</td>
          <td>${escapeHTML(avgPrice)}</td>
        </tr>
      `;
    }).join('');
    quartiles.innerHTML = rows || '<tr><td colspan="4">No quartile breakdown available.</td></tr>';
  }

  const projectTypes = document.getElementById('client-summary-project-types');
  if (projectTypes) {
    const rows = (summary.project_type_breakdown || []).map(item => `
      <tr>
        <td><strong>${escapeHTML(item.project_type || '-')}</strong></td>
        <td class="num-col">${formatNumber(item.count || 0)}</td>
        <td class="num-col">${escapeHTML((item.share_pct ?? 0).toFixed ? item.share_pct.toFixed(2) : String(item.share_pct || 0))}%</td>
      </tr>
    `).join('');
    projectTypes.innerHTML = rows || '<tr><td colspan="3">No project classification breakdown available.</td></tr>';
  }

  const summaryRollup = document.getElementById('client-summary-rollup-controls');
  if (summaryRollup) {
    summaryRollup.innerHTML = buildRolledUpAssetsControlsHtml('summary', true);
  }

  const renderRecommendations = (targetId, rows = []) => {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.innerHTML = rows.slice(0, 5).map((row, idx) => {
      const isLockedCard = !isUnlocked() && idx > 0; // bottom 4
      
      const rationaleText = isLockedCard ? 'Restricted recommended rationale' : row.rationale || '';
      const rationaleClass = isLockedCard ? ' blurred-item' : '';
      
      const shareClass = isLockedCard ? ' blurred-item' : '';
      const statusHtml = row.status && row.status.toLowerCase() !== 'launch now' 
        ? `<span class="status-chip ${statusClass(row.status)}">${escapeHTML(row.status)}</span>` 
        : '';
        
      const cardClick = isLockedCard ? 'onclick="openUnlockModal()"' : '';
      
      // Calculate offices count dynamically for zone cards; city cluster cards use score instead.
      let officesCount = 0;
      let schoolValidationHtml = '';
      let thirdMetricLabel = 'Score';
      let thirdMetricValue = formatNumber(row.score, 1);
      if (targetId === 'client-zone-recommendations') {
        officesCount = (layerData.sez_offices || []).filter(o => o.zone === row.name).length;
        thirdMetricLabel = 'Offices';
        thirdMetricValue = formatNumber(officesCount, 0);
        if (schoolMarketState?.entities?.length) {
          const peer = getStaticSchoolReadiness('zone').get(row.name);
          schoolValidationHtml = `<div class="recommendation-school-validation"><span>Separate validation evidence</span><strong>Tier ${peer?.tier || 'D'} · ${formatNumber(peer?.school || 0)} Premium+ entity-associated enrollment · ${formatNumber(peer?.residential || 0)} known residential units</strong></div>`;
        }
      }
      
      return `
        <article class="recommendation-card" ${cardClick} style="${isLockedCard ? 'cursor:pointer;' : ''}">
          <header>
            <div>
              <strong>${escapeHTML(row.name)}</strong>
              <p class="${rationaleClass}">${escapeHTML(rationaleText)}</p>
            </div>
            ${statusHtml}
          </header>
          <div class="recommendation-meta">
            <div><span>Known units</span><strong>${formatNumber(firstFiniteNumber(row.known_units, row.direct_total_units, row.units) || 0)}</strong></div>
            <div class="${shareClass}" ${isLockedCard ? 'onclick="event.stopPropagation(); openUnlockModal();"' : ''}>
              <span>Projects</span><strong>${formatNumber(firstFiniteNumber(row.residential_project_count, row.project_count, row.projects) || 0)}</strong>
            </div>
            <div class="${shareClass}" ${isLockedCard ? 'onclick="event.stopPropagation(); openUnlockModal();"' : ''}>
              <span>${escapeHTML(thirdMetricLabel)}</span><strong>${escapeHTML(thirdMetricValue)}</strong>
            </div>
          </div>
          ${schoolValidationHtml}
        </article>
      `;
    }).join('');
  };
  renderRecommendations('client-market-recommendations', summary.recommendations?.micro_markets || []);

  const validation = document.getElementById('client-validation-list');
  if (validation) {
    validation.innerHTML = (summary.validation?.checks || []).map(check => `
      <div class="validation-item">
        <div><span>${escapeHTML(check.status)}</span><strong>${escapeHTML(check.name)}</strong></div>
        <div>${escapeHTML(String(check.value))} / ${escapeHTML(String(check.expected))}</div>
      </div>
    `).join('');
  }

  const links = document.getElementById('client-handoff-links');
  if (links) {
    links.innerHTML = (summary.handoff_links || []).map(link => {
      const clickHandler = isUnlocked() ? '' : 'event.preventDefault(); openUnlockModal();';
      const href = isUnlocked() ? escapeHTML(link.href) : '#';
      const target = isUnlocked() ? 'target="_blank"' : '';
      const label = isUnlocked() ? 'Open' : 'Restricted';
      return `
        <a class="handoff-link" href="${href}" ${target} onclick="${clickHandler}" rel="noopener">
          <span>${escapeHTML(link.label)}</span>
          <strong>${label}</strong>
        </a>
      `;
    }).join('');
  }

  // Lazy-populate network KPIs from graph_network.json
  renderNetworkKPIs();
}

async function renderNetworkKPIs() {
  // Only run once
  if (document.getElementById('net-kpi-hubs')?.dataset.loaded === 'true') return;

  let graphData;
  try {
    const resp = await fetch(legacyDataResource('graph_network.json'));
    graphData = await resp.json();
  } catch (e) {
    return; // silently fail — not critical
  }

  const nodes = graphData.nodes || [];
  const hubs = nodes.filter(n => n.classification === 'Strategic Hub');
  const islands = nodes.filter(n => n.classification === 'Wealth Island');
  const topHub = hubs.sort((a, b) => b.pagerank_personalized - a.pagerank_personalized)[0];
  const communities = graphData.meta?.total_communities || graphData.communities?.length || 0;

  const setKpi = (id, val) => {
    const el = document.getElementById(id);
    if (el) { el.textContent = val; el.dataset.loaded = 'true'; }
  };
  setKpi('net-kpi-hubs', hubs.length);
  setKpi('net-kpi-islands', islands.length);
  setKpi('net-kpi-top-hub', topHub ? topHub.name.split('-')[0].split('/')[0].trim().slice(0, 14) : '—');
  setKpi('net-kpi-communities', communities);
  setKpi('graph-hero-hubs', hubs.length);
  setKpi('graph-hero-islands', islands.length);
  setKpi('graph-hero-clusters', communities);

  // Render hub mini-cards (top 8 hubs + top 3 wealth islands)
  const hubsRow = document.getElementById('hub-cards-row');
  if (!hubsRow) return;

  const topHubs = [...hubs].sort((a, b) => b.pagerank_personalized - a.pagerank_personalized).slice(0, 8);
  const topIslands = [...islands].sort((a, b) => a.rank_shift - b.rank_shift).slice(0, 3);

  const makeCard = (node, isIsland) => {
    const ppr = (node.pagerank_personalized * 1000).toFixed(1);
    const shift = node.rank_shift;
    const shiftStr = shift > 0 ? `+${shift} ▲` : shift < 0 ? `${shift} ▼` : '—';
    const shiftClass = shift > 0 ? 'rank-shift-up' : shift < 0 ? 'rank-shift-down' : 'rank-shift-stable';
    const badgeClass = isIsland ? 'island-badge' : 'hub-badge';
    const badgeText = isIsland ? 'Island' : 'Hub';
    const cardClass = isIsland ? 'hub-mini-card hub-island' : 'hub-mini-card';
    return `
      <div class="${cardClass}" onclick="switchTab('overview'); setTimeout(() => focusHexOnMap('${node.id}'), 50);" title="Click to focus on map: ${node.name}">
        <span class="hub-mc-name">${node.name.split('-')[0].trim()}</span>
        <div class="hub-mc-row"><span>PPR</span><strong>${ppr}</strong></div>
        <div class="hub-mc-row"><span>Shift</span><strong class="${shiftClass}">${shiftStr}</strong></div>
        <div class="hub-mc-row"><span>Aff.</span><strong>${node.affluence_score}</strong></div>
        <span class="hub-mc-badge ${badgeClass}">${badgeText}</span>
      </div>
    `;
  };

  hubsRow.innerHTML = topHubs.map(n => makeCard(n, false)).join('') +
    topIslands.map(n => makeCard(n, true)).join('');
}
window.renderNetworkKPIs = renderNetworkKPIs;


function getSidebarWidthPreference() {
  const stored = parseInt(localStorage.getItem(SIDEBAR_STORAGE_KEY) || '', 10);
  if (Number.isFinite(stored)) {
    return Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, stored));
  }
  return DEFAULT_SIDEBAR_WIDTH;
}

function applySidebarWidth(width, persist = true, invalidateMap = true) {
  const clamped = Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, Math.round(width)));
  document.documentElement.style.setProperty('--sidebar-width', `${clamped}px`);
  const sidebar = document.getElementById('app-sidebar');
  if (sidebar) {
    sidebar.style.width = `${clamped}px`;
  }
  if (persist) {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(clamped));
  }
  if (invalidateMap && map) {
    requestAnimationFrame(() => map.invalidateSize(false));
  }
  return clamped;
}

function initSidebarResize() {
  const handle = document.getElementById('sidebar-resize-handle');
  const sidebar = document.getElementById('app-sidebar');
  if (!handle || !sidebar) return;

  const initialWidth = getSidebarWidthPreference();
  applySidebarWidth(initialWidth, false);

  let startX = 0;
  let startWidth = initialWidth;
  let dragging = false;

  const onMove = event => {
    if (!dragging) return;
    const clientX = Number.isFinite(event.clientX) ? event.clientX : startX;
    const nextWidth = startWidth + (clientX - startX);
    applySidebarWidth(nextWidth, false, false);
  };

  const endDrag = event => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.classList.remove('sidebar-resizing');
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', endDrag);
    document.removeEventListener('pointercancel', endDrag);
    if (event && Number.isFinite(event.clientX)) {
      const finalWidth = startWidth + (event.clientX - startX);
      applySidebarWidth(finalWidth, true, true);
    } else {
      const currentWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width') || `${initialWidth}`, 10);
      applySidebarWidth(currentWidth, true, true);
    }
  };

  handle.addEventListener('pointerdown', event => {
    event.preventDefault();
    dragging = true;
    startX = event.clientX;
    startWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width') || `${initialWidth}`, 10) || initialWidth;
    handle.classList.add('dragging');
    document.body.classList.add('sidebar-resizing');
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', endDrag);
    document.addEventListener('pointercancel', endDrag);
  });

  window.addEventListener('resize', () => {
    const savedWidth = getSidebarWidthPreference();
    applySidebarWidth(savedWidth, false);
  });
}

const RIGHT_PANEL_MIN_WIDTH = 340;
const RIGHT_PANEL_MAX_WIDTH = 680;
const DEFAULT_RIGHT_PANEL_WIDTH = 420;
const RIGHT_PANEL_STORAGE_KEY = 'rancho_right_panel_width';

function getRightPanelWidthPreference() {
  const stored = parseInt(localStorage.getItem(RIGHT_PANEL_STORAGE_KEY) || '', 10);
  if (Number.isFinite(stored)) {
    return Math.max(RIGHT_PANEL_MIN_WIDTH, Math.min(RIGHT_PANEL_MAX_WIDTH, stored));
  }
  return DEFAULT_RIGHT_PANEL_WIDTH;
}

function applyRightPanelWidth(width, persist = true, invalidateMap = true) {
  const clamped = Math.max(RIGHT_PANEL_MIN_WIDTH, Math.min(RIGHT_PANEL_MAX_WIDTH, Math.round(width)));
  document.documentElement.style.setProperty('--right-panel-width', `${clamped}px`);
  const rightPanel = document.getElementById('app-right-panel');
  if (rightPanel) {
    rightPanel.style.width = `${clamped}px`;
  }
  if (persist) {
    localStorage.setItem(RIGHT_PANEL_STORAGE_KEY, String(clamped));
  }
  if (invalidateMap && map) {
    requestAnimationFrame(() => map.invalidateSize(false));
  }
  return clamped;
}

function initRightPanelResize() {
  const handle = document.getElementById('right-panel-resize-handle');
  const rightPanel = document.getElementById('app-right-panel');
  if (!handle || !rightPanel) return;

  const initialWidth = getRightPanelWidthPreference();
  applyRightPanelWidth(initialWidth, false);

  let startX = 0;
  let startWidth = initialWidth;
  let dragging = false;

  const onMove = event => {
    if (!dragging) return;
    const clientX = Number.isFinite(event.clientX) ? event.clientX : startX;
    const nextWidth = startWidth - (clientX - startX); // moving left increases width
    applyRightPanelWidth(nextWidth, false, false);
  };

  const endDrag = event => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.classList.remove('sidebar-resizing');
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', endDrag);
    document.removeEventListener('pointercancel', endDrag);
    if (event && Number.isFinite(event.clientX)) {
      const finalWidth = startWidth - (event.clientX - startX);
      applyRightPanelWidth(finalWidth, true, true);
    } else {
      const currentWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--right-panel-width') || `${initialWidth}`, 10);
      applyRightPanelWidth(currentWidth, true, true);
    }
  };

  handle.addEventListener('pointerdown', event => {
    event.preventDefault();
    dragging = true;
    startX = event.clientX;
    startWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--right-panel-width') || `${initialWidth}`, 10) || initialWidth;
    handle.classList.add('dragging');
    document.body.classList.add('sidebar-resizing');
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', endDrag);
    document.addEventListener('pointercancel', endDrag);
  });

  window.addEventListener('resize', () => {
    const savedWidth = getRightPanelWidthPreference();
    applyRightPanelWidth(savedWidth, false);
  });
}

function syncPanelVisibilityControls() {
  const sidebar = document.getElementById('app-sidebar');
  const rightPanel = document.getElementById('app-right-panel');
  const leftButton = document.getElementById('toggle-left-panel-btn');
  const rightButton = document.getElementById('toggle-right-panel-btn');

  const updateButton = (button, isOpen, side) => {
    if (!button) return;
    const isLeft = side === 'left';
    button.classList.toggle('is-open', isOpen);
    button.setAttribute('aria-pressed', String(isOpen));
    button.setAttribute('aria-label', `${isOpen ? 'Collapse' : 'Open'} ${side} panel`);
    button.title = `${isOpen ? 'Collapse' : 'Open'} ${side} panel`;
    const state = button.querySelector('small');
    if (state) state.textContent = isOpen ? 'Hide' : 'Show';
    const icon = button.querySelector('.panel-control-icon');
    if (icon) icon.textContent = isLeft ? (isOpen ? '‹' : '›') : (isOpen ? '›' : '‹');
  };

  updateButton(leftButton, !sidebar?.classList.contains('collapsed'), 'left');
  updateButton(rightButton, !rightPanel?.classList.contains('collapsed'), 'right');
}

function toggleLeftSidebar(open) {
  const sidebar = document.getElementById('app-sidebar');
  const expandBtn = document.getElementById('left-sidebar-expand-btn');
  const handle = document.getElementById('sidebar-resize-handle');
  if (!sidebar) return;

  if (open) {
    sidebar.classList.remove('collapsed');
    if (expandBtn) expandBtn.classList.add('hidden');
    if (handle) {
      handle.style.pointerEvents = 'auto';
      handle.style.opacity = '1';
    }
    localStorage.setItem('left_sidebar_collapsed', 'false');
  } else {
    sidebar.classList.add('collapsed');
    if (expandBtn) expandBtn.classList.remove('hidden');
    if (handle) {
      handle.style.pointerEvents = 'none';
      handle.style.opacity = '0';
    }
    localStorage.setItem('left_sidebar_collapsed', 'true');
  }
  syncPanelVisibilityControls();
  // Invalidate Leaflet map size cleanly after CSS transition completes
  const onTransitionEnd = (e) => {
    if (e.target !== sidebar) return;
    if (map) map.invalidateSize({ pan: false });
    sidebar.removeEventListener('transitionend', onTransitionEnd);
  };
  sidebar.addEventListener('transitionend', onTransitionEnd);
}

function toggleRightPanel(open) {
  const rightPanel = document.getElementById('app-right-panel');
  const expandBtn = document.getElementById('right-panel-expand-btn');
  const handle = document.getElementById('right-panel-resize-handle');
  if (!rightPanel) return;

  if (open) {
    rightPanel.classList.remove('collapsed');
    if (expandBtn) expandBtn.classList.add('hidden');
    if (handle) {
      handle.style.pointerEvents = 'auto';
      handle.style.opacity = '1';
    }
    localStorage.setItem('right_panel_collapsed', 'false');
  } else {
    rightPanel.classList.add('collapsed');
    if (expandBtn) expandBtn.classList.remove('hidden');
    if (handle) {
      handle.style.pointerEvents = 'none';
      handle.style.opacity = '0';
    }
    localStorage.setItem('right_panel_collapsed', 'true');
  }
  syncPanelVisibilityControls();
  // Invalidate Leaflet map size cleanly after CSS transition completes
  const onTransitionEnd = (e) => {
    if (e.target !== rightPanel) return;
    if (map) map.invalidateSize({ pan: false });
    rightPanel.removeEventListener('transitionend', onTransitionEnd);
  };
  rightPanel.addEventListener('transitionend', onTransitionEnd);
}

function showDetailsPanel(panelId) {
  const allPanels = [
    'zone-details-card',
    'market-details-card',
    'school-market-details-panel',
    'catchment-results-panel',
    'commercial-details-panel',
    'commercial-comparison-panel',
    'hex-details-card'
  ];

  allPanels.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      if (id === panelId) {
        el.classList.remove('hidden');
      } else {
        el.classList.add('hidden');
      }
    }
  });

  // Automatically expand right panel when showing details
  toggleRightPanel(true);
  updateRightPanelVisibility();
}

function updateRightPanelVisibility() {
  const zoneCard = document.getElementById('zone-details-card');
  const marketCard = document.getElementById('market-details-card');
  const schoolCard = document.getElementById('school-market-details-panel');
  const catchmentCard = document.getElementById('catchment-results-panel');
  const commercialCard = document.getElementById('commercial-details-panel');
  const commercialCompCard = document.getElementById('commercial-comparison-panel');
  const hexCard = document.getElementById('hex-details-card');
  const placeholder = document.getElementById('right-panel-placeholder');

  const zoneVisible = zoneCard && !zoneCard.classList.contains('hidden');
  const marketVisible = marketCard && !marketCard.classList.contains('hidden');
  const schoolVisible = schoolCard && !schoolCard.classList.contains('hidden');
  const catchmentVisible = catchmentCard && !catchmentCard.classList.contains('hidden');
  const commercialVisible = commercialCard && !commercialCard.classList.contains('hidden');
  const commercialCompVisible = commercialCompCard && !commercialCompCard.classList.contains('hidden');
  const hexVisible = hexCard && !hexCard.classList.contains('hidden');

  const anyDetailVisible = zoneVisible || marketVisible || schoolVisible || catchmentVisible || commercialVisible || commercialCompVisible || hexVisible;

  if (anyDetailVisible) {
    if (placeholder) placeholder.style.display = 'none';
  } else {
    if (placeholder) placeholder.style.display = 'flex';
  }
}

function runWhenIdle(callback) {
  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(callback, { timeout: 1500 });
  } else {
    window.setTimeout(callback, 0);
  }
}

async function fetchJsonResource(url, fallback, optional = false) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`${url} returned HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    if (!optional) throw error;
    console.warn(`Optional data unavailable: ${url}`, error);
    return fallback;
  }
}

function legacyDataResource(filename) {
  return activeLegacyCityId === 'bengaluru'
    ? `data/${filename}`
    : `data/city_legacy/${activeLegacyCityId}/${filename}`;
}

function legacySchoolDataResource(filename) {
  return `data/city_legacy/${activeLegacyCityId}/${filename}`;
}

function generatedLegacyDataResource(filename) {
  return `data/city_legacy/${activeLegacyCityId}/${filename}`;
}

function enrichLegacyReportWithGeneratedRollups(report, generatedReport) {
  if (!report?.zones || !generatedReport?.zones || report === generatedReport) return report;
  const generatedZones = generatedReport.zones || {};
  Object.entries(report.zones).forEach(([zoneName, zone]) => {
    const generatedZone = generatedZones[zoneName];
    if (!generatedZone) return;
    [
      'school_count',
      'students_grade_2_9',
      'premium_plus_students_grade_2_9',
      'top_score',
      'top_10_avg_score'
    ].forEach(key => {
      if ((zone[key] == null || Number(zone[key] || 0) === 0) && generatedZone[key] != null) {
        zone[key] = generatedZone[key];
      }
    });
  });
  return report;
}

function normalizeLegacyCityId(value) {
  const key = String(value || '').trim().toLowerCase().replace(/\s+/g, '_');
  return LEGACY_CITY_ALIASES[key] || null;
}

function legacyCityLabel(cityId = activeLegacyCityId) {
  return LEGACY_CITY_LABELS[cityId] || 'Bengaluru';
}

function isLegacyBengaluru() {
  return activeLegacyCityId === 'bengaluru';
}

function activeLegacyCategory() {
  const manifestCategory = layerData.multicity?.manifest?.categories?.find(item => item.id === activeLegacyCategoryId);
  return manifestCategory || { id: activeLegacyCategoryId, label: 'Premium + Super-Premium' };
}

function activeLegacyCitySummary() {
  return (layerData.multicity?.comparison?.cities || [])
    .find(city => city.canonical_city_id === activeLegacyCityId) || null;
}

function activeLegacyCityMeta() {
  return (layerData.multicity?.manifest?.cities || [])
    .find(city => city.canonical_city_id === activeLegacyCityId) || null;
}

async function activeLegacyCityDetail() {
  const cache = layerData.multicity?.details;
  if (!cache) return null;
  if (!cache.has(activeLegacyCityId)) {
    const meta = activeLegacyCityMeta();
    const path = meta?.detail_path || `cities/${activeLegacyCityId}.json`;
    cache.set(activeLegacyCityId, await fetchJsonResource(`data/multicity/${path}`, null, true));
  }
  return cache.get(activeLegacyCityId);
}

function firstFiniteNumber(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}

function decisionSupportList(detail, key) {
  const raw = detail?.decision_support?.[key];
  if (Array.isArray(raw)) return raw;
  if (!raw || typeof raw !== 'object') return [];
  const categoryRows = raw[activeLegacyCategoryId] || raw.rows || raw.items || raw.targets;
  return Array.isArray(categoryRows) ? categoryRows : [];
}

function reportedGrade29Value(row = {}) {
  const explicit = firstFiniteNumber(
    row.reported_students_grade_2_9,
    row.reported_grade_2_9_students,
    row.students_grade_2_9_reported,
    row.reported_enrollment_grade_2_9,
    row.metrics?.reported_students_grade_2_9,
    row.category_metrics?.[activeLegacyCategoryId]?.reported_students_grade_2_9
  );
  if (explicit !== null) return explicit;
  const source = String(row.enrollment_source || row.source_type || '').toLowerCase();
  if (source && !source.includes('estimat') && !source.includes('model')) {
    return firstFiniteNumber(row.students_grades_2_9, row.students_grade_2_9) || 0;
  }
  return 0;
}

function modeledGrade29Value(row = {}) {
  return firstFiniteNumber(
    row.modeled_students_grade_2_9,
    row.estimated_students_grade_2_9,
    row.students_grade_2_9_modeled,
    row.metrics?.modeled_students_grade_2_9
  ) || 0;
}

function activeDecisionMetrics(detail) {
  const comparison = activeLegacyCitySummary();
  const metrics = detail?.category_metrics?.[activeLegacyCategoryId]
    || comparison?.category_metrics?.[activeLegacyCategoryId]
    || {};
  const sourceBreakdown = schoolMarketState.summary?.bucket_summaries?.[activeLegacyCategoryId]?.students_grades_2_9_by_source
    || schoolMarketState.summary?.q4?.students_grades_2_9_by_source
    || {};
  const reportedGrade29 = firstFiniteNumber(
    metrics.reported_students_grade_2_9,
    metrics.reported_grade_2_9_students,
    metrics.students_grade_2_9_reported,
    sourceBreakdown.reported,
    sourceBreakdown.udise_backed
  ) || 0;
  const reportedTotal = firstFiniteNumber(
    metrics.reported_enrollment_total,
    metrics.reported_total_enrollment,
    metrics.enrollment_total
  ) || 0;
  const modeled = firstFiniteNumber(
    metrics.modeled_students_grade_2_9,
    metrics.estimated_students_grade_2_9,
    sourceBreakdown.modeled,
    sourceBreakdown.estimated
  ) || 0;
  return { metrics, reportedTotal, reportedGrade29, modeled };
}

function normalizedSchoolPartners(detail) {
  const supplied = decisionSupportList(detail, 'priority_school_partners');
  const sourceRows = activeLegacyCategoryId === LEGACY_DEFAULT_CATEGORY && supplied.length
    ? supplied
    : getSchoolAudienceEntities();
  return sourceRows.map((row, index) => ({
    id: row.school_entity_id || row.entity_id || row.campus_id || `school-${index}`,
    campusId: row.campus_id || row.school_campus_id || '',
    name: row.school_name || row.name || row.label || 'Unnamed school',
    area: row.area || row.locality || row.zone || row.geography_label || 'Area unavailable',
    board: Array.isArray(row.boards || row.board) ? (row.boards || row.board).join(', ') : (row.boards || row.board || 'Not reported'),
    reported: reportedGrade29Value(row),
    modeled: modeledGrade29Value(row),
    source: row.enrollment_source || row.evidence_basis || row.source_type || '',
    url: row.url || row.source_url || '',
    lat: firstFiniteNumber(row.lat, row.latitude, row.centroid_lat),
    lon: firstFiniteNumber(row.lon, row.lng, row.longitude, row.centroid_lon)
  })).filter(row => row.reported > 0 || supplied.length).sort((a, b) => b.reported - a.reported || a.name.localeCompare(b.name));
}

function normalizedResidentialTargets(detail) {
  const supplied = decisionSupportList(detail, 'residential_project_targets');
  const sourceRows = supplied.length ? supplied : (layerData.societies || []);
  return sourceRows.map((row, index) => ({
    id: row.project_id || row.id || `project-${index}`,
    name: row.project_name || row.name || row.label || 'Unnamed residential project',
    area: row.area || row.locality || row.zone || row.geography_label || 'Area unavailable',
    positioning: row.positioning || row.category || row.q4_segment || row.quartile || row.project_type || 'Not classified',
    units: firstFiniteNumber(row.known_units, row.residential_units, row.units, row.total_units),
    url: row.url || row.source_url || '',
    lat: firstFiniteNumber(row.lat, row.latitude, row.centroid_lat),
    lon: firstFiniteNumber(row.lon, row.lng, row.longitude, row.centroid_lon)
  })).sort((a, b) => (b.units || -1) - (a.units || -1) || a.name.localeCompare(b.name));
}

function normalizedCandidateCatchments(detail) {
  const supplied = decisionSupportList(detail, 'candidate_catchments');
  const categoryCells = detail?.geographies?.h3_cells || [];
  const sourceRows = activeLegacyCategoryId === LEGACY_DEFAULT_CATEGORY && supplied.length
    ? supplied
    : categoryCells;
  return sourceRows.map((row, index) => {
    const categoryMetric = row.category_metrics?.[activeLegacyCategoryId] || row.metrics || {};
    return {
      id: row.catchment_id || row.hex_id || row.id || `catchment-${index}`,
      name: row.catchment_name || row.name || row.label || row.locality || row.id || 'Unnamed catchment',
      reported: firstFiniteNumber(
        row.reported_students_grade_2_9,
        row.reported_grade_2_9_students,
        categoryMetric.reported_students_grade_2_9,
        categoryMetric.reported_grade_2_9_students
      ) || 0,
      schools: firstFiniteNumber(row.school_count, row.priority_school_count, categoryMetric.school_count) || 0,
      residentialTargets: firstFiniteNumber(row.residential_project_count, row.residential_targets, row.project_count, row.context?.residential_project_count) || 0,
      overlap: row.overlap_note || row.overlap_status || row.next_step || row.action || 'Validate drive time and overlap',
      lat: firstFiniteNumber(row.lat, row.latitude, row.centroid_lat, row.center?.latitude),
      lon: firstFiniteNumber(row.lon, row.lng, row.longitude, row.centroid_lon, row.center?.longitude)
    };
  }).sort((a, b) => b.reported - a.reported || b.schools - a.schools || a.name.localeCompare(b.name));
}

function decisionActionButton(row, kind, label = 'View on map') {
  const hasPoint = row.lat !== null && row.lon !== null;
  const actionLabel = hasPoint ? label : (kind === 'catchment' ? 'Open catchments' : kind === 'school' ? 'Open School Market' : 'Review target');
  return `<button class="decision-focus-btn" data-kind="${escapeHTML(kind)}" data-id="${escapeHTML(String(row.campusId || row.id || ''))}"${hasPoint ? ` data-lat="${row.lat}" data-lon="${row.lon}"` : ''} type="button">${escapeHTML(actionLabel)}</button>`;
}

function renderDecisionCatchmentRows(rows, targetIds = []) {
  const html = rows.slice(0, 6).map((row, index) => `
    <tr>
      <td><span class="decision-priority">${index + 1}</span></td>
      <td><strong>${escapeHTML(row.name)}</strong></td>
      <td class="num-col"><strong>${formatNumber(row.reported)}</strong></td>
      <td class="num-col">${formatNumber(row.schools)}</td>
      <td class="num-col">${formatNumber(row.residentialTargets)}</td>
      <td><span class="decision-next-step">${escapeHTML(row.overlap)}</span>${decisionActionButton(row, 'catchment')}</td>
    </tr>`).join('') || '<tr><td colspan="6" class="decision-empty">No catchment shortlist is available for this city and bucket.</td></tr>';
  targetIds.forEach(id => {
    const target = document.getElementById(id);
    if (target) target.innerHTML = html;
  });
}

function renderSchoolPartnershipTargets(detail) {
  let rows = normalizedSchoolPartners(detail);
  if (schoolPartnershipSort === 'name') rows = rows.slice().sort((a, b) => a.name.localeCompare(b.name));
  if (schoolPartnershipSort === 'area') rows = rows.slice().sort((a, b) => a.area.localeCompare(b.area) || b.reported - a.reported);
  const summaryRows = rows.slice(0, 5).map(row => `
    <tr><td><strong>${escapeHTML(row.name)}</strong></td><td>${escapeHTML(row.area)}</td><td class="num-col"><strong>${formatNumber(row.reported)}</strong></td><td>${row.modeled ? `<span class="modeled-evidence">+${formatNumber(row.modeled)} modeled separately</span>` : '<span class="reported-evidence">Reported source row</span>'}</td><td>${decisionActionButton(row, 'school')}</td></tr>`).join('');
  const detailRows = rows.slice(0, 25).map(row => `
    <tr><td><strong>${escapeHTML(row.name)}</strong></td><td>${escapeHTML(row.area)}</td><td>${escapeHTML(row.board)}</td><td class="num-col"><strong>${formatNumber(row.reported)}</strong></td><td>${row.modeled ? `<span class="modeled-evidence">${formatNumber(row.modeled)} modeled addition</span>` : '<span class="reported-evidence">Reported</span>'}</td><td>${decisionActionButton(row, 'school')}</td></tr>`).join('');
  const summaryTarget = document.getElementById('decision-school-partners-body');
  if (summaryTarget) summaryTarget.innerHTML = summaryRows || `<tr><td colspan="5" class="decision-empty">No directly reported ${escapeHTML(activeLegacyCategory().label)} school partner rows are available.</td></tr>`;
  const detailTarget = document.getElementById('school-partnership-targets-body');
  if (detailTarget) detailTarget.innerHTML = detailRows || `<tr><td colspan="6" class="decision-empty">No directly reported ${escapeHTML(activeLegacyCategory().label)} school partner rows are available.</td></tr>`;
}

function renderResidentialTargets(detail) {
  const rows = normalizedResidentialTargets(detail);
  const target = document.getElementById('decision-residential-targets-body');
  if (!target) return;
  target.innerHTML = rows.slice(0, 8).map(row => `
    <tr><td><strong>${escapeHTML(row.name)}</strong></td><td>${escapeHTML(row.area)}</td><td>${escapeHTML(row.positioning)}</td><td class="num-col">${row.units === null ? 'Unavailable' : formatNumber(row.units)}</td><td>${decisionActionButton(row, 'residential')}</td></tr>`).join('') || '<tr><td colspan="5" class="decision-empty">No named residential-project targets are available.</td></tr>';
}

function renderCampusScenarios(reported, detail) {
  const target = document.getElementById('decision-campus-scenarios');
  if (!target) return;
  const supplied = activeLegacyCategoryId === LEGACY_DEFAULT_CATEGORY
    ? decisionSupportList(detail, 'campus_scenarios')
    : [];
  const scenarios = [1, 2, 3].map(rate => {
    const suppliedRow = supplied.find(row => Number(row.capture_rate_pct ?? row.capture_rate) === rate || Number(row.capture_rate) === rate / 100) || {};
    const captured = firstFiniteNumber(suppliedRow.captured_students, suppliedRow.captured_demand) ?? (reported * rate / 100);
    const campuses = firstFiniteNumber(suppliedRow.campuses_supported, suppliedRow.campuses, suppliedRow.centers_supported, suppliedRow.minimum_centers_required) ?? (reported > 0 ? Math.floor(captured / (200 * 0.8)) : 0);
    return { rate, captured, campuses };
  });
  target.innerHTML = scenarios.map(row => `
    <article><span>${row.rate}% capture</span><strong>${reported > 0 ? formatNumber(row.campuses) : 'Unavailable'}</strong><small>${reported > 0 ? `${formatNumber(row.captured)} students · fully supported campuses at 160 occupied seats each` : 'Reported enrollment required'}</small></article>`).join('');
}

async function renderClientDecisionBrief(detail = null) {
  const cityDetail = detail || await activeLegacyCityDetail();
  if (!cityDetail) return;
  const { metrics, reportedTotal, reportedGrade29, modeled } = activeDecisionMetrics(cityDetail);
  const catchments = normalizedCandidateCatchments(cityDetail);
  const partners = normalizedSchoolPartners(cityDetail);
  const residential = normalizedResidentialTargets(cityDetail);
  const campusLow = reportedGrade29 > 0 ? Math.floor((reportedGrade29 * 0.01) / 160) : null;
  const campusHigh = reportedGrade29 > 0 ? Math.floor((reportedGrade29 * 0.03) / 160) : null;
  const target = document.getElementById('client-decision-metrics');
  if (target) target.innerHTML = `
    <article class="decision-question-card posture"><span>Decision basis</span><strong>Direct evidence first</strong><small>Compare source-reported ${escapeHTML(activeLegacyCategory().label)} enrollment before local validation and operating scenarios.</small></article>
    <article class="decision-question-card"><span>First catchment to validate</span><strong>${escapeHTML(catchments[0]?.name || 'Unavailable')}</strong><small>${catchments[0] ? `${formatNumber(catchments[0].reported)} reported students · ${formatNumber(catchments[0].schools)} schools` : 'Awaiting catchment evidence'}</small></article>
    <article class="decision-question-card"><span>Named outreach targets</span><strong>${formatNumber(partners.length)} schools</strong><small>${formatNumber(residential.length)} residential projects available for prioritization</small></article>
    <article class="decision-question-card"><span>Campus scenario range</span><strong>${campusLow === null ? 'Unavailable' : `${formatNumber(campusLow)}–${formatNumber(campusHigh)}`}</strong><small>1%–3% of reported demand · 200 seats · 80% utilization</small></article>`;
  const postureNote = target?.querySelector('.decision-question-card.posture small');
  if (postureNote) postureNote.textContent = `Priority order follows source-reported ${activeLegacyCategory().label} enrollment`;
  renderDecisionCatchmentRows(catchments, ['decision-catchments-body', 'candidate-catchments-body']);
  renderSchoolPartnershipTargets(cityDetail);
  renderResidentialTargets(cityDetail);
  renderCampusScenarios(reportedGrade29, cityDetail);
  const contextTarget = document.getElementById('methodology-live-context');
  if (contextTarget) {
    const sourceDate = cityDetail.decision_support?.evidence_policy?.source_observation_as_of || cityDetail.quality?.source_as_of || cityDetail.source_as_of || 'not supplied';
    contextTarget.textContent = `Current view: ${legacyCityLabel()} · ${activeLegacyCategory().label}. Source/as-of: ${sourceDate}. Source-reported enrollment: ${reportedTotal ? formatNumber(reportedTotal) : 'unavailable'}; derived reported Grade 2–9: ${reportedGrade29 ? formatNumber(reportedGrade29) : 'unavailable'}; modeled addition: ${modeled ? formatNumber(modeled) : 'none shown'}.`;
  }
}

function focusDecisionTarget(button) {
  const kind = button?.dataset?.kind || '';
  const lat = Number(button?.dataset?.lat);
  const lon = Number(button?.dataset?.lon);
  if (kind === 'school') switchTab('schoolmarket');
  else if (kind === 'catchment') switchTab('zones');
  else if (kind === 'residential') switchTab('overview');
  const campusId = button?.dataset?.id;
  if (kind === 'school' && campusId && typeof showSchoolCampusDetails === 'function') {
    showSchoolCampusDetails(campusId);
  }
  if (map && Number.isFinite(lat) && Number.isFinite(lon)) {
    map.flyTo([lat, lon], Math.max(map.getZoom(), 13), { duration: 0.65 });
  }
}

window.focusDecisionTarget = focusDecisionTarget;

async function activeLegacyCityHexes() {
  const cache = layerData.multicity?.hexes;
  if (!cache) return null;
  const key = `${activeLegacyCityId}:${activeLegacyCategoryId}`;
  if (!cache.has(key)) {
    cache.set(key, await fetchJsonResource(`data/multicity/hexes/${activeLegacyCityId}__${activeLegacyCategoryId}.geojson`, null, true));
  }
  return cache.get(key);
}

function activeLegacyCityMap() {
  const meta = activeLegacyCityMeta();
  const fallback = LEGACY_CITY_CENTERS[activeLegacyCityId] || LEGACY_CITY_CENTERS.bengaluru;
  return {
    center: meta?.map?.center
      ? { lat: meta.map.center.latitude, lon: meta.map.center.longitude }
      : { lat: fallback.lat, lon: fallback.lon },
    bounds: meta?.map?.bounds || null,
    zoom: meta?.map?.zoom || fallback.zoom
  };
}

function activeLegacyCitySearchViewbox() {
  return LEGACY_CITY_SEARCH_VIEWBOXES[activeLegacyCityId] || LEGACY_CITY_SEARCH_VIEWBOXES.bengaluru;
}

function updateLegacyCityUrl() {
  if (!window.history?.replaceState) return;
  const url = new URL(window.location.href);
  url.searchParams.set('city', activeLegacyCityId);
  url.searchParams.set('category', activeLegacyCategoryId);
  url.searchParams.delete('school_fee');
  url.searchParams.delete('school_view');
  window.history.replaceState({}, '', url);
}

function setTextIfPresent(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value;
}

function renderLegacyCityOverview() {
  const target = document.getElementById('legacy-city-overview');
  if (!target) return;
  const summary = activeLegacyCitySummary();
  const category = activeLegacyCategory();
  if (!summary) {
    target.innerHTML = '<div class="legacy-unavailable-banner"><strong>Multi-city evidence unavailable</strong><span>Rebuild the generated city artifacts to populate this deep dive.</span></div>';
    return;
  }
  const metrics = summary.category_metrics?.[activeLegacyCategoryId] || {};
  const context = summary.context_layers || {};
  const reportedTotal = firstFiniteNumber(metrics.reported_enrollment_total, metrics.reported_total_enrollment, metrics.enrollment_total) || 0;
  const reportedGrade29 = firstFiniteNumber(metrics.reported_students_grade_2_9, metrics.reported_grade_2_9_students) || 0;
  const modeled = firstFiniteNumber(metrics.modeled_students_grade_2_9, metrics.estimated_students_grade_2_9) || 0;
  const rankText = 'Direct evidence view';
  target.innerHTML = `
    <div class="legacy-city-overview-header">
      <div>
        <h3>${escapeHTML(summary.city_label || legacyCityLabel())} market evidence</h3>
        <p>${escapeHTML(category.label)} school demand, named partnership targets, and residential projects. Reported enrollment is the primary decision anchor.</p>
      </div>
      <span class="legacy-city-pill">${escapeHTML(rankText)}</span>
    </div>
    <div class="legacy-city-grid">
      <article><span>Schools</span><strong>${formatNumber(metrics.school_count || 0)}</strong><small>${escapeHTML(category.label)}</small></article>
      <article class="primary"><span>Source-reported enrollment</span><strong>${reportedTotal ? formatNumber(reportedTotal) : 'Unavailable'}</strong><small>Primary city-ranking demand input</small></article>
      <article><span>Derived reported Grade 2–9</span><strong>${reportedGrade29 ? formatNumber(reportedGrade29) : 'Unavailable'}</strong><small>${modeled ? `+${formatNumber(modeled)} modeled separately` : 'Campus-scenario basis'}</small></article>
      <article><span>Residential projects</span><strong>${formatNumber(context.projects?.record_count || 0)}</strong><small>${context.projects?.known_residential_units == null ? 'Known units unavailable' : `${formatNumber(context.projects.known_residential_units)} known units`}</small></article>
    </div>
    `;
}

function renderLegacyUnavailableBanner(containerId, title, copy) {
  const target = document.getElementById(containerId);
  if (!target || isLegacyBengaluru()) return;
  target.querySelectorAll('.legacy-unavailable-banner[data-city-shell="true"]').forEach(node => node.remove());
  target.insertAdjacentHTML('afterbegin', `
    <div class="legacy-unavailable-banner" data-city-shell="true">
      <strong>${escapeHTML(title)}</strong>
      <span>${escapeHTML(copy)}</span>
    </div>
  `);
}

function syncLegacyCityChrome() {
  const label = legacyCityLabel();
  const categoryLabel = activeLegacyCategory().label;
  document.body.classList.toggle('legacy-city-bengaluru', isLegacyBengaluru());
  document.body.dataset.legacyCity = activeLegacyCityId;
  const selector = document.getElementById('legacy-city-select');
  if (selector) selector.value = activeLegacyCityId;
  const categorySelector = document.getElementById('legacy-category-select');
  if (categorySelector) categorySelector.value = activeLegacyCategoryId;
  const coverageSelector = document.getElementById('legacy-hex-coverage-select');
  if (coverageSelector) coverageSelector.value = activeHexCoverageMode;
  document.title = `RanchoLabs ${label} Deep Dive`;
  setTextIfExists('app-title', `RanchoLabs ${label}`);
  setTextIfPresent('.subtitle', `${label} deep dive in the multi-city portal`);
  setTextIfPresent('.landing-kicker', `${label} market research deck`);
  setTextIfExists('landing-slide-1-title', `RanchoLabs ${label} Market Research`);
  const mapSearch = document.getElementById('map-search-query-top');
  if (mapSearch) mapSearch.placeholder = `Search ${label} places, companies, and localities`;
  const commercialAddress = document.getElementById('commercial-custom-address');
  if (commercialAddress) commercialAddress.placeholder = `Example: ${label} office corridor or landmark`;
  setTextIfExists('graph-network-help-text', `Explore ${label}'s spatial contiguity network as a secondary context view. Node size represents known residential units and edges represent adjacent cells with comparable context.`);
  setTextIfExists('map-search-status', isLegacyBengaluru()
    ? 'Search map places and localities, including areas outside this dataset.'
    : `Map shows ${label} school-demand areas; use search to inspect a specific location.`);
  setTextIfExists('school-market-breadcrumb', label);
  setTextIfExists('school-capacity-scope', `${label} · ${categoryLabel}`);
  setTextIfExists('school-method-badge', `${categoryLabel} source bucket`);
  setTextIfExists('school-audience-legend-label', `${categoryLabel} audience`);
  setTextIfExists('school-market-help', `Use source-reported all-grade ${categoryLabel} enrollment to compare cities and prioritize partnership evidence. Derived Grade 2–9 is used for local screening and capacity scenarios; modeled additions remain separate.`);
  setTextIfExists('zones-help-text', `Compare ${categoryLabel} school enrollment and campus locations by zone, then qualify each area with named residential projects, access, and overlap risk.`);
  setTextIfPresent('.decision-evidence-chip', `${categoryLabel} · reported enrollment first`);
  setTextIfPresent('.decision-intro', `A concise operating view of source-reported ${categoryLabel} school enrollment, the first catchment to validate, and the partners and residential projects to approach.`);
  setTextIfPresent('.decision-scenario-section .school-method-note', `Scenarios apply 1%, 2%, and 3% capture only to derived reported ${categoryLabel} Grade 2–9 enrollment, transparently prorated from source-reported grade spans. Overlapping catchments, competition, pricing, and site economics must be validated before committing.`);
  const indiaLink = document.getElementById('portal-home-link');
  if (indiaLink) indiaLink.href = `/?city=${encodeURIComponent(activeLegacyCityId)}&category=${encodeURIComponent(activeLegacyCategoryId)}#deep-dive`;
}

function syncLegacyCityTabs() {
  const cityAwareTabs = ['overview', 'zones', 'micromarkets', 'commercial', 'catchment', 'graph'];
  cityAwareTabs.forEach(tabId => {
    const button = document.getElementById(`tab-btn-${tabId}`);
    const pane = document.getElementById(`pane-${tabId}`);
    if (!button) return;
    button.classList.remove('bengaluru-only-tab');
    pane?.classList.remove('legacy-restricted-pane');
    button.title = `${legacyCityLabel()} city-aware legacy module`;
  });
  const summaryBengaluruOnlySelectors = [
    '#client-summary-hero',
    '#client-summary-metrics',
    '#client-summary-quartiles',
    '#client-summary-project-types',
    '#client-summary-rollup-controls',
    '#client-validation-list',
    '#client-handoff-links',
    '#school-zone-list',
    '#school-hierarchy-detail',
    '#pane-summary > h4.notion-heading-4',
    '#pane-summary > .table-container',
    '#pane-summary > .recommendation-card',
    '#pane-summary > .school-market-section'
  ];
  summaryBengaluruOnlySelectors.forEach(selector => {
    document.querySelectorAll(selector).forEach(node => node.classList.remove('legacy-summary-bengaluru-only'));
  });
}

function clearLegacyMultiCityMap() {
  if (legacyCityHexLayer && map?.hasLayer(legacyCityHexLayer)) map.removeLayer(legacyCityHexLayer);
  if (legacyCityMarkerLayer && map?.hasLayer(legacyCityMarkerLayer)) map.removeLayer(legacyCityMarkerLayer);
  legacyCityHexLayer = null;
  legacyCityMarkerLayer = null;
}

async function renderLegacyCityMap() {
  if (!map || !window.L || !layerData.multicity?.manifest) return;
  clearLegacyMultiCityMap();
  const cityMap = activeLegacyCityMap();
  if (overlayLayers.hexes) {
    if (!map.hasLayer(overlayLayers.hexes)) overlayLayers.hexes.addTo(map);
    const bounds = overlayLayers.hexes.getBounds?.();
    if (bounds?.isValid()) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 11 });
    else map.setView([cityMap.center.lat, cityMap.center.lon], cityMap.zoom || 10);
    return;
  }
  const payload = await activeLegacyCityHexes();
  if (!payload?.features?.length) {
    map.setView([cityMap.center.lat, cityMap.center.lon], cityMap.zoom || 10);
    legacyCityMarkerLayer = L.marker([cityMap.center.lat, cityMap.center.lon])
      .bindPopup(`${escapeHTML(legacyCityLabel())}: H3 category layer unavailable`)
      .addTo(map);
    return;
  }
  const values = payload.features.map(feature => feature.properties?.category_metrics?.[activeLegacyCategoryId]?.reported_students_grade_2_9 || 0);
  const max = Math.max(...values, 1);
  legacyCityHexLayer = L.geoJSON(payload, {
    style: feature => {
      const props = feature.properties || {};
      const metric = props.category_metrics?.[activeLegacyCategoryId] || {};
      const value = metric.reported_students_grade_2_9 || 0;
      return {
        color: '#185c46',
        weight: value ? 1 : 0.35,
        fillColor: props.context?.projects?.project_count ? '#2f8064' : '#c8f04e',
        fillOpacity: value ? 0.16 + 0.58 * Math.sqrt(value / max) : 0.04
      };
    },
    onEachFeature: (feature, layer) => {
      const props = feature.properties || {};
      const metric = props.category_metrics?.[activeLegacyCategoryId] || {};
      const context = props.context || {};
      layer.bindPopup(`
        <div class="notion-popup">
          <div class="popup-header"><strong>${escapeHTML(props.name || props.neighborhood_name || 'Named H3 area')}</strong><span class="popup-badge">H3 #${escapeHTML(props.hex_id || '')}</span></div>
          <div class="popup-grid" style="grid-template-columns:1fr 1fr;">
            <div>Reported students: <strong>${formatNumber(metric.reported_students_grade_2_9 || 0)}</strong></div>
            <div>Schools: <strong>${formatNumber(metric.school_count || 0)}</strong></div>
            <div>Projects: <strong>${formatNumber(context.projects?.project_count || 0)}</strong></div>
            <div>Known units: <strong>${context.projects?.known_units == null ? 'Unavailable' : formatNumber(context.projects.known_units)}</strong></div>
            <div>Tier-1 offices: <strong>${formatNumber(context.offices?.tier_1_office_count || 0)}</strong></div>
            <div>Hospitals: <strong>${formatNumber(context.hospitals?.hospital_count || 0)}</strong></div>
          </div>
        </div>
      `);
    }
  }).addTo(map);
  const bounds = legacyCityHexLayer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 11 });
  else map.setView([cityMap.center.lat, cityMap.center.lon], cityMap.zoom || 10);
}

async function renderLegacyMulticitySchoolMarket() {
  if (isLegacyBengaluru()) return false;
  const status = document.getElementById('school-market-status');
  const kpis = document.getElementById('school-market-kpis');
  const board = document.getElementById('school-board-grid');
  const tiers = document.getElementById('school-tier-grid');
  const city = activeLegacyCitySummary();
  const detail = await activeLegacyCityDetail();
  if (!status || !kpis || !city) return true;
  const metrics = city.category_metrics?.[activeLegacyCategoryId] || {};
  const context = city.context_layers || {};
  const reported = firstFiniteNumber(metrics.reported_students_grade_2_9, metrics.reported_grade_2_9_students) || 0;
  const reportedTotal = firstFiniteNumber(metrics.reported_enrollment_total, metrics.reported_total_enrollment) || 0;
  const clientTitle = document.getElementById('client-school-market-title');
  const clientBody = document.getElementById('client-school-market-body');
  if (clientTitle) clientTitle.textContent = `${legacyCityLabel()} school audience`;
  if (clientBody) {
    clientBody.innerHTML = `
      <div class="client-school-primary-grid" style="grid-template-columns: repeat(3, 1fr);">
       <article><span>Selected bucket schools</span><strong>${formatNumber(metrics.school_count || 0)}</strong><small>${escapeHTML(activeLegacyCategory().label)}</small></article>
       <article><span>Source-reported all-grade</span><strong>${reportedTotal ? formatNumber(reportedTotal) : 'Unavailable'}</strong><small>Primary city-ranking demand input</small></article>
       <article><span>Derived reported Grade 2–9</span><strong>${reported ? formatNumber(reported) : 'Unavailable'}</strong><small>Local screening and campus-scenario basis</small></article>
      </div>`;
  }
  status.className = 'school-market-status ready';
  status.textContent = `${legacyCityLabel()} ${activeLegacyCategory().label}: source-reported all-grade enrollment is the primary city-ranking signal. Grade 2–9 is transparently derived from reported grade spans for local screening; modeled additions remain separate.`;
  kpis.setAttribute('aria-busy', 'false');
  kpis.innerHTML = `
    <article><span>Private schools</span><strong>${formatNumber(metrics.school_count || 0)}</strong><small>${escapeHTML(activeLegacyCategory().label)}</small></article>
    <article class="primary"><span>Source-reported all-grade</span><strong>${reportedTotal ? formatNumber(reportedTotal) : 'Unavailable'}</strong><small>Primary city-ranking demand input</small></article>
    <article><span>Derived reported Grade 2–9</span><strong>${reported ? formatNumber(reported) : 'Unavailable'}</strong><small>Prorated from source-reported grade spans</small></article>
    <article><span>Residential projects</span><strong>${formatNumber(context.projects?.record_count || 0)}</strong><small>${context.projects?.known_residential_units == null ? 'Known units unavailable' : `${formatNumber(context.projects.known_residential_units)} known units`}</small></article>
  `;
  if (board) {
    const boardCounts = new Map();
    decisionSupportList(detail, 'priority_school_partners').forEach(row => {
      const boardName = String(row.board || 'Not reported').trim() || 'Not reported';
      boardCounts.set(boardName, (boardCounts.get(boardName) || 0) + 1);
    });
    board.innerHTML = [...boardCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([boardName, count]) => `
      <article><strong>${escapeHTML(boardName)}</strong><span>${formatNumber(count)}</span><small>priority school partners</small></article>
    `).join('') || '<div class="school-empty-state">Board data is unavailable for the current partner list.</div>';
  }
  if (tiers && detail) {
    tiers.innerHTML = (detail.geographies?.h3_cells || []).slice(0, 8).map(cell => {
      const cellMetric = cell.category_metrics?.[activeLegacyCategoryId] || {};
      return `<article class="school-tier-card"><span class="school-tier-dot"></span><div><strong>${escapeHTML(cell.label || cell.id)}</strong><small>Candidate catchment evidence</small></div><b>${formatNumber(cellMetric.reported_students_grade_2_9 || 0)} reported students</b><span>${formatNumber(cellMetric.school_count || 0)} schools</span></article>`;
    }).join('') || '<div class="school-empty-state">No mapped H3 demand cells for this bucket.</div>';
  }
  return true;
}

function renderLegacyCityUnavailableStates() {
  document.querySelectorAll('.legacy-unavailable-banner[data-city-shell="true"]').forEach(node => node.remove());
  const hasOfficeBoundaries = Boolean((layerData.sez_zones?.features || []).length);
  document.getElementById('layer-card-sez')?.toggleAttribute('hidden', !hasOfficeBoundaries);
  document.getElementById('button-sez-only-pill-boundary-type')?.toggleAttribute('hidden', !hasOfficeBoundaries);
  if (layerData.commute_scores?.status === 'unavailable') {
    renderLegacyUnavailableBanner('pane-catchment', 'Travel-time context is directional', 'Use the available access geometry for early screening, then validate shortlisted sites with current drive-time checks before committing.');
  }
}

async function applyLegacyCityShell() {
  syncLegacyCityChrome();
  syncLegacyCityTabs();
  if (isLegacyBengaluru()) {
    document.querySelectorAll('.legacy-unavailable-banner[data-city-shell="true"]').forEach(node => node.remove());
  }
  renderLegacyCityOverview();
  await renderLegacyMulticitySchoolMarket();
  const cityDetail = await activeLegacyCityDetail();
  await renderClientDecisionBrief(cityDetail);
  renderLegacyCityUnavailableStates();
  await renderLegacyCityMap();
}

async function switchLegacyCity(cityId) {
  const resolved = normalizeLegacyCityId(cityId) || 'bengaluru';
  activeLegacyCityId = resolved;
  schoolMarketState.mode = 'q4';
  const url = new URL(window.location.href);
  url.searchParams.set('city', activeLegacyCityId);
  url.searchParams.set('category', activeLegacyCategoryId);
  url.searchParams.delete('school_fee');
  url.searchParams.delete('school_view');
  window.location.assign(url.toString());
}

function refreshSchoolAudienceDependentViews(previousRolledUpScope = null) {
  renderZonesTab();
  renderSchoolDirectory();

  if (selectedZone && layerData.report?.zones?.[selectedZone]) {
    const rowId = `zone-row-${selectedZone.replace(/\s+/g, '-').toLowerCase()}`;
    selectZone(selectedZone, document.getElementById(rowId));
  } else {
    clearAreaSchoolContext();
  }

  if (previousRolledUpScope) {
    renderRolledUpAssetsMapLayers(previousRolledUpScope);
  }
}

function initializeLegacyCityShell() {
  const params = new URLSearchParams(window.location.search);
  const requestedCategory = params.get('category');
  if ((layerData.multicity?.manifest?.categories || []).some(category => category.id === requestedCategory)) {
    activeLegacyCategoryId = requestedCategory;
  }
  activeLegacyCityId = normalizeLegacyCityId(params.get('city')) || activeLegacyCityId;
  const selector = document.getElementById('legacy-city-select');
  if (selector && !selector.dataset.bound) {
    selector.dataset.bound = 'true';
    selector.addEventListener('change', event => switchLegacyCity(event.target.value));
  }
  const categorySelector = document.getElementById('legacy-category-select');
  if (categorySelector && !categorySelector.dataset.bound) {
    categorySelector.dataset.bound = 'true';
    categorySelector.value = activeLegacyCategoryId;
    categorySelector.addEventListener('change', async () => {
      const previousRolledUpScope = rolledUpAssetsScope;
      activeLegacyCategoryId = categorySelector.value;
      clearSchoolLiveEvaluation();
      schoolMarketState.selectedZone = null;
      schoolMarketState.selectedMarketIndex = null;
      schoolMarketState.selectedHexId = null;
      updateLegacyCityUrl();
      await applyLegacyCityShell();
      if (isLegacyBengaluru()) {
        renderClientSummary();
        renderSchoolExecutiveSurfaces();
        renderSchoolMarket();
      }
      refreshSchoolAudienceDependentViews(previousRolledUpScope);
    });
  }
  applyLegacyCityShell();
}

// Math helper to calculate destination coordinate given start, distance and bearing
function destinationLatLng(lat, lon, d, bearingDegrees) {
  const R = 6371.0088; // Earth radius in km
  const phi1 = lat * Math.PI / 180;
  const lam1 = lon * Math.PI / 180;
  const theta = bearingDegrees * Math.PI / 180;
  const dDivR = d / R;

  const phi2 = Math.asin(Math.sin(phi1) * Math.cos(dDivR) + Math.cos(phi1) * Math.sin(dDivR) * Math.cos(theta));
  const lam2 = lam1 + Math.atan2(Math.sin(theta) * Math.sin(dDivR) * Math.cos(phi1), Math.cos(dDivR) - Math.sin(phi1) * Math.sin(phi2));

  return [phi2 * 180 / Math.PI, lam2 * 180 / Math.PI];
}

// Generate coordinate array for wedge polygons
function generateWedge(c_lat, c_lon, r_inner, r_outer, angle1, angle2) {
  const points = [];
  const steps = 15; // smooth curves

  // Inner arc: angle1 to angle2
  for (let i = 0; i <= steps; i++) {
    const angle = angle1 + (angle2 - angle1) * (i / steps);
    const normalizedAngle = (angle + 360) % 360;
    points.push(destinationLatLng(c_lat, c_lon, r_inner, normalizedAngle));
  }

  // Outer arc: angle2 back to angle1
  for (let i = steps; i >= 0; i--) {
    const angle = angle1 + (angle2 - angle1) * (i / steps);
    const normalizedAngle = (angle + 360) % 360;
    points.push(destinationLatLng(c_lat, c_lon, r_outer, normalizedAngle));
  }

  return points;
}

// Generate coordinates for Central zone (circle of radius r)
function generateCentralCircle(c_lat, c_lon, r) {
  const points = [];
  const steps = 60;
  for (let i = 0; i <= steps; i++) {
    const angle = (360 / steps) * i;
    points.push(destinationLatLng(c_lat, c_lon, r, angle));
  }
  return points;
}

// Map Initialization
function initMap() {
  const initialCity = LEGACY_CITY_CENTERS[activeLegacyCityId] || LEGACY_CITY_CENTERS.bengaluru;
  map = L.map('leaflet-map-canvas', {
    zoomControl: false,
    preferCanvas: true
  }).setView([initialCity.lat, initialCity.lon], initialCity.zoom || 10);

  // Muted Notion-style Map Tiles (CartoDB Positron)
  baseLayers.light = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
  });
  baseLayers.satellite = L.tileLayer('https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', {
    attribution: 'Map data &copy; Google',
    maxZoom: 20
  });
  setBasemap('light', false);

  // Position Zoom Control to Bottom-Left for cleaner interface
  L.control.zoom({ position: 'bottomleft' }).addTo(map);

  // Add click listener on map base canvas for Catchment queries (only triggers if mode is enabled)
  map.on('click', onMapBaseClick);
  map.on('zoomend', () => {
    syncHexTooltipVisibility();
    checkMapZoomLock();
  });
  map.on('popupclose', () => {
    if (commuteRouteLayer && map.hasLayer(commuteRouteLayer)) {
      map.removeLayer(commuteRouteLayer);
    }
  });
}

function setBasemap(mode, fitMap = true) {
  if (!map || !baseLayers.light || !baseLayers.satellite) return;
  const nextMode = mode === 'satellite' ? 'satellite' : 'light';
  if (activeBasemap === nextMode && fitMap !== false) {
    return;
  }

  Object.entries(baseLayers).forEach(([key, layer]) => {
    if (!layer) return;
    if (map.hasLayer(layer)) {
      map.removeLayer(layer);
    }
  });
  baseLayers[nextMode].addTo(map);
  activeBasemap = nextMode;

  const lightBtn = document.getElementById('basemap-light-btn');
  const satelliteBtn = document.getElementById('basemap-satellite-btn');
  lightBtn?.classList.toggle('active', nextMode === 'light');
  satelliteBtn?.classList.toggle('active', nextMode === 'satellite');

  if (fitMap !== false) {
    setTimeout(() => map.invalidateSize(false), 0);
  }
}

// Load static assets
async function loadData() {
  try {
    const [
      hexes,
      report,
      localities,
      societies,
      hospitals,
      sezZones,
      clientSummary,
      commuteScores,
      metroStations,
      sezOffices,
      microMarkets,
      projectQuartileAssetsData,
      schoolEntities,
      schoolCampuses,
      schoolMarketSummary,
      schoolMarketAudit,
      generatedLegacyReport,
      multicityManifest,
      multicityComparison,
      multicityScore,
      multicityCityLayer
    ] = await Promise.all([
      fetchJsonResource(legacyDataResource('hexes.geojson')),
      fetchJsonResource(legacyDataResource('report.json')),
      fetchJsonResource(legacyDataResource('localities.json')),
      fetchJsonResource(legacyDataResource('societies.json')),
      fetchJsonResource(legacyDataResource('hospitals.json')),
      fetchJsonResource(legacyDataResource('sez_zones.geojson'), { type: 'FeatureCollection', features: [] }, true),
      fetchJsonResource(generatedLegacyDataResource('client_summary.json'), null, true),
      fetchJsonResource(legacyDataResource('commute_scores.json'), EMPTY_COMMUTE_SCORES, true),
      fetchJsonResource(legacyDataResource(activeLegacyCityId === 'bengaluru' ? 'bangalore_metro_stations.json' : 'metro_stations.json'), [], true),
      fetchJsonResource(legacyDataResource('sez_offices.json'), [], true),
      fetchJsonResource(legacyDataResource('micromarket_suggestions_8hex.json'), null, true),
      fetchJsonResource(legacyDataResource('project_assets_by_quartile.json'), [], true),
      fetchJsonResource(legacySchoolDataResource('school_entities.json'), [], true),
      fetchJsonResource(legacySchoolDataResource('school_campuses.json'), null, true),
      fetchJsonResource(legacySchoolDataResource('school_market_summary.json'), null, true),
      fetchJsonResource(legacySchoolDataResource('school_market_audit.json'), null, true),
      fetchJsonResource(generatedLegacyDataResource('report.json'), null, true),
      fetchJsonResource('data/multicity/manifest.json', null, true),
      fetchJsonResource('data/multicity/city_comparison.json', null, true),
      fetchJsonResource('data/multicity/score_model.json', null, true),
      fetchJsonResource('data/multicity/india_cities.geojson', null, true)
    ]);

    layerData.hexes = hexes;
    layerData.microMarkets = microMarkets;

    // Precompute PageRank node types for H3 hexes
    if (layerData.hexes && layerData.hexes.features) {
      layerData.hexes.features.forEach(feat => {
        const props = feat.properties;
        const lat1 = props.centroid_lat;
        const lon1 = props.centroid_lon;
        const adjacentNeighbors = [];
        layerData.hexes.features.forEach(otherFeat => {
          const o = otherFeat.properties;
          if (o.hex_id === props.hex_id) return;
          const dist = L.latLng(lat1, lon1).distanceTo(L.latLng(o.centroid_lat, o.centroid_lon));
          if (dist <= 2600) {
            adjacentNeighbors.push(o);
          }
        });
        const neighborCount = adjacentNeighbors.length;
        const shift = props.rank_shift || 0;
        
        let nodeType = 'Connected Residential';
        if (shift >= 10 && neighborCount >= 4) {
          nodeType = 'Strategic Hub';
        } else if (shift <= -15 && props.final_affluence_score >= 65) {
          nodeType = 'Wealth Island';
        }
        props.pagerank_node_type = nodeType;
      });
    }
    layerData.report = enrichLegacyReportWithGeneratedRollups(report, generatedLegacyReport);
    layerData.localities = Array.isArray(localities) ? localities : (localities?.localities || []);
    layerData.societies = societies;
    const normalizedSchoolEntities = Array.isArray(schoolEntities) ? schoolEntities : (schoolEntities?.entities || []);
    let normalizedSchoolCampuses = normalizeSchoolCampusCollection(schoolCampuses || []);
    if (!normalizedSchoolCampuses.length && normalizedSchoolEntities.length) {
      normalizedSchoolCampuses = normalizeSchoolCampusCollection(normalizedSchoolEntities);
    }
    layerData.schools = normalizedSchoolCampuses;
    layerData.school_entities = normalizedSchoolEntities;
    layerData.school_market_summary = schoolMarketSummary;
    layerData.school_market_audit = schoolMarketAudit;
    layerData.hospitals = hospitals;
    layerData.sez_zones = sezZones;
    layerData.client_summary = clientSummary;
    layerData.commute_scores = commuteScores || EMPTY_COMMUTE_SCORES;
    layerData.metro_stations = metroStations || [];
    layerData.sez_offices = sezOffices || [];
    layerData.project_assets = projectQuartileAssetsData || [];
    layerData.multicity = {
      manifest: multicityManifest,
      comparison: multicityComparison,
      score: multicityScore,
      cityLayer: multicityCityLayer,
      details: new Map(),
      hexes: new Map()
    };
    projectQuartileAssets = layerData.project_assets;

    // Compute exact selected-city known residential units from H3 features.
    let tempTotal = 0;
    if (layerData.hexes && layerData.hexes.features) {
      layerData.hexes.features.forEach(feat => {
        tempTotal += Number(feat.properties.direct_total_units || feat.properties.known_residential_units || 0);
      });
    }
    if (tempTotal > 0) {
      totalSelectedCityTam = tempTotal;
    }
    rawLocalityRecordCount = Number(layerData.client_summary?.coverage?.raw_locality_records || layerData.localities.length || 0);
    console.log(`Calculated ${legacyCityLabel()} known residential units:`, totalSelectedCityTam);

    // Build Lookup Maps for fast POI resolution on click
    societyLookup = new Map(layerData.societies.map(s => [s.name, s]));
    hospitalLookup = new Map(layerData.hospitals.map(h => [h.name, h]));

    // Calculate Welcome Landing stats dynamically
    let totalConfidence = 0;
    let confCount = 0;
    let readyToMove = 0;
    let underConstruction = 0;
    let unreported = 0;

    layerData.societies.forEach(soc => {
      if (soc.confidence !== undefined) {
        totalConfidence += soc.confidence;
        confCount++;
      }
      if (soc.construction_status === 'Ready To Move') {
        readyToMove++;
      } else if (soc.construction_status === 'Under Construction') {
        underConstruction++;
      } else {
        unreported++;
      }
    });

    const avgConf = confCount > 0 ? (totalConfidence / confCount) * 100 : 91.2;
    const zoneCount = Object.keys(layerData.report?.zones || {}).length;
    const microMarketCount = layerData.report?.all_micro_market_count || 0;
    const activeHexCount = layerData.client_summary?.coverage?.active_analysis_hexes || layerData.report?.overall?.total_hexes || 0;
    const finalHexCount = layerData.client_summary?.coverage?.final_h3_hexes || activeHexCount;

    setTextIfExists('landing-slide1-total-tam', totalSelectedCityTam.toLocaleString());
    setTextIfExists('landing-slide1-localities', rawLocalityRecordCount.toLocaleString());
    setTextIfExists('landing-slide1-confidence', `${avgConf.toFixed(1)}%`);
    setTextIfExists('landing-slide1-hexes', finalHexCount.toLocaleString());
    setTextIfExists('landing-slide1-zones', zoneCount.toLocaleString());
    setTextIfExists('landing-slide1-markets', microMarketCount.toLocaleString());
    setTextIfExists('landing-slide2-localities', rawLocalityRecordCount.toLocaleString());
    setTextIfExists('landing-slide2-localities-plotted', layerData.localities.length.toLocaleString());
    setTextIfExists('landing-slide2-societies', layerData.societies.length.toLocaleString());
    setTextIfExists('landing-slide2-societies-breakdown', `${readyToMove} Ready | ${underConstruction} UC | ${unreported} NA`);
    setTextIfExists('landing-slide2-hospitals', layerData.hospitals.length.toLocaleString());
    setTextIfExists('landing-slide2-hexes', `${finalHexCount.toLocaleString()} final / ${activeHexCount.toLocaleString()} active hexes`);
    setTextIfExists('landing-slide2-zones', zoneCount.toLocaleString());
    setTextIfExists('landing-slide2-markets', microMarketCount.toLocaleString());

    // Render components
    renderClientSummary();
    if (shouldShowOnboarding()) {
      initLandingMapPreview();
    }
    setupLayers();
    initZonePolygons();
    refreshBoundaryOverlay();
    renderZonesTab();
    initializeSchoolMarket();
    initCommercialModule();
    runWhenIdle(loadCommercialListings);
    updateActiveLayersPanel();
    initializeLegacyCityShell();
  } catch (e) {
    console.error("Error fetching web data:", e);
  }
}

async function loadCommercialListings() {
  if (!isLegacyBengaluru()) {
    commercialListings = (layerData.sez_offices || []).map(office => normalizeCommercialListing({
      ...office,
      listing_id: office.office_id,
      title: office.name,
      property_type: 'Office anchor evidence',
      price: 0,
      sqft: 0,
      latitude: office.lat,
      longitude: office.lon,
      source: 'city office anchor layer',
      data_warning: 'Lease price and available area are unavailable in the supplied office dataset.'
    }));
    applyCommercialPreferences();
    updateCommercialStats();
    setCommercialDataNote(`${legacyCityLabel()} office anchors are shown as workplace evidence; rent and available-area fields are unavailable.`);
    return;
  }
  try {
    const commercialRes = await fetch('/api/listings');
    if (commercialRes.ok) {
      const payload = await commercialRes.json();
      commercialListings = payload.status === 'success'
        ? (payload.data || []).map(normalizeCommercialListing)
        : [];
    } else {
      commercialListings = [];
    }
  } catch (commercialError) {
    console.warn("Commercial API not available:", commercialError);
    commercialListings = [];
  }

  applyCommercialPreferences();
  updateCommercialStats();
}

function initLandingMapPreview() {
  const previewEl = document.getElementById('landing-map-preview');
  if (!previewEl || landingPreviewMap || !layerData.hexes || !window.L) return;

  landingPreviewMap = L.map(previewEl, {
    attributionControl: false,
    boxZoom: false,
    doubleClickZoom: false,
    dragging: false,
    fadeAnimation: false,
    inertia: false,
    keyboard: false,
    markerZoomAnimation: false,
    scrollWheelZoom: false,
    touchZoom: false,
    zoomAnimation: false,
    zoomControl: false
  }).setView([CENTRAL_LAT, CENTRAL_LON], (LEGACY_CITY_CENTERS[activeLegacyCityId]?.zoom || 10));

  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '',
    subdomains: 'abcd',
    maxZoom: 20
  }).addTo(landingPreviewMap);

  const previewHexes = L.geoJSON(layerData.hexes, {
    interactive: false,
    style: function (feature) {
      const score = feature.properties.final_affluence_score;
      return {
        fillColor: getHexColor(score),
        color: '#ffffff',
        weight: 0.75,
        fillOpacity: 0.66
      };
    }
  }).addTo(landingPreviewMap);

  landingPreviewMap.fitBounds(previewHexes.getBounds(), { padding: [12, 12], animate: false });
  setTimeout(() => landingPreviewMap.invalidateSize(false), 0);
}

// Build Leaflet Layers
function setupLayers() {
  // A. H3 Hex Layer
  hexLayerLookup.clear();
  overlayLayers.hexes = L.geoJSON(layerData.hexes, {
    style: getHexFeatureStyle,
    onEachFeature: function (feature, layer) {
      const p = feature.properties;
      hexLayerLookup.set(p.hex_id, layer);
      const tooltipContent = `
        <strong>#${p.rank} ${p.name}</strong><br/>
        Context score: <strong>${Number(p.final_affluence_score || 0).toFixed(1)}</strong> (${p.affluence_tier || 'Directional'})<br/>
        Known residential units: <strong>${formatNumber(p.direct_total_units || p.known_residential_units || 0)}</strong><br/>
        Cluster: <strong>#${p.community_id !== undefined ? p.community_id : 'N/A'}</strong> | Hub Centrality: <strong>${p.pagerank_personalized ? (p.pagerank_personalized * 1000).toFixed(2) : '0.0'}</strong>
      `;
      layer._tooltipContent = tooltipContent;
      layer.on('click', function (e) {
        if (commercialLocationPickMode) {
          setCommercialDraftLocation(p.centroid_lat, p.centroid_lon, 'Picked from hex center');
        } else if (catchmentModeEnabled) {
          // Trigger catchment query on the centroid coordinates of the clicked hex
          onMapClick({ latlng: L.latLng(p.centroid_lat, p.centroid_lon) });
        } else {
          // Open normal H3 cell details panel on the right side
          selectHex(p, layer);
        }
      });
    }
  }).addTo(map);
  setLegacyHexCoverage(activeHexCoverageMode);

  // B. Costly Localities Heatmap (Amber-Red point-style KDE)
  const localitiesPoints = layerData.localities.map(loc => {
    const intensity = Math.min(1.0, Math.max(0.6, loc.price_sqft / 12000));
    return [loc.lat, loc.lon, intensity];
  });
  overlayLayers.localities = L.heatLayer(localitiesPoints, {
    radius: 15,
    blur: 10,
    max: 0.7,
    minOpacity: 0.45,
    gradient: {0.2: '#fee8c8', 0.5: '#fdbb84', 0.8: '#e34a33', 1.0: '#b30000'}
  });

  const commutePoints = (layerData.hexes?.features || [])
    .map(feature => {
      const p = feature.properties || {};
      const score = Number(p.commute_score || 0);
      if (!p.centroid_lat || !p.centroid_lon || !score) return null;
      return [p.centroid_lat, p.centroid_lon, Math.max(0.35, score / 100)];
    })
    .filter(Boolean);
  overlayLayers.commute = L.heatLayer(commutePoints, {
    radius: 24,
    blur: 16,
    max: 0.9,
    minOpacity: 0.35,
    gradient: {0.2: '#fee2e2', 0.45: '#fed7aa', 0.65: '#fde68a', 0.82: '#86efac', 1.0: '#16a34a'}
  });

  // C. Societies Heatmap - emerald green (Filtered dynamically, initially all)
  updateSocietiesHeatmapPoints('all');

  // D. Hospitals Heatmap - violet purple (Filtered dynamically, initially all)
  updateHospitalsHeatmapPoints('all');

  // F. SEZ Office Zones Polygons (Filtered dynamically)
  overlayLayers.sez = L.geoJSON(layerData.sez_zones, {
    style: function (feature) {
      return {
        fillColor: '#64748b',
        color: '#475569',
        weight: 1.5,
        fillOpacity: 0.6
      };
    },
    onEachFeature: function (feature, layer) {
      const p = feature.properties;
      const offices = getSEZOffices(p.name);
      const insideOffices = offices.filter(item => item.sez_match_type === 'inside_boundary');
      const nearOffices = offices.filter(item => item.sez_match_type === 'near_boundary');
      const topOffices = offices.slice(0, 6).map(item => `
        <div style="display:flex;justify-content:space-between;gap:8px;">
          <span>${escapeHTML(item.name)}</span>
          <strong>${formatNumber(item.office_rank_score || 0, 0)}</strong>
        </div>
      `).join('');
      layer.bindTooltip(`
        <strong>${p.name}</strong><br/>
        Office Capacity: <strong>${p.office_spaces.toLocaleString()}</strong><br/>
        Offices: <strong>${formatNumber(offices.length, 0)}</strong>
        <small>(${formatNumber(insideOffices.length, 0)} inside, ${formatNumber(nearOffices.length, 0)} near)</small>
      `, { sticky: true });
      layer.bindPopup(`
        <div class="notion-popup">
          <div class="popup-header">
            <strong>${escapeHTML(p.name)}</strong>
            <span class="popup-badge" style="background:#eef2ff; color:#4338ca; border-color:#c7d2fe;">SEZ</span>
          </div>
          <div class="popup-grid" style="grid-template-columns: 1fr; gap: 5px; font-size:11.5px;">
            <div>Office capacity proxy: <strong>${formatNumber(p.office_spaces || 0, 0)}</strong></div>
            <div>Matched office records: <strong>${formatNumber(offices.length, 0)}</strong></div>
            <div>Inside / within 2km: <strong>${formatNumber(insideOffices.length, 0)}</strong> / <strong>${formatNumber(nearOffices.length, 0)}</strong></div>
            <div>Tier 1 MNC/GCC anchors: <strong>${formatNumber(offices.filter(item => item.company_prominence_tier === 'Tier 1 - MNC/GCC anchor').length, 0)}</strong></div>
            ${topOffices ? `<div style="margin-top:6px;border-top:1px solid var(--border-light);padding-top:6px;"><strong>Top office anchors</strong>${topOffices}</div>` : ''}
          </div>
        </div>
      `);
    }
  });
  updateSEZOfficeMarkers();

  overlayLayers.roads = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 20,
    opacity: 0.5,
    detectRetina: true
  });

  overlayLayers.boundaries = null;

  syncHexTooltipVisibility();
}

function syncHexTooltipVisibility() {
  if (!overlayLayers.hexes || !map) return;
  const showTooltips = map.getZoom() >= 12;
  if (tooltipsBound === showTooltips) return;
  tooltipsBound = showTooltips;
  overlayLayers.hexes.eachLayer(layer => {
    if (showTooltips) {
      if (!layer.getTooltip() && layer._tooltipContent) {
        layer.bindTooltip(layer._tooltipContent, { sticky: true });
      }
    } else if (layer.getTooltip()) {
      layer.unbindTooltip();
    }
  });
}

// Interactive Layer Filters
function updateSocietiesHeatmapPoints(category) {
  let filtered = layerData.societies;
  if (category !== 'all') {
    filtered = layerData.societies.filter(soc => soc.category === category);
  }
  const points = filtered.map(soc => {
    const intensity = Math.min(1.0, Math.max(0.35, Number(soc.units || soc.known_units || 0) / 1200));
    return [soc.lat, soc.lon, intensity];
  });

  if (overlayLayers.societies) {
    overlayLayers.societies.setLatLngs(points);
  } else {
    overlayLayers.societies = L.heatLayer(points, {
      radius: 15,
      blur: 10,
      max: 0.7,
      minOpacity: 0.45,
      gradient: {0.2: '#e5f5e0', 0.5: '#a1d99b', 0.8: '#31a354', 1.0: '#006d2c'}
    });
  }
}

function updateSocietiesHeatmap() {
  const cat = document.getElementById('filter-soc-category').value;
  updateSocietiesHeatmapPoints(cat);
  const opacity = parseFloat(document.getElementById('opacity-slider-societies')?.value || '0.75');
  setLayerOpacity('societies', opacity);
  if (document.getElementById('toggle-layer-societies')?.checked && overlayLayers.societies && map && !map.hasLayer(overlayLayers.societies)) {
    overlayLayers.societies.addTo(map);
  }
}

function updateHospitalsHeatmapPoints(category) {
  let filtered = layerData.hospitals;
  if (category !== 'all') {
    filtered = layerData.hospitals.filter(h => h.category === category);
  }
  const points = filtered.map(hosp => {
    const intensity = Math.min(1.0, Math.max(0.6, hosp.beds / 150));
    return [hosp.lat, hosp.lon, intensity];
  });

  if (overlayLayers.hospitals) {
    overlayLayers.hospitals.setLatLngs(points);
  } else {
    overlayLayers.hospitals = L.heatLayer(points, {
      radius: 15,
      blur: 10,
      max: 0.7,
      minOpacity: 0.45,
      gradient: {0.2: '#f2f0f7', 0.5: '#bcbddc', 0.8: '#756bb1', 1.0: '#54278f'}
    });
  }
}

function updateHospitalsHeatmap() {
  const cat = document.getElementById('filter-hosp-category').value;
  updateHospitalsHeatmapPoints(cat);
}

function getSEZOffices(sezName) {
  return (layerData.sez_offices || [])
    .filter(item => item.sez_name === sezName)
    .sort((a, b) => Number(b.office_rank_score || 0) - Number(a.office_rank_score || 0));
}

function getOfficeMarkerColor(office) {
  const tier = office.company_prominence_tier || '';
  if (tier.includes('Tier 1')) return '#111827';
  if (tier.includes('Tier 2')) return '#2563eb';
  if (tier.includes('Tier 3')) return '#7c3aed';
  return '#64748b';
}

function officeMatchesTierFilter(office, filter) {
  if (!filter || filter === 'all') return true;
  const tier = String(office.company_prominence_tier || '').toLowerCase().replaceAll('-', ' ');
  if (filter === 'tier1') return tier.includes('tier 1');
  if (filter === 'tier2plus') return tier.includes('tier 1') || tier.includes('tier 2');
  if (filter === 'local') return tier.includes('tier 4') || tier.includes('local');
  return true;
}

function officeMatchesProximityFilter(office, filter) {
  if (!filter || filter === 'within2') return Number(office.distance_to_sez_km || 0) <= 2;
  if (filter === 'within1') return Number(office.distance_to_sez_km || 0) <= 1;
  if (filter === 'inside') return office.sez_match_type === 'inside_boundary';
  return true;
}

function getOfficeSEZMatchLabel(office) {
  if (office.sez_match_type === 'inside_boundary') return 'Inside sourced boundary';
  if (office.distance_to_sez_km == null) return 'Office anchor';
  const distance = Number(office.distance_to_sez_km || 0);
  return `${formatNumber(distance, 2)} km from sourced boundary`;
}

function makeOfficePopup(office) {
  const isLockedDetails = !isUnlocked();
  const website = office.website || '';
  const websiteHtml = isLockedDetails
    ? '<span style="color:#ef4444; cursor:pointer; font-weight:600;" onclick="openUnlockModal()">Restricted website/contact (Enter Passcode)</span>'
    : (website ? `<a href="${escapeHTML(website)}" target="_blank" class="notion-link">Open website ↗</a>` : '<span style="color:#9ca3af">No website in source</span>');
  const reasons = (office.ranking_reasons || []).slice(0, 3).map(reason => `<li>${escapeHTML(reason)}</li>`).join('');
  return `
    <div class="notion-popup">
      <div class="popup-header">
        <strong>${escapeHTML(isLockedDetails ? 'Restricted Office Name' : office.name)}</strong>
        <span class="popup-badge" style="background:#e0f2fe; color:#075985; border-color:#bae6fd;">OFFICE</span>
      </div>
      <div class="popup-score">Prominence proxy: <strong>${formatNumber(office.office_rank_score || 0, 0)}</strong> · ${escapeHTML(office.company_prominence_tier || 'Unclassified')}</div>
      <div class="popup-grid" style="grid-template-columns: 1fr; gap: 4px; font-size:11.5px;">
        <div>Office area: <strong>${escapeHTML(office.sez_name || office.locality || 'NA')}</strong></div>
        <div>Office evidence: <strong>${escapeHTML(getOfficeSEZMatchLabel(office))}</strong></div>
        <div>Zone / Hex: <strong>${escapeHTML(office.zone || 'NA')}</strong> · ${escapeHTML(office.hex_name || office.hex_id || 'NA')}</div>
        <div>Type proxy: <strong>${escapeHTML(office.company_type_proxy || 'NA')}</strong></div>
        <div>Address: <span style="color:var(--text-muted);">${escapeHTML(isLockedDetails ? 'Restricted Address' : (office.address || office.locality || 'NA'))}</span></div>
        ${reasons ? `<div style="margin-top:4px;"><strong>Ranking reasons</strong><ul style="padding-left:16px;margin:3px 0 0;">${reasons}</ul></div>` : ''}
        <div style="margin-top: 6px; border-top: 1px solid var(--border-light); padding-top: 6px;">${websiteHtml}</div>
      </div>
    </div>
  `;
}

function updateSEZOfficeMarkers() {
  const filter = document.getElementById('filter-office-tier')?.value || 'tier2plus';
  const proximityFilter = document.getElementById('filter-office-proximity')?.value || 'within2';
  const markers = (layerData.sez_offices || [])
    .filter(office => officeMatchesTierFilter(office, filter))
    .filter(office => officeMatchesProximityFilter(office, proximityFilter))
    .map(office => {
      const marker = L.circleMarker([office.lat, office.lon], {
        radius: office.company_prominence_tier === 'Tier 1 - MNC/GCC anchor' ? 6 : 4.5,
        color: '#ffffff',
        fillColor: getOfficeMarkerColor(office),
        fillOpacity: 0.86,
        weight: 1.5,
        opacity: 1
      });
      marker.bindTooltip(`${office.name} · ${office.company_prominence_tier} · ${getOfficeSEZMatchLabel(office)}`, { sticky: true });
      marker.bindPopup(makeOfficePopup(office), { maxWidth: 340, className: 'notion-popup-container' });
      marker.on('click', () => focusOnPoi(office, 'office'));
      return marker;
    });

  const wasVisible = overlayLayers.sezOffices && map && map.hasLayer(overlayLayers.sezOffices);
  if (overlayLayers.sezOffices && map && map.hasLayer(overlayLayers.sezOffices)) {
    map.removeLayer(overlayLayers.sezOffices);
  }
  overlayLayers.sezOffices = L.layerGroup(markers);
  const checkbox = document.getElementById('toggle-layer-sezOffices');
  if (checkbox?.checked || wasVisible) {
    overlayLayers.sezOffices.addTo(map);
  }
}

function renderOfficeList(offices, options = {}) {
  const limit = options.limit || 25;
  if (!offices || !offices.length) {
    return `<div style="padding: 10px; color:#6b7280;">${escapeHTML(options.emptyText || 'No office anchors matched this area.')}</div>`;
  }
  return offices.slice(0, limit).map((office, idx) => {
    const isLockedItem = !isUnlocked() && idx >= 5;
    const name = isLockedItem ? 'Restricted Office Name' : office.name;
    const tier = isLockedItem ? 'Company tier restricted' : office.company_prominence_tier;
    const tag = isLockedItem
      ? 'Office details restricted | Score restricted'
      : `${office.sez_name || office.locality || 'Office area NA'} | ${getOfficeSEZMatchLabel(office)} | ${office.zone || 'Zone NA'} | Score ${formatNumber(office.office_rank_score || 0, 0)}`;
    return `
      <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-type="office" data-idx="${idx}" data-locked="${isLockedItem}">
        <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(office.name)}">#${office.overall_office_rank || idx + 1} ${escapeHTML(name)}</div>
        <div class="poi-item-tag">${escapeHTML(tier || 'Unclassified')} · ${escapeHTML(tag)}</div>
      </div>
    `;
  }).join('');
}

function updateSEZLayer() {
  const minSpaces = parseInt(document.getElementById('filter-sez-spaces').value || '0', 10);
  if (overlayLayers.sez) {
    overlayLayers.sez.clearLayers();
    const filteredFeatures = layerData.sez_zones.features.filter(feat => {
      return (feat.properties.office_spaces || 0) >= minSpaces;
    });
    overlayLayers.sez.addData({
      type: "FeatureCollection",
      features: filteredFeatures
    });
  }
  boundaryOverlayNeedsRefresh = true;
  refreshBoundaryOverlay();
}

// Layer Toggle Handlers
function toggleLayer(layerName) {
  const checkbox = document.getElementById(`toggle-layer-${layerName}`);
  if (layerName === 'boundaries' && (!overlayLayers.boundaries || boundaryOverlayNeedsRefresh)) {
    refreshBoundaryOverlay();
  }
  const layer = overlayLayers[layerName];
  if (!layer) return;

  if (checkbox.checked) {
    layer.addTo(map);
  } else {
    map.removeLayer(layer);
  }
}

// Set opacity dynamically for layers
function setLayerOpacity(layerName, value) {
  const layer = overlayLayers[layerName];
  if (!layer) return;

  if (layerName === 'hexes') {
    refreshHexLayerStyles();
  } else if (layerName === 'localities' || layerName === 'societies' || layerName === 'hospitals' || layerName === 'commute') {
    const canvas = layer._canvas;
    if (canvas) {
      canvas.style.opacity = value;
    }
  } else {
    // GeoJSON layers
    layer.setStyle({ fillOpacity: value });
  }
}

function initOverviewLayerControls() {
  if (overviewLayerControlsInitialized) return;
  overviewLayerControlsInitialized = true;

  const societyToggle = document.getElementById('toggle-layer-societies');
  if (societyToggle) {
    societyToggle.addEventListener('change', () => {
      updateSocietiesHeatmap();
      toggleLayer('societies');
    });
  }

  const societyFilter = document.getElementById('filter-soc-category');
  if (societyFilter) {
    societyFilter.addEventListener('change', updateSocietiesHeatmap);
  }

  const societyOpacity = document.getElementById('opacity-slider-societies');
  if (societyOpacity) {
    societyOpacity.addEventListener('input', event => {
      setLayerOpacity('societies', event.target.value);
    });
  }
}

// Sync catchment mode enabling across elements
function syncCatchmentMode(enabled) {
  catchmentModeEnabled = enabled;

  const sidebarToggle = document.getElementById('btn-toggle-catchment-mode');
  if (sidebarToggle) sidebarToggle.checked = enabled;

  const mapToggle = document.getElementById('map-btn-toggle-catchment-mode');
  if (mapToggle) mapToggle.checked = enabled;

  // Update the big toggle label text
  const toggleLabel = document.getElementById('catchment-toggle-label');
  if (toggleLabel) toggleLabel.textContent = enabled ? 'Armed' : 'Off';

  // Show / hide the armed banner
  const banner = document.getElementById('catchment-armed-banner');
  if (banner) banner.classList.toggle('visible', enabled);

  // Pulse the setup card border when armed
  const setupCard = document.getElementById('catchment-setup-card');
  if (setupCard) setupCard.classList.toggle('armed', enabled);

  const mapCanvas = document.getElementById('leaflet-map-canvas');
  if (enabled) {
    mapCanvas.classList.add('catchment-cursor');
  } else {
    mapCanvas.classList.remove('catchment-cursor');
  }
}

function getCatchmentGoogleApiKey() {
  return document.getElementById('catchment-google-api-key')?.value.trim() || '';
}

function isValidCatchmentGoogleApiKey(key) {
  return key.length >= 20 && key.length <= 200 && !/\s/.test(key);
}

function setCatchmentKeyStatus(message, state = '') {
  const status = document.getElementById('catchment-key-status');
  if (!status) return;
  status.textContent = message;
  status.dataset.state = state;
}

function catchmentRequestOptions(extra = {}) {
  const key = getCatchmentGoogleApiKey();
  const headers = new Headers(extra.headers || {});
  if (key) headers.set('X-Google-Maps-Api-Key', key);
  return { ...extra, headers };
}

function initCatchmentKeyControl() {
  const input = document.getElementById('catchment-google-api-key');
  const visibility = document.getElementById('catchment-key-visibility');
  if (!input) return;
  input.addEventListener('input', () => {
    const key = getCatchmentGoogleApiKey();
    if (!key) setCatchmentKeyStatus('A key is required before the map tool can be armed.');
    else if (!isValidCatchmentGoogleApiKey(key)) setCatchmentKeyStatus('Check the key: it should contain 20–200 characters and no spaces.', 'error');
    else setCatchmentKeyStatus('Key is ready for this browser session.', 'ready');
  });
  visibility?.addEventListener('click', () => {
    const revealing = input.type === 'password';
    input.type = revealing ? 'text' : 'password';
    visibility.textContent = revealing ? 'Hide' : 'Show';
    visibility.setAttribute('aria-pressed', String(revealing));
    visibility.setAttribute('aria-label', `${revealing ? 'Hide' : 'Show'} Google Maps API key`);
    input.focus();
  });
  setCatchmentKeyStatus('A key is required before the map tool can be armed.');
}

function toggleCatchmentMode() {
  const sidebarToggle = document.getElementById('btn-toggle-catchment-mode');
  if (sidebarToggle?.checked) {
    const key = getCatchmentGoogleApiKey();
    if (!isValidCatchmentGoogleApiKey(key)) {
      syncCatchmentMode(false);
      setCatchmentKeyStatus(key ? 'Check the key before arming the map tool.' : 'Paste a restricted Google Maps key first.', 'error');
      document.getElementById('catchment-google-api-key')?.focus();
      return;
    }
  }
  syncCatchmentMode(Boolean(sidebarToggle?.checked));
}

let catchmentQueryRadius = 5.0;
let catchmentQueryTimeMins = 15.0;
let catchmentQuerySpeedKmh = 20.0;
let catchmentQueryMode = 'time';
let catchmentTravelMode = 'DRIVE';
let catchmentLiveTraffic = true;
let catchmentSmoothEdges = true;
let catchmentTimeChipButtons = [];
let catchmentIsochroneSelection = 15;
let catchmentComparisonLookup = new Map();

function selectSegmentMode(mode) {
  toggleCatchmentModeType('time');
}

function updateCatchmentTravelSettings() {
  catchmentTravelMode = 'DRIVE';
  catchmentLiveTraffic = true;
  catchmentSmoothEdges = true;
  calculateDistanceByTimeSpeed();
}

function setCatchmentTimeChipActive(mins) {
  // Target both old .catchment-time-chip and new .catchment-chip
  const chips = document.querySelectorAll('.catchment-time-chip, .catchment-chip');
  chips.forEach(btn => btn.classList.toggle('active', Number(btn.dataset.minutes) === Number(mins)));
  const picker = document.getElementById('catchment-time-picker');
  if (picker) picker.value = String(mins);
}

function selectCatchmentTravelTime(mins, button) {
  const input = document.getElementById('catchment-input-time');
  if (input) input.value = String(mins);
  catchmentQueryTimeMins = Number(mins);
  catchmentIsochroneSelection = Number(mins);
  catchmentQuerySpeedKmh = 20;
  catchmentQueryMode = 'time';
  catchmentQueryRadius = Math.max(1.0, Math.round((catchmentQuerySpeedKmh * (catchmentQueryTimeMins / 60)) * 10) / 10);
  if (input) input.dispatchEvent(new Event('change', { bubbles: true }));
  document.getElementById('catchment-calculated-radius-val').textContent = `${catchmentQueryTimeMins.toFixed(0)}`;
  setCatchmentTimeChipActive(mins);
  updateCatchmentCircleRadius();
}

function toggleCatchmentModeType(mode) {
  const timeGroup = document.getElementById('catchment-input-time-speed-group');
  if (timeGroup) timeGroup.style.display = 'flex';
  calculateDistanceByTimeSpeed();
}

function calculateDistanceByTimeSpeed() {
  const rawTime = parseFloat(document.getElementById('catchment-input-time').value) || catchmentQueryTimeMins || 15;
  const time = Math.min(180, Math.max(1, Math.round(rawTime)));
  const timeInput = document.getElementById('catchment-input-time');
  if (timeInput) timeInput.value = String(time);
  catchmentQuerySpeedKmh = 20;
  catchmentQueryTimeMins = time;
  catchmentQueryMode = 'time';
  
  catchmentQueryRadius = Math.max(1.0, Math.round((catchmentQuerySpeedKmh * (time / 60)) * 10) / 10);
  if (catchmentQueryRadius < 1.0) catchmentQueryRadius = 1.0;
  
  document.getElementById('catchment-calculated-radius-val').textContent = `${catchmentQueryTimeMins.toFixed(0)}`;
  setCatchmentTimeChipActive(time);
  updateCatchmentCircleRadius();
}

function syncCatchmentTimeSelector() {
  const active = Number(catchmentIsochroneSelection || catchmentQueryTimeMins || 15);
  setCatchmentTimeChipActive(active);
  const display = document.getElementById('catchment-calculated-radius-val');
  if (display) display.textContent = String(active);
  const picker = document.getElementById('catchment-time-picker');
  if (picker) picker.value = String(active);
}

document.addEventListener('DOMContentLoaded', () => {
  syncCatchmentTimeSelector();
});

function updateCatchmentCircleRadius() {
  if (catchmentCircle) {
    catchmentCircle.setRadius(catchmentQueryRadius * 1000);
  }
}

// Initialize Wedge Geometry for 9 Zones
function initZonePolygons() {
  const zoneAngles = {
    "North": { start: -22.5, end: 22.5, color: '#3b82f6' },
    "North-East": { start: 22.5, end: 67.5, color: '#10b981' },
    "East": { start: 67.5, end: 112.5, color: '#f59e0b' },
    "South-East": { start: 112.5, end: 157.5, color: '#8b5cf6' },
    "South": { start: 157.5, end: 202.5, color: '#ec4899' },
    "South-West": { start: 202.5, end: 247.5, color: '#6366f1' },
    "West": { start: 247.5, end: 292.5, color: '#14b8a6' },
    "North-West": { start: 292.5, end: 337.5, color: '#84cc16' }
  };

  // 1. Central Zone (Circle at 5km radius)
  const centralCoords = generateCentralCircle(CENTRAL_LAT, CENTRAL_LON, 5.0);
  zonePolygons["Central"] = L.polygon(centralCoords, {
    color: '#ef4444',
    fillColor: '#ef4444',
    weight: 1.5,
    fillOpacity: 0.04,
    dashArray: '3, 4'
  });
  
  zonePolygons["Central"].on('click', () => {
    const tr = document.getElementById('zone-row-central');
    selectZone("Central", tr);
  });

  // 2. Outer sector wedges
  Object.entries(zoneAngles).forEach(([name, cfg]) => {
    const coords = generateWedge(CENTRAL_LAT, CENTRAL_LON, 5.0, 35.0, cfg.start, cfg.end);
    zonePolygons[name] = L.polygon(coords, {
      color: cfg.color,
      fillColor: cfg.color,
      weight: 1.5,
      fillOpacity: 0.04,
      dashArray: '3, 4'
    });

    zonePolygons[name].on('click', () => {
      const rowId = `zone-row-${name.replace(/\s+/g, '-').toLowerCase()}`;
      const tr = document.getElementById(rowId);
      selectZone(name, tr);
    });
  });
}

// Switch Sidebar tabs
function switchTab(tabId) {
  if (tabId === 'micromarkets') tabId = 'zones';
  if (tabId === 'graph') tabId = 'overview';
  activeTab = tabId;
  
  // Update nav buttons style
  document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.classList.remove('active');
    btn.setAttribute('aria-selected', 'false');
    btn.setAttribute('tabindex', '-1');
  });
  const activeButton = document.getElementById(`tab-btn-${tabId}`);
  const activePane = document.getElementById(`pane-${tabId}`);
  if (!activeButton || !activePane) return;
  activeButton.classList.add('active');
  activeButton.setAttribute('aria-selected', 'true');
  activeButton.setAttribute('tabindex', '0');

  // Show/Hide sections
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.remove('active');
  });
  activePane.classList.add('active');
  syncSchoolMapVisibility(tabId === 'schoolmarket');

  // Handle zone boundaries display
  if (tabId === 'zones') {
    Object.values(zonePolygons).forEach(poly => poly.addTo(map));
  } else {
    Object.values(zonePolygons).forEach(poly => map.removeLayer(poly));
    if (activeZoneLabelMarker) {
      map.removeLayer(activeZoneLabelMarker);
      activeZoneLabelMarker = null;
    }
  }



  if (tabId === 'commercial') {
    activateCommercialMode();
  } else {
    deactivateCommercialMode();
  }

}

// Dynamic metro lookup via Overpass API

function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

function formatNumber(value, decimals = 0) {
  const numeric = Number(value || 0);
  return numeric.toLocaleString(undefined, {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals
  });
}

function formatCurrencyShort(value) {
  const numeric = Number(value || 0);
  if (numeric >= 10000000) return `₹${(numeric / 10000000).toFixed(1)}Cr`;
  if (numeric >= 100000) return `₹${(numeric / 100000).toFixed(1)}L`;
  if (numeric >= 1000) return `₹${Math.round(numeric / 1000)}k`;
  return `₹${Math.round(numeric).toLocaleString()}`;
}

function getRolledUpSocietyColor(quartile) {
  switch (String(quartile || '').trim()) {
    case 'Q4': return '#d97706';
    case 'Q3': return '#059669';
    case 'Q2': return '#2563eb';
    case 'Q1': return '#7c3aed';
    default: return '#d97706';
  }
}

function getRolledUpAssetsScopeData(scope) {
  if (scope === 'summary') {
    const quartile = summaryQuartileMode || 'Q4';
    const societies = (projectQuartileAssets || []).filter(item => String(item.quartile_analysis_1 || '').trim() === quartile);
    return {
      societies,
      hospitals: layerData.hospitals || [],
      offices: layerData.sez_offices || [],
      schools: getSchoolAudienceCampuses(),
      quartile
    };
  }

  if (scope === 'zone') {
    return {
      societies: activeDetailsData.zone?.societies || [],
      hospitals: activeDetailsData.zone?.hospitals || [],
      offices: activeDetailsData.zone?.offices || [],
      schools: activeDetailsData.zone?.schools || []
    };
  }

  if (scope === 'hex') {
    return {
      societies: activeDetailsData.hex?.societies || [],
      hospitals: activeDetailsData.hex?.hospitals || [],
      offices: activeDetailsData.hex?.offices || [],
      schools: activeDetailsData.hex?.schools || []
    };
  }

  if (scope === 'catchment') {
    return {
      societies: activeDetailsData.catchment?.societies || [],
      hospitals: activeCatchmentData?.hospitals || [],
      offices: activeCatchmentData?.offices || [],
      schools: activeDetailsData.catchment?.schools || []
    };
  }

  if (scope === 'commercial') {
    const metrics = selectedCommercialListing?.catchment || {};
    return {
      societies: metrics.societies || [],
      hospitals: metrics.hospitals || [],
      offices: metrics.offices || [],
      schools: []
    };
  }

  if (scope === 'market') {
    return {
      societies: activeDetailsData.market?.societies || [],
      hospitals: (layerData.hospitals || []).filter(h => selectedMarket !== null && (layerData.microMarkets?.disjoint_micro_markets?.[selectedMarket]?.hex_ids || []).includes(h.hex_id)),
      offices: (layerData.sez_offices || []).filter(o => selectedMarket !== null && (layerData.microMarkets?.disjoint_micro_markets?.[selectedMarket]?.hex_ids || []).includes(o.hex_id)),
      schools: activeDetailsData.market?.schools || []
    };
  }

  return { societies: [], hospitals: [], offices: [], schools: [] };
}

function clearRolledUpAssetsLayer() {
  if (rolledUpAssetsLayer && map && map.hasLayer(rolledUpAssetsLayer)) {
    map.removeLayer(rolledUpAssetsLayer);
  }
  rolledUpAssetsLayer = null;
  rolledUpAssetsScope = null;
}

function updateSummaryQuartileButtonState() {
  ['Q4', 'Q3', 'Q2', 'Q1'].forEach(quartile => {
    const button = document.getElementById(`summary-quartile-${quartile}`);
    if (button) button.classList.toggle('active', quartile === summaryQuartileMode);
  });
}

function setSummaryQuartileMode(quartile) {
  summaryQuartileMode = quartile || 'Q4';
  updateSummaryQuartileButtonState();
  renderRolledUpAssetsMapLayers('summary');
}

function buildRolledUpAssetsControlsHtml(scope, includeQuartileButtons = false) {
  const scopeKey = String(scope || 'summary');
  const scopeSchoolCount = (getRolledUpAssetsScopeData(scopeKey).schools || []).length;
  const quartileButtons = includeQuartileButtons
    ? `
      <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px;">
        ${['Q4', 'Q3', 'Q2', 'Q1'].map(q => `<button type="button" id="${scopeKey}-quartile-${q}" class="segment-btn${summaryQuartileMode === q ? ' active' : ''}" onclick="setSummaryQuartileMode('${q}')">${q}</button>`).join('')}
      </div>
    `
    : '';

  return `
    <div class="market-map-controls" style="background: var(--bg-sidebar); border: 1px solid var(--border-light); border-radius: 4px; padding: 10px; margin-bottom: 12px; font-size: 11px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid var(--border-light); padding-bottom: 6px;">
        <strong>Show Rolled-up Assets on Map:</strong>
        ${includeQuartileButtons ? '<span style="font-size: 10px; color: var(--text-muted);">Q4 hospitals and workplaces stay visible as context</span>' : ''}
      </div>
      <div style="display:flex; justify-content: space-between; align-items:center; gap: 8px; margin-bottom: 8px;">
        <span style="font-size: 10px; color: var(--text-muted);">Toggle all rolled-up layers</span>
        <label class="switch-container">
          <input id="toggle-${scopeKey}-all" type="checkbox" checked onchange="renderRolledUpAssetsMapLayers('${scopeKey}', 'toggle-${scopeKey}-all')"/>
          <span class="switch-slider"></span>
        </label>
      </div>
      ${quartileButtons}
      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;">
        <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
          <input id="toggle-${scopeKey}-societies" type="checkbox" checked onchange="renderRolledUpAssetsMapLayers('${scopeKey}', 'toggle-${scopeKey}-societies')"/>
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#d97706;"></span> Societies
        </label>
        <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
          <input id="toggle-${scopeKey}-offices" type="checkbox" checked onchange="renderRolledUpAssetsMapLayers('${scopeKey}', 'toggle-${scopeKey}-offices')"/>
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#2563eb;"></span> Workplaces
        </label>
        <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
          <input id="toggle-${scopeKey}-hospitals" type="checkbox" checked onchange="renderRolledUpAssetsMapLayers('${scopeKey}', 'toggle-${scopeKey}-hospitals')"/>
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#ef4444;"></span> Hospitals
        </label>
        <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
          <input id="toggle-${scopeKey}-schools" type="checkbox" checked onchange="renderRolledUpAssetsMapLayers('${scopeKey}', 'toggle-${scopeKey}-schools')"/>
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#8b5cf6;"></span> Schools (${formatNumber(scopeSchoolCount)})
        </label>
      </div>
    </div>
  `;
}

function renderRolledUpAssetsMapLayers(scope = rolledUpAssetsScope, changedId = null) {
  if (!map || !window.L) return;
  const data = getRolledUpAssetsScopeData(scope);
  const scopeKey = String(scope || 'summary');
  const allId = `toggle-${scopeKey}-all`;
  const socId = `toggle-${scopeKey}-societies`;
  const offId = `toggle-${scopeKey}-offices`;
  const hospId = `toggle-${scopeKey}-hospitals`;
  const schoolId = `toggle-${scopeKey}-schools`;

  const allEl = document.getElementById(allId);
  const socEl = document.getElementById(socId);
  const offEl = document.getElementById(offId);
  const hospEl = document.getElementById(hospId);
  const schoolEl = document.getElementById(schoolId);

  if (allEl && changedId === allId) {
    const shouldEnable = allEl.checked;
    if (socEl) socEl.checked = shouldEnable;
    if (offEl) offEl.checked = shouldEnable;
    if (hospEl) hospEl.checked = shouldEnable;
    if (schoolEl) schoolEl.checked = shouldEnable;
  } else if (changedId === socId || changedId === offId || changedId === hospId || changedId === schoolId) {
    if (allEl && (!socEl?.checked || !offEl?.checked || !hospEl?.checked || !schoolEl?.checked)) {
      allEl.checked = false;
    } else if (allEl && socEl?.checked && offEl?.checked && hospEl?.checked && schoolEl?.checked) {
      allEl.checked = true;
    }
  }

  const societiesEnabled = socEl ? socEl.checked : true;
  const officesEnabled = offEl ? offEl.checked : true;
  const hospitalsEnabled = hospEl ? hospEl.checked : true;
  const schoolsEnabled = schoolEl ? schoolEl.checked : true;

  clearRolledUpAssetsLayer();
  const markers = [];
  const societies = data.societies || [];
  const hospitals = data.hospitals || [];
  const offices = data.offices || [];
  const schools = data.schools || [];
  const isLocked = !isUnlocked();

  if (societiesEnabled) {
    societies.forEach((soc, idx) => {
      const isLockedItem = isLocked && idx >= 3;
      const quartile = soc.quartile_analysis_1 || soc.quartile || summaryQuartileMode || 'Q4';
      const markerColor = scopeKey === 'summary' ? getRolledUpSocietyColor(quartile) : '#d97706';
      const name = isLockedItem ? 'Restricted residential project' : soc.name;
      const marker = L.circleMarker([soc.lat, soc.lon], {
        radius: 6,
        color: '#ffffff',
        fillColor: markerColor,
        fillOpacity: 0.88,
        weight: 1.5
      });
      marker.bindPopup(`
        <div style="font-family:'Space Grotesk',sans-serif; font-size:11.5px; line-height:1.45;">
          <strong style="color:var(--text-main); font-size:12.5px;">🏢 ${escapeHTML(name)}</strong><br/>
          <span style="color:${markerColor}; font-weight:600;">${escapeHTML(quartile)}</span><br/>
          ${scopeKey === 'summary' ? `Type: <strong>${escapeHTML(soc.project_type || 'NA')}</strong><br/>` : ''}
          Known units: <strong>${isLockedItem ? 'Restricted' : (soc.units == null ? 'Unavailable' : formatNumber(soc.units))}</strong><br/>
          Locality: <span>${escapeHTML(soc.locality || 'NA')}</span>
        </div>
      `);
      marker.on('click', () => {
        focusOnPoi({
          lat: soc.lat,
          lon: soc.lon,
          name: soc.name,
          units: soc.units || 0,
          price: soc.price || soc.price_sqft || 0,
          locality: soc.locality || 'NA',
          category: soc.category || quartile
        }, 'society');
      });
      markers.push(marker);
    });
  }

  if (officesEnabled) {
    offices.forEach((off, idx) => {
      const isLockedItem = isLocked && idx >= 3;
      const marker = L.circleMarker([off.lat, off.lon], {
        radius: 6,
        color: '#ffffff',
        fillColor: '#2563eb',
        fillOpacity: 0.85,
        weight: 1.5
      });
      marker.bindPopup(`
        <div style="font-family:'Space Grotesk',sans-serif; font-size:11.5px; line-height:1.45;">
          <strong style="color:var(--text-main); font-size:12.5px;">💼 ${escapeHTML(isLockedItem ? 'Restricted Workplace Name' : off.name)}</strong><br/>
          <span style="color:#2563eb; font-weight:600;">${escapeHTML(off.company_prominence_tier || 'Enterprise')}</span><br/>
          Capacity Score: <strong>${isLockedItem ? 'Restricted' : formatNumber(off.office_rank_score || 0, 0)}</strong><br/>
          Office area: <span>${escapeHTML(off.sez_name || off.locality || 'NA')}</span>
        </div>
      `);
      marker.on('click', () => focusOnPoi({
        lat: off.lat,
        lon: off.lon,
        name: off.name,
        office_rank_score: off.office_rank_score || 0,
        company_prominence_tier: off.company_prominence_tier || 'Enterprise'
      }, 'office'));
      markers.push(marker);
    });
  }

  if (hospitalsEnabled) {
    hospitals.forEach((h, idx) => {
      const isLockedItem = isLocked && idx >= 3;
      const marker = L.circleMarker([h.lat, h.lon], {
        radius: 6,
        color: '#ffffff',
        fillColor: '#ef4444',
        fillOpacity: 0.85,
        weight: 1.5
      });
      marker.bindPopup(`
        <div style="font-family:'Space Grotesk',sans-serif; font-size:11.5px; line-height:1.45;">
          <strong style="color:var(--text-main); font-size:12.5px;">🏥 ${escapeHTML(isLockedItem ? 'Restricted Hospital Name' : h.name)}</strong><br/>
          <span style="color:#ef4444; font-weight:600;">${escapeHTML(h.category || 'Hospital')}</span><br/>
          Beds Count: <strong>${isLockedItem ? 'Restricted' : formatNumber(h.beds || 0, 0)}</strong> &middot; Rating: <strong>${isLockedItem ? 'Restricted' : formatNumber(h.rating || 0, 1)}⭐</strong>
        </div>
      `);
      marker.on('click', () => focusOnPoi({
        lat: h.lat,
        lon: h.lon,
        name: h.name,
        rating: h.rating || 0,
        beds: h.beds || 0,
        category: h.category || 'Hospital'
      }, 'hospital'));
      markers.push(marker);
    });
  }

  if (schoolsEnabled) {
    schools.forEach(school => {
      const markerColor = '#8b5cf6';
      const marker = L.circleMarker([school.lat, school.lon], {
        radius: 6,
        color: '#ffffff',
        fillColor: markerColor,
        fillOpacity: 0.88,
        weight: 1.5
      });
      const urlLink = /^https?:\/\//i.test(school.url || '')
        ? `<br/>Link: <a href="${escapeHTML(school.url)}" rel="noopener noreferrer" target="_blank" style="color:#8b5cf6; font-weight:600; text-decoration:underline;">View source</a>`
        : '';
      const boardsValue = school.boards || school.board || [];
      const boardsList = (Array.isArray(boardsValue) ? boardsValue.join(', ') : String(boardsValue)) || 'Unknown';
      marker.bindPopup(`
        <div style="font-family:'Space Grotesk',sans-serif; font-size:11.5px; line-height:1.45;">
          <strong style="color:var(--text-main); font-size:12.5px;">🏫 ${escapeHTML(school.name)}</strong><br/>
          ${escapeHTML(activeLegacyCategory().label)} enrollment (Grades 2-9): <strong>${formatNumber(school.audience_enrollment ?? school.students_grades_2_9 ?? 0)}</strong><br/>
          Total enrollment: <strong>${formatNumber(school.students_total || 0)}</strong><br/>
          Fee bucket: <strong>${escapeHTML(school.fee_bucket || school.fee_tier || 'NA')}</strong><br/>
          Board: <span>${escapeHTML(boardsList)}</span>
          ${urlLink}
        </div>
      `);
      marker.on('click', () => showSchoolCampusDetails(school.campus_id));
      markers.push(marker);
    });
  }

  if (markers.length > 0) {
    rolledUpAssetsLayer = L.layerGroup(markers).addTo(map);
    rolledUpAssetsScope = scopeKey;
  }
}

window.renderRolledUpAssetsMapLayers = renderRolledUpAssetsMapLayers;
window.setSummaryQuartileMode = setSummaryQuartileMode;

function clientHaversineKm(lat1, lon1, lat2, lon2) {
  const radius = 6371.0088;
  const phi1 = lat1 * Math.PI / 180;
  const phi2 = lat2 * Math.PI / 180;
  const dPhi = (lat2 - lat1) * Math.PI / 180;
  const dLam = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2) ** 2;
  return 2 * radius * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function calculateMetroScore(minDistance) {
  let score = 8;
  if (minDistance <= 0.5) score = 100;
  else if (minDistance <= 1) score = 92;
  else if (minDistance <= 2) score = 78;
  else if (minDistance <= 3.5) score = 62;
  else if (minDistance <= 5) score = 42;
  else score = Math.max(8, 35 - (minDistance - 5) * 3.5);
  return Number(score.toFixed(2));
}

function getLocalNearestMetro(lat, lon) {
  const cityStations = (layerData.metro_stations || [])
    .map(station => ({
      name: station.name,
      lat: Number(station.lat ?? station.latitude),
      lon: Number(station.lon ?? station.longitude),
      line: station.line || station.network || 'Unknown'
    }))
    .filter(station => station.name && Number.isFinite(station.lat) && Number.isFinite(station.lon));

  if (cityStations.length) {
    const mapped = cityStations.map(station => {
      const distance = clientHaversineKm(lat, lon, station.lat, station.lon);
      return {
        name: station.name,
        line: station.line || 'Unknown',
        distance_km: Number(distance.toFixed(2)),
        duration_mins: Number(((distance / 20.0) * 60).toFixed(1)),
        score: calculateMetroScore(distance),
        routing_method: 'city_station_file'
      };
    }).sort((a, b) => a.distance_km - b.distance_km);
    const stations_out = mapped.slice(0, 3);
    const primary = stations_out[0] || { name: 'NA', distance_km: 99, score: 0 };
    return {
      nearest_station: primary.name,
      distance_km: primary.distance_km,
      score: primary.score,
      stations: stations_out
    };
  }

  if (!isLegacyBengaluru()) {
    return {
      nearest_station: 'Metro evidence unavailable',
      distance_km: null,
      score: 0,
      stations: [],
      status: 'unavailable',
      warning: `${legacyCityLabel()} metro station source is unavailable; Bengaluru fallback stations were not substituted.`
    };
  }

  const stations = [
    { name: "Majestic Metro Station", lat: 12.9756, lon: 77.5728 },
    { name: "MG Road Metro Station", lat: 12.9754, lon: 77.6067 },
    { name: "Indiranagar Metro Station", lat: 12.9784, lon: 77.6386 },
    { name: "Halasuru Metro Station", lat: 12.9778, lon: 77.6236 },
    { name: "Trinity Metro Station", lat: 12.9745, lon: 77.6169 },
    { name: "Cubbon Park Metro Station", lat: 12.9809, lon: 77.5975 },
    { name: "Vidhana Soudha Metro Station", lat: 12.9798, lon: 77.5928 },
    { name: "Sir M. Visvesvaraya Metro Station", lat: 12.9747, lon: 77.5835 },
    { name: "City Railway Station Metro Station", lat: 12.9757, lon: 77.5658 },
    { name: "Magadi Road Metro Station", lat: 12.9755, lon: 77.5501 },
    { name: "Hosahalli Metro Station", lat: 12.9751, lon: 77.5401 },
    { name: "Vijayanagar Metro Station", lat: 12.9756, lon: 77.5300 },
    { name: "Attiguppe Metro Station", lat: 12.9698, lon: 77.5222 },
    { name: "Deepanjali Nagar Metro Station", lat: 12.9638, lon: 77.5181 },
    { name: "Mysuru Road Metro Station", lat: 12.9536, lon: 77.5288 },
    { name: "Nayandahalli Metro Station", lat: 12.9427, lon: 77.5218 },
    { name: "Rajarajeshwari Nagar Metro Station", lat: 12.9304, lon: 77.5186 },
    { name: "Jnanabharathi Metro Station", lat: 12.9234, lon: 77.5085 },
    { name: "Pattanagere Metro Station", lat: 12.9157, lon: 77.4984 },
    { name: "Kengeri Metro Station", lat: 12.9090, lon: 77.4857 },
    { name: "Kengeri Bus Terminal Metro Station", lat: 12.9031, lon: 77.4729 },
    { name: "Challaghatta Metro Station", lat: 12.9022, lon: 77.4589 },
    { name: "SV Road Metro Station", lat: 12.9840, lon: 77.6534 },
    { name: "Baiyappanahalli Metro Station", lat: 12.9907, lon: 77.6403 },
    { name: "Benniganahalli Metro Station", lat: 12.9912, lon: 77.6621 },
    { name: "KR Puram Metro Station", lat: 12.9959, lon: 77.6749 },
    { name: "Singayyanapalya Metro Station", lat: 12.9953, lon: 77.6881 },
    { name: "Garudacharpalya Metro Station", lat: 12.9934, lon: 77.7018 },
    { name: "Hoodi Junction Metro Station", lat: 12.9918, lon: 77.7142 },
    { name: "Seetharampalya Metro Station", lat: 12.9897, lon: 77.7265 },
    { name: "Kundalahalli Metro Station", lat: 12.9839, lon: 77.7136 },
    { name: "Nallurhalli Metro Station", lat: 12.9792, lon: 77.7288 },
    { name: "Sadarmangla Metro Station", lat: 12.9803, lon: 77.7410 },
    { name: "Pattandur Agrahara Metro Station", lat: 12.9822, lon: 77.7516 },
    { name: "Sri Sathya Sai Hospital Metro Station", lat: 12.9788, lon: 77.7423 },
    { name: "Kadugodi Tree Park Metro Station", lat: 12.9882, lon: 77.7602 },
    { name: "Hopefarm Channasandra Metro Station", lat: 12.9936, lon: 77.7712 },
    { name: "Whitefield Metro Station", lat: 12.9951, lon: 77.7821 },
    { name: "Yeshwanthpur Metro Station", lat: 13.0235, lon: 77.5498 },
    { name: "Sandal Soap Factory Metro Station", lat: 13.0142, lon: 77.5539 },
    { name: "Mahalakshmi Metro Station", lat: 13.0084, lon: 77.5498 },
    { name: "Rajajinagar Metro Station", lat: 13.0001, lon: 77.5497 },
    { name: "Kuvempu Road Metro Station", lat: 12.9937, lon: 77.5562 },
    { name: "Srirampura Metro Station", lat: 12.9892, lon: 77.5629 },
    { name: "Sampige Road Metro Station", lat: 12.9894, lon: 77.5714 },
    { name: "National College Metro Station", lat: 12.9515, lon: 77.5735 },
    { name: "Lalbagh Metro Station", lat: 12.9463, lon: 77.5800 },
    { name: "South End Circle Metro Station", lat: 12.9382, lon: 77.5803 },
    { name: "Jayanagar Metro Station", lat: 12.9304, lon: 77.5824 },
    { name: "RV Road Metro Station", lat: 12.9218, lon: 77.5824 },
    { name: "Banashankari Metro Station", lat: 12.9154, lon: 77.5736 },
    { name: "JP Nagar Metro Station", lat: 12.9074, lon: 77.5736 },
    { name: "Yelachenahalli Metro Station", lat: 12.8961, lon: 77.5727 },
    { name: "Konanakunte Cross Metro Station", lat: 12.8845, lon: 77.5737 },
    { name: "Doddakallasandra Metro Station", lat: 12.8732, lon: 77.5750 },
    { name: "Vajrahalli Metro Station", lat: 12.8631, lon: 77.5760 },
    { name: "Talaghattapura Metro Station", lat: 12.8530, lon: 77.5770 },
    { name: "Silk Institute Metro Station", lat: 12.8429, lon: 77.5780 },
    { name: "Goraguntepalya Metro Station", lat: 13.0287, lon: 77.5401 },
    { name: "Peenya Metro Station", lat: 13.0330, lon: 77.5342 },
    { name: "Peenya Industry Metro Station", lat: 13.0360, lon: 77.5252 },
    { name: "Jalahalli Metro Station", lat: 13.0454, lon: 77.5204 },
    { name: "Dasarahalli Metro Station", lat: 13.0514, lon: 77.5133 },
    { name: "Nagasandra Metro Station", lat: 13.0614, lon: 77.5033 },
    { name: "Madavara Metro Station", lat: 13.0722, lon: 77.4925 }
  ];
  
  const mapped = stations.map(station => {
    const distance = clientHaversineKm(lat, lon, station.lat, station.lon);
    return {
      name: station.name,
      line: station.line || 'Unknown',
      distance_km: Number(distance.toFixed(2)),
      duration_mins: Number(((distance / 20.0) * 60).toFixed(1)),
      score: calculateMetroScore(distance),
      routing_method: 'local_fallback'
    };
  });
  
  mapped.sort((a, b) => a.distance_km - b.distance_km);
  const stations_out = mapped.slice(0, 3);
  const primary = stations_out[0] || { name: 'NA', distance_km: 99, score: 0 };
  
  return {
    nearest_station: primary.name,
    distance_km: primary.distance_km,
    score: primary.score,
    stations: stations_out
  };
}

async function nearestCommercialMetro(lat, lon) {
  // Browser code never receives Google credentials. The bundled station
  // evidence provides a deterministic fallback for the legacy commercial
  // listing workflow; live school routing remains server-side only.
  return getLocalNearestMetro(lat, lon);
  const apiKey = null;
  try {
    // 1. Search for subway stations using Places API
    const placesUrl = "https://places.googleapis.com/v1/places:searchNearby";
    const placesRes = await fetch(placesUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": apiKey,
        "X-Goog-FieldMask": "places.id,places.displayName,places.location"
      },
      body: JSON.stringify({
        includedTypes: ["subway_station"],
        maxResultCount: 10,
        locationRestriction: {
          circle: {
            center: { latitude: lat, longitude: lon },
            radius: 15000.0
          }
        }
      })
    });
    if (!placesRes.ok) throw new Error("Places API error " + placesRes.status);
    const placesData = await placesRes.json();
    const candidates = placesData.places || [];
    
    if (candidates.length === 0) {
      return {
        nearest_station: "NA",
        distance_km: 99.0,
        score: 0.0,
        stations: []
      };
    }
    
    // 2. Compute route matrix via Routes API
    const routesUrl = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix";
    const destinations = candidates.map(c => ({
      waypoint: {
        location: {
          latLng: {
            latitude: c.location.latitude,
            longitude: c.location.longitude
          }
        }
      }
    }));
    const routesRes = await fetch(routesUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": apiKey,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status"
      },
      body: JSON.stringify({
        origins: [{ waypoint: { location: { latLng: { latitude: lat, longitude: lon } } } }],
        destinations: destinations,
        travelMode: "DRIVE"
      })
    });
    if (!routesRes.ok) throw new Error("Routes API error " + routesRes.status);
    const matrixData = await routesRes.json();
    
    const results = [];
    matrixData.forEach(row => {
      if (row.originIndex !== 0) return;
      const dest_idx = parseInt(row.destinationIndex);
      if (isNaN(dest_idx) || dest_idx < 0 || dest_idx >= candidates.length) return;
      const cand = candidates[dest_idx];
      const dist_m = row.distanceMeters;
      const dur_s = row.duration ? parseFloat(row.duration.replace("s", "")) : null;
      if (dist_m !== undefined && dist_m >= 0) {
        const dist_km = Number((dist_m / 1000.0).toFixed(2));
        const dur_min = dur_s !== null ? Number((dur_s / 60.0).toFixed(1)) : Number(((dist_km / 20.0) * 60).toFixed(1));
        results.push({
          name: cand.displayName.text,
          line: "Metro",
          distance_km: dist_km,
          duration_mins: dur_min,
          score: calculateMetroScore(dist_km),
          routing_method: "google_api"
        });
      }
    });
    
    results.sort((a, b) => a.distance_km - b.distance_km);
    const stations_out = results.slice(0, 3);
    const primary = stations_out[0] || { name: 'NA', distance_km: 99, score: 0 };
    
    return {
      nearest_station: primary.name,
      distance_km: primary.distance_km,
      score: primary.score,
      stations: stations_out
    };
  } catch (e) {
    console.error("Google Metro Lookup failed:", e);
    throw e;
  }
}

async function calculateRoadVisibility(lat, lon) {
  // Road enrichment previously exposed a browser credential. Keep the
  // optional field neutral until a server-side enrichment endpoint exists.
  return { road_type: 'Unknown', score: 20 };
  const apiKey = null;
  try {
    // 1. Call Google Roads API Snap to Roads
    const roadsUrl = `https://roads.googleapis.com/v1/nearestRoads?points=${lat},${lon}&key=${apiKey}`;
    const roadsRes = await fetch(roadsUrl);
    if (!roadsRes.ok) throw new Error("Roads API error " + roadsRes.status);
    const roadsData = await roadsRes.json();
    const snappedPoints = roadsData.snappedPoints || [];
    
    if (snappedPoints.length === 0) {
      return { road_type: 'Unknown', score: 20 };
    }
    
    // Find closest snapped point
    let closestPoint = null;
    let minDistance = Infinity;
    snappedPoints.forEach(pt => {
      const d = clientHaversineKm(lat, lon, pt.location.latitude, pt.location.longitude);
      if (d < minDistance) {
        minDistance = d;
        closestPoint = pt;
      }
    });
    
    // If the snapped road is within 100m (0.1 km)
    if (closestPoint && minDistance <= 0.1) {
      // 2. Fetch road name using Google Place Details with placeId
      const placeId = closestPoint.placeId;
      const detailsUrl = `https://maps.googleapis.com/maps/api/place/details/json?place_id=${placeId}&fields=name&key=${apiKey}`;
      const detailsRes = await fetch(detailsUrl);
      if (!detailsRes.ok) throw new Error("Place Details error " + detailsRes.status);
      const detailsData = await detailsRes.json();
      const placeName = detailsData.result?.name || "";
      
      let bestRoadType = 'residential';
      let highestScore = 40;
      
      const lowerName = placeName.toLowerCase();
      if (lowerName.includes("highway") || lowerName.includes("national highway") || /nh\s*\d+/.test(lowerName) || /ah\s*\d+/.test(lowerName) || lowerName.includes("ring road") || lowerName.includes("orr") || lowerName.includes("expressway") || lowerName.includes("flyover") || lowerName.includes("trunk")) {
        bestRoadType = 'primary';
        highestScore = 100;
      } else if (lowerName.includes("main road") || lowerName.includes("double road") || lowerName.includes("80 feet") || lowerName.includes("100 feet") || lowerName.includes("varthur") || lowerName.includes("sarjapur") || lowerName.includes("hosur") || lowerName.includes("tumkur") || lowerName.includes("kanakapura") || lowerName.includes("bannerghatta")) {
        bestRoadType = 'primary';
        highestScore = 100;
      } else if (lowerName.includes("road") || lowerName.includes("rd") || lowerName.includes("avenue") || lowerName.includes("boulevard")) {
        bestRoadType = 'secondary';
        highestScore = 80;
      } else if (lowerName === "unnamed road" || lowerName.includes("cross") || lowerName.includes("lane") || lowerName.includes("layout") || lowerName.includes("path") || lowerName.includes("street")) {
        bestRoadType = 'residential';
        highestScore = 40;
      } else {
        bestRoadType = 'service';
        highestScore = 20;
      }
      
      return {
        road_type: bestRoadType,
        score: highestScore
      };
    }
    
    return { road_type: 'Unknown', score: 20 };
  } catch (e) {
    console.error("Google Roads/Visibility Lookup failed:", e);
    return { road_type: 'Unknown', score: 20 };
  }
}

function normalizeCommercialListing(listing) {
  const catchment = listing.catchment || {};
  const center = catchment.center || {};
  const lat = Number(listing.latitude ?? listing.lat ?? center.lat);
  const lon = Number(listing.longitude ?? listing.lon ?? center.lon);
  const metro = listing.metro || { nearest_station: 'NA', distance_km: 99, score: 0 };
  return {
    ...listing,
    listing_id: String(listing.listing_id || listing.id || `commercial_${commercialListings.length + 1}`),
    title: listing.title || listing.name || 'Commercial listing',
    property_type: listing.property_type || 'Office Space',
    price: Number(listing.price || listing.monthly_rent || 0),
    sqft: Number(listing.sqft || listing.area_sqft || 0),
    floor: listing.floor || 'Mid',
    amenities: Array.isArray(listing.amenities) ? listing.amenities : [],
    source: listing.source || 'saved',
    latitude: lat,
    longitude: lon,
    metro,
    catchment: {
      ...catchment,
      center: { lat, lon },
      metrics: catchment.metrics || {},
      income_bands: catchment.income_bands || {},
      societies: catchment.societies || [],
      hospitals: catchment.hospitals || [],
      radius_expansion: catchment.radius_expansion || catchment.comparison || []
    }
  };
}

function updateCommercialStats() {
  setTextIfExists('commercial-total-count', formatNumber(commercialListings.length));
  setTextIfExists('commercial-visible-count', formatNumber(rankedCommercialListings.length));
  setTextIfExists('commercial-top-score', rankedCommercialListings.length ? rankedCommercialListings[0].commercial_score : '0');
}

async function deleteCommercialListing(listingId) {
  if (!confirm("Are you sure you want to delete this listing?")) return;
  try {
    const res = await fetch(`/api/listings?id=${encodeURIComponent(listingId)}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error("HTTP status " + res.status);
    const data = await res.json();
    if (data.status === 'success') {
      commercialListings = commercialListings.filter(item => item.listing_id !== listingId);
      rankedCommercialListings = rankedCommercialListings.filter(item => item.listing_id !== listingId);
      commercialComparisonSet.delete(listingId);
      
      if (selectedCommercialListing?.listing_id === listingId) {
        clearCommercialSelection();
      } else {
        renderCommercialList();
        renderCommercialMarkers();
        renderCommercialComparison();
      }
      updateCommercialStats();
    } else {
      alert(`Error deleting listing: ${data.message || 'Unknown error'}`);
    }
  } catch (e) {
    console.error("Failed to delete listing:", e);
    alert("Failed to delete listing due to connection error.");
  }
}
window.deleteCommercialListing = deleteCommercialListing;

function initCommercialModule() {
  const totalEl = document.getElementById('commercial-total-count');
  if (totalEl) totalEl.textContent = formatNumber(commercialListings.length);
  setCommercialMode('browse');
  applyCommercialPreferences();
  updateCommercialStats();
}

function getCommercialPreferences() {
  const checkedAmenities = Array.from(document.querySelectorAll('#commercial-amenity-filter input:checked')).map(input => input.value);
  const numberValue = id => {
    const value = Number(document.getElementById(id)?.value || 0);
    return Number.isFinite(value) && value > 0 ? value : null;
  };
  return {
    propertyType: document.getElementById('commercial-filter-type')?.value || 'all',
    sqftMin: numberValue('commercial-filter-sqft-min'),
    sqftMax: numberValue('commercial-filter-sqft-max'),
    priceMin: numberValue('commercial-filter-price-min'),
    priceMax: numberValue('commercial-filter-price-max'),
    floor: document.getElementById('commercial-filter-floor')?.value || 'any',
    transit: document.getElementById('commercial-filter-transit')?.value || 'balanced',
    amenities: checkedAmenities,
    searchTerm: (commercialListingFilterTerm || '').trim().toLowerCase()
  };
}

function rangeFit(value, min, max) {
  if (min == null && max == null) return 100;
  if (min != null && value < min) return Math.max(0, 100 - ((min - value) / Math.max(min, 1)) * 100);
  if (max != null && value > max) return Math.max(0, 100 - ((value - max) / Math.max(max, 1)) * 100);
  return 100;
}

function calculateCommercialScore(listing, preferences = {}) {
  if (!listing) return { final: 0, components: {} };
  const catchment = listing.catchment || {};
  const metrics = catchment.metrics || {};
  const metro = listing.metro || {};
  const visibility = listing.visibility || {};
  const price = Number(listing.price || 0);
  const sqft = Number(listing.sqft || 0);
  const floor = listing.floor || 'Mid';
  const propertyType = listing.property_type || 'Office Space';
  const amenities = listing.amenities || [];
  const preferredAmenities = Array.isArray(preferences.amenities) ? preferences.amenities : [];

  // 1. Context score (0-100) based on known residential units, not household proxies.
  const knownUnits = Number(metrics.direct_total_units || metrics.known_residential_units || 0);
  const catchmentScore = Math.min(100, Math.round((knownUnits / 25000) * 100));

  // 2. Metro Score (0-100)
  const metroScore = Math.round(Number(metro.score || 0));

  // 3. Preference Score (0-100) - property type and road visibility
  let typeScore = 70;
  if (propertyType === 'Learning Centre') typeScore = 100;
  else if (propertyType === 'High Street Retail') typeScore = 90;
  else if (propertyType === 'Office Space' || propertyType === 'Managed Office') typeScore = 80;

  const visibilityScore = Math.round(Number(visibility.score || 20));
  const preferenceScore = Math.round((typeScore + visibilityScore) / 2);

  // 4. Amenities Score (0-100)
  const amenitiesScore = Math.min(100, Math.round((amenities.length / 5) * 100));

  // 5. Floor Score (0-100)
  let floorScore = 70;
  if (floor === 'Ground') floorScore = 100;
  else if (floor === 'Lower' || floor === 'Mid') floorScore = 85;
  else if (floor === 'Upper') floorScore = 70;

  // 6. Price Score (0-100) - suitability of rent per sqft
  let priceScore = 70;
  if (sqft > 0) {
    const rentPerSqft = price / sqft;
    if (rentPerSqft <= 60) priceScore = 100;
    else if (rentPerSqft <= 100) priceScore = 90;
    else if (rentPerSqft <= 150) priceScore = 75;
    else priceScore = 50;
  }

  const queryPriceScore = rangeFit(price, preferences.priceMin, preferences.priceMax);
  const querySqftScore = rangeFit(sqft, preferences.sqftMin, preferences.sqftMax);
  const transitScore = preferences.transit === 'within_2km'
    ? Math.max(0, 100 - Math.max(0, Number(metro.distance_km || 999) - 2) * 30)
    : 50;
  const preferredAmenityScore = preferredAmenities.length
    ? Math.min(100, Math.round((preferredAmenities.filter(item => amenities.map(a => String(a).toLowerCase()).includes(String(item).toLowerCase())).length / preferredAmenities.length) * 100))
    : 50;

  // 7. Confidence Score (0-100) - POI density in catchment
  const totalPois = Number(metrics.society_count || 0) + Number(metrics.hospital_count || 0);
  const confidenceScore = Math.min(100, Math.round((totalPois / 40) * 100));
  const commuteSummary = catchment.commute || summarizeCommuteForHexIds(catchment.matched_hex_ids || []);
  const commuteScore = Math.round(Number(commuteSummary?.score || 50));

  const fitSignals = [];
  if (preferences.priceMin != null || preferences.priceMax != null) fitSignals.push(queryPriceScore);
  if (preferences.sqftMin != null || preferences.sqftMax != null) fitSignals.push(querySqftScore);
  if (preferredAmenities.length) fitSignals.push(preferredAmenityScore);
  if (preferences.transit === 'within_2km') fitSignals.push(transitScore);
  const queryFitScore = fitSignals.length
    ? Math.round(fitSignals.reduce((sum, value) => sum + value, 0) / fitSignals.length)
    : 50;

  // Integrate components with a stronger preference and map-suitability signal
  const finalScore = (
    catchmentScore * 0.34 +
    confidenceScore * 0.08 +
    metroScore * 0.14 +
    preferenceScore * 0.10 +
    priceScore * 0.08 +
    floorScore * 0.04 +
    amenitiesScore * 0.04 +
    queryFitScore * 0.14 +
    transitScore * 0.04 +
    commuteScore * 0.04
  );

  return {
    final: Math.round(finalScore),
    components: {
      catchment: catchmentScore,
      metro: metroScore,
      preference: preferenceScore,
      amenities: amenitiesScore,
      floor: floorScore,
      price: priceScore,
      confidence: confidenceScore,
      queryFit: queryFitScore,
      transit: Math.round(transitScore),
      commute: commuteScore,
      matchedAmenities: preferredAmenityScore
    }
  };
}

function commercialPassesFilters(listing, preferences) {
  if (preferences.propertyType !== 'all' && listing.property_type !== preferences.propertyType) return false;
  if (preferences.sqftMin && Number(listing.sqft || 0) < preferences.sqftMin) return false;
  if (preferences.sqftMax && Number(listing.sqft || 0) > preferences.sqftMax) return false;
  if (preferences.priceMin && Number(listing.price || 0) < preferences.priceMin) return false;
  if (preferences.priceMax && Number(listing.price || 0) > preferences.priceMax) return false;
  if (preferences.floor !== 'any' && listing.floor !== preferences.floor) return false;
  if (preferences.transit === 'within_2km' && Number(listing.metro?.distance_km || 999) > 2) return false;
  if (preferences.searchTerm) {
    const haystack = [
      listing.title,
      listing.property_type,
      listing.floor,
      listing.metro?.nearest_station,
      listing.listing_url,
      ...(listing.amenities || [])
    ].join(' ').toLowerCase();
    if (!haystack.includes(preferences.searchTerm)) return false;
  }
  return true;
}

function applyCommercialPreferences() {
  const preferences = getCommercialPreferences();
  rankedCommercialListings = commercialListings
    .map(listing => {
      const score = calculateCommercialScore(listing, preferences);
      return { ...listing, commercial_score: score.final, score_components: score.components };
    })
    .filter(listing => commercialPassesFilters(listing, preferences))
    .sort((a, b) => b.commercial_score - a.commercial_score);

  rankedCommercialListings.forEach((listing, index) => {
    listing.commercial_rank = index + 1;
  });

  setTextIfExists('commercial-visible-count', formatNumber(rankedCommercialListings.length));
  setTextIfExists('commercial-top-score', rankedCommercialListings.length ? rankedCommercialListings[0].commercial_score : '0');
  renderCommercialList();
  renderCommercialMarkers();

  if (selectedCommercialListing) {
    const refreshed = rankedCommercialListings.find(item => item.listing_id === selectedCommercialListing.listing_id)
      || commercialListings.find(item => item.listing_id === selectedCommercialListing.listing_id);
    if (refreshed) renderCommercialDetails(refreshed);
  }
  renderCommercialComparison();
}

function setCommercialMode(mode) {
  const browsePanel = document.getElementById('commercial-browse-panel');
  const customPanel = document.getElementById('commercial-custom-panel');
  const browseBtn = document.getElementById('commercial-mode-browse');
  const customBtn = document.getElementById('commercial-mode-custom');
  if (!browsePanel || !customPanel) return;
  const custom = mode === 'custom';
  browsePanel.classList.toggle('hidden', custom);
  customPanel.classList.toggle('hidden', !custom);
  browseBtn?.classList.toggle('active', !custom);
  customBtn?.classList.toggle('active', custom);
}

function getCommercialDataNoteEl() {
  return document.getElementById('commercial-data-note');
}

function setCommercialDataNote(message) {
  const note = getCommercialDataNoteEl();
  if (note) note.textContent = message;
}

function setMapSearchStatus(message) {
  const el = document.getElementById('map-search-status');
  if (el) el.textContent = message;
}

function clearCommercialMapSearchMarker() {
  if (commercialSearchMarker && map && map.hasLayer(commercialSearchMarker)) {
    map.removeLayer(commercialSearchMarker);
  }
  commercialSearchMarker = null;
}

function clearCommercialDraftMarker() {
  if (commercialDraftMarker && map && map.hasLayer(commercialDraftMarker)) {
    map.removeLayer(commercialDraftMarker);
  }
  commercialDraftMarker = null;
}

function commercialMarkerIcon(className, label) {
  return L.divIcon({
    className: '',
    html: `<div class="${className}">${escapeHTML(label)}</div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17]
  });
}

function setCommercialDraftLocation(lat, lon, sourceLabel = 'Picked from map') {
  const latEl = document.getElementById('commercial-custom-lat');
  const lonEl = document.getElementById('commercial-custom-lon');
  if (latEl) latEl.value = Number(lat).toFixed(6);
  if (lonEl) lonEl.value = Number(lon).toFixed(6);

  const point = L.latLng(lat, lon);
  if (!commercialDraftMarker) {
    commercialDraftMarker = L.marker(point, {
      icon: commercialMarkerIcon('commercial-draft-pin', 'Draft'),
      riseOnHover: true
    }).addTo(map);
  } else {
    commercialDraftMarker.setLatLng(point);
    if (!map.hasLayer(commercialDraftMarker)) commercialDraftMarker.addTo(map);
  }

  const draftNote = document.getElementById('commercial-draft-note');
  if (draftNote) {
    draftNote.textContent = `${sourceLabel} at ${Number(lat).toFixed(5)}, ${Number(lon).toFixed(5)}`;
  }
  setCommercialDataNote(`Draft location set at ${Number(lat).toFixed(5)}, ${Number(lon).toFixed(5)}.`);
}

function toggleCommercialLocationPickMode(force) {
  commercialLocationPickMode = typeof force === 'boolean' ? force : !commercialLocationPickMode;
  const btn = document.getElementById('commercial-pick-location-btn');
  if (btn) {
    btn.classList.toggle('active', commercialLocationPickMode);
    btn.textContent = commercialLocationPickMode ? 'Picking on map...' : 'Pick from map';
  }
  if (!commercialLocationPickMode) {
    setCommercialDataNote('Pick from map mode turned off.');
  } else {
    setCommercialMode('custom');
    setCommercialDataNote('Click the map to set latitude and longitude for a custom listing.');
  }
}

function commercialListingSearchHaystack(listing) {
  return [
    listing.title,
    listing.property_type,
    listing.floor,
    listing.metro?.nearest_station,
    listing.listing_url,
    ...(listing.amenities || [])
  ].join(' ').toLowerCase();
}

function normalizeMapSearchText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

function getMapSearchInput() {
  return document.getElementById('map-search-query-top') || document.getElementById('map-search-query');
}

function getMapSearchSuggestionsEl() {
  return document.getElementById('map-search-suggestions');
}

function mapSearchTypeLabel(type) {
  const labels = {
    locality: 'Locality',
    society: 'Society',
    hospital: 'Hospital',
    metro: 'Metro station',
    sez: 'Office zone',
    hex: 'H3 cell',
    micromarket: 'Micro-market',
    office: 'Office anchor',
    commercial: 'Saved listing',
    external: 'Map place'
  };
  return labels[type] || 'Place';
}

function mapSearchTypeIcon(type) {
  const icons = {
    locality: 'L',
    society: 'A',
    hospital: 'H',
    metro: 'M',
    sez: 'Z',
    hex: '#',
    micromarket: 'MM',
    office: 'O',
    commercial: 'C',
    external: 'P'
  };
  return icons[type] || 'P';
}

function mapSearchSubtitle(item) {
  if (item.subtitle) return item.subtitle;
  const parts = [
    mapSearchTypeLabel(item.type),
    item.item?.locality,
    item.item?.zone || item.item?.primary_zone,
    item.item?.category,
    item.item?.board,
    item.item?.line
  ].filter(Boolean);
  return [...new Set(parts)].join(' · ');
}

function mapSearchPopupContent(result) {
  const subtitle = mapSearchSubtitle(result);
  const coordinateText = `${Number(result.lat).toFixed(5)}, ${Number(result.lon).toFixed(5)}`;
  return `
    <div class="map-search-popup">
      <strong>${escapeHTML(result.label)}</strong>
      <span>${escapeHTML(mapSearchTypeLabel(result.type))}</span>
      ${subtitle ? `<small>${escapeHTML(subtitle)}</small>` : ''}
      <em>${escapeHTML(coordinateText)}</em>
    </div>
  `;
}

function mapSearchMarkerIcon(result) {
  const iconText = mapSearchTypeIcon(result?.type);
  return L.divIcon({
    className: '',
    html: `
      <div class="map-search-pin" title="${escapeHTML(result?.label || 'Selected place')}">
        <span>${escapeHTML(iconText)}</span>
      </div>
    `,
    iconSize: [40, 48],
    iconAnchor: [20, 46],
    popupAnchor: [0, -44]
  });
}

function buildMapSearchCandidates() {
  const candidates = [];
  const pushItem = (item, type, label, lat, lon, extra = {}) => {
    const numericLat = Number(lat);
    const numericLon = Number(lon);
    if (!Number.isFinite(numericLat) || !Number.isFinite(numericLon) || !label) return;
    const aliases = (extra.aliases || []).filter(Boolean);
    candidates.push({
      type,
      label,
      lat: numericLat,
      lon: numericLon,
      aliases,
      searchText: normalizeMapSearchText([
        label,
        type,
        ...aliases,
        item?.name,
        item?.original_name,
        item?.locality,
        item?.zone,
        item?.primary_zone,
        item?.category,
        item?.board,
        item?.address,
        item?.property_type,
        item?.title,
        item?.line,
        item?.hex_id
      ].filter(Boolean).join(' ')),
      ...extra,
      item
    });
  };

  (layerData.localities || []).forEach(item => pushItem(item, 'locality', item.name || item.title || item.locality, item.lat, item.lon));
  (layerData.societies || []).forEach(item => pushItem(item, 'society', item.name, item.lat, item.lon, {
    subtitle: [item.locality, item.category, item.zone].filter(Boolean).join(' · ')
  }));
  (layerData.hospitals || []).forEach(item => pushItem(item, 'hospital', item.name, item.lat, item.lon));
  (layerData.metro_stations || []).forEach(item => pushItem(item, 'metro', item.name, item.latitude, item.longitude, {
    aliases: [item.original_name],
    subtitle: [item.original_name, item.line].filter(Boolean).join(' · ')
  }));
  (layerData.sez_zones?.features || []).forEach(feature => {
    const p = feature.properties || {};
    pushItem(p, 'sez', p.name, p.centroid_lat, p.centroid_lon, {
      subtitle: `Office zone · ${formatNumber(p.office_spaces || 0, 0)} office spaces`
    });
  });
  (layerData.hexes?.features || []).forEach(feature => {
    const p = feature.properties || {};
    pushItem(p, 'hex', p.name, p.centroid_lat, p.centroid_lon, {
      aliases: [p.hex_id, p.refined_budget_segment, p.affluence_tier],
      subtitle: [p.affluence_tier, `${formatNumber(p.direct_total_units || 0, 0)} known units`].filter(Boolean).join(' · ')
    });
  });
  (layerData.report?.top_10_micro_markets || []).forEach(item => pushItem(item, 'micromarket', item.primary_name, item.centroid_lat, item.centroid_lon, {
    aliases: item.all_locality_names || [],
    subtitle: [item.primary_zone, `${item.hex_count} hexes`, `${formatNumber(item.direct_total_units || item.known_units || 0, 0)} known units`].filter(Boolean).join(' · ')
  }));
  (layerData.sez_offices || []).forEach(item => pushItem(item, 'office', item.name, item.lat, item.lon, {
    aliases: [item.company_key, item.sez_name, item.company_prominence_tier],
    subtitle: [item.sez_name, getOfficeSEZMatchLabel(item), item.zone, item.company_prominence_tier].filter(Boolean).join(' · ')
  }));
  (commercialListings || []).forEach(item => pushItem(item, 'commercial', item.title, item.latitude, item.longitude));

  return candidates;
}

function scoreMapSearchCandidate(item, normalizedQuery) {
  const label = normalizeMapSearchText(item.label);
  const aliases = (item.aliases || []).map(normalizeMapSearchText);
  const searchable = item.searchText || label;
  const typeBoost = {
    locality: 35,
    society: 34,
    hospital: 30,
    metro: 28,
    micromarket: 26,
    office: 25,
    sez: 24,
    hex: 18,
    commercial: 16
  }[item.type] || 0;

  if (label === normalizedQuery || aliases.includes(normalizedQuery)) return 1000 + typeBoost;
  if (label.startsWith(normalizedQuery)) return 860 + typeBoost;
  if (aliases.some(alias => alias.startsWith(normalizedQuery))) return 820 + typeBoost;
  if (label.split(' ').some(word => word.startsWith(normalizedQuery))) return 760 + typeBoost;
  if (searchable.includes(` ${normalizedQuery}`)) return 650 + typeBoost;
  if (label.includes(normalizedQuery)) return 600 + typeBoost;
  if (searchable.includes(normalizedQuery)) return 500 + typeBoost;
  return 0;
}

function getLocalMapSearchMatches(query, limit = 8) {
  const normalizedQuery = normalizeMapSearchText(query);
  if (!normalizedQuery) return [];
  const seen = new Set();
  return buildMapSearchCandidates()
    .map(item => ({ ...item, score: scoreMapSearchCandidate(item, normalizedQuery) }))
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score || String(a.label).localeCompare(String(b.label)))
    .filter(item => {
      const key = `${item.type}:${normalizeMapSearchText(item.label)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, limit);
}

function findMapSearchMatch(query) {
  return getLocalMapSearchMatches(query, 1)[0] || null;
}

function setMapSearchMarker(result) {
  clearMapSearchMarker();
  const point = L.latLng(result.lat, result.lon);
  mapSearchHalo = L.circleMarker(point, {
    radius: 26,
    color: '#ea4335',
    weight: 2,
    opacity: 0.38,
    fillColor: '#ea4335',
    fillOpacity: 0.12,
    interactive: false
  }).addTo(map);
  mapSearchMarker = L.marker(point, {
    icon: mapSearchMarkerIcon(result),
    riseOnHover: true
  }).addTo(map);
  mapSearchMarker.bindTooltip(result.label, { sticky: true });
  mapSearchMarker.bindPopup(mapSearchPopupContent(result), {
    closeButton: false,
    className: 'map-search-popup-shell',
    offset: [0, -8]
  });
  map.setView(point, Math.max(13, MAP_SEARCH_ZOOM));
  mapSearchMarker.openPopup();
}

function clearMapSearchMarker() {
  if (mapSearchMarker && map && map.hasLayer(mapSearchMarker)) {
    map.removeLayer(mapSearchMarker);
  }
  mapSearchMarker = null;
  if (mapSearchHalo && map && map.hasLayer(mapSearchHalo)) {
    map.removeLayer(mapSearchHalo);
  }
  mapSearchHalo = null;
}

function renderMapSearchSuggestions(suggestions = []) {
  const panel = getMapSearchSuggestionsEl();
  if (!panel) return;
  mapSearchSuggestions = suggestions;
  mapSearchActiveSuggestionIndex = suggestions.length ? Math.max(0, Math.min(mapSearchActiveSuggestionIndex, suggestions.length - 1)) : -1;
  if (!suggestions.length) {
    panel.classList.remove('visible');
    panel.innerHTML = '';
    return;
  }
  panel.innerHTML = suggestions.map((item, index) => `
    <button type="button" class="map-search-suggestion${index === mapSearchActiveSuggestionIndex ? ' active' : ''}" data-index="${index}">
      <span class="map-search-suggestion-icon map-search-suggestion-icon-${escapeHTML(item.type || 'place')}">${escapeHTML(mapSearchTypeIcon(item.type))}</span>
      <span class="map-search-suggestion-copy">
        <strong>${escapeHTML(item.label)}</strong>
        <small><span>${escapeHTML(mapSearchTypeLabel(item.type))}</span>${escapeHTML(mapSearchSubtitle(item) ? ` · ${mapSearchSubtitle(item)}` : '')}</small>
      </span>
    </button>
  `).join('');
  panel.classList.add('visible');
}

function hideMapSearchSuggestions() {
  renderMapSearchSuggestions([]);
}

function selectMapSearchSuggestion(result) {
  if (!result) return;
  const input = getMapSearchInput();
  if (input) input.value = result.label;
  hideMapSearchSuggestions();
  setMapSearchMarker(result);
  const label = result.type === 'external' ? 'map place' : 'local dataset match';
  setMapSearchStatus(`Centered map on ${label}: ${result.label}.`);
}

function handleMapSearchSuggestionKeydown(event) {
  if (!mapSearchSuggestions.length) {
    if (event.key === 'ArrowDown') updateMapSearchAutocomplete();
    return;
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault();
    mapSearchActiveSuggestionIndex = (mapSearchActiveSuggestionIndex + 1) % mapSearchSuggestions.length;
    renderMapSearchSuggestions(mapSearchSuggestions);
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    mapSearchActiveSuggestionIndex = (mapSearchActiveSuggestionIndex - 1 + mapSearchSuggestions.length) % mapSearchSuggestions.length;
    renderMapSearchSuggestions(mapSearchSuggestions);
  } else if (event.key === 'Enter') {
    event.preventDefault();
    selectMapSearchSuggestion(mapSearchSuggestions[mapSearchActiveSuggestionIndex] || mapSearchSuggestions[0]);
  } else if (event.key === 'Escape') {
    hideMapSearchSuggestions();
  }
}

async function fetchExternalMapSuggestions(query, limit = 5) {
  try {
    const cityLabel = legacyCityLabel();
    const searchText = query.toLowerCase().includes(cityLabel.toLowerCase()) ? query : `${query}, ${cityLabel}`;
    const params = new URLSearchParams({
      format: 'jsonv2',
      limit: String(limit),
      addressdetails: '1',
      countrycodes: 'in',
      viewbox: activeLegacyCitySearchViewbox(),
      bounded: '0',
      q: searchText
    });
    const response = await fetch(`https://nominatim.openstreetmap.org/search?${params.toString()}`, {
      headers: { Accept: 'application/json' }
    });
    if (!response.ok) return [];
    const data = await response.json();
    if (!Array.isArray(data)) return [];
    return data.map(item => {
      const lat = Number(item.lat);
      const lon = Number(item.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
      return {
        type: 'external',
        label: item.display_name || query,
        subtitle: [item.type, item.class].filter(Boolean).join(' · ') || 'Map place',
        lat,
        lon,
        item
      };
    }).filter(Boolean);
  } catch (error) {
    console.warn('Map autocomplete failed:', error);
    return [];
  }
}

function updateMapSearchAutocomplete() {
  const input = getMapSearchInput();
  const query = (input?.value || '').trim();
  clearTimeout(mapSearchAutocompleteTimer);
  mapSearchAutocompleteSequence += 1;
  const sequence = mapSearchAutocompleteSequence;

  if (!query) {
    hideMapSearchSuggestions();
    setMapSearchStatus('Search map places and localities, including areas outside this dataset.');
    return;
  }

  const localMatches = getLocalMapSearchMatches(query, 5);
  mapSearchActiveSuggestionIndex = localMatches.length ? 0 : -1;
  renderMapSearchSuggestions(localMatches);
  setMapSearchStatus(localMatches.length ? `${localMatches.length} local matches found. Press Enter or pick a result.` : 'Searching map places...');

  if (query.length < 3) return;

  mapSearchAutocompleteTimer = setTimeout(async () => {
    const externalMatches = await fetchExternalMapSuggestions(query, Math.max(2, 7 - localMatches.length));
    if (sequence !== mapSearchAutocompleteSequence) return;
    const combined = [...localMatches, ...externalMatches].slice(0, 7);
    mapSearchActiveSuggestionIndex = combined.length ? 0 : -1;
    renderMapSearchSuggestions(combined);
    setMapSearchStatus(combined.length ? `${combined.length} suggestions found.` : 'No suggestions found yet.');
  }, localMatches.length >= 5 ? 350 : 180);
}

function clearMapSearch() {
  const input = getMapSearchInput();
  if (input) input.value = '';
  clearTimeout(mapSearchAutocompleteTimer);
  hideMapSearchSuggestions();
  clearMapSearchMarker();
  setMapSearchStatus('Search map places and localities, including areas outside this dataset.');
}

async function searchMapLocation() {
  const input = getMapSearchInput();
  const query = (input?.value || '').trim();
  if (!query) {
    clearMapSearch();
    return;
  }

  const activeSuggestion = mapSearchSuggestions[mapSearchActiveSuggestionIndex];
  if (activeSuggestion && normalizeMapSearchText(activeSuggestion.label).includes(normalizeMapSearchText(query))) {
    selectMapSearchSuggestion(activeSuggestion);
    return;
  }

  const localMatch = findMapSearchMatch(query);
  if (localMatch) {
    selectMapSearchSuggestion(localMatch);
    return;
  }

  setMapSearchStatus('Searching the map...');
  const resolved = await geocodeMapQuery(query);
  if (resolved) {
    selectMapSearchSuggestion(resolved);
    return;
  }

  setMapSearchStatus('No map place or local dataset match found.');
}

async function geocodeMapQuery(query) {
  try {
    const cityLabel = legacyCityLabel();
    const searchText = query.toLowerCase().includes(cityLabel.toLowerCase()) ? query : `${query}, ${cityLabel}`;
    const params = new URLSearchParams({
      format: 'jsonv2',
      limit: '1',
      addressdetails: '1',
      countrycodes: 'in',
      viewbox: activeLegacyCitySearchViewbox(),
      bounded: '0',
      q: searchText
    });
    const url = `https://nominatim.openstreetmap.org/search?${params.toString()}`;
    const response = await fetch(url, {
      headers: {
        Accept: 'application/json'
      }
    });
    if (!response.ok) return null;
    const data = await response.json();
    if (!Array.isArray(data) || !data.length) return null;
    const first = data[0];
    const lat = Number(first.lat);
    const lon = Number(first.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return {
      type: 'external',
      label: first.display_name || query,
      subtitle: [first.type, first.class].filter(Boolean).join(' · ') || 'Map place',
      lat,
      lon,
      item: first
    };
  } catch (error) {
    console.warn('Map geocoding failed:', error);
    return null;
  }
}

function commercialLocalPlaceSearch(query) {
  return findMapSearchMatch(query);
}

async function geocodeCommercialQuery(query) {
  try {
    const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`;
    const response = await fetch(url, {
      headers: {
        Accept: 'application/json'
      }
    });
    if (!response.ok) return null;
    const data = await response.json();
    if (!Array.isArray(data) || !data.length) return null;
    const first = data[0];
    const lat = Number(first.lat);
    const lon = Number(first.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return {
      label: first.display_name || query,
      lat,
      lon
    };
  } catch (error) {
    console.warn('Commercial geocoding failed:', error);
    return null;
  }
}

function fitCommercialListings(listings = rankedCommercialListings) {
  const points = listings
    .filter(item => Number.isFinite(item.latitude) && Number.isFinite(item.longitude))
    .slice(0, 60)
    .map(item => [item.latitude, item.longitude]);
  if (!points.length) return false;
  const bounds = L.latLngBounds(points);
  if (!bounds.isValid()) return false;
  map.fitBounds(bounds, { padding: [40, 40] });
  return true;
}

function clearCommercialSearch() {
  commercialListingFilterTerm = '';
  const searchEl = document.getElementById('commercial-search-query');
  if (searchEl) searchEl.value = '';
  clearCommercialMapSearchMarker();
  applyCommercialPreferences();
  setCommercialDataNote('Commercial search cleared.');
}

async function runCommercialSearch() {
  const searchEl = document.getElementById('commercial-search-query');
  const query = (searchEl?.value || '').trim();
  if (!query) {
    clearCommercialSearch();
    return;
  }
  const normalizedQuery = query.toLowerCase();

  const matches = commercialListings
    .filter(listing => commercialListingSearchHaystack(listing).includes(normalizedQuery))
    .sort((a, b) => {
      const aExact = commercialListingSearchHaystack(a).startsWith(normalizedQuery) ? 1 : 0;
      const bExact = commercialListingSearchHaystack(b).startsWith(normalizedQuery) ? 1 : 0;
      return bExact - aExact;
    });

  if (matches.length) {
    commercialListingFilterTerm = normalizedQuery;
    applyCommercialPreferences();
    selectCommercialListing(matches[0].listing_id);
    fitCommercialListings(matches);
    setCommercialDataNote(`Found ${matches.length} matching listing${matches.length === 1 ? '' : 's'}.`);
    clearCommercialMapSearchMarker();
    return;
  }

  commercialListingFilterTerm = '';
  applyCommercialPreferences();

  const localMatch = commercialLocalPlaceSearch(query);
  const resolved = localMatch || await geocodeCommercialQuery(query);
  if (resolved) {
    clearCommercialMapSearchMarker();
    commercialSearchMarker = L.marker([resolved.lat, resolved.lon], {
      icon: commercialMarkerIcon('commercial-search-pin', 'Search'),
      riseOnHover: true
    }).addTo(map);
    commercialSearchMarker.bindTooltip(resolved.label, { sticky: true });
    map.setView([resolved.lat, resolved.lon], 13);
    setCommercialDataNote(`Centered map on ${resolved.label}.`);
    return;
  }

  setCommercialDataNote('No listing or place matched that search.');
}

async function resolveCommercialCustomLocation() {
  const lat = parseFloat(document.getElementById('commercial-custom-lat')?.value);
  const lon = parseFloat(document.getElementById('commercial-custom-lon')?.value);
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    return { lat, lon, source: 'Coordinates' };
  }

  const address = document.getElementById('commercial-custom-address')?.value?.trim() || '';
  if (!address) return null;

  const localMatch = commercialLocalPlaceSearch(address);
  if (localMatch) {
    return {
      lat: Number(localMatch.lat),
      lon: Number(localMatch.lon),
      source: localMatch.label || address
    };
  }

  const geocoded = await geocodeCommercialQuery(address);
  if (geocoded) {
    return {
      lat: geocoded.lat,
      lon: geocoded.lon,
      source: geocoded.label || address
    };
  }

  return null;
}

function renderCommercialList() {
  const container = document.getElementById('commercial-list');
  if (!container) return;
  if (!rankedCommercialListings.length) {
    const query = (commercialListingFilterTerm || '').trim();
    container.innerHTML = `<div class="notion-block info-block">No commercial listings match the current preferences${query ? ` for "${escapeHTML(query)}"` : ''}.</div>`;
    return;
  }

  container.innerHTML = rankedCommercialListings.map((listing, idx) => {
    const isLockedItem = !isUnlocked() && idx >= 3;
    const title = isUnlocked() ? listing.title : `Restricted Commercial Listing #${listing.commercial_rank || idx+1}`;
    const station = isUnlocked() ? (listing.metro?.nearest_station || 'Nearest metro NA') : 'Restricted Transit Station';

    const metrics = listing.catchment?.metrics || {};
    const checked = commercialComparisonSet.has(listing.listing_id) ? 'checked' : '';
    const selected = selectedCommercialListing?.listing_id === listing.listing_id ? ' selected' : '';
    const isSearchHit = commercialListingFilterTerm && commercialListingSearchHaystack(listing).includes(commercialListingFilterTerm);
    
    const blurredClass = isLockedItem ? ' blurred-item' : '';
    const clickHandler = isLockedItem ? 'openUnlockModal()' : `selectCommercialListing('${escapeHTML(listing.listing_id)}')`;

    return `
      <article class="commercial-card${selected}${isSearchHit ? ' search-hit' : ''}${blurredClass}" id="commercial-card-${escapeHTML(listing.listing_id)}" onclick="${clickHandler}">
        <div class="commercial-card-top">
          <div>
            <span class="commercial-rank-pill">#${listing.commercial_rank || '-'}</span>
            <div class="commercial-card-title">${escapeHTML(title)}</div>
            <div class="commercial-card-subtitle">${escapeHTML(listing.property_type)} · ${formatNumber(listing.sqft)} sqft · ${escapeHTML(listing.floor)}</div>
          </div>
          <div class="commercial-card-score">${formatNumber(listing.commercial_score, 1)}</div>
        </div>
        <div class="commercial-card-meta">
          <div>Rent: <strong>${formatCurrencyShort(listing.price)}/mo</strong></div>
          <div>Metro: <strong>${formatNumber(listing.metro?.distance_km || 0, 1)} km</strong></div>
          <div>Known units: <strong>${formatNumber(metrics.direct_total_units || metrics.known_residential_units || 0)}</strong></div>
          <div>Offices: <strong>${formatNumber(metrics.sez_office_spaces || 0)}</strong></div>
        </div>
        <div class="commercial-compare-row" onclick="event.stopPropagation()">
          <span>${escapeHTML(station)}</span>
          <div style="display: flex; gap: 12px; align-items: center;">
            <label style="margin: 0; display: inline-flex; align-items: center; gap: 4px; cursor: pointer;">
              <input type="checkbox" ${checked} ${isLockedItem ? 'disabled' : ''} onchange="toggleCommercialCompare('${escapeHTML(listing.listing_id)}', this.checked)"> Compare
            </label>
            <button class="delete-listing-btn" ${isLockedItem ? 'disabled' : ''} onclick="deleteCommercialListing('${escapeHTML(listing.listing_id)}')" title="Delete listing" style="background: none; border: none; color: #ef4444; cursor: pointer; padding: 2px 4px; display: inline-flex; align-items: center; justify-content: center; transition: color 0.15s ease;">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                <line x1="10" y1="11" x2="10" y2="17"></line>
                <line x1="14" y1="11" x2="14" y2="17"></line>
              </svg>
            </button>
          </div>
        </div>
      </article>
    `;
  }).join('');
}

function commercialPinIcon(listing) {
  const pinLabel = listing.commercial_rank ? (listing.commercial_rank > 99 ? '99+' : listing.commercial_rank) : '+';
  const classes = [
    'commercial-pin',
    listing.commercial_rank <= 10 ? 'top' : '',
    selectedCommercialListing?.listing_id === listing.listing_id ? 'selected' : '',
    listing.source === 'custom' ? 'custom' : ''
  ].filter(Boolean).join(' ');
  return L.divIcon({
    className: '',
    html: `<div class="${classes}">${pinLabel}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16]
  });
}

function renderCommercialMarkers() {
  if (!map || !window.L) return;
  if (!commercialMarkersLayer) {
    commercialMarkersLayer = L.layerGroup();
  }
  commercialMarkersLayer.clearLayers();
  rankedCommercialListings.forEach((listing, idx) => {
    if (!Number.isFinite(listing.latitude) || !Number.isFinite(listing.longitude)) return;
    const isLockedItem = !isUnlocked() && idx >= 3;
    const marker = L.marker([listing.latitude, listing.longitude], {
      icon: commercialPinIcon(listing),
      riseOnHover: true
    });
    const title = isUnlocked() ? listing.title : `Restricted Listing #${listing.commercial_rank || idx+1}`;
    marker.bindTooltip(`#${listing.commercial_rank || idx+1} ${title}<br/>Score ${listing.commercial_score}`, { sticky: true });
    marker.on('click', () => {
      if (isLockedItem) {
        openUnlockModal();
      } else {
        selectCommercialListing(listing.listing_id);
      }
    });
    marker.addTo(commercialMarkersLayer);
  });
  if (activeTab === 'commercial' && !map.hasLayer(commercialMarkersLayer)) {
    commercialMarkersLayer.addTo(map);
  }
}

function activateCommercialMode() {
  if (!rankedCommercialListings.length && commercialListings.length) {
    applyCommercialPreferences();
  }
  if (commercialMarkersLayer && !map.hasLayer(commercialMarkersLayer)) {
    commercialMarkersLayer.addTo(map);
  }
  if (rankedCommercialListings.length) {
    const top = rankedCommercialListings.slice(0, 60).map(item => [item.latitude, item.longitude]);
    const bounds = L.latLngBounds(top);
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [35, 35] });
  }
}

function deactivateCommercialMode() {
  if (commercialMarkersLayer && map.hasLayer(commercialMarkersLayer)) {
    map.removeLayer(commercialMarkersLayer);
  }
  if (commercialIsochroneLayer && map.hasLayer(commercialIsochroneLayer)) {
    map.removeLayer(commercialIsochroneLayer);
  }
  if (selectedCommercialListing) {
    resetHexHighlights();
  }
  clearCommercialMapSearchMarker();
  if (commercialLocationPickMode) {
    toggleCommercialLocationPickMode(false);
  }
}

function clearCommercialSelection() {
  selectedCommercialListing = null;
  document.getElementById('commercial-details-panel')?.classList.add('hidden');
  if (commercialIsochroneLayer && map.hasLayer(commercialIsochroneLayer)) {
    map.removeLayer(commercialIsochroneLayer);
  }
  clearRolledUpAssetsLayer();
  resetHexHighlights();
  renderCommercialList();
  renderCommercialMarkers();
  updateActiveLayersPanel();
  updateRightPanelVisibility();
}

function selectCommercialListing(listingId, focusMap = true) {
  const listing = rankedCommercialListings.find(item => item.listing_id === listingId)
    || commercialListings.find(item => item.listing_id === listingId);
  if (!listing) return;
  selectedCommercialListing = listing;
  renderCommercialDetails(listing);
  renderCommercialList();
  renderCommercialMarkers();
  showCommercialIsochrone(listing);
  highlightCatchmentHexes(listing.catchment?.matched_hex_ids || []);
  if (focusMap && Number.isFinite(listing.latitude) && Number.isFinite(listing.longitude)) {
    map.setView([listing.latitude, listing.longitude], 13);
  }
  updateActiveLayersPanel();
}

async function showCommercialIsochrone(listing) {
  if (commercialIsochroneLayer && map.hasLayer(commercialIsochroneLayer)) {
    map.removeLayer(commercialIsochroneLayer);
  }
  let geojson = listing.catchment?.isochrone_geojson || null;
  if (!geojson && listing.catchment?.web_isochrone_file) {
    try {
      const response = await fetch(listing.catchment.web_isochrone_file);
      if (response.ok) geojson = await response.json();
    } catch (e) {
      console.warn("Unable to load commercial isochrone:", e);
    }
  }
  if (!geojson && listing.catchment?.geometry) {
    geojson = { type: "FeatureCollection", features: [{ type: "Feature", geometry: listing.catchment.geometry, properties: {} }] };
  }
  if (!geojson) {
    commercialIsochroneLayer = L.circle([listing.latitude, listing.longitude], {
      radius: 7000,
      color: '#dc2626',
      weight: 2,
      fillColor: '#2563eb',
      fillOpacity: 0.08
    }).addTo(map);
    return;
  }
  const drawable = geojson.type === 'FeatureCollection'
    ? geojson
    : { type: "FeatureCollection", features: [{ type: "Feature", geometry: geojson, properties: {} }] };
  commercialIsochroneLayer = L.geoJSON(drawable, {
    style: {
      color: '#dc2626',
      weight: 2,
      fillColor: '#2563eb',
      fillOpacity: 0.08,
      dashArray: '8, 5'
    }
  }).addTo(map);
}

function getMetroLineColor(line, name) {
  if (line && line.startsWith('#')) return line;
  const nameLower = String(name || '').toLowerCase();
  
  // Interchange
  if (nameLower.includes('majestic') || nameLower.includes('kempegowda')) {
    return 'linear-gradient(135deg, #7c3aed 50%, #059669 50%)';
  }
  
  const purpleStations = [
    'attiguppe', 'baiyappanahalli', 'benniganahalli', 'challaghatta', 'cubbon park', 'deepanjali', 
    'vidhana soudha', 'ambedkar', 'garudacharpalya', 'halasuru', 'hoodi', 'hopefarm', 'channasandra', 
    'hosahalli', 'indiranagar', 'jnanabharathi', 'kengeri', 'kr puram', 'krishnarajapura', 'kundalahalli', 
    'mg road', 'magadi', 'mysore', 'mysuru', 'nallurahalli', 'nallurhalli', 'nayandahalli', 'pantharapalya', 
    'pattanagere', 'pattandur', 'rajarajeshwari', 'visvesvaraya', 'central college', 'balagangadharanatha', 
    'sathya sai', 'sv road', 'vivekananda', 'trinity', 'vijayanagar', 'whitefield', 'singayyanapalya'
  ];
  
  const greenStations = [
    'banashankari', 'doddakallasandra', 'jalahalli', 'jp nagar', 'jaya prakash', 'jayanagar', 
    'konanakunte', 'national college', 'lalbagh', 'nagasandra', 'madavara', 'silk institute', 
    'peenya', 'dasarahalli', 'goraguntepalya', 'yeshwanthpur', 'sandal soap', 'mahalakshmi', 
    'rajajinagar', 'kuvempu', 'srirampura', 'sampige', 'mantri', 'krishna rajendra', 'market', 
    'chickpete', 'south end', 'rv road', 'rashtreeya vidyalaya', 'yelachenahalli', 'vajrahalli', 
    'vajarahalli', 'talaghattapura', 'thalaghattapura', 'btm layout', 'hosa road', 'huskur', 
    'infosys foundation', 'konappana', 'electronic city', 'bommanahalli', 'central silk board', 
    'hongasandra', 'kudlu gate', 'singasandra', 'beratena agrahara', 'hebbagodi', 'bommasandra'
  ];
  
  for (const st of purpleStations) {
    if (nameLower.includes(st)) return '#7c3aed';
  }
  for (const st of greenStations) {
    if (nameLower.includes(st)) return '#059669';
  }
  
  if (line && line.toLowerCase().includes('purple')) return '#7c3aed';
  if (line && line.toLowerCase().includes('green')) return '#059669';
  
  return '#9ca3af';
}

function renderMetroList(metroData, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!metroData || !metroData.stations || metroData.stations.length === 0) {
    container.innerHTML = '<div style="padding: 10px; color:#6b7280;">No metro stations found nearby</div>';
    return;
  }

  container.innerHTML = metroData.stations.map(st => {
    const dotColor = getMetroLineColor(st.line, st.name);
    const lineName = st.line || 'Namma Metro';
    const method = st.routing_method || '';
    const isWalkRouted = method === 'google_walk';
    const isFallback = method === 'haversine_fallback';
    const methodIcon = isWalkRouted ? '🚶' : '📐';
    const methodTitle = isWalkRouted
      ? 'Walk distance via Google Routes API'
      : isFallback
        ? 'Straight-line distance (routing unavailable)'
        : 'Distance estimate';

    const dotStyle = dotColor.startsWith('linear')
      ? `background: ${dotColor};`
      : `background-color: ${dotColor};`;

    const durationLabel = st.duration_mins
      ? `${formatNumber(st.duration_mins, 1)} min walk`
      : '';

    return `
      <div class="poi-list-item" style="cursor: pointer;" onclick="flyToMetro(${st.lat || 0}, ${st.lon || 0}, '${escapeHTML(st.name)}', '${escapeHTML(lineName)}')">
        <div>
          <div class="poi-item-name" style="display: flex; align-items: center; gap: 6px;" title="${escapeHTML(st.name)}">
            <span style="display: inline-block; width: 8px; height: 8px; border-radius: 999px; ${dotStyle}" title="${escapeHTML(lineName)}"></span>
            ${escapeHTML(st.name)}
          </div>
          <div class="poi-item-tag" title="${methodTitle}">${methodIcon} ${escapeHTML(lineName)}</div>
        </div>
        <div style="text-align: right;">
          <div style="font-weight: 600; font-size: 12px; color: var(--text-main);">${formatNumber(st.distance_km, 1)} km</div>
          <div class="poi-item-tag">${durationLabel}${durationLabel ? ' · ' : ''}Score: ${formatNumber(st.score, 0)}</div>
        </div>
      </div>
    `;
  }).join('');
}


let activeMetroMarker = null;
function flyToMetro(lat, lon, name, line) {
  if (!lat || !lon) return;
  if (activeMetroMarker) {
    map.removeLayer(activeMetroMarker);
  }
  
  const iconHtml = `
    <div style="background: ${getMetroLineColor(line, name)}; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 1px 4px rgba(0,0,0,0.4);"></div>
  `;
  const customIcon = L.divIcon({
    html: iconHtml,
    className: '',
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -10]
  });

  activeMetroMarker = L.marker([lat, lon], { icon: customIcon }).addTo(map);
  activeMetroMarker.bindPopup(`<strong>${name}</strong><br/>${line} Line`).openPopup();
  map.flyTo([lat, lon], 14, { duration: 0.8 });
}


function renderCommercialDetails(listing) {
  const panel = document.getElementById('commercial-details-panel');
  if (!panel) return;
  showDetailsPanel('commercial-details-panel');
  clearRolledUpAssetsLayer();
  
  const commLocked = !isUnlocked();
  const metrics = listing.catchment?.metrics || {};
  const officeCount = Number(metrics.sez_office_spaces || 0);

  // Unified Standard Layout Template Injection
  renderStandardDetails(panel, {
    title: isUnlocked() ? listing.title : `Restricted Commercial Listing #${listing.commercial_rank || '-'}`,
    titleId: 'commercial-details-title',
    badge: `#${listing.commercial_rank || '-'} · ${listing.property_type}`,
    badgeId: 'commercial-details-rank',
    onClose: 'clearCommercialSelection()',
    kpis: [
      { id: 'commercial-detail-score', value: formatNumber(listing.commercial_score || listing.score || 0, 1), label: 'Final score', locked: commLocked },
      { id: 'commercial-detail-tam', value: formatNumber(metrics.direct_total_units || metrics.known_residential_units || 0), label: 'Known residential units' },
      { id: 'commercial-detail-q3-below', value: formatNumber(metrics.society_count || metrics.residential_project_count || 0, 0), label: 'Residential projects', locked: commLocked },
      { id: 'commercial-detail-metro', value: `${formatNumber(listing.metro?.distance_km || 0, 1)} km`, label: 'Metro distance', locked: commLocked },
      { id: 'commercial-detail-visibility', value: formatNumber(listing.visibility?.score || 0), label: (listing.visibility?.road_type || 'Road').replace('_', ' '), locked: commLocked },
      { id: 'commercial-detail-offices', value: formatNumber(officeCount, 0), label: 'Office anchors', locked: commLocked }
    ],
    mainContent: `
      <h4 class="notion-heading-4">Score breakdown</h4>
      <div class="commercial-score-bars" id="commercial-score-bars"></div>

      <h4 class="notion-heading-4">Catchment output</h4>
      <div class="commercial-catchment-grid" id="commercial-catchment-grid"></div>

      ${buildRolledUpAssetsControlsHtml('commercial')}
    `,
    sections: [
      { title: 'Radius expansion comparison', id: 'commercial-radius-table-details', contentHtml: `
        <div class="table-container commercial-mini-table">
          <table class="notion-table">
            <thead>
              <tr>
                <th>Radius</th>
                <th class="num-col">Hexes</th>
                <th class="num-col">Known units</th>
              </tr>
            </thead>
            <tbody id="commercial-radius-table"></tbody>
          </table>
        </div>
      `, open: true },
      { title: 'Nearest 3 Metro Stations (Routing-based)', id: 'commercial-metro-list', open: true },
      { title: 'Residential projects, hospitals, and workplace anchors', id: 'commercial-poi-list' }
    ]
  });

  const bars = document.getElementById('commercial-score-bars');
  if (bars) {
    const labels = [
      ['Catchment', 'catchment'],
      ['Metro', 'metro'],
      ['Preference', 'preference'],
      ['Amenities', 'amenities'],
      ['Floor', 'floor'],
      ['Price', 'price'],
      ['Confidence', 'confidence'],
      ['Query fit', 'queryFit'],
      ['Transit', 'transit'],
      ['Commute', 'commute']
    ];
    bars.innerHTML = labels.map(([label, key]) => {
      const value = Number(listing.score_components?.[key] || 0);
      return `
        <div class="commercial-score-row">
          <span>${label}</span>
          <div class="commercial-score-track"><div class="commercial-score-fill" style="width:${Math.max(0, Math.min(100, value))}%"></div></div>
          <strong>${formatNumber(value, 0)}</strong>
        </div>
      `;
    }).join('');
  }

  const catchmentGrid = document.getElementById('commercial-catchment-grid');
  if (catchmentGrid) {
    const values = [
      ['Known residential units', metrics.direct_total_units || metrics.known_residential_units || 0],
      ['Residential projects', metrics.society_count || metrics.residential_project_count || 0],
      ['Hospital count', metrics.hospital_count],
      ['Office anchors', metrics.sez_office_spaces],
      ['Matched hexes', listing.catchment?.matched_hex_ids?.length || 0],
      ['Rent per sqft', `₹${formatNumber(listing.rent_per_sqft || 0, 0)}`]
    ];
    catchmentGrid.innerHTML = values.map(([label, value]) => `
      <div class="commercial-catchment-metric">
        <span>${escapeHTML(label)}</span>
        <strong>${typeof value === 'number' ? formatNumber(value) : escapeHTML(value)}</strong>
      </div>
    `).join('');
  }

  const radiusTable = document.getElementById('commercial-radius-table');
  if (radiusTable) {
    radiusTable.innerHTML = (listing.catchment?.radius_expansion || []).map(row => `
      <tr>
        <td>${formatNumber(row.radius, 1)} km</td>
        <td class="num-col">${formatNumber(row.hex_count)}</td>
        <td class="num-col">${formatNumber(row.direct_total_units || row.known_residential_units || 0)}</td>
      </tr>
    `).join('');
  }

  const poiList = document.getElementById('commercial-poi-list');
  if (poiList) {
    const societies = (listing.catchment?.societies || []).slice(0, 5).map(item => `<div class="poi-list-item" data-type="society" data-name="${escapeHTML(item.name)}"><div class="poi-item-name">${escapeHTML(item.name)}</div><div class="poi-item-tag">${escapeHTML(item.category || 'Residential project')}</div></div>`);
    const offices = (listing.catchment?.offices || []).slice(0, 5).map(item => `<div class="poi-list-item" data-type="office" data-name="${escapeHTML(item.name)}"><div class="poi-item-name">${escapeHTML(item.name)}</div><div class="poi-item-tag">${escapeHTML(item.company_prominence_tier || 'Office')}</div></div>`);
    const hospitals = (listing.catchment?.hospitals || []).slice(0, 5).map(item => `<div class="poi-list-item" data-type="hospital" data-name="${escapeHTML(item.name)}"><div class="poi-item-name">${escapeHTML(item.name)}</div><div class="poi-item-tag">${escapeHTML(item.category || 'Hospital')}</div></div>`);
    poiList.innerHTML = [...societies, ...hospitals, ...offices].join('') || '<div class="poi-list-item">No POIs matched this catchment.</div>';
  }

  renderMetroList(listing.metro, 'commercial-metro-list');
}

function toggleCommercialCompare(listingId, checked) {
  if (checked && commercialComparisonSet.size >= 5) {
    const card = document.getElementById(`commercial-card-${listingId}`);
    const input = card ? card.querySelector('input[type="checkbox"]') : null;
    if (input) input.checked = false;
    const note = document.getElementById('commercial-data-note');
    if (note) note.textContent = 'Comparison mode supports 2 to 5 listings.';
    return;
  }
  if (checked) commercialComparisonSet.add(listingId);
  else commercialComparisonSet.delete(listingId);
  renderCommercialComparison();
  renderCommercialList();
}

function renderCommercialComparison() {
  const panel = document.getElementById('commercial-comparison-panel');
  const table = document.getElementById('commercial-comparison-table');
  if (!panel || !table) return;
  if (commercialComparisonSet.size < 2) {
    panel.classList.add('hidden');
    updateRightPanelVisibility();
    return;
  }
  // Show comparison in right panel strip
  showDetailsPanel('commercial-comparison-panel');
  const selected = [...commercialComparisonSet]
    .map(id => rankedCommercialListings.find(item => item.listing_id === id) || commercialListings.find(item => item.listing_id === id))
    .filter(Boolean)
    .sort((a, b) => (b.commercial_score || 0) - (a.commercial_score || 0));
  table.innerHTML = selected.map(item => `
    <tr onclick="selectCommercialListing('${escapeHTML(item.listing_id)}')">
      <td>${escapeHTML(item.title)}</td>
      <td class="num-col">${formatNumber(item.commercial_score || 0, 1)}</td>
      <td class="num-col">${formatNumber(item.catchment?.metrics?.direct_total_units || item.catchment?.metrics?.known_residential_units || 0)}</td>
      <td class="num-col">${formatNumber(item.metro?.distance_km || 0, 1)} km</td>
    </tr>
  `).join('');
}

function clearCommercialComparison() {
  commercialComparisonSet.clear();
  document.getElementById('commercial-comparison-panel')?.classList.add('hidden');
  renderCommercialList();
  updateRightPanelVisibility();
}

async function addCustomCommercialListing() {
  const address = document.getElementById('commercial-custom-address').value.trim();
  const url = document.getElementById('commercial-custom-url').value;
  const price = parseFloat(document.getElementById('commercial-custom-price').value) || 0;
  const sqft = parseFloat(document.getElementById('commercial-custom-sqft').value) || 0;
  const propertyType = document.getElementById('commercial-custom-type').value;
  const floor = document.getElementById('commercial-custom-floor').value;
  const amenitiesStr = document.getElementById('commercial-custom-amenities').value;
  const amenities = amenitiesStr ? amenitiesStr.split(',').map(s => s.trim()) : [];

  const setStatus = (msg) => {
    const el = document.getElementById('commercial-custom-status');
    if (el) el.textContent = msg;
  };

  let lat = parseFloat(document.getElementById('commercial-custom-lat').value);
  let lon = parseFloat(document.getElementById('commercial-custom-lon').value);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    setStatus('Resolving location from map or address...');
    const resolved = await resolveCommercialCustomLocation();
    if (resolved) {
      lat = resolved.lat;
      lon = resolved.lon;
      setCommercialDraftLocation(lat, lon, resolved.source || 'Resolved location');
    }
  }

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    setStatus('Latitude and longitude are required. Use the map picker or address field first.');
    return;
  }

  setStatus('Calculating catchment area (Google Maps / routing)...');

  let catchment = null;
  try {
    const params = new URLSearchParams({
      city: activeLegacyCityId,
      category: activeLegacyCategoryId,
      lat: String(lat),
      lon: String(lon),
      radius: '7',
      travel_time_mins: String(catchmentQueryTimeMins),
      travel_speed_kmh: String(catchmentQuerySpeedKmh),
      travel_mode: catchmentTravelMode,
      live_traffic: String(catchmentLiveTraffic),
      smooth_edges: String(catchmentSmoothEdges),
      catchment_mode: catchmentQueryMode
    });
    const response = await fetch(`/api/catchment?${params.toString()}`, catchmentRequestOptions());
    let data;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    if (response.ok && data && data.status === 'success') {
      catchment = {
        radius_km: data.radius_km,
        travel_time_mins: data.travel_time_mins,
        travel_speed_kmh: data.travel_speed_kmh,
        travel_mode: data.travel_mode,
        live_traffic: data.live_traffic,
        smooth_edges: data.smooth_edges,
        catchment_mode: data.catchment_mode,
        routing_method: data.routing_method,
        center: data.center,
        matched_hex_ids: data.matched_hex_ids || [],
        metrics: data.metrics || {},
        income_bands: data.income_bands || {},
        societies: data.societies || [],
        hospitals: data.hospitals || [],
        radius_expansion: data.comparison || [],
        isochrone_geojson: data.isochrone_geojson
      };
    } else {
      const errMsg = data ? (data.message || (data.error && data.error.message)) : `HTTP ${response.status}`;
      setStatus(`API Error: ${errMsg || 'Unknown error'}`);
      return;
    }
  } catch (e) {
    console.error("Custom commercial API catchment failed:", e);
    setStatus('API catchment failed.');
    return;
  }

  if (!catchment) {
      setStatus('Failed to generate catchment using routing provider.');
    return;
  }
  catchment.commute = summarizeCommuteForHexIds(catchment.matched_hex_ids || []);

  setStatus('Fetching nearest metro station via Overpass API...');
  const metro = await nearestCommercialMetro(lat, lon);

  setStatus('Fetching road visibility data via Overpass API...');
  const visibility = await calculateRoadVisibility(lat, lon);

  const id = `custom_${commercialCustomCounter++}_${Date.now()}`;
  let customTitle = `Custom listing ${commercialCustomCounter - 1}`;
  if (address) {
    customTitle = address.length > 56 ? `${address.slice(0, 53)}...` : address;
  }
  if (url) {
    try {
      customTitle = `Custom listing ${new URL(url).hostname.replace(/^www\./, '')}`;
    } catch (e) {
      customTitle = 'Custom pasted listing';
    }
  }

  const rawListing = {
    listing_id: id,
    title: customTitle,
    property_type: propertyType,
    price,
    sqft,
    floor,
    amenities,
    latitude: lat,
    longitude: lon,
    listing_url: url,
    metro,
    visibility,
    catchment,
    source: 'custom'
  };
  
  const scoreResult = calculateCommercialScore(rawListing);
  rawListing.commercial_score = scoreResult.final;
  rawListing.score_components = scoreResult.components;

  setStatus('Saving listing to database...');
  try {
    const saveRes = await fetch('/api/listings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rawListing)
    });
    if (!saveRes.ok) {
      throw new Error(`Failed to save: HTTP ${saveRes.status}`);
    }
  } catch (err) {
    console.error(err);
    setStatus('Listing analyzed but failed to save to database.');
  }

  const listing = normalizeCommercialListing(rawListing);
  commercialListings.push(listing);
  rankedCommercialListings = [...commercialListings].sort((a, b) => (b.commercial_score || b.score || 0) - (a.commercial_score || a.score || 0));

  commercialComparisonSet.add(id);
  setTextIfExists('commercial-total-count', formatNumber(commercialListings.length));
  renderCommercialList();
  updateCommercialStats();
  selectCommercialListing(id);
  renderCommercialComparison();
  setStatus('Custom listing saved and ranked successfully.');
  commercialListingFilterTerm = '';
  const searchEl = document.getElementById('commercial-search-query');
  if (searchEl) searchEl.value = '';
  toggleCommercialLocationPickMode(false);
  clearCommercialDraftMarker();
}

async function resolveCustomListingPreview() {
  const statusEl = document.getElementById('commercial-custom-status');
  const setStatus = msg => {
    if (statusEl) statusEl.textContent = msg;
  };
  const resolved = await resolveCommercialCustomLocation();
  if (!resolved) {
    setStatus('Could not resolve that address. Try clicking the map instead.');
    return;
  }
  setCommercialDraftLocation(resolved.lat, resolved.lon, resolved.source || 'Resolved address');
  const mapTarget = L.latLng(resolved.lat, resolved.lon);
  map.setView(mapTarget, 14);
  setStatus(`Resolved to ${resolved.source || 'selected place'}.`);
}

function setZoneQuickFilter(filter) {
  zoneQuickFilter = filter || 'all';
  document.querySelectorAll('.zone-filter-chip').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-filter') === zoneQuickFilter);
  });
  renderZonesTab();
}

function clearZoneSearch() {
  zoneSearchTerm = '';
  const input = document.getElementById('zone-search-query');
  if (input) input.value = '';
  renderZonesTab();
}

function filterZonesList() {
  const input = document.getElementById('zone-search-query');
  zoneSearchTerm = (input?.value || '').trim().toLowerCase();
  renderZonesTab();
}

function renderZoneSummaryStrip(zoneEntries) {
  const strip = document.getElementById('zone-summary-strip');
  if (!strip) return;
  const totalZones = zoneEntries.length;
  const totalUnits = zoneEntries.reduce((sum, [, stats]) => sum + Number(stats.direct_total_units || 0), 0);
  const totalAudienceStudents = zoneEntries.reduce((sum, [, stats]) => sum + Number(stats.audience_students_grade_2_9 || 0), 0);
  strip.innerHTML = `
    <div class="zone-summary-card"><span>Zones</span><strong>${totalZones}</strong></div>
    <div class="zone-summary-card"><span>Total Units</span><strong>${totalUnits.toLocaleString()}</strong></div>
    <div class="zone-summary-card"><span>${escapeHTML(activeLegacyCategory().label)} students</span><strong>${formatNumber(totalAudienceStudents, 0)}</strong></div>
  `;
}

// TAB 2: ZONES
function renderZonesTab() {
  const tableBody = document.getElementById('zones-table-body');
  if (!tableBody) return;
  tableBody.innerHTML = '';

  const zoneEntries = getAudienceZoneEntries().sort((a, b) => (
    Number(b[1].audience_students_grade_2_9 || 0) - Number(a[1].audience_students_grade_2_9 || 0)
    || Number(b[1].top_score || b[1].avg_affluence_score || 0) - Number(a[1].top_score || a[1].avg_affluence_score || 0)
    || Number(b[1].direct_total_units || 0) - Number(a[1].direct_total_units || 0)
  ));
  renderZoneSummaryStrip(zoneEntries);
  setTextIfExists('zones-school-audience-heading', `${activeLegacyCategory().label} students`);
  setTextIfExists('zone-top-demand-filter-label', `Top ${activeLegacyCategory().label} demand`);

  const totalUnits = zoneEntries.reduce((sum, [, s]) => sum + Number(s.direct_total_units || 0), 0);

  const filteredEntries = zoneEntries.filter(([zoneName, stats], index) => {
    const searchHaystack = `${zoneName} ${stats.hex_count} ${stats.direct_total_units} ${stats.audience_school_count || 0} ${stats.audience_students_grade_2_9 || 0}`.toLowerCase();
    if (zoneSearchTerm && !searchHaystack.includes(zoneSearchTerm)) return false;
    if (zoneQuickFilter === 'top') return Number(stats.audience_students_grade_2_9 || 0) > 0 && index < 3;
    if (zoneQuickFilter === 'has_tam') return Number(stats.direct_total_units || 0) > 0 || Number(stats.audience_students_grade_2_9 || 0) > 0;
    return true;
  });

  filteredEntries.forEach(([zoneName, stats]) => {
    const pctShare = ((Number(stats.direct_total_units || 0) / Math.max(totalUnits, 1)) * 100).toFixed(1);
    const tr = document.createElement('tr');
    tr.id = `zone-row-${zoneName.replace(/\s+/g, '-').toLowerCase()}`;
    tr.classList.toggle('selected', selectedZone === zoneName);
    tr.innerHTML = `
      <td><strong>${zoneName}</strong></td>
      <td class="num-col">${stats.hex_count}</td>
      <td class="num-col">${Number(stats.direct_total_units || 0).toLocaleString()}</td>
      <td class="num-col">${formatNumber(stats.audience_students_grade_2_9 || 0, 0)}<small class="zone-school-count">${formatNumber(stats.audience_school_count || 0)} campuses</small></td>
    `;
    tr.addEventListener('click', () => selectZone(zoneName, tr));
    tableBody.appendChild(tr);
  });
}

function selectZone(zoneName, trElement) {
  // Highlight row
  document.querySelectorAll('#zones-table-body tr').forEach(row => row.classList.remove('selected'));
  if (trElement) trElement.classList.add('selected');

  selectedZone = zoneName;
  clearRolledUpAssetsLayer();
  const stats = getAudienceZoneStats(zoneName);
  const totalZoneUnits = getAudienceZoneEntries().reduce((s, [, z]) => s + Number(z.direct_total_units || 0), 0);
  const pctShare = ((Number(stats.direct_total_units || 0) / Math.max(totalZoneUnits, 1)) * 100).toFixed(1);
  const zoneLocked = !isUnlocked();
  const zoneHexIds = (layerData.hexes?.features || [])
    .filter(feature => feature.properties?.zone === zoneName)
    .map(feature => feature.properties.hex_id);
  const zoneSchoolEvidence = getAreaSchoolEvidence({
    type: 'zone', zone: zoneName, hexIds: zoneHexIds, center: getAreaSchoolCenter(zoneHexIds)
  });
  activeDetailsData.zone.schools = zoneSchoolEvidence.allInside;

  // Unified Standard Layout Template Injection
  renderStandardDetails(document.getElementById('zone-details-card'), {
    title: `${zoneName} Zone (${pctShare}%)`,
    titleId: 'zone-details-title',
    badge: 'Zone Details',
    onClose: 'clearZoneSelection()',
    headerActions: `<button class="gumroad-btn" id="button-view-full-data-table-zone-details" type="button">View Full Data Table</button>`,
    kpis: [
      { id: 'zone-kpi-students', value: formatNumber(zoneSchoolEvidence.allInsideStudents || 0, 0), label: 'Total no. of students' },
      { id: 'zone-kpi-schools', value: formatNumber(zoneSchoolEvidence.allInsideCount || 0, 0), label: 'Total no. of schools' },
      { id: 'zone-kpi-units', value: (stats.direct_total_units || 0).toLocaleString(), label: 'Total residential units' },
      { id: 'zone-kpi-q3-below', value: formatNumber(stats.q3_and_below_property_count || 0, 0), label: 'Q3 and Below Properties' },
      { id: 'zone-kpi-offices', value: '0', label: 'Office anchors', locked: zoneLocked }
    ],
    mainContent: `
      <h4 class="notion-heading-4">Units by Society Price Classification</h4>
      <div class="chart-container" id="zone-income-chart"></div>
      ${buildRolledUpAssetsControlsHtml('zone')}

      <h4 class="notion-heading-4">Who lives here?</h4>
      <ol class="notion-list" id="zone-top-localities-list"></ol>
    `,
    sections: [
      { title: 'Which schools are inside or close to this zone?', count: zoneSchoolEvidence.displayed.length, id: 'zone-schools-list', contentHtml: buildAreaSchoolEvidenceHtml(zoneSchoolEvidence, `${zoneName} Zone`), open: true },
      { title: 'Which residential projects are in this zone?', countId: 'zone-count-societies', id: 'zone-societies-list', onCopy: 'copyZoneSocieties(event)', open: true },
      { title: 'Which office anchors are present?', countId: 'zone-count-offices', id: 'zone-offices-list' },
      { title: 'What hospitals/markets support the affluence signal?', countId: 'zone-count-hospitals-markets', id: 'zone-hospitals-markets-list', onCopy: 'copyZoneHospitalsMarkets(event)' }
    ]
  });

  const fullDataButton = document.getElementById('button-view-full-data-table-zone-details');
  if (fullDataButton) {
    fullDataButton.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      openFullDataView();
    });
  }

  // Calculate zone confidence (metadata)
  const zoneSocieties = layerData.societies.filter(soc => soc.zone === zoneName);
  let zoneTotalConf = 0;
  let zoneConfCount = 0;
  zoneSocieties.forEach(soc => {
    if (soc.confidence !== undefined) {
      zoneTotalConf += soc.confidence;
      zoneConfCount++;
    }
  });
  const zoneAvgConf = zoneConfCount > 0 ? (zoneTotalConf / zoneConfCount) * 100 : 91.2;
  
  // Update office count for zone
  const zoneOfficesForKpi = (layerData.sez_offices || []).filter(o => o.zone === zoneName);
  setTextIfExists('zone-kpi-offices', formatNumber(zoneOfficesForKpi.length, 0));

  // Render real residential project classification, not synthetic income bands.
  renderProjectClassificationChart('zone-income-chart', zoneSocieties);

  // Render Top localities list
  const list = document.getElementById('zone-top-localities-list');
  list.innerHTML = '';
  const audienceByHex = new Map();
  getSchoolAudienceCampuses().forEach(campus => {
    const key = String(campus.hex_id || '');
    audienceByHex.set(key, (audienceByHex.get(key) || 0) + Number(campus.audience_enrollment || 0));
  });
  (stats.top_hexes || []).forEach(hex => {
    const li = document.createElement('li');
    const audienceStudents = audienceByHex.get(String(hex.hex_id || '')) || 0;
    li.innerHTML = `
      <span class="locality-name"><span class="ranking-num">#${hex.rank}</span> ${escapeHTML(hex.name || hex.hex_id)}</span>
      <span class="locality-val">${formatNumber(audienceStudents)} ${escapeHTML(activeLegacyCategory().label)} Grade 2–9 · ${formatNumber(hex.direct_total_units || 0)} units</span>
    `;
    list.appendChild(li);
  });

  // Render residential projects inside the selected zone, ranked by known units.
  zoneSocieties.sort((a, b) => Number(b.units || 0) - Number(a.units || 0));
  activeDetailsData.zone.societies = zoneSocieties;
  document.getElementById('zone-count-societies').textContent = zoneSocieties.length;
  const socList = document.getElementById('zone-societies-list');
  if (zoneSocieties.length > 0) {
    socList.innerHTML = zoneSocieties.map((soc, idx) => {
      const isLockedItem = !isUnlocked() && idx >= 3;
      const socName = isLockedItem ? 'Restricted residential project' : soc.name;
      const socTag = isLockedItem ? 'Positioning and units restricted' : `${soc.category || 'Positioning unavailable'} | Known units ${soc.units == null ? 'unavailable' : Number(soc.units).toLocaleString()}`;
      return `
        <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}">
          <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(soc.name)}">${escapeHTML(socName)}</div>
          <div class="poi-item-tag">${escapeHTML(socTag)}</div>
        </div>
      `;
    }).join('');
  } else {
    socList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No projects reported in this zone</div>';
  }

  // Render office-anchor listings inside selected zone
  const zoneOffices = (layerData.sez_offices || [])
    .filter(office => office.zone === zoneName)
    .sort((a, b) => Number(b.office_rank_score || 0) - Number(a.office_rank_score || 0));
  activeDetailsData.zone.offices = zoneOffices;
  setTextIfExists('zone-count-offices', formatNumber(zoneOffices.length, 0));
  const officeList = document.getElementById('zone-offices-list');
  if (officeList) {
    officeList.innerHTML = renderOfficeList(zoneOffices, {
      limit: 30,
      emptyText: 'No office anchor records matched this zone.'
    });
  }

  // Render Hospitals and Markets inside selected zone
  const zoneHospitals = layerData.hospitals.filter(h => h.zone === zoneName);
  zoneHospitals.sort((a, b) => b.beds - a.beds || b.rating - a.rating);
  activeDetailsData.zone.hospitals = zoneHospitals;

  const zoneLocalities = layerData.localities.filter(l => l.zone === zoneName);
  zoneLocalities.sort((a, b) => b.price_sqft - a.price_sqft);
  activeDetailsData.zone.localities = zoneLocalities;

  document.getElementById('zone-count-hospitals-markets').textContent = zoneHospitals.length + zoneLocalities.length;
  const hmList = document.getElementById('zone-hospitals-markets-list');
  
  let hmHtml = '';
  if (zoneHospitals.length > 0 || zoneLocalities.length > 0) {
    if (zoneHospitals.length > 0) {
      hmHtml += '<div class="poi-section-header">🏥 Key Hospitals</div>';
      hmHtml += zoneHospitals.slice(0, 15).map((h, idx) => {
        const isLockedItem = !isUnlocked() && idx >= 3;
        const hName = isLockedItem ? "Restricted Hospital Name" : h.name;
        const hTag = isLockedItem ? "Premium Category | Rating: Restricted | Beds: Restricted" : `${h.category} | Rating: ${h.rating}⭐ | Beds: ${h.beds || 'N/A'}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-type="hospital" data-idx="${idx}" data-locked="${isLockedItem}">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(h.name)}">${escapeHTML(hName)}</div>
            <div class="poi-item-tag">${escapeHTML(hTag)}</div>
          </div>
        `;
      }).join('');
    }
    if (zoneLocalities.length > 0) {
      hmHtml += '<div class="poi-section-header">🛍️ Costly Localities / Markets</div>';
      hmHtml += zoneLocalities.slice(0, 15).map((l, idx) => {
        const isLockedItem = !isUnlocked() && idx >= 3;
        const lName = isLockedItem ? "Restricted Locality Name" : l.name;
        const lTag = isLockedItem ? "Avg Price: Restricted/sqft | Segment: Restricted" : `Avg Price: ₹${l.price_sqft == null ? 'NA' : l.price_sqft.toLocaleString()}/sqft | Segment: ${l.budget_segment}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-type="locality" data-idx="${idx}" data-locked="${isLockedItem}">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(l.name)}">${escapeHTML(lName)}</div>
            <div class="poi-item-tag">${escapeHTML(lTag)}</div>
          </div>
        `;
      }).join('');
    }
  } else {
    hmHtml = '<div style="padding: 10px; color:#6b7280;">No premium hospitals or markets in this zone</div>';
  }
  hmList.innerHTML = hmHtml;

  // Display detail card
  showDetailsPanel('zone-details-card');
  setAreaSchoolContext(zoneSchoolEvidence.displayed);

  // Map Filter: Highlight zone hexes, zoom map
  highlightZoneHexes(zoneName);

  // Style Zone Polygon boundary
  Object.entries(zonePolygons).forEach(([name, poly]) => {
    if (name === zoneName) {
      poly.setStyle({
        fillOpacity: 0.12,
        weight: 3,
        dashArray: ''
      });
    } else {
      poly.setStyle({
        fillOpacity: 0.01,
        weight: 1.0,
        dashArray: '3, 4'
      });
    }
  });

  // Add/Update floating divIcon label at centroid
  if (activeZoneLabelMarker) {
    map.removeLayer(activeZoneLabelMarker);
  }

  let labelLat = CENTRAL_LAT;
  let labelLon = CENTRAL_LON;
  if (zoneName !== 'Central') {
    const zoneAngles = {
      "North": { start: -22.5, end: 22.5 },
      "North-East": { start: 22.5, end: 67.5 },
      "East": { start: 67.5, end: 112.5 },
      "South-East": { start: 112.5, end: 157.5 },
      "South": { start: 157.5, end: 202.5 },
      "South-West": { start: 202.5, end: 247.5 },
      "West": { start: 247.5, end: 292.5 },
      "North-West": { start: 292.5, end: 337.5 }
    };
    const angleCfg = zoneAngles[zoneName];
    const midAngle = (angleCfg.start + angleCfg.end) / 2;
    // Position label in the middle sector at 14km distance from center
    const dest = destinationLatLng(CENTRAL_LAT, CENTRAL_LON, 14.0, midAngle);
    labelLat = dest[0];
    labelLon = dest[1];
  } else {
    // slightly offset Central zone label
    labelLat = CENTRAL_LAT + 0.005;
  }

  const customIcon = L.divIcon({
    className: 'custom-zone-label-icon',
    html: `<div class="zone-floating-label">
             <strong>${zoneName} Zone</strong><br/>
             ${formatNumber(stats.audience_students_grade_2_9 || 0)} ${escapeHTML(activeLegacyCategory().label)} Grade 2–9
           </div>`,
    iconSize: [140, 40],
    iconAnchor: [70, 20]
  });

  activeZoneLabelMarker = L.marker([labelLat, labelLon], { icon: customIcon }).addTo(map);
  // The roll-up controls are checked by default, so keep the map in sync as soon
  // as a zone is selected (including every school in the active audience bucket).
  renderRolledUpAssetsMapLayers('zone');
  updateActiveLayersPanel();
}

function clearZoneSelection() {
  document.getElementById('zone-details-card').classList.add('hidden');
  updateRightPanelVisibility();
  document.querySelectorAll('#zones-table-body tr').forEach(row => row.classList.remove('selected'));
  selectedZone = null;
  clearRolledUpAssetsLayer();
  clearAreaSchoolContext();
  resetHexHighlights();
  if (activePoiMarker) {
    map.removeLayer(activePoiMarker);
    activePoiMarker = null;
  }

  // Reset zone accordions details
  document.getElementById('zone-count-societies').textContent = '0';
  document.getElementById('zone-societies-list').innerHTML = '';

  // Reset polygon boundaries style
  Object.entries(zonePolygons).forEach(([name, poly]) => {
    poly.setStyle({
      fillOpacity: 0.04,
      weight: 1.5,
      dashArray: '3, 4'
    });
  });

  if (activeZoneLabelMarker) {
    map.removeLayer(activeZoneLabelMarker);
    activeZoneLabelMarker = null;
  }
  updateActiveLayersPanel();
}

function highlightZoneHexes(zoneName) {
  const bounds = [];
  overlayLayers.hexes.eachLayer(function (layer) {
    const props = layer.feature.properties;
    const fZone = props.zone;
    if (fZone === zoneName) {
      layer.setStyle({
        fillColor: getHexColor(props.final_affluence_score),
        fillOpacity: hexHighlightEnabled ? 0.85 : 0,
        weight: 2,
        color: '#111827'
      });
      const coords = layer.getLatLngs()[0];
      coords.forEach(pt => bounds.push(pt));
    } else {
      layer.setStyle({
        fillColor: getHexColor(props.final_affluence_score),
        fillOpacity: hexHighlightEnabled ? 0.1 : 0,
        weight: 0.5,
        color: '#e5e7eb'
      });
    }
  });
  hexesAreHighlighted = true;

  if (bounds.length > 0) {
    map.fitBounds(L.latLngBounds(bounds), { padding: [30, 30] });
  }
}



// Reset H3 Hex layers highlighting
function resetHexHighlights() {
  if (!hexesAreHighlighted) return;
  const defaultOpacity = parseFloat(document.getElementById('opacity-slider-hexes').value);
  overlayLayers.hexes.eachLayer(function (layer) {
    const score = layer.feature.properties.final_affluence_score;
    layer.setStyle({
      fillColor: getHexColor(score),
      color: '#ffffff',
      weight: 1,
      fillOpacity: defaultOpacity
    });
  });
  hexesAreHighlighted = false;
}

// Helper to draw horizontal custom bar graph with percentages
function renderIncomeBandChart(containerId, data) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';
  if (!data) return;
  
  const bands = ["Ultra Luxury", "Elite Luxury", "Super Luxury", "Premium Luxury", "Luxury", "Premium", "Aspirational Premium"];
  const labelMapping = {
    "Ultra Luxury": "Ultra Luxury",
    "Elite Luxury": "Elite Luxury",
    "Super Luxury": "Super Luxury",
    "Premium Luxury": "Premium Luxury",
    "Luxury": "Luxury",
    "Premium": "Premium",
    "Aspirational Premium": "Aspirational Premium"
  };
  const totalUnits = Object.values(data).reduce((acc, v) => acc + v, 0);
  
  // Find max value to establish percentage widths
  let maxVal = 0;
  bands.forEach(b => {
    const val = data[b] || 0;
    if (val > maxVal) maxVal = val;
  });

  const html = bands.map(b => {
    const val = data[b] || 0;
    const label = labelMapping[b] || b;
    const pctShare = totalUnits > 0 ? ((val / totalUnits) * 100).toFixed(1) : '0.0';
    const barId = `${containerId}-bar-${b.replace(/[\+\-\s]/g, '')}`;
    return `
      <div class="chart-bar-row">
        <div class="chart-bar-labels">
          <span class="chart-label">${label}</span>
          <span class="chart-value">${val.toLocaleString()} units (${pctShare}%)</span>
        </div>
        <div class="chart-bar-bg">
          <div class="chart-bar-fill" style="width: 0%;" id="${barId}"></div>
        </div>
      </div>
    `;
  }).join('');
  
  container.innerHTML = html;

  // Apply animation width with slight timeout
  setTimeout(() => {
    bands.forEach(b => {
      const val = data[b] || 0;
      const pctWidth = maxVal > 0 ? (val / maxVal * 100) : 0;
      const fillBar = document.getElementById(`${containerId}-bar-${b.replace(/[\+\-\s]/g, '')}`);
      if (fillBar) fillBar.style.width = `${pctWidth}%`;
    });
  }, 50);
}

function renderProjectClassificationChart(containerId, societies) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const rows = Array.isArray(societies) ? societies : [];
  const grouped = new Map();
  rows.forEach(soc => {
    const label = soc.category || soc.quartile || 'Unclassified';
    if (!grouped.has(label)) grouped.set(label, { units: 0, count: 0 });
    const bucket = grouped.get(label);
    bucket.units += Number(soc.units || 0);
    bucket.count += 1;
  });
  const entries = [...grouped.entries()]
    .sort((a, b) => b[1].units - a[1].units || a[0].localeCompare(b[0]));
  const totalUnits = entries.reduce((sum, [, bucket]) => sum + bucket.units, 0);
  const maxUnits = entries.reduce((max, [, bucket]) => Math.max(max, bucket.units), 0);
  if (!entries.length || totalUnits <= 0) {
    container.innerHTML = '<div class="empty-state">No unit-bearing residential projects are available for this zone.</div>';
    return;
  }
  container.innerHTML = entries.map(([label, bucket]) => {
    const pctShare = totalUnits > 0 ? ((bucket.units / totalUnits) * 100).toFixed(1) : '0.0';
    const width = maxUnits > 0 ? Math.max(2, (bucket.units / maxUnits) * 100) : 0;
    return `
      <div class="chart-bar-row">
        <div class="chart-bar-labels">
          <span class="chart-label">${escapeHTML(label)}</span>
          <span class="chart-value">${formatNumber(bucket.units, 0)} units (${pctShare}%) · ${formatNumber(bucket.count, 0)} projects</span>
        </div>
        <div class="chart-bar-bg">
          <div class="chart-bar-fill" style="width:${width}%;"></div>
        </div>
      </div>
    `;
  }).join('');
}

let selectedHexFeature = null;

function selectHex(props, layer) {
  selectedHexFeature = props;
  clearRolledUpAssetsLayer();
  
  // Filter databases dynamically using hex_id
  const hexSocieties = layerData.societies.filter(soc => soc.hex_id === props.hex_id);
  hexSocieties.sort((a, b) => Number(b.units || 0) - Number(a.units || 0));
  activeDetailsData.hex.societies = hexSocieties;

  const hexHospitals = layerData.hospitals.filter(h => h.hex_id === props.hex_id);
  hexHospitals.sort((a, b) => b.beds - a.beds || b.rating - a.rating);
  activeDetailsData.hex.hospitals = hexHospitals;

  const hexOffices = (layerData.sez_offices || [])
    .filter(office => office.hex_id === props.hex_id)
    .sort((a, b) => Number(b.office_rank_score || 0) - Number(a.office_rank_score || 0));
  activeDetailsData.hex.offices = hexOffices;
  const hexSchoolEvidence = getAreaSchoolEvidence({
    type: 'hex',
    hexIds: [props.hex_id],
    center: { lat: Number(props.centroid_lat), lon: Number(props.centroid_lon) }
  });
  activeDetailsData.hex.schools = hexSchoolEvidence.allInside;

  const pctShare = ((Number(props.direct_total_units || 0) / Math.max(totalSelectedCityTam, 1)) * 100).toFixed(2);
  const priceSqft = props.market_price_per_sqft ? `₹${props.market_price_per_sqft.toLocaleString(undefined, {maximumFractionDigits:0})}` : 'N/A';
  const rentYield = props.rental_yield_pct ? `${props.rental_yield_pct.toFixed(1)}%` : 'N/A';
  const shift = props.rank_shift || 0;

  // Unified Standard Layout Template Injection
  renderStandardDetails(document.getElementById('hex-details-card'), {
    title: props.name || `Hex #${props.rank || ''}`,
    titleId: 'hex-details-title',
    badge: props.affluence_tier || 'N/A',
    badgeId: 'hex-details-badge',
    onClose: 'clearHexSelection()',
    kpis: [
      { id: 'hex-kpi-score', value: props.final_affluence_score ? props.final_affluence_score.toFixed(1) : '0', label: 'Context score' },
      { id: 'hex-kpi-reported', value: formatNumber(props.premium_plus_students_grade_2_9 || 0), label: 'Reported Premium+ Grade 2–9' },
      { id: 'hex-kpi-units', value: props.direct_total_units ? props.direct_total_units.toLocaleString() : '0', label: 'Known residential units' },
      { id: 'hex-kpi-societies', value: formatNumber(hexSocieties.length, 0), label: 'Residential projects' },
      { id: 'hex-kpi-schools', value: formatNumber(hexSchoolEvidence.allInsideCount, 0), label: 'Campuses in this hex' },
    ],
    metadata: {
      'Avg price / SqFt': priceSqft,
      'Rental yield': rentYield,
      'Network Cluster': (props.community_id !== undefined && props.community_id !== null) ? `#${props.community_id}` : 'N/A',
      'PageRank (×1k)': props.pagerank_personalized ? (props.pagerank_personalized * 1000).toFixed(2) : 'N/A'
    },
    mainContent: `
      <div id="hex-kpi-badge-container" style="margin-top: 10px; display: none; align-items: center; gap: 8px;">
        <span class="badge" id="hex-kpi-node-type" style="padding: 3px 8px; font-size: 10px; border-radius: 4px; font-weight: 600; text-transform: uppercase;">Strategic Hub</span>
        <span style="font-size: 10.5px; font-weight: 500; color: var(--text-muted);" id="hex-kpi-node-shift-text">Rank shift: +15 positions</span>
      </div>
      <div id="hex-kpi-node-explanation" style="margin-top: 8px; font-size: 11px; line-height: 1.45; color: var(--text-main); background: var(--bg-sidebar); border: 1px solid var(--border-light); border-radius: 4px; padding: 10px; display: none;"></div>
      <h4 class="notion-heading-4">Known units by project positioning</h4>
      <div class="chart-container" id="hex-income-chart"></div>
      ${buildRolledUpAssetsControlsHtml('hex')}
    `,
    sections: [
      { title: 'Nearest canonical school campuses', count: hexSchoolEvidence.displayed.length, id: 'hex-schools-list', contentHtml: buildAreaSchoolEvidenceHtml(hexSchoolEvidence, props.name || props.hex_id), open: true },
      { title: 'Residential projects', countId: 'hex-count-societies', id: 'hex-societies-list', onCopy: 'copyHexSocieties(event)', open: true },
      { title: 'Hospitals nearby', countId: 'hex-count-hospitals', id: 'hex-hospitals-list', onCopy: 'copyHexHospitals(event)' },
      { title: 'Office anchors in this hex', countId: 'hex-count-offices', id: 'hex-offices-list' }
    ]
  });

  renderProjectClassificationChart('hex-income-chart', hexSocieties);

  const rankShiftEl = document.getElementById('hex-kpi-rankshift');
  if (rankShiftEl) {
    if (shift > 0) {
      rankShiftEl.innerHTML = `<span class="rank-shift-up">▲ +${shift}</span>`;
    } else if (shift < 0) {
      rankShiftEl.innerHTML = `<span class="rank-shift-down">▼ ${shift}</span>`;
    } else {
      rankShiftEl.innerHTML = `<span class="rank-shift-stable">Stable</span>`;
    }
  }

  // Calculate adjacent neighbors dynamically
  const lat1 = props.centroid_lat;
  const lon1 = props.centroid_lon;
  const adjacentNeighbors = [];
  if (layerData.hexes && layerData.hexes.features) {
    layerData.hexes.features.forEach(feat => {
      const p = feat.properties;
      if (p.hex_id === props.hex_id) return;
      const dist = L.latLng(lat1, lon1).distanceTo(L.latLng(p.centroid_lat, p.centroid_lon));
      if (dist <= 2600) {
        adjacentNeighbors.push(p);
      }
    });
  }
  const neighborCount = adjacentNeighbors.length;

  // Dynamic Badge & Explanation updating
  const badgeContainer = document.getElementById('hex-kpi-badge-container');
  const badgeNodeType = document.getElementById('hex-kpi-node-type');
  const badgeShiftText = document.getElementById('hex-kpi-node-shift-text');
  const nodeExplanation = document.getElementById('hex-kpi-node-explanation');
  
  if (badgeContainer && badgeNodeType && badgeShiftText && nodeExplanation) {
    // Classify node type
    let nodeType = props.pagerank_node_type || 'Connected Residential';
    let explanation = `This cell is a standard connected residential zone with stable local contiguity (${neighborCount} adjacent premium cells) and steady catchment drawing potential.`;
    let badgeBg = '#eff6ff';
    let badgeColor = '#2563eb';
    let badgeBorder = '#bfdbfe';
    
    if (nodeType === 'Strategic Hub') {
      explanation = `This cell is a strategic centrality hub in the directional network view. It is contiguous with ${neighborCount} adjacent premium-context cells; validate direct school enrollment and access before treating it as a launch gateway.`;
      badgeBg = '#f0fdf4';
      badgeColor = '#16a34a';
      badgeBorder = '#bbf7d0';
    } else if (nodeType === 'Wealth Island') {
      explanation = `This cell is isolated in the directional network view despite a high context score (${Number(props.final_affluence_score || 0).toFixed(1)}). Only ${neighborCount} adjacent cells share this bracket, so validate direct school demand and access before site selection.`;
      badgeBg = '#fef2f2';
      badgeColor = '#dc2626';
      badgeBorder = '#fca5a5';
    }
    
    badgeNodeType.textContent = nodeType;
    badgeNodeType.style.background = badgeBg;
    badgeNodeType.style.color = badgeColor;
    badgeNodeType.style.border = `1px solid ${badgeBorder}`;
    
    if (shift > 0) {
      badgeShiftText.textContent = `Rank improved by +${shift} positions`;
    } else if (shift < 0) {
      badgeShiftText.textContent = `Rank dropped by ${shift} positions`;
    } else {
      badgeShiftText.textContent = 'Rank is stable';
    }
    
    nodeExplanation.textContent = explanation;
    badgeContainer.style.display = 'flex';
    nodeExplanation.style.display = 'block';
  }

  // Update rollup count text in headers
  document.getElementById('hex-count-societies').textContent = hexSocieties.length;
  document.getElementById('hex-count-hospitals').textContent = hexHospitals.length;
  document.getElementById('hex-count-offices').textContent = hexOffices.length;

  // Build lists with Zone-like premium markup
  const socList = document.getElementById('hex-societies-list');
  if (socList) {
    if (hexSocieties.length > 0) {
      socList.innerHTML = hexSocieties.map((soc, idx) => {
        const isLockedItem = !isUnlocked() && idx >= 3;
        const socName = isLockedItem ? 'Restricted residential project' : soc.name;
        const socTag = isLockedItem ? 'Positioning and units restricted' : `${soc.category || 'Positioning unavailable'} | Known units ${soc.units == null ? 'unavailable' : Number(soc.units).toLocaleString()}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(soc.name)}">${escapeHTML(socName)}</div>
            <div class="poi-item-tag">${escapeHTML(socTag)}</div>
          </div>
        `;
      }).join('');
    } else {
      socList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No projects reported in this hex</div>';
    }
  }

  const hospList = document.getElementById('hex-hospitals-list');
  if (hospList) {
    if (hexHospitals.length > 0) {
      hospList.innerHTML = hexHospitals.map((h, idx) => {
        const isLockedItem = !isUnlocked() && idx >= 3;
        const hName = isLockedItem ? "Restricted Hospital Name" : h.name;
        const hTag = isLockedItem ? "Premium Category | Rating: Restricted | Beds: Restricted" : `${h.category} | Rating: ${h.rating}⭐ | Beds: ${h.beds || 'N/A'}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(h.name)}">${escapeHTML(hName)}</div>
            <div class="poi-item-tag">${escapeHTML(hTag)}</div>
          </div>
        `;
      }).join('');
    } else {
      hospList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No premium hospitals in this hex</div>';
    }
  }

  const hexOfficeList = document.getElementById('hex-offices-list');
  if (hexOfficeList) {
    hexOfficeList.innerHTML = renderOfficeList(hexOffices, {
      limit: 25,
      emptyText: 'No office anchor records in this hex.'
    });
  }

  // Highlight this hex specifically on the map
  highlightSingleHex(props.hex_id);

  // Show right details panel
  showDetailsPanel('hex-details-card');
  setAreaSchoolContext(hexSchoolEvidence.displayed);
}

function clearHexSelection() {
  document.getElementById('hex-details-card').classList.add('hidden');
  const badgeContainer = document.getElementById('hex-kpi-badge-container');
  const nodeExplanation = document.getElementById('hex-kpi-node-explanation');
  if (badgeContainer) badgeContainer.style.display = 'none';
  if (nodeExplanation) nodeExplanation.style.display = 'none';
  
  clearRolledUpAssetsLayer();
  clearAreaSchoolContext();
  resetHexHighlights();
  if (activePoiMarker) {
    map.removeLayer(activePoiMarker);
    activePoiMarker = null;
  }
  if (commuteRouteLayer && map.hasLayer(commuteRouteLayer)) {
    map.removeLayer(commuteRouteLayer);
  }
  selectedHexFeature = null;
  updateRightPanelVisibility();
}

function highlightSingleHex(hexId) {
  resetHexHighlights();
  const layer = hexLayerLookup.get(hexId);
  if (layer) {
    layer.setStyle({
      weight: 3.5,
      color: '#2383e2',
      fillOpacity: 0.8
    });
    if (typeof layer.bringToFront === 'function') {
      layer.bringToFront();
    }
    hexesAreHighlighted = true;
  }
}

// Leaflet Hex click callback
function showHexDetailsPopup(props, layer) {
  const societies = props.top_societies ? props.top_societies.split(" | ") : [];
  const hospitals = props.top_hospitals ? props.top_hospitals.split(" | ") : [];
  let socHtml = "";
  if (societies.length > 0) {
    socHtml = societies.map(s => `<li>${s}</li>`).join("");
  } else {
    socHtml = "<li>No premium societies in this hex</li>";
  }

  let hospHtml = "";
  if (hospitals.length > 0) {
    hospHtml = hospitals.map(h => `<li>${h}</li>`).join("");
  } else {
    hospHtml = "<li>No premium hospitals nearby</li>";
  }

  const rentYield = props.rental_yield_pct ? `${props.rental_yield_pct.toFixed(1)}%` : 'N/A';
  const yearlyApp = props.yearly_appreciation_pct ? `${props.yearly_appreciation_pct.toFixed(1)}%` : 'N/A';
  const priceSqft = props.market_price_per_sqft ? `₹${props.market_price_per_sqft.toLocaleString(undefined, {maximumFractionDigits:0})}/sqft` : 'N/A';
  const pctShare = ((Number(props.direct_total_units || 0) / Math.max(totalSelectedCityTam, 1)) * 100).toFixed(2);
  const commute = getCommuteByHexId(props.hex_id) || { score: props.commute_score, band: props.commute_band, evidence: props.commute_evidence };
  const commuteScore = commute?.score || props.commute_score || 0;
  const commuteBand = commute?.band || props.commute_band || 'Commute proxy';

  const popupContent = `
    <div class="notion-popup">
      <div class="popup-header">
        <strong>#${props.rank} ${props.name}</strong>
        <span class="popup-badge">${props.affluence_tier}</span>
      </div>
      <div class="popup-score">
        Context score: <strong>${Number(props.final_affluence_score || 0).toFixed(1)}</strong>
      </div>
      <div class="popup-score">
        Commute Convenience: <strong>${formatNumber(commuteScore, 1)}</strong> <span style="color:var(--text-muted);">(${escapeHTML(commuteBand)})</span>
      </div>
      <div class="popup-grid">
        <div>Reported Premium+ Grade 2–9: <strong>${formatNumber(props.premium_plus_students_grade_2_9 || 0)}</strong></div>
        <div>Known units: <strong>${formatNumber(props.direct_total_units || 0)} (${pctShare}% of known city units)</strong></div>
        <div>Avg Price: <strong>${priceSqft}</strong></div>
        <div>Rent Yield: <strong>${rentYield}</strong></div>
        <div>Appreciation: <strong>${yearlyApp}</strong></div>
        <div>Segment: <strong>${props.refined_budget_segment}</strong></div>
        <div>Net. Cluster: <strong>#${props.community_id !== undefined && props.community_id !== null ? props.community_id : 'N/A'}</strong></div>
        <div>PageRank (×1k): <strong>${props.pagerank_personalized ? (props.pagerank_personalized * 1000).toFixed(2) : 'N/A'}</strong></div>
        <div>Rank Shift: <strong>${props.rank_shift !== undefined ? (props.rank_shift > 0 ? '+' + props.rank_shift : props.rank_shift) : 'N/A'}</strong></div>
        <div>Entry/exit proxy: <strong>${commute?.evidence?.entry_exit_proxy_count || 'N/A'}</strong></div>
      </div>
      <div class="popup-section">
        <strong>Residential projects:</strong>
        <ul>${socHtml}</ul>
      </div>
      <div class="popup-section">
        <strong>Hospitals:</strong>
        <ul>${hospHtml}</ul>
      </div>
      <div class="popup-section">
        <strong>Commute caveat:</strong>
        <div>${escapeHTML(commute?.evidence?.traffic_caveat || 'Free OSM/OSRM proxy; not live traffic.')}</div>
      </div>
    </div>
  `;

  L.popup({
    maxWidth: 340,
    className: 'notion-popup-container'
  })
  .setLatLng([props.centroid_lat, props.centroid_lon])
  .setContent(popupContent)
  .openOn(map);
}

function drawCommuteRouteGuides(props) {
  if (commuteRouteLayer && map.hasLayer(commuteRouteLayer)) {
    map.removeLayer(commuteRouteLayer);
  }
  commuteRouteLayer = L.layerGroup();
  const origin = [props.centroid_lat, props.centroid_lon];
  const targets = [];
  (props.top_hospitals ? props.top_hospitals.split(" | ") : []).slice(0, 1).forEach(raw => {
    const name = raw.split('(')[0].trim();
    const hospital = hospitalLookup.get(name);
    if (hospital?.lat && hospital?.lon) targets.push({ name, lat: hospital.lat, lon: hospital.lon, color: '#7c3aed' });
  });
  targets.forEach(target => {
    L.polyline([origin, [target.lat, target.lon]], {
      color: target.color,
      weight: 1.5,
      opacity: 0.72,
      dashArray: '5, 6'
    }).bindTooltip(`Commute guide: ${target.name}`, { sticky: true }).addTo(commuteRouteLayer);
  });
  if (targets.length) commuteRouteLayer.addTo(map);
}

// Map base click callback (if clicking outside direct hexes in Catchment mode)
function onMapBaseClick(e) {
  if (commercialLocationPickMode) {
    setCommercialDraftLocation(e.latlng.lat, e.latlng.lng, 'Picked from map');
    return;
  }
  if (catchmentModeEnabled) {
    onMapClick(e);
  }
}

// TAB 4: CATCHMENT AGGREGATOR CLICK QUERY
function onMapClick(e) {
  const lat = e.latlng.lat;
  const lon = e.latlng.lng;

  // Add catchment marker
  if (catchmentMarker) {
    catchmentMarker.setLatLng(e.latlng);
  } else {
    catchmentMarker = L.marker(e.latlng).addTo(map);
  }

  // Draw catchment circle (Removed to keep map clean until isochrones load)
  if (catchmentCircle) {
    map.removeLayer(catchmentCircle);
    catchmentCircle = null;
  }
  
  // Auto zoom fit catchment point
  map.setView(e.latlng, 12);

  // Move sidebar to catchment tab
  switchTab('catchment');

  // Trigger query API backend
  fetchCatchmentData(lat, lon);
}

function _setCatchmentLoadingStatus(title, detail) {
  const ph = document.getElementById('catchment-placeholder');
  if (!ph) return;
  ph.innerHTML = `
    <div style="padding: 30px; text-align:center; color: var(--text-muted);" class="fade-container">
      <div class="spinner" style="margin: 0 auto 12px auto; width: 24px; height: 24px; border: 2.5px solid #e9e9e6; border-top-color: var(--accent-color); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
      <div style="font-weight: 600; font-size: 12.5px; color: var(--text-main); margin-top: 8px;">${title}</div>
      <div style="font-size: 10.5px; color: var(--text-muted); margin-top: 4px;">${detail}</div>
    </div>
  `;
}

async function fetchCatchmentData(lat, lon) {
  const apiKey = getCatchmentGoogleApiKey();
  if (!isValidCatchmentGoogleApiKey(apiKey)) {
    syncCatchmentMode(false);
    setCatchmentKeyStatus('Paste a valid restricted Google Maps key before running a catchment.', 'error');
    document.getElementById('catchment-google-api-key')?.focus();
    return;
  }
  _setCatchmentLoadingStatus('Connecting to Google Isochrone API', `Requesting boundaries for 15, 30, 45 &amp; 60 min · ${catchmentTravelMode} · ${catchmentLiveTraffic ? 'Live Traffic' : 'No Traffic'}`);
  document.getElementById('catchment-placeholder').classList.remove('hidden');
  document.getElementById('catchment-results-panel').classList.add('hidden');
  updateRightPanelVisibility();

  try {
    const params = new URLSearchParams({
      city: activeLegacyCityId,
      category: activeLegacyCategoryId,
      lat: String(lat),
      lon: String(lon),
      radius: String(catchmentQueryRadius),
      travel_time_mins: String(catchmentQueryTimeMins),
      travel_speed_kmh: String(catchmentQuerySpeedKmh),
      travel_mode: catchmentTravelMode,
      live_traffic: String(catchmentLiveTraffic),
      smooth_edges: String(catchmentSmoothEdges),
      catchment_mode: catchmentQueryMode,
      include_bands: 'true'
    });

    // Update status while waiting for network
    const statusInterval = (() => {
      const phases = [
        ['Computing H3 hex intersections', 'Matching hexes that overlap ≥25% with each isochrone band...'],
        ['Aggregating direct evidence', 'Matching school enrollment, named residential projects, and known units...'],
        ['Fetching metro routing', 'Computing drive distances to nearest metro stations...']
      ];
      let i = 0;
      return setInterval(() => {
        if (i < phases.length) {
          _setCatchmentLoadingStatus(phases[i][0], phases[i][1]);
          i++;
        }
      }, 4000);
    })();

    const res = await fetch(`/api/catchment?${params.toString()}`, catchmentRequestOptions());
    clearInterval(statusInterval);
    const data = await res.json();

    if (data.status === 'success') {
      setCatchmentKeyStatus('Routing completed. The key remains only in this browser tab.', 'ready');
      _setCatchmentLoadingStatus('Rendering map layers', 'Drawing isochrone polygons and highlighting matched hexes...');
      // Yield to browser paint so the status message is actually visible
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      renderCatchmentDashboard(data);
    } else {
      const errMsg = data.message || (data.error && data.error.message) || 'An unknown error occurred.';
      setCatchmentKeyStatus('Routing did not complete. Check the key restrictions and enabled APIs.', 'error');
      document.getElementById('catchment-placeholder').innerHTML = `
        <div class="notion-block warning-block">
          <p><strong>Error Querying Catchment</strong></p>
          <p>${errMsg}</p>
        </div>
      `;
    }
  } catch (err) {
    setCatchmentKeyStatus('The routing service could not be reached. Your key was not stored.', 'error');
    document.getElementById('catchment-placeholder').innerHTML = `
      <div class="notion-block warning-block">
        <p><strong>Connection Error</strong></p>
        <p>Could not connect to python backend server. Verify server is running on port 8050.</p>
      </div>
    `;
    console.error("Catchment fetch error:", err);
  }
}

function buildCatchmentComparison(rows, selectedTimeMins) {
  const times = [15, 30, 45, 60];
  const sorted = [...rows].sort((a, b) => Number(a.time_mins || a.radius || 0) - Number(b.time_mins || b.radius || 0));
  const keyed = new Map(sorted.map(row => [Math.round(Number(row.time_mins ?? row.radius ?? 0)), row]));
  catchmentComparisonLookup = keyed;
  const base = times.map(t => keyed.get(t) || null).filter(Boolean);
  if (!selectedTimeMins || !keyed.has(Number(selectedTimeMins))) return base;
  return times.map(t => keyed.get(t) || {
    time_mins: t,
    hex_count: 0,
    reported_students_grade_2_9: 0
  });
}

function setCatchmentIsochroneSelection(mins) {
  catchmentIsochroneSelection = Number(mins);
  const chips = document.querySelectorAll('.catchment-iso-toggle');
  chips.forEach(btn => btn.classList.toggle('active', Number(btn.dataset.minutes) === Number(mins)));
  // Update layer styles without re-adding layers
  updateCatchmentIsochroneStyles(Number(mins));
  // Update dashboard metrics and POI lists for selected band
  if (activeCatchmentData) {
    updateCatchmentDashboardMetrics(activeCatchmentData, Number(mins));
    // Re-render POI lists filtered to this time band
    updateCatchmentPOILists(activeCatchmentData, Number(mins));
    const selectedRow = catchmentComparisonLookup.get(Number(mins));
    if (selectedRow && selectedRow.matched_hex_ids) {
      highlightCatchmentHexes(selectedRow.matched_hex_ids);
      updateActiveLayersPanel();
    }
  }
}

const ISOCHRONE_COLORS = { 15: '#2563eb', 30: '#7c3aed', 45: '#ea580c', 60: '#16a34a' };
const ISOCHRONE_LABELS = { 15: '15 min', 30: '30 min', 45: '45 min', 60: '60 min' };

function renderCatchmentIsochroneGeometryLayer(data) {
  // Remove ALL old layers properly
  if (catchmentPolygonLayer) {
    catchmentPolygonLayer.remove();
    catchmentPolygonLayer = null;
  }
  catchmentIsochroneLayers = {};

  const geoms = data.isochrone_geometries || {};
  const selected = Number(catchmentIsochroneSelection || data.travel_time_mins || catchmentQueryTimeMins || 15);
  const layers = [];

  // Add in reverse order so smaller (inner) bands render on top
  [60, 45, 30, 15].forEach(mins => {
    const geom = geoms[String(mins)];
    if (!geom) return;
    const isSelected = mins === selected;
    const color = ISOCHRONE_COLORS[mins] || '#2383e2';
    const layer = L.geoJSON(geom, {
      style: {
        color: color,
        fillColor: color,
        fillOpacity: isSelected ? 0.20 : 0,
        opacity: isSelected ? 1 : 0,
        weight: isSelected ? 3.5 : 0
      }
    });
    if (isSelected) {
      layer.bindTooltip(ISOCHRONE_LABELS[mins] || `${mins}m`, {
        sticky: true,
        className: 'isochrone-tooltip',
        direction: 'top'
      });
    }
    catchmentIsochroneLayers[mins] = layer;
    layers.push(layer);
  });

  if (layers.length) {
    // Add as a single featureGroup to the map (fixes the removal bug)
    catchmentPolygonLayer = L.featureGroup(layers);
    catchmentPolygonLayer.addTo(map);
    // Bring the selected band to front
    if (catchmentIsochroneLayers[selected]) {
      catchmentIsochroneLayers[selected].bringToFront();
    }
  }
}

function updateCatchmentIsochroneStyles(selectedMins) {
  Object.entries(catchmentIsochroneLayers).forEach(([mins, layer]) => {
    const m = Number(mins);
    const isSelected = m === selectedMins;
    const color = ISOCHRONE_COLORS[m] || '#2383e2';
    layer.setStyle({
      color: color,
      fillColor: color,
      fillOpacity: isSelected ? 0.20 : 0,
      opacity: isSelected ? 1 : 0,
      weight: isSelected ? 3.5 : 0
    });
    if (isSelected) {
      if (!layer.getTooltip()) {
        layer.bindTooltip(ISOCHRONE_LABELS[m] || `${m}m`, {
          sticky: true,
          className: 'isochrone-tooltip',
          direction: 'top'
        });
      }
    } else {
      layer.unbindTooltip();
    }
  });
  // Bring selected to front
  if (catchmentIsochroneLayers[selectedMins]) {
    catchmentIsochroneLayers[selectedMins].bringToFront();
  }
}

function updateCatchmentDashboardMetrics(data, selectedMins) {
  // selectedRow comes from the comparison array returned by the backend.
  const selectedRow = catchmentComparisonLookup.get(selectedMins) || null;
  const travelModeLabel = data.travel_mode || catchmentTravelMode || 'DRIVE';

  const evidence = catchmentDirectEvidence(selectedRow, data, selectedMins);
  setTextIfExists('catchment-kpi-reported-students', evidence.reported ? formatNumber(evidence.reported) : 'Unavailable');
  setTextIfExists('catchment-kpi-schools', formatNumber(evidence.schools.length));
  setTextIfExists('catchment-kpi-projects', formatNumber(evidence.projects.length));
  setTextIfExists('catchment-kpi-units', evidence.knownUnits === null ? 'Unavailable' : formatNumber(evidence.knownUnits));

  const officesCount = selectedRow
    ? (selectedRow.office_count || 0)
    : (data.metrics.office_count || 0);
  setTextIfExists('catchment-kpi-offices', formatNumber(officesCount, 0));

  const sezSpaces = selectedRow
    ? (selectedRow.office_count || 0)
    : (data.metrics.sez_office_spaces || 0);
  setTextIfExists('catchment-kpi-sez-spaces', Math.round(Number(sezSpaces)).toLocaleString());

  // Update time badge
  const timeBadge = document.querySelector('.center-planner .preview-badge:last-child');
  if (timeBadge) {
    timeBadge.textContent = data.catchment_mode === 'time' ? `${selectedMins} min` : `${data.radius_km.toFixed(1)} km`;
  }

  // Update method badge
  const methodBadge = document.getElementById('catchment-method');
  if (methodBadge) {
    const trafficLabel = String(data.live_traffic).toLowerCase() === 'true' ? 'Live Traffic' : 'Traffic Unaware';
    const methodPrefix = data.routing_method === 'google' ? 'Google Isochrone' : 'Fallback';
    methodBadge.textContent = `${methodPrefix} · ${travelModeLabel} · ${trafficLabel} · ${selectedMins}m`;
    if (data.routing_method === 'google') {
      methodBadge.style.backgroundColor = '#dcfce7';
      methodBadge.style.color = '#166534';
      methodBadge.style.borderColor = '#bbf7d0';
    } else {
      methodBadge.style.backgroundColor = '#fef3c7';
      methodBadge.style.color = '#92400e';
      methodBadge.style.borderColor = '#fde68a';
    }
  }

  // Update expansion table highlighting
  const expRows = document.querySelectorAll('#catchment-expansion-table-body tr');
  expRows.forEach(tr => {
    const firstCell = tr.querySelector('td');
    if (!firstCell) return;
    const cellText = firstCell.textContent.replace('🌟 ', '').trim();
    const rowMins = parseInt(cellText);
    if (rowMins === selectedMins) {
      tr.style.backgroundColor = 'var(--block-info-bg)';
      tr.style.fontWeight = 'bold';
      firstCell.textContent = `🌟 ${cellText}`;
    } else {
      tr.style.backgroundColor = '';
      tr.style.fontWeight = '';
      firstCell.textContent = cellText.replace('🌟 ', '');
    }
  });

  const overlap = document.getElementById('catchment-overlap-note');
  if (overlap) overlap.textContent = `${formatNumber(evidence.hexCount)} matched cells in this view. Compare shortlisted sites before adding demand; overlapping school or project evidence must be counted once.`;
}

function catchmentDirectEvidence(selectedRow, data, selectedMins) {
  const matched = new Set(selectedRow?.matched_hex_ids || data.matched_hex_ids || []);
  const schoolRows = getSchoolAudienceEntities().filter(row => !matched.size || matched.has(row.hex_id));
  const schools = schoolRows.map((row, index) => ({
    ...row,
    reported_students_grade_2_9: reportedGrade29Value(row),
    id: row.entity_id || row.school_entity_id || `catchment-school-${index}`
  })).filter(row => row.reported_students_grade_2_9 > 0);
  const reportedFromRow = firstFiniteNumber(selectedRow?.reported_students_grade_2_9, selectedRow?.reported_grade_2_9_students);
  const reported = reportedFromRow ?? schools.reduce((sum, row) => sum + row.reported_students_grade_2_9, 0);
  const projects = (data.societies || []).filter(row => Number(row.time_mins || 0) <= Number(selectedMins || 0));
  const units = projects.map(row => firstFiniteNumber(row.known_units, row.units, row.total_units)).filter(value => value !== null);
  return {
    reported,
    schools,
    projects,
    knownUnits: units.length ? units.reduce((sum, value) => sum + value, 0) : null,
    hexCount: firstFiniteNumber(selectedRow?.hex_count, matched.size) || 0
  };
}

/**
 * Re-renders the societies / hospitals / offices POI lists
 * filtered to the given time band. Called both on initial render and
 * whenever the user clicks a 15/30/45/60 min toggle chip.
 */
function updateCatchmentPOILists(data, selectedMins) {
  const catchmentLocked = !isUnlocked();

  const filteredSocieties = (data.societies || []).filter(s => (s.time_mins || 0) <= selectedMins);
  const filteredHospitals = (data.hospitals  || []).filter(h => (h.time_mins || 0) <= selectedMins);
  const filteredOffices   = (data.offices    || []).filter(o => (o.time_mins || 0) <= selectedMins);

  // Stash for copy functions
  activeDetailsData.catchment.societies = filteredSocieties;
  activeDetailsData.catchment.hospitals = filteredHospitals;
  activeDetailsData.catchment.offices   = filteredOffices;

  // --- Residential projects ---
  const socCount = document.getElementById('catchment-count-societies');
  const socList  = document.getElementById('catchment-societies-list');
  if (socCount) socCount.textContent = filteredSocieties.length;
  if (socList) {
    if (filteredSocieties.length > 0) {
      socList.innerHTML = filteredSocieties.map((soc, idx) => {
        const isLockedItem = catchmentLocked && idx >= 3;
        const socName = isLockedItem ? 'Restricted residential project' : soc.name;
        const socTag  = isLockedItem
          ? 'Project positioning and units restricted'
          : `${soc.category || 'Positioning unavailable'} | Known units ${soc.units == null ? 'unavailable' : Number(soc.units).toLocaleString()}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}" data-type="society">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(soc.name)}">${escapeHTML(socName)}</div>
            <div class="poi-item-tag">${escapeHTML(socTag)}</div>
          </div>`;
      }).join('');
    } else {
      socList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No premium projects in drive range</div>';
    }
  }

  const evidence = catchmentDirectEvidence(catchmentComparisonLookup.get(Number(selectedMins)), data, selectedMins);
  activeDetailsData.catchment.schools = evidence.schools;
  const schoolCount = document.getElementById('catchment-count-schools');
  const schoolList = document.getElementById('catchment-schools-list');
  if (schoolCount) schoolCount.textContent = formatNumber(evidence.schools.length);
  if (schoolList) {
    schoolList.innerHTML = evidence.schools.slice(0, 30).map((school, idx) => {
      const isLockedItem = catchmentLocked && idx >= 5;
      const name = isLockedItem ? 'Restricted school partner' : (school.name || 'Unnamed school');
      const reported = school.reported_students_grade_2_9 || 0;
      return `<div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}" data-type="school"><div class="poi-item-name">${escapeHTML(name)}</div><div class="poi-item-tag">${isLockedItem ? 'Partnership evidence restricted' : `${formatNumber(reported)} reported Grade 2–9 · ${escapeHTML(school.area || school.zone || 'Area unavailable')}`}</div></div>`;
    }).join('') || '<div style="padding:10px;color:#6b7280;">No directly reported Premium+ school evidence in this band.</div>';
  }

  // --- Hospitals ---
  const hospCount = document.getElementById('catchment-count-hospitals');
  const hospList  = document.getElementById('catchment-hospitals-list');
  if (hospCount) hospCount.textContent = filteredHospitals.length;
  if (hospList) {
    if (filteredHospitals.length > 0) {
      hospList.innerHTML = filteredHospitals.map((hosp, idx) => {
        const isLockedItem = catchmentLocked && idx >= 3;
        const hospName = isLockedItem ? 'Restricted Hospital Name' : hosp.name;
        const hospTag  = isLockedItem
          ? 'Premium Category | Rating: Restricted | Beds: Restricted'
          : `${hosp.category} | Rating: ${(hosp.rating || 0).toFixed(1)}⭐ | Beds: ${hosp.beds || 'N/A'}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}" data-type="hospital">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(hosp.name)}">${escapeHTML(hospName)}</div>
            <div class="poi-item-tag">${escapeHTML(hospTag)}</div>
          </div>`;
      }).join('');
    } else {
      hospList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No premium hospitals in drive range</div>';
    }
  }

  // --- Offices ---
  const offCount = document.getElementById('catchment-count-offices');
  const offList  = document.getElementById('catchment-offices-list');
  if (offCount) offCount.textContent = filteredOffices.length;
  if (offList) {
    if (filteredOffices.length > 0) {
      offList.innerHTML = filteredOffices.slice(0, 50).map((office, idx) => {
        const isLockedItem = catchmentLocked && idx >= 5;
        const name     = isLockedItem ? 'Restricted Office Name' : office.name;
        const tier     = isLockedItem ? 'Company tier restricted' : office.company_prominence_tier;
        const subtitle = isLockedItem
          ? 'Office details restricted | Score restricted'
          : `${office.sez_name || office.locality || 'Office area NA'} | Score ${formatNumber(office.office_rank_score || 0, 0)}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-type="office" data-idx="${idx}" data-locked="${isLockedItem}">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(office.name)}">${escapeHTML(name)}</div>
            <div class="poi-item-tag" title="${escapeHTML(tier)}">${escapeHTML(subtitle)}</div>
          </div>`;
      }).join('');
    } else {
      offList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No office anchors inside catchment</div>';
    }
  }

}

function renderCatchmentDashboard(data) {
  activeCatchmentData = data;
  clearRolledUpAssetsLayer();
  // NOTE: placeholder is kept visible (spinner) until AFTER map layers are rendered.
  // It is hidden at the very end of this function via requestAnimationFrame.
  
  const catchmentLocked = !isUnlocked();
  const travelModeLabel = data.travel_mode || catchmentTravelMode || 'DRIVE';
  const trafficLabel = String(data.live_traffic).toLowerCase() === 'true' ? 'Live Traffic' : 'Traffic Unaware';
  const selectedMins = Number(catchmentIsochroneSelection || data.travel_time_mins || catchmentQueryTimeMins || 15);
  const methodText = data.routing_method === 'google'
    ? `Google Isochrone · ${travelModeLabel} · ${trafficLabel} · ${selectedMins}m`
    : `Fallback · ${travelModeLabel} · ${trafficLabel} · ${selectedMins}m`;
  const selectedRow = catchmentComparisonLookup.get(selectedMins) || null;
  const selectedMetrics = selectedRow || data.metrics || {};

  // Unified Standard Layout Template Injection
  renderStandardDetails(document.getElementById('catchment-results-panel'), {
    title: 'Site Catchment Check',
    titleId: 'catchment-dashboard-title',
    badge: methodText,
    badgeId: 'catchment-method',
    onClose: 'clearCatchmentSelection()',
    kpis: [
      { id: 'catchment-kpi-reported-students', value: 'Unavailable', label: 'Reported Premium+ Grade 2–9' },
      { id: 'catchment-kpi-schools', value: '0', label: 'Premium+ schools' },
      { id: 'catchment-kpi-projects', value: '0', label: 'Residential projects', locked: catchmentLocked },
      { id: 'catchment-kpi-units', value: 'Unavailable', label: 'Known residential units', locked: catchmentLocked }
    ],
    mainContent: `
      <div class="notion-block info-block" style="margin-bottom:12px;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
          <div>
            <strong style="display:block; font-size:12px; margin-bottom:4px;">Isochrone Viewer</strong>
            <div style="font-size:11px; color: var(--text-muted);">Switch the active minute band shown in the dashboard.</div>
          </div>
          <div id="catchment-iso-toggle-row" style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="segment-btn catchment-iso-toggle${selectedMins === 15 ? ' active' : ''}" data-minutes="15" type="button" onclick="setCatchmentIsochroneSelection(15)">15m</button>
            <button class="segment-btn catchment-iso-toggle${selectedMins === 30 ? ' active' : ''}" data-minutes="30" type="button" onclick="setCatchmentIsochroneSelection(30)">30m</button>
            <button class="segment-btn catchment-iso-toggle${selectedMins === 45 ? ' active' : ''}" data-minutes="45" type="button" onclick="setCatchmentIsochroneSelection(45)">45m</button>
            <button class="segment-btn catchment-iso-toggle${selectedMins === 60 ? ' active' : ''}" data-minutes="60" type="button" onclick="setCatchmentIsochroneSelection(60)">60m</button>
          </div>
        </div>
        <div class="iso-legend">
          <div class="iso-legend-item"><span class="iso-legend-swatch" style="background:#2563eb;"></span>15 min</div>
          <div class="iso-legend-item"><span class="iso-legend-swatch" style="background:#7c3aed;"></span>30 min</div>
          <div class="iso-legend-item"><span class="iso-legend-swatch" style="background:#ea580c;"></span>45 min</div>
          <div class="iso-legend-item"><span class="iso-legend-swatch" style="background:#16a34a;"></span>60 min</div>
        </div>
      </div>
      <div class="notion-block info-block catchment-direct-note">
        <strong>Read this as a validation view.</strong>
        <span id="catchment-overlap-note">Reported enrollment stays attached to school records. Residential projects provide a direct-marketing list, and overlapping catchments must be deduplicated.</span>
      </div>
      ${buildRolledUpAssetsControlsHtml('catchment')}
    `,
    sections: [
      { title: 'Residential projects inside catchment', countId: 'catchment-count-societies', count: data.metrics.society_count || 0, id: 'catchment-societies-list', onCopy: 'copyCatchmentSocieties(event)', open: true },
      { title: 'Premium+ schools inside catchment', countId: 'catchment-count-schools', count: 0, id: 'catchment-schools-list', open: true },
      { title: 'Access context', id: 'catchment-metro-list' },
      { title: 'Expansion Analysis', id: 'catchment-expansion-analysis-details', contentHtml: `
        <p style="font-size: 12px; margin-bottom: 8px; color: var(--text-muted);">Compare direct evidence as the travel-time boundary expands. Do not add rows because the larger bands contain the smaller bands.</p>
        <div class="table-container">
          <table class="notion-table" id="catchment-expansion-table" style="font-size: 11px; width: 100%;">
            <thead>
              <tr>
                <th>Minutes</th>
                <th class="num-col">Hexes</th>
                <th class="num-col">Reported students</th>
                <th class="num-col">Schools</th>
              </tr>
            </thead>
            <tbody id="catchment-expansion-table-body"></tbody>
          </table>
        </div>
      ` }
    ]
  });

  showDetailsPanel('catchment-results-panel');

  const methodBadge = document.getElementById('catchment-method');
  if (methodBadge) {
    methodBadge.textContent = data.routing_method === 'google'
      ? `Google Isochrone · ${travelModeLabel} · ${trafficLabel} · ${selectedMins}m`
      : `Fallback · ${travelModeLabel} · ${trafficLabel} · ${selectedMins}m`;
    if (data.routing_method === 'google') {
      methodBadge.style.backgroundColor = '#dcfce7';
      methodBadge.style.color = '#166534';
      methodBadge.style.borderColor = '#bbf7d0';
    } else {
      methodBadge.style.backgroundColor = '#fef3c7';
      methodBadge.style.color = '#92400e';
      methodBadge.style.borderColor = '#fde68a';
    }
  }

  // Draw catchment polygon layer on map
  renderCatchmentIsochroneGeometryLayer(data);
  syncCatchmentTimeSelector();

  // Adjust catchment circle visibility based on routing method
  if (catchmentCircle) {
  if (data.routing_method === 'google') {
    catchmentCircle.setStyle({ opacity: 0, fillOpacity: 0 });
  } else {
      catchmentCircle.setStyle({
        color: '#d97706',
        fillColor: '#d97706',
        fillOpacity: 0.12,
        weight: 1.5,
        dashArray: '4, 4'
      });
    }
  }

  // Direct evidence summary for the selected band.
  const directEvidence = catchmentDirectEvidence(selectedRow, data, selectedMins);
  setTextIfExists('catchment-kpi-reported-students', directEvidence.reported ? formatNumber(directEvidence.reported) : 'Unavailable');
  setTextIfExists('catchment-kpi-schools', formatNumber(directEvidence.schools.length));
  setTextIfExists('catchment-kpi-projects', formatNumber(directEvidence.projects.length));
  setTextIfExists('catchment-kpi-units', directEvidence.knownUnits === null ? 'Unavailable' : formatNumber(directEvidence.knownUnits));
  // Handle Paywall for other Catchment KPIs
  // catchmentLocked is already defined above
  ['catchment-kpi-units', 'catchment-kpi-projects'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const card = el.closest('.kpi-card');
    if (card) {
      card.classList.toggle('blurred-item', catchmentLocked);
      if (catchmentLocked) {
        card.style.cursor = 'pointer';
        card.onclick = openUnlockModal;
      } else {
        card.style.cursor = '';
        card.onclick = null;
      }
    }
  });

  // Office anchors
  setTextIfExists('catchment-kpi-sez-spaces', Number(selectedMetrics.sez_office_spaces || data.metrics.sez_office_spaces || 0).toLocaleString());

  // Render Metro List (Static per center, doesn't depend on time band)
  renderMetroList(data.metro, 'catchment-metro-list');

  // Dynamically Filter arrays based on selectedMins
  const filteredSocieties = (data.societies || []).filter(s => (s.time_mins || 0) <= selectedMins);
  const filteredHospitals = (data.hospitals || []).filter(h => (h.time_mins || 0) <= selectedMins);
  const filteredOffices = (data.offices || []).filter(o => (o.time_mins || 0) <= selectedMins);
  
  activeDetailsData.catchment.societies = filteredSocieties;
  activeDetailsData.catchment.hospitals = filteredHospitals;
  activeDetailsData.catchment.offices = filteredOffices;

  const socCount = document.getElementById('catchment-count-societies');
  const socList = document.getElementById('catchment-societies-list');
  socCount.textContent = filteredSocieties.length;
  if (filteredSocieties.length > 0) {
    socList.innerHTML = filteredSocieties.map((soc, idx) => {
      const isLockedItem = !isUnlocked() && idx >= 3;
      const socName = isLockedItem ? 'Restricted residential project' : soc.name;
      const socTag = isLockedItem ? 'Project positioning and units restricted' : `${soc.category || 'Positioning unavailable'} | Known units ${soc.units == null ? 'unavailable' : Number(soc.units).toLocaleString()}`;
      return `
        <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}" data-type="society">
          <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(soc.name)}">${escapeHTML(socName)}</div>
          <div class="poi-item-tag">${escapeHTML(socTag)}</div>
        </div>
      `;
    }).join('');
  } else {
    socList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No premium projects in drive range</div>';
  }

  activeDetailsData.catchment.schools = directEvidence.schools;
  setTextIfExists('catchment-count-schools', formatNumber(directEvidence.schools.length));
  const catchmentSchoolList = document.getElementById('catchment-schools-list');
  if (catchmentSchoolList) {
    catchmentSchoolList.innerHTML = directEvidence.schools.slice(0, 30).map((school, idx) => {
      const isLockedItem = !isUnlocked() && idx >= 5;
      const name = isLockedItem ? 'Restricted school partner' : (school.name || 'Unnamed school');
      return `<div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}" data-type="school"><div class="poi-item-name">${escapeHTML(name)}</div><div class="poi-item-tag">${isLockedItem ? 'Partnership evidence restricted' : `${formatNumber(school.reported_students_grade_2_9 || 0)} reported Grade 2–9 · ${escapeHTML(school.area || school.zone || 'Area unavailable')}`}</div></div>`;
    }).join('') || '<div style="padding:10px;color:#6b7280;">No directly reported Premium+ school evidence in this band.</div>';
  }

  // Render Hospitals List
  const hospCount = document.getElementById('catchment-count-hospitals');
  const hospList = document.getElementById('catchment-hospitals-list');
  if (hospCount) hospCount.textContent = filteredHospitals.length;
  if (filteredHospitals.length > 0) {
    hospList.innerHTML = filteredHospitals.map((hosp, idx) => {
      const isLockedItem = !isUnlocked() && idx >= 3;
      const hospName = isLockedItem ? "Restricted Hospital Name" : hosp.name;
      const hospTag = isLockedItem ? "Premium Category | Rating: Restricted | Beds: Restricted" : `${hosp.category} | Rating: ${(hosp.rating || 0).toFixed(1)}⭐ | Beds: ${hosp.beds || 'N/A'}`;
      return `
        <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-idx="${idx}" data-locked="${isLockedItem}" data-type="hospital">
          <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(hosp.name)}">${escapeHTML(hospName)}</div>
          <div class="poi-item-tag">${escapeHTML(hospTag)}</div>
        </div>
      `;
    }).join('');
  } else {
    hospList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No premium hospitals in drive range</div>';
  }

  // Render Offices List
  const offCount = document.getElementById('catchment-count-offices');
  const offList = document.getElementById('catchment-offices-list');
  if (offCount) offCount.textContent = filteredOffices.length;
  if (offList) {
    if (filteredOffices.length > 0) {
      offList.innerHTML = filteredOffices.slice(0, 50).map((office, idx) => {
        const isLockedItem = !isUnlocked() && idx >= 5;
        const name = isLockedItem ? 'Restricted Office Name' : office.name;
        const tier = isLockedItem ? 'Company tier restricted' : office.company_prominence_tier;
        const subtitle = isLockedItem 
          ? 'Office details restricted | Score restricted' 
          : `${office.sez_name || office.locality || 'Office area NA'} | Score ${formatNumber(office.office_rank_score || 0, 0)}`;
        return `
          <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" data-type="office" data-idx="${idx}" data-locked="${isLockedItem}">
            <div class="poi-item-name" title="${isLockedItem ? 'Restricted' : escapeHTML(office.name)}">${escapeHTML(name)}</div>
            <div class="poi-item-tag" title="${escapeHTML(tier)}">${escapeHTML(subtitle)}</div>
          </div>
        `;
      }).join('');
    } else {
      offList.innerHTML = '<div style="padding: 10px; color:#6b7280;">No office anchors inside catchment</div>';
    }
  }

  // Render Catchment Expansion / Growth table
  const expTableBody = document.getElementById('catchment-expansion-table-body');
  expTableBody.innerHTML = '';
  if (data.comparison && data.comparison.length > 0) {
    const comparisonRows = buildCatchmentComparison(data.comparison, data.travel_time_mins || catchmentQueryTimeMins);
    comparisonRows.sort((a, b) => Number(a.time_mins || a.radius || 0) - Number(b.time_mins || b.radius || 0));
    const headerCells = document.querySelectorAll('#catchment-expansion-table thead th');
    if (headerCells.length >= 4) {
      headerCells[0].textContent = data.catchment_mode === 'time' ? 'Minutes' : 'Radius';
      headerCells[2].textContent = 'Reported students';
      headerCells[3].textContent = 'Schools';
    }
    comparisonRows.forEach((item, idx) => {
      const selectedTime = Number(catchmentIsochroneSelection || data.travel_time_mins || catchmentQueryTimeMins);
      const isPrimary = data.catchment_mode === 'time'
        ? Math.abs(Number(item.time_mins || item.radius) - selectedTime) < 0.5
        : Math.abs(item.radius - data.radius_km) < 0.05;
      const tr = document.createElement('tr');
      if (isPrimary) {
        tr.style.backgroundColor = 'var(--block-info-bg)';
        tr.style.fontWeight = 'bold';
      }
      
      const rowEvidence = catchmentDirectEvidence(item, data, Number(item.time_mins || selectedMins));
      const primaryLabel = data.catchment_mode === 'time' && item.time_mins != null ? `${item.time_mins.toFixed(0)}m` : `${item.radius.toFixed(1)} km`;
      
      tr.innerHTML = `
        <td>${isPrimary ? '🌟 ' : ''}${primaryLabel}</td>
        <td class="num-col">${item.hex_count}</td>
        <td class="num-col">${rowEvidence.reported ? formatNumber(rowEvidence.reported) : 'Unavailable'}</td>
        <td class="num-col">${formatNumber(rowEvidence.schools.length)}</td>
      `;
      expTableBody.appendChild(tr);
    });
  }

  // Highlight matched hexes on map
  highlightCatchmentHexes(data.matched_hex_ids);
  updateActiveLayersPanel();

  // Now that all rendering is done, hide loading state and show results panel.
  // Auto-disarm the click tool so the user can freely navigate the map.
  // The re-query strip lets them re-arm whenever they want.
  requestAnimationFrame(() => {
    document.getElementById('catchment-placeholder').classList.add('hidden');

    // Disarm click tool — user can navigate without accidentally re-triggering queries
    syncCatchmentMode(false);

    // Show (or refresh) the re-query hint strip beneath the setup card
    const setupCard = document.getElementById('catchment-setup-card');
    if (setupCard) {
      let hint = document.getElementById('catchment-requery-hint');
      if (!hint) {
        hint = document.createElement('div');
        hint.id = 'catchment-requery-hint';
        hint.className = 'catchment-requery-hint';
        setupCard.after(hint);
      }
      hint.innerHTML = `
        <span>Re-query a different location?</span>
        <button onclick="syncCatchmentMode(true)" class="catchment-requery-btn">
          🎯 Arm &amp; Click Again
        </button>
      `;
    }
  });
}

function renderCatchmentPlaceholder() {
  const currentRadius = catchmentQueryRadius.toFixed(1);
  document.getElementById('catchment-placeholder').innerHTML = `
    <div class="notion-block info-block" style="border-left-color: var(--accent-color); background-color: var(--block-info-bg); padding: 16px;" class="fade-container">
      <h3 class="notion-heading-3" style="margin-top: 0; margin-bottom: 12px; font-size: 14px; display: flex; align-items: center; gap: 6px;">
        🧭 Interactive Travel Catchment
      </h3>
      <p style="font-size: 12px; margin-bottom: 14px; line-height: 1.45; color: var(--text-main);">
        Validate spatial access, directly reported school enrollment, residential projects, workplace anchors, and overlap inside custom time-based catchment boundaries.
      </p>
      
      <div style="display: flex; flex-direction: column; gap: 12px; font-size: 11.5px; border-top: 1px dashed var(--border-light); padding-top: 12px;">
        <div style="display: flex; gap: 8px; align-items: flex-start;">
          <span class="onboarding-step-num">1</span>
          <div>
            <strong>Configure Mode:</strong> Pick a travel mode, keep live traffic on, and set the exact travel time in minutes.
          </div>
        </div>
        <div style="display: flex; gap: 8px; align-items: flex-start;">
          <span class="onboarding-step-num">2</span>
          <div>
            <strong>Activate Tool:</strong> Enable the <em>Catchment Click Tool</em> toggle above. The cursor will change to a crosshair.
          </div>
        </div>
        <div style="display: flex; gap: 8px; align-items: flex-start;">
          <span class="onboarding-step-num">3</span>
          <div>
            <strong>Query Location:</strong> Click anywhere on the map to retrieve isochrones and aggregate demographics.
          </div>
        </div>
      </div>
    </div>
  `;
}

function clearCatchmentSelection() {
  if (catchmentMarker) {
    map.removeLayer(catchmentMarker);
    catchmentMarker = null;
  }
  if (catchmentCircle) {
    map.removeLayer(catchmentCircle);
    catchmentCircle = null;
  }
  if (catchmentPolygonLayer) {
    catchmentPolygonLayer.remove();
    catchmentPolygonLayer = null;
  }
  catchmentIsochroneLayers = {};
  clearRolledUpAssetsLayer();
  if (activePoiMarker) {
    map.removeLayer(activePoiMarker);
    activePoiMarker = null;
  }
  activeCatchmentData = null;
  
  document.getElementById('catchment-results-panel').classList.add('hidden');
  updateRightPanelVisibility();
  renderCatchmentPlaceholder();
  document.getElementById('catchment-placeholder').classList.remove('hidden');

  resetHexHighlights();
  switchTab('overview');
  updateActiveLayersPanel();
}

function highlightCatchmentHexes(matchedHexIds) {
  const hexSet = new Set(matchedHexIds);
  
  overlayLayers.hexes.eachLayer(function (layer) {
    const props = layer.feature.properties;
    const fId = props.hex_id;
    if (hexSet.has(fId)) {
      layer.setStyle({
        fillColor: getHexColor(props.final_affluence_score),
        fillOpacity: hexHighlightEnabled ? 0.85 : 0,
        weight: 2,
        color: '#2383e2' // Blue outline for catchment hexes
      });
    } else {
      layer.setStyle({
        fillColor: getHexColor(props.final_affluence_score),
        fillOpacity: hexHighlightEnabled ? 0.08 : 0,
        weight: 0.5,
        color: '#e5e7eb'
      });
    }
  });
  hexesAreHighlighted = true;
}

// Interactive POI Centering and Popups
function focusOnPoi(poi, type) {
  if (!poi || !poi.lat || !poi.lon) {
    console.warn("POI coordinates missing for item:", poi);
    return;
  }

  // Centering map at zoom level 15
  map.setView([poi.lat, poi.lon], 15);

  // Remove existing highlight marker
  if (activePoiMarker) {
    map.removeLayer(activePoiMarker);
  }

  let markerColor = '#2383e2'; // Default blue (used for external places / unknown types)
  if (type === 'society') {
    markerColor = '#d97706'; // warning yellow/gold for societies
  } else if (type === 'hospital') {
    markerColor = '#ef4444'; // red for hospitals
  } else if (type === 'office') {
    markerColor = getOfficeMarkerColor(poi);
  }

  // Create a high-contrast circle marker with a clean border
  activePoiMarker = L.circleMarker([poi.lat, poi.lon], {
    radius: 9,
    color: '#ffffff',
    fillColor: markerColor,
    fillOpacity: 1,
    weight: 3,
    opacity: 1
  }).addTo(map);

  if (type === 'society') {
    const units = poi.units || 0;
    const price = poi.price || 0;
    const priceStr = price > 0 ? `₹${price.toLocaleString()}/sqft` : "NA";
    const locality = poi.locality || "NA";
    const url = poi.url || "NA";
    const urlLink = isUnlocked()
      ? (url && url !== 'NA' ? `<a href="${url}" target="_blank" class="notion-link">View on 99acres ↗</a>` : '<span style="color:#9ca3af">No link available</span>')
      : '<span style="color:#ef4444; cursor:pointer; font-weight:600;" onclick="openUnlockModal()">Restricted URL (Enter Passcode)</span>';
    const displayName = isUnlocked() ? poi.name : 'Restricted residential project';

    popupContent = `
      <div class="notion-popup">
        <div class="popup-header">
          <strong>${displayName}</strong>
          <span class="popup-badge" style="background:#fef9c3; color:#a16207; border-color:#fef08a;">RESIDENTIAL PROJECT</span>
        </div>
        <div class="popup-score">Category: <strong>${poi.category || "NA"}</strong></div>
        <div class="popup-grid" style="grid-template-columns: 1fr; gap: 4px; font-size:11.5px;">
          <div>Locality: <strong>${locality}</strong></div>
          <div>Known units: <strong>${units > 0 ? units.toLocaleString() : "Unavailable"}</strong></div>
          <div>Avg Price per SqFt: <strong>${priceStr}</strong></div>
          <div style="margin-top: 6px; border-top: 1px solid var(--border-light); padding-top: 6px;">
            ${urlLink}
          </div>
        </div>
      </div>
    `;
  } else if (type === 'hospital') {
    const beds = poi.beds || 0;
    const rating = poi.rating || 0;
    const reviews = poi.reviews || 0;
    const ratingStr = rating > 0 ? `★ ${rating.toFixed(1)} (${reviews} reviews)` : "NA";
    const displayName = isUnlocked() ? poi.name : 'Restricted Hospital Name';

    popupContent = `
      <div class="notion-popup">
        <div class="popup-header">
          <strong>${displayName}</strong>
          <span class="popup-badge" style="background:#fee2e2; color:#b91c1c; border-color:#fecaca;">HOSPITAL</span>
        </div>
        <div class="popup-score">Category: <strong>${poi.category || "NA"}</strong></div>
        <div class="popup-grid" style="grid-template-columns: 1fr; gap: 4px; font-size:11.5px;">
          <div>Beds: <strong>${beds > 0 ? beds.toLocaleString() : "NA"}</strong></div>
          <div>Rating: <strong>${ratingStr}</strong></div>
        </div>
      </div>
    `;
  } else if (type === 'office') {
    popupContent = makeOfficePopup(poi);
  }

  const popup = L.popup({
    maxWidth: 325,
    className: 'notion-popup-container'
  })
  .setLatLng([poi.lat, poi.lon])
  .setContent(popupContent)
  .openOn(map);

  popup.on('remove', () => {
    if (activePoiMarker) {
      map.removeLayer(activePoiMarker);
      activePoiMarker = null;
    }
  });
}

// Quick Clipboard Exports (Spreadsheet TSV Format)
function copyToClipboard(text, buttonEl) {
  navigator.clipboard.writeText(text).then(() => {
    const originalContent = buttonEl.innerHTML;
    buttonEl.innerHTML = "✓ Copied!";
    buttonEl.classList.add("success");
    setTimeout(() => {
      buttonEl.innerHTML = originalContent;
      buttonEl.classList.remove("success");
    }, 2000);
  }).catch(err => {
    console.error("Clipboard copy error:", err);
    alert("Could not copy to clipboard. Ensure site has clipboard permissions.");
  });
}

function exportSocietiesTable(societiesList, buttonEl) {
  if (!isUnlocked()) {
    openUnlockModal();
    return;
  }
  const topSocieties = societiesList.slice(0, 25);
  if (topSocieties.length === 0) {
    alert("No societies in this list to copy.");
    return;
  }

  const headers = ["Residential Project", "Locality", "Positioning", "Known Units", "Avg Price per SqFt", "Website URL"];
  const rows = topSocieties.map(soc => {
    const full = societyLookup.get(soc.name) || {};
    const name = soc.name || full.name || "NA";
    const locality = soc.locality || full.locality || "NA";
    const category = soc.category || full.category || "NA";
    const units = soc.units || full.units || 0;
    const price = soc.price || full.price || 0;
    const url = full.url || "NA";

    return [
      name,
      locality,
      category,
      units > 0 ? units.toLocaleString() : "NA",
      price > 0 ? `₹${price.toLocaleString()}` : "NA",
      url
    ];
  });

  const tsvContent = [headers.join("\t"), ...rows.map(r => r.join("\t"))].join("\n");
  copyToClipboard(tsvContent, buttonEl);
}

// Copy Action Wrappers
function copyZoneSocieties(e) {
  e.stopPropagation();
  e.preventDefault();
  if (!selectedZone) return;
  const zoneSocieties = layerData.societies.filter(soc => soc.zone === selectedZone);
  zoneSocieties.sort((a, b) => b.tam - a.tam);
  exportSocietiesTable(zoneSocieties, e.currentTarget);
}

function copyHexSocieties(e) {
  e.stopPropagation();
  e.preventDefault();
  if (!selectedHexFeature) return;
  const hexSocieties = layerData.societies.filter(soc => soc.hex_id === selectedHexFeature.hex_id);
  hexSocieties.sort((a, b) => b.tam - a.tam);
  exportSocietiesTable(hexSocieties, e.currentTarget);
}

function copyHexHospitals(e) {
  e.stopPropagation();
  e.preventDefault();
  if (!selectedHexFeature) return;
  const hexHospitals = layerData.hospitals.filter(h => h.hex_id === selectedHexFeature.hex_id);
  hexHospitals.sort((a, b) => b.beds - a.beds || b.rating - a.rating);
  exportHospitalsMarketsTable(hexHospitals, [], e.currentTarget);
}

function copyCatchmentSocieties(e) {
  e.stopPropagation();
  e.preventDefault();
  if (!activeCatchmentData || !activeCatchmentData.societies) return;
  exportSocietiesTable(activeCatchmentData.societies, e.currentTarget);
}

// Copy Action Wrappers
function copyZoneHospitalsMarkets(e) {
  e.stopPropagation();
  e.preventDefault();
  if (!selectedZone) return;
  const zoneHospitals = layerData.hospitals.filter(h => h.zone === selectedZone);
  zoneHospitals.sort((a, b) => b.beds - a.beds || b.rating - a.rating);
  const zoneLocalities = layerData.localities.filter(l => l.zone === selectedZone);
  zoneLocalities.sort((a, b) => b.price_sqft - a.price_sqft);
  exportHospitalsMarketsTable(zoneHospitals, zoneLocalities, e.currentTarget);
}

function exportHospitalsMarketsTable(hospitalsList, localitiesList, buttonEl) {
  if (!isUnlocked()) {
    openUnlockModal();
    return;
  }
  const topHospitals = hospitalsList.slice(0, 15);
  const topLocalities = localitiesList.slice(0, 15);
  if (topHospitals.length === 0 && topLocalities.length === 0) {
    alert("No hospitals or markets in this list to copy.");
    return;
  }

  const headers = ["Name", "Type", "Details / Metrics"];
  const rows = [];
  
  topHospitals.forEach(h => {
    rows.push([
      h.name,
      "Hospital",
      `Beds: ${h.beds || 'NA'}, Rating: ${h.rating || 'NA'}⭐, Reviews: ${h.reviews || 'NA'}, Category: ${h.category || 'NA'}`
    ]);
  });

  topLocalities.forEach(l => {
    rows.push([
      l.name,
      "Locality/Market",
      `Avg Price: ₹${l.price_sqft ? l.price_sqft.toLocaleString() : 'NA'}/sqft, Segment: ${l.budget_segment || 'NA'}`
    ]);
  });

  const tsvContent = [headers.join("\t"), ...rows.map(r => r.join("\t"))].join("\n");
  copyToClipboard(tsvContent, buttonEl);
}



// Methodology Accordion Trigger
function toggleMethodologyAccordion() {
  const content = document.getElementById('methodology-content');
  const chevron = document.getElementById('methodology-chevron');
  if (content && chevron) {
    if (content.classList.contains('open')) {
      content.classList.remove('open');
      chevron.classList.remove('open');
    } else {
      content.classList.add('open');
      chevron.classList.add('open');
    }
  }
}

function refreshBoundaryOverlay() {
  if (!window.L || !map || !layerData.sez_zones || !Object.keys(zonePolygons).length) {
    return;
  }

  const boundaryFeatures = [];

  // Zone boundaries
  if (activeBoundaryTypeFilter === 'both' || activeBoundaryTypeFilter === 'zone') {
    Object.entries(zonePolygons).forEach(([name, poly]) => {
      const coords = poly.getLatLngs();
      if (!coords || !coords.length) return;
      boundaryFeatures.push(L.polygon(coords, {
        color: '#1f2937',
        weight: 1.25,
        fillOpacity: 0,
        opacity: 0.9,
        dashArray: '5, 5',
        interactive: false
      }));
    });
  }

  // SEZ boundaries
  if (activeBoundaryTypeFilter === 'both' || activeBoundaryTypeFilter === 'sez') {
    const sezOutline = L.geoJSON(layerData.sez_zones, {
      style: {
        color: '#334155',
        weight: 1.25,
        fillOpacity: 0,
        opacity: 0.8,
        dashArray: '4, 6',
        interactive: false
      }
    });
    boundaryFeatures.push(sezOutline);
  }

  const nextLayer = L.layerGroup(boundaryFeatures);
  if (overlayLayers.boundaries && map.hasLayer(overlayLayers.boundaries)) {
    map.removeLayer(overlayLayers.boundaries);
  }
  overlayLayers.boundaries = nextLayer;
  boundaryOverlayNeedsRefresh = false;

  const checkbox = document.getElementById('toggle-layer-boundaries');
  if (checkbox && checkbox.checked) {
    overlayLayers.boundaries.addTo(map);
  }
}

function setBoundaryTypeFilter(type, btnEl) {
  activeBoundaryTypeFilter = type;

  // Update active pill styling
  const pillGroup = document.getElementById('pill-boundary-type');
  if (pillGroup) {
    pillGroup.querySelectorAll('.pill-item').forEach(btn => {
      btn.classList.remove('active');
    });
  }
  if (btnEl) {
    btnEl.classList.add('active');
  }

  refreshBoundaryOverlay();
}
window.setBoundaryTypeFilter = setBoundaryTypeFilter;

// Custom Pill Group Click handlers syncing with hidden native selects
function initCustomPills() {
  document.querySelectorAll('.pill-group').forEach(group => {
    const selectId = group.getAttribute('data-select-id');
    const select = document.getElementById(selectId);
    if (!select) return;

    group.querySelectorAll('.pill-item').forEach(pill => {
      pill.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();

        if (this.classList.contains('active')) return;

        // Toggle visual active state
        group.querySelectorAll('.pill-item').forEach(p => p.classList.remove('active'));
        this.classList.add('active');

        // Sync standard select value and trigger change event
        const val = this.getAttribute('data-val');
        select.value = val;
        select.dispatchEvent(new Event('change'));
      });
    });
  });
}

function renderTrustOnboardingMarkup() {
  const welcome = document.getElementById('welcome-landing');
  if (!welcome) return;
  welcome.innerHTML = `
    <div class="landing-container trust-onboarding" role="document">
      <div class="landing-topbar">
        <div class="landing-brand-stack">
          <span class="brand-tag">RanchoLabs market research</span>
          <span class="landing-kicker">Client release walkthrough</span>
        </div>
        <div aria-label="Walkthrough progress" class="landing-progress-pill">
          <span class="landing-progress-label">Step</span>
          <span id="landing-current-slide">1</span>
          <span class="landing-progress-divider">/</span>
          <span id="landing-total-slides">3</span>
        </div>
      </div>
      <div class="landing-stage">
        <section aria-labelledby="landing-slide-1-title" class="landing-slide active" data-slide="0">
          <div class="trust-slide-layout">
            <div class="trust-slide-copy">
              <p class="landing-slide-label">01 · What changed</p>
              <h1 id="landing-slide-1-title">A clearer answer to “where should we go next?”</h1>
              <p class="trust-lead">The portal now starts with direct school-demand evidence and turns it into an operating shortlist: cities, catchments, school partners, residential projects, and planning capacity.</p>
            </div>
            <div class="trust-change-grid">
              <article><span>City sequence</span><strong>Delhi NCR → Bengaluru → Hyderabad → Mumbai</strong><p>A consistent four-city path across the portal.</p></article>
              <article><span>Primary demand anchor</span><strong>Source-reported Premium+ enrollment</strong><p>The most direct count is used first; derived and modeled values remain visibly separate.</p></article>
              <article><span>Client navigation</span><strong>Five decision modules</strong><p>Decision Brief, School Market, Candidate Catchments, Site Catchment, and Map Layers.</p></article>
              <article><span>Operational output</span><strong>Named outreach lists</strong><p>Schools for partnerships and residential projects for direct marketing.</p></article>
            </div>
          </div>
        </section>
        <section aria-labelledby="landing-slide-2-title" class="landing-slide" data-slide="1">
          <div class="trust-slide-layout">
            <div class="trust-slide-copy">
              <p class="landing-slide-label">02 · What was fixed and verified</p>
              <h2 id="landing-slide-2-title">The evidence is easier to inspect and harder to misread.</h2>
              <p class="trust-lead">This release was checked at desktop size across all four city deep dives and the production build was verified Ready on 17 July 2026.</p>
            </div>
            <div class="trust-verification-list">
              <article><span class="trust-check">✓</span><div><strong>Raw, derived, and planning metrics are separated</strong><p>Each explained metric states what it is, how it was calculated, and why it matters.</p></div></article>
              <article><span class="trust-check">✓</span><div><strong>Duplicate noise and oversized fixed UI were reduced</strong><p>More of the client’s usable decision content is visible without scrolling.</p></div></article>
              <article><span class="trust-check">✓</span><div><strong>Tables and controls were rebuilt for the available width</strong><p>Labels remain readable when the left panel is resized.</p></div></article>
              <article><span class="trust-check">✓</span><div><strong>Site Catchment was restored with a client-controlled key</strong><p>The key is used for the current browser session only and is sent in a protected request header.</p></div></article>
              <article><span class="trust-check">✓</span><div><strong>Methodology was repaired around evidence lineage</strong><p>Observed values, calculations, scenarios, and directional context are disclosed separately.</p></div></article>
            </div>
          </div>
        </section>
        <section aria-labelledby="landing-slide-3-title" class="landing-slide" data-slide="2">
          <div class="trust-slide-layout">
            <div class="trust-slide-copy">
              <p class="landing-slide-label">03 · How to use it</p>
              <h2 id="landing-slide-3-title">Go from market question to action in four passes.</h2>
              <p class="trust-lead">Use the direct counts to choose where to investigate, then validate locally before making a campus commitment.</p>
            </div>
            <ol class="trust-use-steps">
              <li><span>1</span><div><strong>Choose the city and school audience</strong><p>Start with source-reported all-grade enrollment for city scale.</p></div></li>
              <li><span>2</span><div><strong>Read the candidate catchments</strong><p>Use derived reported Grade 2–9 for local comparison while remembering that enrollment remains attached to schools.</p></div></li>
              <li><span>3</span><div><strong>Build the operating list</strong><p>Prioritize named school partners and residential projects with known unit evidence.</p></div></li>
              <li><span>4</span><div><strong>Validate a proposed site</strong><p>Connect a restricted Google Maps key, run a live drive-time catchment, and then test competition, pricing, access, and site economics.</p></div></li>
            </ol>
            <div class="trust-reading-key"><strong>Reading key</strong><span><i class="truth-dot observed"></i>Source-reported</span><span><i class="truth-dot derived"></i>Derived from reported</span><span><i class="truth-dot scenario"></i>Planning scenario</span></div>
          </div>
        </section>
      </div>
      <div class="landing-footer">
        <div aria-label="Walkthrough steps" class="landing-step-dots">
          <button aria-label="Go to step 1" class="landing-step-dot active" id="button-gotolandingslide-0-welcome-landing" type="button"></button>
          <button aria-label="Go to step 2" class="landing-step-dot" id="button-gotolandingslide-1-welcome-landing" type="button"></button>
          <button aria-label="Go to step 3" class="landing-step-dot" id="button-gotolandingslide-2-welcome-landing" type="button"></button>
        </div>
        <div class="landing-footer-actions">
          <button class="landing-nav-btn secondary" id="button-skip-intro-welcome-landing" type="button">Open portal</button>
          <button class="landing-nav-btn secondary" disabled id="landing-back-btn" type="button">Back</button>
          <button class="landing-nav-btn primary" id="landing-next-btn" type="button">Next</button>
        </div>
      </div>
    </div>`;
}

renderTrustOnboardingMarkup();

function getLandingSlides() {
  return Array.from(document.querySelectorAll('.landing-slide'));
}

function getLandingDots() {
  return Array.from(document.querySelectorAll('.landing-step-dot'));
}

function updateLandingDeck(index) {
  const slides = getLandingSlides();
  if (!slides.length) return;

  landingSlideIndex = Math.max(0, Math.min(index, slides.length - 1));

  slides.forEach((slide, slideIndex) => {
    slide.classList.toggle('active', slideIndex === landingSlideIndex);
  });

  const current = document.getElementById('landing-current-slide');
  const total = document.getElementById('landing-total-slides');
  if (current) current.textContent = String(landingSlideIndex + 1);
  if (total) total.textContent = String(slides.length);

  getLandingDots().forEach((dot, dotIndex) => {
    dot.classList.toggle('active', dotIndex === landingSlideIndex);
  });

  const backBtn = document.getElementById('landing-back-btn');
  const nextBtn = document.getElementById('landing-next-btn');
  if (backBtn) backBtn.disabled = landingSlideIndex === 0;
  if (nextBtn) {
    nextBtn.textContent = landingSlideIndex === slides.length - 1 ? 'Explore the map' : 'Next';
  }

  if (landingPreviewMap && landingSlideIndex === 0) {
    setTimeout(() => landingPreviewMap.invalidateSize(false), 0);
  }
}

function initLandingDeck() {
  updateLandingDeck(landingSlideIndex);
}

function goToLandingSlide(index) {
  updateLandingDeck(index);
}

function nextLandingSlide() {
  const slides = getLandingSlides();
  if (!slides.length) return;

  if (landingSlideIndex >= slides.length - 1) {
    playMapTransition();
    return;
  }

  updateLandingDeck(landingSlideIndex + 1);
}

function previousLandingSlide() {
  if (landingSlideIndex <= 0) return;
  updateLandingDeck(landingSlideIndex - 1);
}

function handleLandingKeyboard(event) {
  const welcome = document.getElementById('welcome-landing');
  if (!welcome || welcome.classList.contains('fade-out') || welcome.style.display === 'none') return;

  const tagName = (event.target && event.target.tagName) ? event.target.tagName.toUpperCase() : '';
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName) || event.isComposing) return;

  if (event.key === 'ArrowRight' || event.key === 'PageDown') {
    event.preventDefault();
    nextLandingSlide();
  } else if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
    event.preventDefault();
    previousLandingSlide();
  } else if (event.key === 'Enter' && landingSlideIndex === getLandingSlides().length - 1) {
    event.preventDefault();
    playMapTransition();
  }
}

// Initialization lifecycle
window.addEventListener('DOMContentLoaded', () => {
  initSidebarResize();
  initRightPanelResize();
  try {
    initMap();
  } catch (error) {
    console.error('Map initialization did not complete; loading the decision workspace without blocking it.', error);
  }
  loadData();
  
  updateUnlockUi();
  
  // Restore left sidebar collapse state from localStorage
  const sidebarCollapsed = localStorage.getItem('left_sidebar_collapsed') === 'true';
  if (sidebarCollapsed) {
    const sidebar = document.getElementById('app-sidebar');
    const expandBtn = document.getElementById('left-sidebar-expand-btn');
    const handle = document.getElementById('sidebar-resize-handle');
    if (sidebar) sidebar.classList.add('collapsed');
    if (expandBtn) expandBtn.classList.remove('hidden');
    if (handle) { handle.style.pointerEvents = 'none'; handle.style.opacity = '0'; }
  }

  // Restore the independently saved right-panel state. First-time visitors start
  // with details collapsed until they select a map or list item.
  const rightPanel = document.getElementById('app-right-panel');
  const rightExpandBtn = document.getElementById('right-panel-expand-btn');
  const rightHandle = document.getElementById('right-panel-resize-handle');
  const savedRightState = localStorage.getItem('right_panel_collapsed');
  const rightPanelCollapsed = savedRightState === null ? true : savedRightState === 'true';
  if (rightPanel) rightPanel.classList.toggle('collapsed', rightPanelCollapsed);
  if (rightExpandBtn) rightExpandBtn.classList.toggle('hidden', !rightPanelCollapsed);
  if (rightHandle) {
    rightHandle.style.pointerEvents = rightPanelCollapsed ? 'none' : 'auto';
    rightHandle.style.opacity = rightPanelCollapsed ? '0' : '1';
  }
  localStorage.setItem('right_panel_collapsed', String(rightPanelCollapsed));
  syncPanelVisibilityControls();

  // Set initial sync state
  syncCatchmentMode(false);
  initCatchmentKeyControl();

  // Initialize custom selectors
  initCustomPills();
  initOverviewLayerControls();
  initFullDataControls();
  initLandingDeck();
  const welcome = document.getElementById('welcome-landing');
  if (welcome) {
    welcome.style.display = 'none';
    if (shouldShowOnboarding()) {
      setTimeout(showOnboarding, 250);
    }
  }
  const formulasDrawer = document.getElementById('formulas-drawer');
  if (formulasDrawer) {
    formulasDrawer.addEventListener('click', event => {
      if (event.target === formulasDrawer) closeFormulasDrawer();
    });
  }
  const mapSearchSuggestionsEl = getMapSearchSuggestionsEl();
  if (mapSearchSuggestionsEl) {
    mapSearchSuggestionsEl.addEventListener('mousedown', event => {
      event.preventDefault();
      const option = event.target.closest('.map-search-suggestion');
      if (!option) return;
      const index = parseInt(option.getAttribute('data-index'), 10);
      selectMapSearchSuggestion(mapSearchSuggestions[index]);
    });
  }
  document.addEventListener('mousedown', event => {
    const searchControl = event.target.closest('.map-search-control');
    if (!searchControl) hideMapSearchSuggestions();
  });
  setMapSearchStatus('Search map places and localities, including areas outside this dataset.');
  document.addEventListener('keydown', handleLandingKeyboard);
  document.addEventListener('keydown', event => {
    trapMethodologyDrawerFocus(event);
    if (event.key === 'Escape') {
      closeFullDataView();
      closeFormulasDrawer();
    }
  });

  // Set up delegation handler for Details Cards POI clicks on all pages
  document.addEventListener('click', (e) => {
    const item = e.target.closest('.poi-list-item');
    if (!item) return;

    if (item.getAttribute('data-locked') === 'true') {
      openUnlockModal();
      return;
    }

    // 1. Check if name-based lookup is used (e.g. Hex lists, Commercial list)
    const type = item.getAttribute('data-type');
    const name = item.getAttribute('data-name');
    if (type && name) {
      let poi = null;
      if (type === 'society') poi = societyLookup.get(name);
      else if (type === 'hospital') poi = hospitalLookup.get(name);
      if (poi) {
        focusOnPoi(poi, type);
        return;
      }
    }

    // 2. Fallback to index-based lookup (e.g. Zone lists, Catchment lists, Hex offices)
    const idxAttr = item.getAttribute('data-idx');
    if (idxAttr === null) return;
    const idx = parseInt(idxAttr, 10);
    if (isNaN(idx)) return;

    const listEl = item.closest('[id]');
    if (!listEl) return;
    const listId = listEl.id;

    if (listId === 'zone-societies-list') {
      const data = activeDetailsData.zone.societies[idx];
      focusOnPoi(data, 'society');
    } else if (listId === 'zone-hospitals-markets-list') {
      const itemType = item.getAttribute('data-type');
      const data = itemType === 'hospital' ? activeDetailsData.zone.hospitals[idx] : activeDetailsData.zone.localities[idx];
      focusOnPoi(data, itemType);
    } else if (listId === 'zone-offices-list') {
      const data = activeDetailsData.zone.offices[idx];
      focusOnPoi(data, 'office');
    } else if (listId === 'catchment-societies-list') {
      const itemData = activeDetailsData.catchment.societies[idx];
      const fullSoc = societyLookup.get(itemData.name) || itemData;
      focusOnPoi(fullSoc, 'society');
    } else if (listId === 'catchment-hospitals-list') {
      const itemData = activeDetailsData.catchment.hospitals[idx];
      const fullHosp = hospitalLookup.get(itemData.name) || itemData;
      focusOnPoi(fullHosp, 'hospital');
    } else if (listId === 'hex-societies-list') {
      const data = activeDetailsData.hex.societies[idx];
      focusOnPoi(data, 'society');
    } else if (listId === 'hex-hospitals-list') {
      const data = activeDetailsData.hex.hospitals[idx];
      focusOnPoi(data, 'hospital');
    } else if (listId === 'hex-offices-list') {
      const data = activeDetailsData.hex.offices[idx];
      focusOnPoi(data, 'office');
    }
  });
});

function exploreMapPortal() {
  const welcome = document.getElementById('welcome-landing');
  if (welcome) {
    welcome.style.display = 'none';
    if (map) {
      setTimeout(() => map.invalidateSize(false), 0);
    }
  }
}

function playMapTransition(persistOnboardingDismissal = true) {
  const overlay = document.getElementById('map-transition-overlay');
  const welcome = document.getElementById('welcome-landing');
  if (!overlay || !welcome) {
    if (persistOnboardingDismissal) {
      localStorage.setItem(ONBOARDING_STORAGE_KEY, 'dismissed');
    }
    exploreMapPortal();
    return;
  }

  const revealMap = () => {
    welcome.classList.add('fade-out');
    setTimeout(() => {
      if (persistOnboardingDismissal) {
        localStorage.setItem(ONBOARDING_STORAGE_KEY, 'dismissed');
      }
      welcome.style.display = 'none';
      overlay.classList.remove('active');
      if (map) {
        setTimeout(() => map.invalidateSize(false), 0);
      }
    }, 420);
  };

  overlay.classList.remove('active');
  void overlay.offsetWidth;
  overlay.classList.add('active');
  window.setTimeout(revealMap, 860);
}

function recalculateCapacityPlanner() {
  // The legacy family-proxy planner has been retired. Campus scenarios are
  // calculated only from reported Premium+ Grade 2–9 enrollment.
  renderSchoolCapacityPlanner();
}


// --- FULL PAGE DATA VIEW LOGIC (Gumroad Style) ---

let currentFullData = {
  zone: { societies: [], hospitals: [], offices: [], schools: [] },
  all: { societies: [], hospitals: [], offices: [], schools: [] }
};
let currentFullDataScope = 'zone'; // zone, all
let currentFullDataTab = 'societies'; // societies, hospitals, offices, schools
const FULL_DATA_PAGE_SIZE = 100;
let fullDataState = {
  zone: {
    societies: { search: '', filter: 'all', sortColumn: null, sortAsc: true },
    hospitals: { search: '', filter: 'all', sortColumn: null, sortAsc: true },
    offices: { search: '', filter: 'all', sortColumn: null, sortAsc: true },
    schools: { search: '', filter: 'all', sortColumn: null, sortAsc: true }
  },
  all: {
    societies: { search: '', filter: 'all', sortColumn: null, sortAsc: true },
    hospitals: { search: '', filter: 'all', sortColumn: null, sortAsc: true },
    offices: { search: '', filter: 'all', sortColumn: null, sortAsc: true },
    schools: { search: '', filter: 'all', sortColumn: null, sortAsc: true }
  }
};

function getFullDataState(scope = currentFullDataScope, tab = currentFullDataTab) {
  return fullDataState[scope][tab];
}

function setFullDataState(partial) {
  const state = getFullDataState();
  Object.assign(state, partial);
}

function resetFullDataPage(scope = currentFullDataScope, tab = currentFullDataTab) {
  const state = getFullDataState(scope, tab);
  state.page = 1;
}

function buildFullDataRows(scope) {
  const isAll = scope === 'all';
  const zoneSocieties = isAll
    ? layerData.societies
    : (selectedZone ? layerData.societies.filter(soc => soc.zone === selectedZone) : []);
  const zoneHospitals = isAll
    ? layerData.hospitals
    : (selectedZone ? layerData.hospitals.filter(h => h.zone === selectedZone) : []);
  const zoneLocalities = isAll
    ? layerData.localities
    : (selectedZone ? layerData.localities.filter(l => l.zone === selectedZone) : []);
  const zoneOffices = isAll
    ? (layerData.sez_offices || [])
    : (selectedZone ? (layerData.sez_offices || []).filter(o => o.zone === selectedZone) : []);
  const schoolSourceRows = Array.isArray(layerData.school_entities) && layerData.school_entities.length
    ? layerData.school_entities
    : (layerData.schools || []);
  const zoneSchools = isAll
    ? schoolSourceRows
    : (selectedZone ? schoolSourceRows.filter(s => s.zone === selectedZone) : []);

  const societies = zoneSocieties.map(s => ({
    name: s.name,
    category: s.category,
    zone: s.zone || 'N/A',
    locality: s.locality || 'N/A',
    tam: Number(s.tam || 0),
    units: Number(s.units || 0),
    price: Number(s.price || 0),
    confidence: Number(s.confidence || 0),
    construction_status: s.construction_status || 'N/A',
    lat: Number(s.lat || 0),
    lon: Number(s.lon || 0),
    pincode: s.pincode || 'N/A',
    url: s.url || s.website || ''
  }));

  const hospitals = [
    ...zoneHospitals.map(h => ({
      name: h.name,
      type: 'Hospital',
      category: h.category,
      zone: h.zone || 'N/A',
      metric1Label: 'Rating',
      metric1Value: Number(h.rating || 0),
      metric2Label: 'Beds',
      metric2Value: Number(h.beds || 0),
      pincode: h.pincode || 'N/A',
      lat: Number(h.lat || 0),
      lon: Number(h.lon || 0),
      url: h.url || h.website || ''
    })),
    ...zoneLocalities.map(l => ({
      name: l.name,
      type: 'Locality/Market',
      category: l.budget_segment || 'N/A',
      zone: l.zone || 'N/A',
      metric1Label: 'Avg Price/Sqft',
      metric1Value: Number(l.price_sqft || 0),
      metric2Label: 'Family proxy',
      metric2Value: Number(l.direct_tam || 0),
      pincode: l.pincode || 'N/A',
      lat: Number(l.lat || 0),
      lon: Number(l.lon || 0),
      url: l.url || l.website || ''
    }))
  ];

  const offices = zoneOffices.map(o => ({
    name: o.name,
    company_prominence_tier: o.company_prominence_tier || 'N/A',
    zone: o.zone || 'N/A',
    sez_name: o.sez_name || 'N/A',
    sez_match_type: o.sez_match_type || 'N/A',
    distance_to_sez_km: Number(o.distance_to_sez_km ?? 0),
    office_rank_score: Number(o.office_rank_score ?? 0),
    locality: o.locality || o.address || 'N/A',
    pincode: o.postcode || o.pincode || 'N/A',
    url: o.website || o.url || ''
  }));

  const schools = zoneSchools.map(s => {
    const detail = Array.isArray(layerData.school_entities) && layerData.school_entities.includes(s)
      ? { boards: Array.isArray(s.boards) ? s.boards : (Array.isArray(s.board) ? s.board : String(s.board || '').split(/[,/]/).filter(Boolean)), q4Meta: null }
      : getSchoolCampusEvidence(s);
    const feeRange = s.fee_tier || s.fee_bucket || 'Bucket unavailable';
    const boards = Array.isArray(detail.boards) ? detail.boards : [];
    const boardLabel = boards.length ? boards.join(', ') : 'N/A';
    return {
      name: s.name,
      zone: s.zone || 'N/A',
      area: s.area || 'N/A',
      boards: boardLabel,
      fee_bucket: feeRange,
      fees: feeRange,
      students: Number(s.students_grades_2_9 ?? s.grade_2_9_enrollment ?? 0),
      q4_status: s.q4_tier_label || s.quartile || (detail.q4Meta ? detail.q4Meta.label : 'Outside Q4'),
      lat: Number(s.lat || 0),
      lon: Number(s.lon || 0),
      url: s.url || s.website || ''
    };
  });

  return { societies, hospitals, offices, schools };
}

function refreshFullDataMeta() {
  const meta = document.getElementById('full-data-meta-row');
  if (!meta) return;
  const counts = currentFullData[currentFullDataScope] || {};
  const scopeLabel = currentFullDataScope === 'all'
    ? `${legacyCityLabel()} all zones`
    : `${selectedZone || 'Selected'} zone`;
  meta.innerHTML = `
    <span><strong>${scopeLabel}</strong></span>
    <span>Residential projects: <strong>${formatNumber((counts.societies || []).length, 0)}</strong></span>
    <span>Hospitals/Markets: <strong>${formatNumber((counts.hospitals || []).length, 0)}</strong></span>
    <span>Offices: <strong>${formatNumber((counts.offices || []).length, 0)}</strong></span>
    <span>Schools: <strong>${formatNumber((counts.schools || []).length, 0)}</strong></span>
  `;
}

function getFullDataSearchQuery() {
  return document.getElementById('full-data-search-query')?.value?.trim().toLowerCase() || '';
}

function matchesFullDataSearch(item, query, tabName) {
  if (!query) return true;
  const parts = [
    item.name,
    item.category,
    item.zone,
    item.board,
    item.boards,
    item.q4_status,
    item.fee_bucket,
    item.area,
    item.type,
    item.url,
    item.pincode,
    item.locality,
    item.construction_status,
    item.company_prominence_tier,
    item.sez_name,
    item.sez_match_type
  ];
  if (tabName === 'societies') {
    parts.push(item.tam, item.units, item.price, item.confidence, item.lat, item.lon);
  } else if (tabName === 'offices') {
    parts.push(item.distance_to_sez_km, item.office_rank_score);
  } else if (tabName === 'schools') {
    parts.push(item.students, item.lat, item.lon);
  } else {
    parts.push(item.metric1Value, item.metric2Value, item.lat, item.lon);
  }
  return parts
    .map(value => String(value ?? '').toLowerCase())
    .join(' ')
    .includes(query);
}

function openFullDataView() {
  if (!selectedZone) return;
  if (!isUnlocked()) {
    openUnlockModal();
    return;
  }

  currentFullData.zone = buildFullDataRows('zone');
  currentFullData.all = buildFullDataRows('all');
  currentFullDataTab = 'societies';
  currentFullDataScope = 'zone';

  // Update UI
  document.getElementById('full-data-title').textContent = `${selectedZone} Zone Data`;
  document.getElementById('full-data-modal').classList.remove('hidden');
  const scopeSelect = document.getElementById('full-data-scope');
  if (scopeSelect) scopeSelect.value = 'zone';
  const searchEl = document.getElementById('full-data-search-query');
  if (searchEl) searchEl.value = getFullDataState().search || '';
  resetFullDataPage('zone', 'societies');
  switchFullDataTab('societies');
}

function initFullDataControls() {
  if (document.body.dataset.fullDataControlsBound === 'true') return;
  document.body.dataset.fullDataControlsBound = 'true';

  document.addEventListener('click', event => {
    const fullDataButton = event.target.closest('#button-view-full-data-table-zone-details');
    if (!fullDataButton) return;
    event.preventDefault();
    openFullDataView();
  });

  const closeBtn = document.getElementById('button-close-full-data-modal');
  if (closeBtn) closeBtn.addEventListener('click', closeFullDataView);

  const exportBtn = document.getElementById('button-export-csv-full-data-modal');
  if (exportBtn) exportBtn.addEventListener('click', exportFullDataCSV);

  const scopeSelect = document.getElementById('full-data-scope');
  if (scopeSelect) {
    scopeSelect.addEventListener('change', event => setFullDataScope(event.target.value));
  }

  const searchEl = document.getElementById('full-data-search-query');
  if (searchEl) {
    searchEl.addEventListener('input', () => {
      setFullDataState({ search: getFullDataSearchQuery(), page: 1 });
      renderFullDataTable();
    });
  }

  [
    ['tab-societies', 'societies'],
    ['tab-schools', 'schools'],
    ['tab-hospitals', 'hospitals'],
    ['tab-offices', 'offices'],
  ].forEach(([id, tabName]) => {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener('click', () => switchFullDataTab(tabName));
  });
}

function closeFullDataView() {
  document.getElementById('full-data-modal').classList.add('hidden');
}

function setFullDataScope(scope) {
  const normalizedScope = scope === 'all' ? 'all' : 'zone';
  currentFullDataScope = normalizedScope;
  resetFullDataPage(currentFullDataScope, currentFullDataTab);

  const scopeSelect = document.getElementById('full-data-scope');
  if (scopeSelect && scopeSelect.value !== normalizedScope) {
    scopeSelect.value = normalizedScope;
  }

  const searchEl = document.getElementById('full-data-search-query');
  const activeState = getFullDataState();
  if (searchEl && searchEl.value !== activeState.search) {
    searchEl.value = activeState.search || '';
  }

  renderFullDataFilters();
  renderFullDataTable();
}

function switchFullDataTab(tabName) {
  currentFullDataTab = tabName;
  resetFullDataPage(currentFullDataScope, currentFullDataTab);
  
  // Update tab UI
  document.querySelectorAll('.gumroad-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`tab-${tabName}`).classList.add('active');

  const state = getFullDataState();
  const searchEl = document.getElementById('full-data-search-query');
  if (searchEl) {
    searchEl.value = state.search || '';
  }
  renderFullDataFilters();
  renderFullDataTable();
}

function renderFullDataFilters() {
  const container = document.getElementById('gumroad-filters-container');
  container.innerHTML = '';
  const state = getFullDataState();
  let categories = new Set();
  const dataList = currentFullData[currentFullDataScope][currentFullDataTab];
  dataList.forEach(item => {
    if (item.category && item.category !== 'N/A') categories.add(item.category);
    if (item.board && item.board !== 'N/A') categories.add(item.board);
    if (item.boards && item.boards !== 'N/A') {
      String(item.boards).split(', ').forEach(b => {
        if (b && b !== 'N/A') categories.add(b);
      });
    }
    if (item.q4_status && item.q4_status !== 'N/A') categories.add(item.q4_status);
    if (item.zone && item.zone !== 'N/A') categories.add(item.zone);
    if (item.company_prominence_tier && item.company_prominence_tier !== 'N/A') categories.add(item.company_prominence_tier);
    if (item.sez_match_type && item.sez_match_type !== 'N/A') categories.add(item.sez_match_type);
  });

  const allChip = document.createElement('button');
  allChip.className = `gumroad-filter-chip ${state.filter === 'all' ? 'active' : ''}`;
  allChip.textContent = 'All';
  allChip.onclick = () => { setFullDataState({ filter: 'all', page: 1 }); renderFullDataFilters(); renderFullDataTable(); };
  container.appendChild(allChip);

  Array.from(categories).sort().forEach(cat => {
    const chip = document.createElement('button');
    chip.className = `gumroad-filter-chip ${state.filter === cat ? 'active' : ''}`;
    chip.textContent = cat;
    chip.onclick = () => { setFullDataState({ filter: cat, page: 1 }); renderFullDataFilters(); renderFullDataTable(); };
    container.appendChild(chip);
  });
}

function sortFullData(column) {
  const state = getFullDataState();
  if (state.sortColumn === column) {
    state.sortAsc = !state.sortAsc;
  } else {
    state.sortColumn = column;
    state.sortAsc = true;
  }
  state.page = 1;
  renderFullDataTable();
}

function setFullDataPage(page) {
  const state = getFullDataState();
  state.page = Math.max(1, Number(page || 1));
  renderFullDataTable();
}

function getFullDataHeaders(tabName = currentFullDataTab) {
  if (tabName === 'societies') {
    return [
      { key: 'name', label: 'Name' },
      { key: 'category', label: 'Category' },
      { key: 'zone', label: 'Zone' },
      { key: 'locality', label: 'Locality' },
      { key: 'units', label: 'Known units' },
      { key: 'confidence', label: 'Confidence' },
      { key: 'construction_status', label: 'Status' },
      { key: 'pincode', label: 'Pincode' },
      { key: 'url', label: 'URL Link' },
    ];
  }
  if (tabName === 'offices') {
    return [
      { key: 'name', label: 'Name' },
      { key: 'company_prominence_tier', label: 'Prominence Tier' },
      { key: 'zone', label: 'Zone' },
      { key: 'sez_name', label: 'Office Area' },
      { key: 'sez_match_type', label: 'Match Type' },
      { key: 'distance_to_sez_km', label: 'Boundary Distance' },
      { key: 'office_rank_score', label: 'Rank Score' },
      { key: 'locality', label: 'Locality' },
      { key: 'pincode', label: 'Pincode' },
      { key: 'url', label: 'URL Link' },
    ];
  }
  if (tabName === 'schools') {
    return [
      { key: 'name', label: 'School Name' },
      { key: 'zone', label: 'Zone' },
      { key: 'area', label: 'Area' },
      { key: 'boards', label: 'Boards' },
      { key: 'fee_bucket', label: 'Fee Bucket' },
      { key: 'students', label: 'Students (Grades 2-9)' },
      { key: 'q4_status', label: 'Bucket Status' },
      { key: 'url', label: 'URL Link' },
    ];
  }
  return [
    { key: 'name', label: 'Name' },
    { key: 'type', label: 'Type' },
    { key: 'category', label: 'Category' },
    { key: 'zone', label: 'Zone' },
    { key: 'metric1Value', label: 'Metric 1' },
    { key: 'metric2Value', label: 'Metric 2' },
    { key: 'pincode', label: 'Pincode' },
    { key: 'url', label: 'URL Link' },
  ];
}

function renderFullDataPagination(totalRows, page, pageSize) {
  const target = document.getElementById('full-data-pagination');
  if (!target) return;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  const start = totalRows === 0 ? 0 : ((page - 1) * pageSize) + 1;
  const end = Math.min(totalRows, page * pageSize);
  const tabLabel = {
    societies: 'residential projects',
    schools: 'schools',
    hospitals: 'hospitals/markets',
    offices: 'offices'
  }[currentFullDataTab] || 'rows';

  target.innerHTML = `
    <span>Showing <strong>${formatNumber(start, 0)}–${formatNumber(end, 0)}</strong> of <strong>${formatNumber(totalRows, 0)}</strong> ${escapeHTML(tabLabel)}</span>
    <div class="full-data-page-actions">
      <button type="button" ${page <= 1 ? 'disabled' : ''} onclick="setFullDataPage(${page - 1})">Previous</button>
      <span>Page ${formatNumber(page, 0)} / ${formatNumber(totalPages, 0)}</span>
      <button type="button" ${page >= totalPages ? 'disabled' : ''} onclick="setFullDataPage(${page + 1})">Next</button>
    </div>
  `;
}

function renderFullDataTable() {
  const thead = document.getElementById('full-data-thead');
  const tbody = document.getElementById('full-data-tbody');
  if (!thead || !tbody) return;
  const state = getFullDataState();
  const query = getFullDataSearchQuery();
  state.search = query;
  const headers = getFullDataHeaders(currentFullDataTab);

  let dataList = [...currentFullData[currentFullDataScope][currentFullDataTab]];

  // Filter
  if (state.filter !== 'all') {
    const filterValue = String(state.filter).toLowerCase();
    dataList = dataList.filter(item => {
      const matchCandidates = [item.category, item.board, item.q4_status, item.zone, item.company_prominence_tier, item.sez_match_type];
      if (item.boards) {
        String(item.boards).split(', ').forEach(b => matchCandidates.push(b));
      }
      return matchCandidates.map(v => String(v || '').toLowerCase()).includes(filterValue);
    });
  }

  if (query) {
    dataList = dataList.filter(item => matchesFullDataSearch(item, query, currentFullDataTab));
  }

  // Sort
  if (state.sortColumn) {
    dataList.sort((a, b) => {
      let valA = a[state.sortColumn];
      let valB = b[state.sortColumn];
      if (typeof valA === 'string') valA = valA.toLowerCase();
      if (typeof valB === 'string') valB = valB.toLowerCase();
      
      if (valA < valB) return state.sortAsc ? -1 : 1;
      if (valA > valB) return state.sortAsc ? 1 : -1;
      return 0;
    });
  }

  const totalRows = dataList.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / FULL_DATA_PAGE_SIZE));
  const activePage = Math.min(Math.max(1, Number(state.page || 1)), totalPages);
  state.page = activePage;
  const visibleRows = dataList.slice((activePage - 1) * FULL_DATA_PAGE_SIZE, activePage * FULL_DATA_PAGE_SIZE);
  renderFullDataPagination(totalRows, activePage, FULL_DATA_PAGE_SIZE);

  thead.innerHTML = `<tr>${headers.map(h => `<th onclick="sortFullData('${h.key}')">${escapeHTML(h.label)} ${state.sortColumn === h.key ? (state.sortAsc ? '↑' : '↓') : ''}</th>`).join('')}</tr>`;

  // Body
  tbody.innerHTML = visibleRows.map(item => {
    const linkHtml = item.url ? `<a href="${item.url}" target="_blank" style="color:#2563eb;text-decoration:none;">View Link ↗</a>` : `<span style="color:#9ca3af;">N/A</span>`;
    
    if (currentFullDataTab === 'societies') {
      return `<tr>
        <td><strong>${item.name}</strong></td>
        <td>${item.category}</td>
        <td>${item.zone || 'N/A'}</td>
        <td>${item.locality || 'N/A'}</td>
        <td>${item.units == null ? 'Unavailable' : Number(item.units).toLocaleString()}</td>
        <td>${item.confidence ? Number(item.confidence).toFixed(2) : 'N/A'}</td>
        <td>${item.construction_status || 'N/A'}</td>
        <td>${item.pincode || 'N/A'}</td>
        <td>${linkHtml}</td>
      </tr>`;
    } else if (currentFullDataTab === 'offices') {
      return `<tr>
        <td><strong>${item.name}</strong></td>
        <td>${item.company_prominence_tier}</td>
        <td>${item.zone || 'N/A'}</td>
        <td>${item.sez_name || 'N/A'}</td>
        <td>${item.sez_match_type || 'N/A'}</td>
        <td>${item.distance_to_sez_km ? item.distance_to_sez_km.toFixed(3) + ' km' : '0.000 km'}</td>
        <td>${item.office_rank_score || 0}</td>
        <td>${item.locality || 'N/A'}</td>
        <td>${item.pincode || 'N/A'}</td>
        <td>${linkHtml}</td>
      </tr>`;
    } else if (currentFullDataTab === 'schools') {
      return `<tr>
        <td><strong>${item.name}</strong></td>
        <td>${item.zone || 'N/A'}</td>
        <td>${item.area || 'N/A'}</td>
        <td>${item.boards || 'N/A'}</td>
        <td>${item.fee_bucket || 'N/A'}</td>
        <td>${item.students.toLocaleString()}</td>
        <td>${item.q4_status || 'N/A'}</td>
        <td>${linkHtml}</td>
      </tr>`;
    } else {
      let m1 = item.type === 'Hospital' ? `${item.metric1Value} ⭐` : `₹${item.metric1Value.toLocaleString()}/sqft`;
      let m2 = item.type === 'Hospital' ? `${item.metric2Value} beds` : `${item.metric2Value.toLocaleString()} source records`;
      return `<tr>
        <td><strong>${item.name}</strong></td>
        <td>${item.type}</td>
        <td>${item.category}</td>
        <td>${item.zone || 'N/A'}</td>
        <td>${item.metric1Label}: ${m1}</td>
        <td>${item.metric2Label}: ${m2}</td>
        <td>${item.pincode || 'N/A'}</td>
        <td>${linkHtml}</td>
      </tr>`;
    }
  }).join('');
  
  if (totalRows === 0) {
    const colSpan = currentFullDataTab === 'schools' ? 8 : (currentFullDataTab === 'societies' ? 9 : (currentFullDataTab === 'offices' ? 10 : 8));
    tbody.innerHTML = `<tr><td colspan="${colSpan}" style="text-align:center;color:#6b7280;">No data found.</td></tr>`;
  }
  refreshFullDataMeta();
}

function exportFullDataCSV() {
  if (!isUnlocked()) {
    openUnlockModal();
    return;
  }
  const state = getFullDataState();
  const query = state.search || getFullDataSearchQuery();
  let dataList = [...currentFullData[currentFullDataScope][currentFullDataTab]];

  if (state.filter !== 'all') {
    const filterValue = String(state.filter).toLowerCase();
    dataList = dataList.filter(item => [item.category, item.board, item.zone, item.company_prominence_tier, item.sez_match_type].map(v => String(v || '').toLowerCase()).includes(filterValue));
  }
  if (query) {
    dataList = dataList.filter(item => matchesFullDataSearch(item, query, currentFullDataTab));
  }

  if (state.sortColumn) {
    dataList.sort((a, b) => {
      let valA = a[state.sortColumn];
      let valB = b[state.sortColumn];
      if (typeof valA === 'string') valA = valA.toLowerCase();
      if (typeof valB === 'string') valB = valB.toLowerCase();
      
      if (valA < valB) return state.sortAsc ? -1 : 1;
      if (valA > valB) return state.sortAsc ? 1 : -1;
      return 0;
    });
  }

  if (dataList.length === 0) return;

  const headers = getFullDataHeaders(currentFullDataTab).map(header => header.label);

  let csvContent = "data:text/csv;charset=utf-8," + headers.join(",") + "\n";

  dataList.forEach(item => {
    let row = [];
    if (currentFullDataTab === 'societies') {
      row = [item.name, item.category, item.zone || 'N/A', item.locality || 'N/A', item.units, item.confidence, item.construction_status || 'N/A', item.pincode || 'N/A', item.url];
    } else if (currentFullDataTab === 'offices') {
      row = [item.name, item.company_prominence_tier, item.zone || 'N/A', item.sez_name || 'N/A', item.sez_match_type || 'N/A', item.distance_to_sez_km, item.office_rank_score, item.locality || 'N/A', item.pincode || 'N/A', item.url];
    } else if (currentFullDataTab === 'schools') {
      row = [item.name, item.zone || 'N/A', item.area || 'N/A', item.boards || 'N/A', item.fee_bucket || 'N/A', item.students, item.q4_status || 'N/A', item.url];
    } else {
      row = [item.name, item.type, item.category, item.zone || 'N/A', `${item.metric1Label}: ${item.metric1Value}`, `${item.metric2Label}: ${item.metric2Value}`, item.pincode || 'N/A', item.url];
    }
    // Escape quotes and commas
    row = row.map(cell => `"${String(cell).replace(/"/g, '""')}"`);
    csvContent += row.join(",") + "\n";
  });

  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `${selectedZone.replace(/\s+/g, '_')}_${currentFullDataTab}_export.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function openFormulasDrawer() {
  const drawer = document.getElementById('formulas-drawer');
  if (!drawer) return;
  formulasDrawerReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  drawer.classList.remove('hidden');
  drawer.setAttribute('aria-hidden', 'false');
  document.body.classList.add('methodology-drawer-open');
  requestAnimationFrame(() => drawer.querySelector('.formulas-drawer-panel')?.focus());
}

function closeFormulasDrawer() {
  const drawer = document.getElementById('formulas-drawer');
  if (!drawer) return;
  drawer.classList.add('hidden');
  drawer.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('methodology-drawer-open');
  
  // Reset fullscreen mode on close
  const panel = drawer.querySelector('.formulas-drawer-panel');
  const btn = document.getElementById('btn-toggle-formulas-fullscreen');
  if (panel) panel.classList.remove('fullscreen');
  if (btn) {
    btn.textContent = 'Fullscreen';
    btn.title = 'Switch to full screen view';
  }
  if (formulasDrawerReturnFocus?.isConnected) formulasDrawerReturnFocus.focus();
  formulasDrawerReturnFocus = null;
}

function trapMethodologyDrawerFocus(event) {
  if (event.key !== 'Tab') return;
  const drawer = document.getElementById('formulas-drawer');
  if (!drawer || drawer.classList.contains('hidden')) return;
  const focusable = [...drawer.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(node => !node.disabled && node.getClientRects().length);
  if (!focusable.length) {
    event.preventDefault();
    drawer.querySelector('.formulas-drawer-panel')?.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function toggleFormulasFullscreen() {
  const panel = document.querySelector('.formulas-drawer-panel');
  const btn = document.getElementById('btn-toggle-formulas-fullscreen');
  if (!panel || !btn) return;
  
  const isFullscreen = panel.classList.toggle('fullscreen');
  if (isFullscreen) {
    btn.textContent = 'Drawer view';
    btn.title = 'Switch to side drawer view';
  } else {
    btn.textContent = 'Fullscreen';
    btn.title = 'Switch to full screen view';
  }
}
window.toggleFormulasFullscreen = toggleFormulasFullscreen;

function shouldShowOnboarding() {
  return localStorage.getItem(ONBOARDING_STORAGE_KEY) !== 'dismissed';
}

function showOnboarding() {
  const welcome = document.getElementById('welcome-landing');
  if (!welcome) return;
  welcome.style.display = '';
  welcome.classList.remove('fade-out');
  initLandingMapPreview();
  updateLandingDeck(landingSlideIndex);
}

function dismissOnboarding(persist = true) {
  if (persist) {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, 'dismissed');
  }
  const welcome = document.getElementById('welcome-landing');
  if (welcome) {
    welcome.classList.add('fade-out');
    setTimeout(() => {
      welcome.style.display = 'none';
      if (map) {
        setTimeout(() => map.invalidateSize(false), 0);
      }
    }, 320);
  } else {
    exploreMapPortal();
  }
}

function openOnboarding() {
  landingSlideIndex = 0;
  showOnboarding();
}

function updateActiveLayersPanel() {
  const panel = document.getElementById('map-active-selections');
  const list = document.getElementById('active-selections-list');
  if (!panel || !list) return;

  list.innerHTML = '';
  let activeCount = 0;

  if (selectedZone) {
    activeCount++;
    const item = document.createElement('div');
    item.className = 'active-selection-item';
    item.innerHTML = `
      <span>Zone: ${selectedZone}</span>
      <button class="active-selection-clear-btn" onclick="clearZoneSelection(); updateActiveLayersPanel();" title="Clear zone selection">×</button>
    `;
    list.appendChild(item);
  }


  if (activeCatchmentData) {
    activeCount++;
    const item = document.createElement('div');
    item.className = 'active-selection-item';
    const radius = activeCatchmentData.radius_km || document.getElementById('catchment-input-radius')?.value || '7.0';
    item.innerHTML = `
      <span>Catchment: ${parseFloat(radius).toFixed(1)}km Isochrone</span>
      <button class="active-selection-clear-btn" onclick="clearCatchmentSelection(); updateActiveLayersPanel();" title="Clear catchment selection">×</button>
    `;
    list.appendChild(item);
  }

  if (selectedCommercialListing) {
    activeCount++;
    const item = document.createElement('div');
    item.className = 'active-selection-item';
    item.innerHTML = `
      <span>Listing: ${selectedCommercialListing.title || 'Selected Listing'}</span>
      <button class="active-selection-clear-btn" onclick="clearCommercialSelection(); updateActiveLayersPanel();" title="Clear listing selection">×</button>
    `;
    list.appendChild(item);
  }

  if (activeCount > 0) {
    panel.style.display = 'flex';
  } else {
    panel.style.display = 'none';
  }
}

// Interactive highlight tooltip for first-time users
function showAssumptionsTooltip() {
  const link = document.getElementById('assumptions-highlight-link');
  if (!link) return;
  
  // Add glow highlight class
  link.classList.add('assumptions-glow');
  
  // Create tooltip element
  const tooltip = document.createElement('div');
  tooltip.id = 'assumptions-prompt-tooltip';
  tooltip.className = 'assumptions-prompt-tooltip';
  tooltip.innerHTML = `
    <div class="tooltip-arrow"></div>
    <div class="tooltip-content">
      <strong>Methodology &amp; Sources</strong><br/>
      Review observed evidence, direct calculations, planning scenarios, and directional indicators.
      <button class="tooltip-close-btn" onclick="dismissAssumptionsTooltip(event)">✕</button>
    </div>
  `;
  
  document.body.appendChild(tooltip);
  
  // Position tooltip relative to the assumptions link
  const positionTooltip = () => {
    const rect = link.getBoundingClientRect();
    tooltip.style.position = 'absolute';
    tooltip.style.top = `${window.scrollY + rect.top - tooltip.offsetHeight - 8}px`;
    tooltip.style.left = `${window.scrollX + rect.left + (rect.width - tooltip.offsetWidth) / 2}px`;
  };
  
  // Position once immediately and show
  setTimeout(() => {
    positionTooltip();
    tooltip.classList.add('visible');
  }, 100);
  
  window.addEventListener('resize', positionTooltip, { passive: true });
  
  // Clean up if link is clicked
  link.addEventListener('click', function onClick() {
    dismissAssumptionsTooltip();
    link.removeEventListener('click', onClick);
  });
}

function dismissAssumptionsTooltip(event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  const tooltip = document.getElementById('assumptions-prompt-tooltip');
  if (tooltip) {
    tooltip.classList.remove('visible');
    setTimeout(() => tooltip.remove(), 300);
  }
  const link = document.getElementById('assumptions-highlight-link');
  if (link) {
    link.classList.remove('assumptions-glow');
  }
  localStorage.setItem(ONBOARDING_STORAGE_KEY, 'dismissed');
}

// --- GRAPH ENGINE UI HELPERS ---

let activeHexTierFilter = 'all';
let activePageRankFilter = 'all';

function setHexColorMode(mode) {
  activeHexStyleMode = mode;

  // Update pill-item active state in the color-by group
  const colorGroup = document.getElementById('hex-color-segmented');
  if (colorGroup) {
    colorGroup.querySelectorAll('.pill-item').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.val === mode);
    });
  }

  updateHexColoringMode(mode);
}
window.setHexColorMode = setHexColorMode;

function setHexTierFilter(tier, btnEl) {
  activeHexTierFilter = tier;
  
  // Update active pill styling
  const pillGroup = document.getElementById('pill-hex-tier');
  if (pillGroup) {
    pillGroup.querySelectorAll('.pill-item').forEach(btn => {
      btn.classList.remove('active');
    });
  }
  if (btnEl) {
    btnEl.classList.add('active');
  }
  
  refreshHexLayerStyles();
}
window.setHexTierFilter = setHexTierFilter;

function setHexPageRankFilter(type, btnEl) {
  activePageRankFilter = type;
  
  // Update active pill styling
  const pillGroup = document.getElementById('pill-hex-pagerank');
  if (pillGroup) {
    pillGroup.querySelectorAll('.pill-item').forEach(btn => {
      btn.classList.remove('active');
    });
  }
  if (btnEl) {
    btnEl.classList.add('active');
  }
  
  refreshHexLayerStyles();
}
window.setHexPageRankFilter = setHexPageRankFilter;

function renderGraphAnalyticsTab() {
  const tbody = document.getElementById('graph-ranking-table-body');
  if (!tbody || !layerData.hexes || !layerData.hexes.features) return;
  
  tbody.innerHTML = '';
  
  // Sort hexes by PageRank Personalized descending
  const hexes = [...layerData.hexes.features];
  hexes.sort((a, b) => {
    const prA = a.properties.pagerank_personalized || 0;
    const prB = b.properties.pagerank_personalized || 0;
    return prB - prA;
  });
  
  hexes.forEach((feat, idx) => {
    const p = feat.properties;
    const rank = idx + 1;
    const pprVal = (p.pagerank_personalized || 0) * 1000;
    
    // Rank shift formatting
    const shift = p.rank_shift || 0;
    let shiftHtml = '';
    if (shift > 0) {
      shiftHtml = `<span class="rank-shift-pill rank-shift-up">▲ +${shift}</span>`;
    } else if (shift < 0) {
      shiftHtml = `<span class="rank-shift-pill rank-shift-down">▼ ${shift}</span>`;
    } else {
      shiftHtml = `<span class="rank-shift-pill rank-shift-stable">Stable</span>`;
    }
    
    const tr = document.createElement('tr');
    tr.className = 'graph-ranking-row';
    tr.onclick = (e) => {
      // Don't trigger if clicked on the focus button specifically
      if (e.target.tagName !== 'BUTTON') {
        focusHexOnMap(p.hex_id);
      }
    };
    tr.innerHTML = `
      <td><span class="graph-rank-number">#${rank}</span></td>
      <td>
        <strong class="graph-rank-locality">${p.name}</strong>
        <span class="graph-rank-meta">${p.affluence_tier} · Score ${p.final_affluence_score.toFixed(1)}</span>
      </td>
      <td class="num-col graph-rank-ppr">${pprVal.toFixed(2)}</td>
      <td class="num-col">${shiftHtml}</td>
      <td>
        <button type="button" class="header-action-btn graph-focus-btn" onclick="focusHexOnMap('${p.hex_id}')">Focus</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}
window.renderGraphAnalyticsTab = renderGraphAnalyticsTab;

function focusHexOnMap(hexId) {
  const layer = hexLayerLookup.get(hexId);
  if (!layer) return;
  const p = layer.feature.properties;
  
  // Center map on hex centroid
  map.setView([p.centroid_lat, p.centroid_lon], 13);
  
  // Trigger click/select on that layer
  selectHex(p, layer);
  
  // Open Right details panel
  toggleRightPanel(true);
}
window.focusHexOnMap = focusHexOnMap;

function openImageModal(src) {
  let modal = document.getElementById('image-zoom-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'image-zoom-modal';
    modal.style.position = 'fixed';
    modal.style.top = '0';
    modal.style.left = '0';
    modal.style.width = '100vw';
    modal.style.height = '100vh';
    modal.style.background = 'rgba(15, 23, 42, 0.85)';
    modal.style.zIndex = '9999';
    modal.style.display = 'flex';
    modal.style.alignItems = 'center';
    modal.style.justifyContent = 'center';
    modal.style.cursor = 'zoom-out';
    modal.onclick = () => { modal.style.display = 'none'; };
    
    const img = document.createElement('img');
    img.id = 'image-zoom-img';
    img.style.maxWidth = '90%';
    img.style.maxHeight = '90%';
    img.style.borderRadius = '8px';
    img.style.boxShadow = '0 10px 25px rgba(0,0,0,0.5)';
    modal.appendChild(img);
    
    document.body.appendChild(modal);
  }
  
  const img = document.getElementById('image-zoom-img');
  img.src = src;
  modal.style.display = 'flex';
}
window.openImageModal = openImageModal;

// =====================================================================
// D3 Interactive Force-Directed Graph
// =====================================================================

const _fgRendered = new Set(); // Track which containers have been rendered
let _graphNetworkCache = null; // Cache graph data to avoid re-fetching

async function initForceGraph(containerId, compact = false) {
  if (_fgRendered.has(containerId)) return; // Already rendered successfully

  const container = document.getElementById(containerId);
  if (!container) return;

  const loadingId = containerId === 'force-graph-container'
    ? 'force-graph-loading'
    : 'force-graph-assumptions-loading';
  const loadingEl = document.getElementById(loadingId);

  // Check D3 is available
  if (typeof d3 === 'undefined') {
    if (loadingEl) loadingEl.textContent = 'D3.js failed to load. Check your network connection.';
    return;
  }

  // Fetch graph network data (cached)
  if (!_graphNetworkCache) {
    try {
      const resp = await fetch(legacyDataResource('graph_network.json'));
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      _graphNetworkCache = await resp.json();
    } catch (e) {
      if (loadingEl) loadingEl.textContent = `Network data unavailable: ${e.message}`;
      return;
    }
  }
  const graphData = _graphNetworkCache;

  // Measure container — use CSS fallback if tab is hidden (clientWidth = 0)
  const width = container.getBoundingClientRect().width || container.clientWidth || (compact ? 400 : 560);
  const height = compact ? 320 : 460;

  try {
    // ---- Color helpers ----
    const nodeColor = d => {
      if (d.classification === 'Strategic Hub') return '#f59e0b';
      if (d.classification === 'Wealth Island') return '#dc2626';
      return '#60a5fa';
    };
    const nodeStroke = d => {
      if (d.classification === 'Strategic Hub') return '#92400e';
      if (d.classification === 'Wealth Island') return '#7f1d1d';
      return '#1d4ed8';
    };

    // Scale node radius by direct family proxy
    const tamExtent = d3.extent(graphData.nodes, d => d.direct_family_tam);
    const rScale = d3.scaleSqrt()
      .domain([tamExtent[0] || 0, tamExtent[1] || 1])
      .range(compact ? [3, 10] : [4, 16]);

    // ---- SVG setup with viewBox so it scales in any container ----
    const svg = d3.create('svg')
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('width', '100%')
      .attr('height', height)
      .style('display', 'block');

    // Zoom behaviour
    const zoomG = svg.append('g');
    const zoom = d3.zoom()
      .scaleExtent([0.15, 10])
      .on('zoom', event => zoomG.attr('transform', event.transform));
    svg.call(zoom);

    // ---- Prepare data (shallow clone so D3 can mutate x/y) ----
    const nodes = graphData.nodes.map(d => ({ ...d }));
    const nodeById = new Map(nodes.map(d => [d.id, d]));

    const links = graphData.links
      .filter(l => nodeById.has(l.source) && nodeById.has(l.target))
      .map(l => ({ ...l }));

    // ---- Force simulation ----
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links)
        .id(d => d.id)
        .distance(compact ? 20 : 32)
        .strength(d => Math.min(1, d.weight * 0.8))
      )
      .force('charge', d3.forceManyBody().strength(compact ? -35 : -60))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide(d => rScale(d.direct_family_tam) + 2))
      .alphaDecay(0.02);

    // ---- Draw edges ----
    const linkSel = zoomG.append('g')
      .attr('class', 'fg-links')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', d => d.same_community ? '#94a3b8' : '#e2e8f0')
      .attr('stroke-opacity', d => d.same_community ? 0.5 : 0.18)
      .attr('stroke-width', d => Math.max(0.4, d.weight * (compact ? 1.2 : 1.8)));

    // ---- Tooltip (shared singleton) ----
    let tooltip = document.querySelector('.fg-tooltip');
    if (!tooltip) {
      tooltip = document.createElement('div');
      tooltip.className = 'fg-tooltip';
      tooltip.style.opacity = '0';
      tooltip.style.pointerEvents = 'none';
      document.body.appendChild(tooltip);
    }

    const classLabel = d => {
      if (d.classification === 'Strategic Hub') return `<span class="fg-tt-hub">⭐ Strategic Hub</span>`;
      if (d.classification === 'Wealth Island') return `<span class="fg-tt-island">🏝 Wealth Island</span>`;
      return `<span class="fg-tt-std">○ Standard</span>`;
    };

    // ---- Draw nodes ----
    const nodeSel = zoomG.append('g')
      .attr('class', 'fg-nodes')
      .selectAll('circle')
      .data(nodes)
      .join('circle')
      .attr('r', d => rScale(d.direct_family_tam))
      .attr('fill', d => nodeColor(d))
      .attr('stroke', d => nodeStroke(d))
      .attr('stroke-width', 1)
      .attr('fill-opacity', 0.9)
      .style('cursor', 'pointer')
      .on('mouseover', (event, d) => {
        const shift = d.rank_shift;
        const shiftStr = shift > 0 ? `+${shift} ▲` : shift < 0 ? `${shift} ▼` : 'Stable';
        const shiftColor = shift > 0 ? '#4ade80' : shift < 0 ? '#f87171' : '#94a3b8';
        tooltip.style.opacity = '1';
        tooltip.innerHTML = `
          <strong>${d.name}</strong><br>
          ${classLabel(d)}<br>
          <hr style="border:none;border-top:1px solid rgba(255,255,255,0.15);margin:5px 0;">
          <div class="fg-tt-row"><span>Affluence</span><span>${d.affluence_score}</span></div>
          <div class="fg-tt-row"><span>PageRank</span><span>${(d.pagerank_personalized * 1000).toFixed(2)}</span></div>
          <div class="fg-tt-row"><span>Rank Shift</span><span style="color:${shiftColor};font-weight:700;">${shiftStr}</span></div>
          <div class="fg-tt-row"><span>Direct family proxy</span><span>${d.direct_family_tam.toLocaleString()}</span></div>
          <div class="fg-tt-row"><span>Cluster</span><span>#${d.community_id}</span></div>
        `;
      })
      .on('mousemove', event => {
        tooltip.style.left = (event.clientX + 14) + 'px';
        tooltip.style.top = event.clientY + 'px';
      })
      .on('mouseleave', () => { tooltip.style.opacity = '0'; })
      .on('click', (event, d) => {
        event.stopPropagation();
        if (d.id) focusHexOnMap(d.id);
      })
      .call(d3.drag()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
      );

    // ---- Hub labels (main graph only) ----
    let labelSel = null;
    if (!compact) {
      const topHubs = [...nodes]
        .filter(d => d.classification === 'Strategic Hub')
        .sort((a, b) => b.pagerank_personalized - a.pagerank_personalized)
        .slice(0, 6);

      labelSel = zoomG.append('g')
        .attr('class', 'fg-labels')
        .selectAll('text')
        .data(topHubs)
        .join('text')
        .attr('font-size', 9)
        .attr('fill', '#0f172a')
        .attr('font-weight', '700')
        .attr('text-anchor', 'middle')
        .attr('pointer-events', 'none')
        .attr('paint-order', 'stroke')
        .attr('stroke', 'white')
        .attr('stroke-width', 3)
        .text(d => d.name.split('-')[0].trim().slice(0, 14));
    }

    // ---- Tick handler ----
    simulation.on('tick', () => {
      linkSel
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);
      nodeSel.attr('cx', d => d.x).attr('cy', d => d.y);
      if (labelSel) {
        labelSel
          .attr('x', d => d.x)
          .attr('y', d => d.y - rScale(d.direct_family_tam) - 4);
      }
    });

    // ---- Append SVG and clear loading state ----
    // Clear container first (in case of retry)
    container.innerHTML = '';
    container.appendChild(svg.node());

    // Only mark as rendered AFTER successful append
    _fgRendered.add(containerId);
    if (loadingEl) loadingEl.style.display = 'none';

    console.log(`[ForceGraph] Rendered ${containerId}: ${nodes.length} nodes, ${links.length} links`);

  } catch (err) {
    console.error('[ForceGraph] Render error:', err);
    if (loadingEl) loadingEl.textContent = `Graph error: ${err.message}`;
    // Don't add to _fgRendered — allow retry
  }
}
window.initForceGraph = initForceGraph;


// =========================================================================
// MICRO-MARKETS MODULE LOGIC
// =========================================================================

function getMarketCoreAreaName(hexIds) {
  if (!layerData.hexes || !layerData.hexes.features) return 'Unknown Area';
  let bestHex = null;
  let maxScore = -1;
  hexIds.forEach(id => {
    const feat = layerData.hexes.features.find(f => f.properties.hex_id === id);
    if (feat && feat.properties.final_affluence_score > maxScore) {
      maxScore = feat.properties.final_affluence_score;
      bestHex = feat.properties;
    }
  });
  return bestHex ? bestHex.name : 'Unknown Area';
}

function getMarketTier(m) {
  if (m.avg_score >= 70) {
    return {
      id: 'tier1',
      name: 'Tier 1: Core High-Affluence Anchors',
      badgeClass: 'tier-one-badge',
      color: '#10b981' // emerald
    };
  } else if (m.avg_score >= 60) {
    return {
      id: 'tier2',
      name: 'Tier 2: Established Premium Corridors',
      badgeClass: 'tier-two-badge',
      color: '#3b82f6' // blue
    };
  } else {
    return {
      id: 'tier3',
      name: 'Tier 3: Emerging High-Growth Belts',
      badgeClass: 'tier-three-badge',
      color: '#f59e0b' // amber
    };
  }
}

function renderMicroMarketsTab() {
  const container = document.getElementById('micromarkets-hierarchy-container');
  if (!container) return;
  container.innerHTML = '';

  if (!layerData.microMarkets || !layerData.microMarkets.disjoint_micro_markets) {
    container.innerHTML = '<div style="padding: 20px; color:#6b7280; text-align:center;">Micro-markets data loading...</div>';
    return;
  }

  const markets = layerData.microMarkets.disjoint_micro_markets;
  
  // Group markets by tier
  const groups = {
    tier1: [],
    tier2: [],
    tier3: []
  };

  markets.forEach((m, idx) => {
    const tier = getMarketTier(m);
    const coreName = getMarketCoreAreaName(m.hex_ids);
    
    // Add index to market object for selection
    const marketWithIdx = { ...m, originalIndex: idx, coreName, tier };
    
    // Apply search filter
    if (marketSearchTerm) {
      const otherNames = m.hex_ids.map(id => {
        const feat = layerData.hexes.features.find(f => f.properties.hex_id === id);
        return feat ? feat.properties.name : '';
      }).join(' ').toLowerCase();
      
      const haystack = `${coreName} ${otherNames} ${m.total_units} ${m.total_tam}`.toLowerCase();
      if (!haystack.includes(marketSearchTerm)) {
        return;
      }
    }
    
    groups[tier.id].push(marketWithIdx);
  });

  const tierOrder = ['tier1', 'tier2', 'tier3'];
  let totalRendered = 0;

  tierOrder.forEach(tierId => {
    const list = groups[tierId];
    if (list.length === 0) return;

    totalRendered += list.length;
    
    const tierName = getMarketTier(list[0]).name;
    const tierColor = getMarketTier(list[0]).color;
    const badgeClass = getMarketTier(list[0]).badgeClass;

    const section = document.createElement('div');
    section.className = 'market-tier-section';
    section.innerHTML = `
      <h3 class="market-tier-title" style="border-left: 3px solid ${tierColor}; padding-left: 8px; margin-top: 18px; margin-bottom: 8px;">
        ${tierName} <span class="market-tier-count-pill">${list.length}</span>
      </h3>
      <div class="market-cards-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
    `;

    const cardsList = section.querySelector('.market-cards-list');
    list.forEach(m => {
      const isSelected = selectedMarket === m.originalIndex;
      const card = document.createElement('div');
      card.className = `market-card ${isSelected ? 'selected' : ''}`;
      card.style.borderLeft = `3px solid ${isSelected ? 'var(--notion-primary)' : 'transparent'}`;
      card.innerHTML = `
        <div class="market-card-header-row" style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
          <strong class="market-card-title">${m.coreName} Market</strong>
          <span class="badge ${badgeClass}">${m.combined_score.toFixed(0)} pts</span>
        </div>
        <div class="market-card-details" style="font-size: 11px; color: var(--text-muted); display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; margin-top: 4px;">
          <div><span>Units:</span> <strong>${m.total_units.toLocaleString()}</strong></div>
          <div><span>Avg Score:</span> <strong>${m.avg_score.toFixed(1)}</strong></div>
          <div><span>TAM:</span> <strong>${m.total_tam.toLocaleString()}</strong></div>
        </div>
      `;
      card.addEventListener('click', () => selectMicroMarket(m.originalIndex, card));
      cardsList.appendChild(card);
    });

    container.appendChild(section);
  });

  if (totalRendered === 0) {
    container.innerHTML = '<div style="padding: 20px; color:#6b7280; text-align:center;">No matching micro-markets found.</div>';
  }
}

function filterMicroMarketsList() {
  const input = document.getElementById('market-search-query');
  marketSearchTerm = (input?.value || '').trim().toLowerCase();
  renderMicroMarketsTab();
}

function clearMicroMarketSearch() {
  marketSearchTerm = '';
  const input = document.getElementById('market-search-query');
  if (input) input.value = '';
  renderMicroMarketsTab();
}

function selectMicroMarket(marketIdx, cardElement) {
  // Highlight selection in list
  document.querySelectorAll('.market-card').forEach(c => c.classList.remove('selected'));
  if (cardElement) cardElement.classList.add('selected');

  selectedMarket = marketIdx;
  clearRolledUpAssetsLayer();
  const m = layerData.microMarkets.disjoint_micro_markets[marketIdx];
  const coreName = getMarketCoreAreaName(m.hex_ids);
  const tier = getMarketTier(m);
  const isLocked = !isUnlocked();

  // Highlight micro-market hexes on map
  highlightMarketHexes(m.hex_ids);

  // Roll up societies, hospitals, offices, localities in these 8 hexes
  const marketSocieties = layerData.societies.filter(soc => m.hex_ids.includes(soc.hex_id));
  marketSocieties.sort((a, b) => b.tam - a.tam);
  activeDetailsData.market.societies = marketSocieties;

  const marketHospitals = layerData.hospitals.filter(h => m.hex_ids.includes(h.hex_id));
  marketHospitals.sort((a, b) => b.beds - a.beds || b.rating - a.rating);

  const marketOffices = (layerData.sez_offices || []).filter(off => m.hex_ids.includes(off.hex_id));
  marketOffices.sort((a, b) => (b.office_rank_score || 0) - (a.office_rank_score || 0));

  const marketLocalities = layerData.localities.filter(l => m.hex_ids.includes(l.hex_id));
  marketLocalities.sort((a, b) => b.price_sqft - a.price_sqft);
  const marketSchoolEvidence = getAreaSchoolEvidence({
    type: 'market', hexIds: m.hex_ids, center: getAreaSchoolCenter(m.hex_ids)
  });
  activeDetailsData.market.schools = marketSchoolEvidence.allInside;

  // Roll up income bands
  const marketIncomeBands = {
    "1.5Cr+": 0,
    "60L-1.5Cr": 0,
    "30L-60L": 0,
    "15L-30L": 0,
    "8L-15L": 0
  };
  marketSocieties.forEach(soc => {
    const cat = soc.category || 'Premium';
    if (cat.includes('Ultra')) {
      marketIncomeBands["1.5Cr+"] += soc.tam || 0;
    } else if (cat.includes('Super')) {
      marketIncomeBands["60L-1.5Cr"] += soc.tam || 0;
    } else if (cat.includes('Luxury')) {
      marketIncomeBands["30L-60L"] += soc.tam || 0;
    } else if (cat.includes('Aspirational')) {
      marketIncomeBands["8L-15L"] += soc.tam || 0;
    } else {
      marketIncomeBands["15L-30L"] += soc.tam || 0;
    }
  });

  // Render unified details card layout
  renderStandardDetails(document.getElementById('market-details-card'), {
    title: `${coreName} Micro Market`,
    titleId: 'market-details-title',
    badge: tier.name.split(':')[0],
    badgeId: 'market-details-badge',
    onClose: 'clearMarketSelection()',
    kpis: [
      { id: 'market-kpi-score', value: m.combined_score.toFixed(1), label: 'Combined Score' },
      { id: 'market-kpi-q4-units', value: m.total_units.toLocaleString(), label: 'Residential Units (Q4)' },
      { id: 'market-kpi-units', value: m.total_units.toLocaleString(), label: 'Total Residential Units' },
      { id: 'market-kpi-avgscore', value: m.avg_score.toFixed(1), label: 'Avg Affluence' },
      { id: 'market-kpi-schools', value: formatNumber(marketSchoolEvidence.allInsideCount, 0), label: 'Canonical campuses inside' },
      { id: 'market-kpi-q3-below', value: formatNumber(m.q3_and_below_property_count ?? sumQ3BelowForHexIds(m.hex_ids), 0), label: 'Q3 and Below Properties' }
    ],
    mainContent: `
      <!-- Map Layer Visualisation Toggles -->
      <div class="market-map-controls" style="background: var(--bg-sidebar); border: 1px solid var(--border-light); border-radius: 4px; padding: 10px; margin-bottom: 12px; font-size: 11px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid var(--border-light); padding-bottom: 6px;">
          <strong>Show Rolled-up Assets on Map:</strong>
          <label class="switch-container">
            <input id="toggle-market-all" type="checkbox" onchange="updateMarketMapLayers('toggle-market-all')"/>
            <span class="switch-slider"></span>
          </label>
        </div>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;">
          <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
            <input id="toggle-market-societies" type="checkbox" checked onchange="updateMarketMapLayers('toggle-market-societies')"/>
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#d97706;"></span> Societies
          </label>
          <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
            <input id="toggle-market-offices" type="checkbox" checked onchange="updateMarketMapLayers('toggle-market-offices')"/>
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#2563eb;"></span> Workplaces
          </label>
          <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
            <input id="toggle-market-hospitals" type="checkbox" checked onchange="updateMarketMapLayers('toggle-market-hospitals')"/>
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#ef4444;"></span> Hospitals
          </label>
        </div>
      </div>

      <h4 class="notion-heading-4">Units by Society Classification</h4>
      <div class="chart-container" id="market-income-chart"></div>
    `,
    sections: [
      {
        title: 'Schools inside and near this micro-market',
        count: marketSchoolEvidence.displayed.length,
        id: 'market-schools-list',
        contentHtml: buildAreaSchoolEvidenceHtml(marketSchoolEvidence, `${coreName} Micro Market`),
        open: true
      },
      {
        title: '8 Contiguous Hexes in this Market',
        count: m.hex_ids.length,
        id: 'market-hexes-list',
        contentHtml: m.hex_ids.map(id => {
          const feat = layerData.hexes.features.find(f => f.properties.hex_id === id);
          const p = feat ? feat.properties : {};
          return `
            <div class="poi-list-item" style="cursor: pointer;" onclick="switchTab('overview'); setTimeout(() => focusHexOnMap('${id}'), 50);">
              <div class="poi-item-name">${escapeHTML(p.name || id)}</div>
              <div class="poi-item-tag">Score: ${p.final_affluence_score?.toFixed(1)} | Units: ${p.direct_total_units?.toLocaleString()} | TAM: ${p.countable_family_tam?.toLocaleString()}</div>
            </div>
          `;
        }).join('')
      },
      {
        title: 'Top Residential Societies',
        count: marketSocieties.length,
        id: 'market-societies-list',
        contentHtml: marketSocieties.length > 0 ? marketSocieties.map((soc, idx) => {
          const isLockedItem = isLocked && idx >= 3;
          const socName = isLockedItem ? "Restricted Society Name" : soc.name;
          const socTag = isLockedItem ? "Premium Category | TAM Restricted | Units Restricted" : `${soc.category} | TAM ${soc.tam.toLocaleString()} | Units ${soc.units.toLocaleString()}`;
          return `
            <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" style="cursor: pointer;" onclick="focusOnPoi({lat: ${soc.lat}, lon: ${soc.lon}, name: '${escapeHTML(soc.name).replace(/'/g, "\\'")}', tam: ${soc.tam}, units: ${soc.units}, price: ${soc.price}, locality: '${escapeHTML(soc.locality || 'NA').replace(/'/g, "\\'")}'}, 'society')">
              <div class="poi-item-name">${escapeHTML(socName)}</div>
              <div class="poi-item-tag">${escapeHTML(socTag)}</div>
            </div>
          `;
        }).join('') : '<div style="padding: 10px; color:#6b7280;">No societies in this micro-market</div>'
      },
      {
        title: 'Workplaces & Enterprise Offices',
        count: marketOffices.length,
        id: 'market-offices-list',
        contentHtml: marketOffices.length > 0 ? marketOffices.map((off, idx) => {
          const isLockedItem = isLocked && idx >= 3;
          const offName = isLockedItem ? "Restricted Workplace Name" : off.name;
          const offTag = isLockedItem ? "Enterprise Anchor | Capacity Restricted" : `${off.company_prominence_tier || 'Enterprise'} | Capacity Score: ${off.office_rank_score || 0}`;
          return `
            <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" style="cursor: pointer;" onclick="focusOnPoi({lat: ${off.lat}, lon: ${off.lon}, name: '${escapeHTML(off.name).replace(/'/g, "\\'")}', office_rank_score: ${off.office_rank_score || 0}, company_prominence_tier: '${escapeHTML(off.company_prominence_tier || 'Enterprise').replace(/'/g, "\\'")}'}, 'office')">
              <div class="poi-item-name">${escapeHTML(offName)}</div>
              <div class="poi-item-tag">${escapeHTML(offTag)}</div>
            </div>
          `;
        }).join('') : '<div style="padding: 10px; color:#6b7280;">No workplaces in this micro-market</div>'
      },
      {
        title: 'Hospitals & Localities',
        count: marketHospitals.length + marketLocalities.length,
        id: 'market-hospitals-markets-list',
        contentHtml: (marketHospitals.length > 0 || marketLocalities.length > 0) ? `
          ${marketHospitals.length > 0 ? `
            <div class="poi-section-header">🏥 Key Hospitals</div>
            ${marketHospitals.slice(0, 15).map((h, idx) => {
              const isLockedItem = isLocked && idx >= 3;
              const hName = isLockedItem ? "Restricted Hospital Name" : h.name;
              const hTag = isLockedItem ? "Premium Category | Rating: Restricted | Beds: Restricted" : `${h.category} | Rating: ${h.rating}⭐ | Beds: ${h.beds || 'N/A'}`;
              return `
                <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" style="cursor: pointer;" onclick="focusOnPoi({lat: ${h.lat}, lon: ${h.lon}, name: '${escapeHTML(h.name).replace(/'/g, "\\'")}', rating: ${h.rating}, beds: ${h.beds || 0}, category: '${escapeHTML(h.category).replace(/'/g, "\\'")}'}, 'hospital')">
                  <div class="poi-item-name">${escapeHTML(hName)}</div>
                  <div class="poi-item-tag">${escapeHTML(hTag)}</div>
                </div>
              `;
            }).join('')}
          ` : ''}
          ${marketLocalities.length > 0 ? `
            <div class="poi-section-header">🛍️ Costly Localities / Markets</div>
            ${marketLocalities.slice(0, 15).map((l, idx) => {
              const isLockedItem = isLocked && idx >= 3;
              const lName = isLockedItem ? "Restricted Locality Name" : l.name;
              const lTag = isLockedItem ? "Avg Price: Restricted/sqft | Segment: Restricted" : `Avg Price: ₹${l.price_sqft == null ? 'NA' : l.price_sqft.toLocaleString()}/sqft | Segment: ${l.budget_segment}`;
              return `
                <div class="poi-list-item${isLockedItem ? ' blurred-item' : ''}" style="cursor: pointer;" onclick="focusOnPoi({lat: ${l.lat}, lon: ${l.lon}, name: '${escapeHTML(l.name).replace(/'/g, "\\'")}', price_sqft: ${l.price_sqft}, budget_segment: '${escapeHTML(l.budget_segment).replace(/'/g, "\\'")}'}, 'locality')">
                  <div class="poi-item-name">${escapeHTML(lName)}</div>
                  <div class="poi-item-tag">${escapeHTML(lTag)}</div>
                </div>
              `;
            }).join('')}
          ` : ''}
        ` : '<div style="padding: 10px; color:#6b7280;">No premium support assets in this micro-market</div>'
      }
    ]
  });

  // Render income band chart
  renderIncomeBandChart('market-income-chart', marketIncomeBands);

  // Show details panel
  showDetailsPanel('market-details-card');
  setAreaSchoolContext(marketSchoolEvidence.displayed);

  // Trigger loading and mapping of micro-market asset layers
  updateMarketMapLayers();

  // Add a floating text label at centroid of micro-market
  addMarketCentroidLabel(m.hex_ids, coreName, m.combined_score);
}

function clearMarketSelection() {
  document.getElementById('market-details-card')?.classList.add('hidden');
  updateRightPanelVisibility();
  
  document.querySelectorAll('.market-card').forEach(c => c.classList.remove('selected'));
  selectedMarket = null;
  clearRolledUpAssetsLayer();
  clearAreaSchoolContext();
  resetHexHighlights();
  
  // Clear custom map layers and labels
  if (marketMarkersGroup) {
    map.removeLayer(marketMarkersGroup);
    marketMarkersGroup = null;
  }
  if (activeMarketLabelMarker) {
    map.removeLayer(activeMarketLabelMarker);
    activeMarketLabelMarker = null;
  }
  if (activePoiMarker) {
    map.removeLayer(activePoiMarker);
    activePoiMarker = null;
  }
  updateActiveLayersPanel();
}

function highlightMarketHexes(hexIds) {
  const bounds = [];
  overlayLayers.hexes.eachLayer(function (layer) {
    const props = layer.feature.properties;
    if (hexIds.includes(props.hex_id)) {
      layer.setStyle({
        fillColor: getHexColor(props.final_affluence_score),
        fillOpacity: hexHighlightEnabled ? 0.85 : 0,
        weight: 2,
        color: '#111827'
      });
      const coords = layer.getLatLngs()[0];
      coords.forEach(pt => bounds.push(pt));
    } else {
      layer.setStyle({
        fillColor: getHexColor(props.final_affluence_score),
        fillOpacity: hexHighlightEnabled ? 0.1 : 0,
        weight: 0.5,
        color: '#e5e7eb'
      });
    }
  });
  hexesAreHighlighted = true;

  if (bounds.length > 0) {
    map.fitBounds(L.latLngBounds(bounds), { padding: [30, 30] });
  }
}

function addMarketCentroidLabel(hexIds, coreName, combinedScore) {
  if (activeMarketLabelMarker) {
    map.removeLayer(activeMarketLabelMarker);
    activeMarketLabelMarker = null;
  }

  // Calculate average coordinates of the 8 hex centroids
  let sumLat = 0;
  let sumLon = 0;
  let count = 0;
  hexIds.forEach(id => {
    const feat = layerData.hexes.features.find(f => f.properties.hex_id === id);
    if (feat && feat.properties) {
      sumLat += feat.properties.centroid_lat;
      sumLon += feat.properties.centroid_lon;
      count++;
    }
  });

  if (count === 0) return;
  const avgLat = sumLat / count;
  const avgLon = sumLon / count;

  const customIcon = L.divIcon({
    className: 'custom-market-label-icon',
    html: `<div class="market-floating-label" style="background: rgba(17, 24, 39, 0.95); color: #ffffff; padding: 6px 12px; border-radius: 4px; border: 1.5px solid var(--notion-primary); box-shadow: 0 4px 6px rgba(0,0,0,0.15); text-align: center; pointer-events: none; font-size: 11px;">
             <strong>${coreName} MM</strong><br/>
             Combined Score: <strong>${combinedScore.toFixed(0)}</strong>
           </div>`,
    iconSize: [140, 44],
    iconAnchor: [70, 22]
  });

  activeMarketLabelMarker = L.marker([avgLat, avgLon], { icon: customIcon }).addTo(map);
}

function updateMarketMapLayers(changedId = null) {
  if (selectedMarket === null) return;

  const m = layerData.microMarkets.disjoint_micro_markets[selectedMarket];
  const isLocked = !isUnlocked();

  // Clear existing markers group
  if (marketMarkersGroup) {
    map.removeLayer(marketMarkersGroup);
    marketMarkersGroup = null;
  }

  const markers = [];

  // Read toggle states
  const toggleAllEl = document.getElementById('toggle-market-all');
  const toggleSocEl = document.getElementById('toggle-market-societies');
  const toggleOffEl = document.getElementById('toggle-market-offices');
  const toggleHospEl = document.getElementById('toggle-market-hospitals');

  if (!toggleAllEl || !toggleSocEl || !toggleOffEl || !toggleHospEl) return;

  // If master toggle is checked, check all child boxes and make them true
  if (toggleAllEl.checked && changedId === 'toggle-market-all') {
    toggleSocEl.checked = true;
    toggleOffEl.checked = true;
    toggleHospEl.checked = true;
  }

  // If any child box is unchecked, uncheck the master toggle
  if ((!toggleSocEl.checked || !toggleOffEl.checked || !toggleHospEl.checked) && toggleAllEl.checked) {
    toggleAllEl.checked = false;
  }

  // Add Societies
  if (toggleSocEl.checked) {
    const marketSocieties = layerData.societies.filter(soc => m.hex_ids.includes(soc.hex_id));
    marketSocieties.forEach((soc, idx) => {
      const isLockedItem = isLocked && idx >= 3;
      const socName = isLockedItem ? "Restricted Society Name" : soc.name;
      const socTag = isLockedItem ? "Premium Category | TAM Restricted | Units Restricted" : `${soc.category} | TAM ${soc.tam.toLocaleString()} | Units ${soc.units.toLocaleString()}`;
      
      const marker = L.circleMarker([soc.lat, soc.lon], {
        radius: 6,
        color: '#ffffff',
        fillColor: '#d97706', // gold/amber
        fillOpacity: 0.85,
        weight: 1.5
      });

      marker.bindPopup(`
        <div style="font-family:'Space Grotesk',sans-serif; font-size:11.5px; line-height:1.45;">
          <strong style="color:var(--text-main); font-size:12.5px;">🏢 ${escapeHTML(socName)}</strong><br/>
          <span style="color:#d97706; font-weight:600;">${escapeHTML(soc.category)}</span><br/>
          TAM: <strong>${isLockedItem ? 'Restricted' : soc.tam.toLocaleString()} families</strong><br/>
          Units: <strong>${isLockedItem ? 'Restricted' : soc.units.toLocaleString()}</strong> &middot; Price: <strong>₹${isLockedItem ? 'NA' : (soc.price || 0).toLocaleString()}/sqft</strong><br/>
          Locality: <span>${escapeHTML(soc.locality || 'NA')}</span>
        </div>
      `);
      markers.push(marker);
    });
  }

  // Add Workplaces (Offices)
  if (toggleOffEl.checked) {
    const marketOffices = (layerData.sez_offices || []).filter(off => m.hex_ids.includes(off.hex_id));
    marketOffices.forEach((off, idx) => {
      const isLockedItem = isLocked && idx >= 3;
      const offName = isLockedItem ? "Restricted Workplace Name" : off.name;
      const offTag = isLockedItem ? "Enterprise Anchor | Capacity Restricted" : `${off.company_prominence_tier || 'Enterprise'} &middot; Capacity Score: ${off.office_rank_score || 0}`;

      const marker = L.circleMarker([off.lat, off.lon], {
        radius: 6,
        color: '#ffffff',
        fillColor: '#2563eb', // blue
        fillOpacity: 0.85,
        weight: 1.5
      });

      marker.bindPopup(`
        <div style="font-family:'Space Grotesk',sans-serif; font-size:11.5px; line-height:1.45;">
          <strong style="color:var(--text-main); font-size:12.5px;">💼 ${escapeHTML(offName)}</strong><br/>
          <span style="color:#2563eb; font-weight:600;">${escapeHTML(off.company_prominence_tier || 'Enterprise')}</span><br/>
          Capacity Score: <strong>${off.office_rank_score || 0}</strong> &middot; Proximity: <strong>${escapeHTML(off.proximity || 'NA')}</strong><br/>
          Office area: <span>${escapeHTML(off.sez_name || off.locality || 'NA')}</span>
        </div>
      `);
      markers.push(marker);
    });
  }

  // Add Hospitals
  if (toggleHospEl.checked) {
    const marketHospitals = layerData.hospitals.filter(h => m.hex_ids.includes(h.hex_id));
    marketHospitals.forEach((h, idx) => {
      const isLockedItem = isLocked && idx >= 3;
      const hName = isLockedItem ? "Restricted Hospital Name" : h.name;

      const marker = L.circleMarker([h.lat, h.lon], {
        radius: 6,
        color: '#ffffff',
        fillColor: '#ef4444', // red
        fillOpacity: 0.85,
        weight: 1.5
      });

      marker.bindPopup(`
        <div style="font-family:'Space Grotesk',sans-serif; font-size:11.5px; line-height:1.45;">
          <strong style="color:var(--text-main); font-size:12.5px;">🏥 ${escapeHTML(hName)}</strong><br/>
          <span style="color:#ef4444; font-weight:600;">${escapeHTML(h.category)}</span><br/>
          Beds Count: <strong>${isLockedItem ? 'Restricted' : (h.beds || 'N/A')}</strong> &middot; Rating: <strong>${h.rating || 0}⭐</strong> (${h.reviews || 0} reviews)
        </div>
      `);
      markers.push(marker);
    });
  }

  if (markers.length > 0) {
    marketMarkersGroup = L.layerGroup(markers).addTo(map);
  }
}

// Bind functions to window scope for event.js integration
window.renderMicroMarketsTab = renderMicroMarketsTab;
window.filterMicroMarketsList = filterMicroMarketsList;
window.clearMicroMarketSearch = clearMicroMarketSearch;
window.selectMicroMarket = selectMicroMarket;
window.clearMarketSelection = clearMarketSelection;
window.updateMarketMapLayers = updateMarketMapLayers;

// =========================================================================
// SCHOOL MARKET MODULE — campus evidence remains separate from residential TAM
// =========================================================================

function normalizeSchoolCampusCollection(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : (payload?.campuses || payload?.data?.campuses || payload?.items || []);

  return rows.map((row, index) => {
    const enrollment = Number(
      row.students_grades_2_9 ??
      row.grade_2_9_enrollment ??
      row.enrollment?.grades_2_9 ??
      row.enrollment?.grade_2_9 ??
      0
    );
    const q1 = row.quartile ?? row.quartile_analysis_1 ?? row['quartile analysis 1'] ?? row.fee_quartile ?? '';
    const q2 = row.q4_subquartile ?? row.quartile_analysis_2 ?? row['quartile analysis 2'] ?? '';
    const sourceValue = String(
      row.enrollment_source ?? row.enrollment?.source ?? row.enrollment_provenance ?? 'unknown'
    ).toLowerCase();
    const source = sourceValue.includes('udise') ? 'udise' : (sourceValue.includes('estim') ? 'estimate' : 'unknown');
    const lat = Number(row.lat ?? row.latitude ?? row.location?.lat);
    const lon = Number(row.lon ?? row.lng ?? row.longitude ?? row.location?.lon ?? row.location?.lng);
    const campusId = String(
      row.campus_id ?? row.id ?? row.google_place_id ?? `${row.hex_id || 'school'}-${index}`
    );

    return {
      ...row,
      campus_id: campusId,
      name: row.name || row.campus_name || row.entity_name || 'Unnamed campus',
      lat,
      lon,
      fee_min: Number(row.fee_min ?? row.fees?.min ?? row.annual_fee_min ?? 0),
      fee_max: Number(row.fee_max ?? row.fees?.max ?? row.annual_fee_max ?? row.fee ?? 0),
      students_grades_2_9: Number.isFinite(enrollment) ? enrollment : 0,
      enrollment_source: source,
      quartile_analysis_1: String(q1),
      quartile_analysis_2: String(q2),
      quartile_category: row.q4_segment || row.quartile_category || getSchoolSubquartileMeta(q2).label,
      zone: row.zone || row.geography?.zone || 'Unassigned',
      hex_id: row.hex_id || row.geography?.hex_id || '',
      board: row.board || row.boards || row.curriculum || 'Unknown',
      source_record_count: Number(row.source_record_count ?? row.source_records?.length ?? 1),
      dedupe_status: row.dedupe_status || row.audit?.dedupe_status || (row.source_record_count > 1 ? 'Merged campus' : 'Canonical campus')
    };
  }).filter(campus => Number.isFinite(campus.lat) && Number.isFinite(campus.lon));
}

function normalizeSchoolEntityCollection(payload, campuses = []) {
  const rows = Array.isArray(payload) ? payload : (payload?.entities || payload?.data?.entities || []);
  const campusById = new Map(campuses.map(campus => [String(campus.campus_id), campus]));
  return rows.map((row, index) => {
    const campus = campusById.get(String(row.campus_id || '')) || {};
    const sourceValue = String(row.enrollment_source ?? row.enrollment?.source ?? 'unknown').toLowerCase();
    const source = sourceValue.includes('udise') ? 'udise' : (sourceValue.includes('estim') ? 'estimate' : 'unknown');
    const q1 = row.quartile ?? row.quartile_analysis_1 ?? row['quartile analysis 1'] ?? campus.quartile_analysis_1 ?? campus.quartile ?? '';
    const q2 = row.q4_subquartile ?? row.quartile_analysis_2 ?? row['quartile analysis 2'] ?? campus.quartile_analysis_2 ?? campus.q4_subquartile ?? '';
    return {
      ...row,
      entity_id: String(row.school_entity_id ?? row.entity_id ?? row.id ?? `school-entity-${index}`),
      campus_id: String(row.campus_id ?? campus.campus_id ?? `campus-${index}`),
      name: row.name || row.entity_name || campus.name || 'Unnamed school entity',
      lat: Number(row.lat ?? row.latitude ?? campus.lat),
      lon: Number(row.lon ?? row.lng ?? row.longitude ?? campus.lon),
      fee_min: Number(row.fee_min ?? row.fees?.min ?? 0),
      fee_max: Number(row.fee_max ?? row.fees?.max ?? row.fee ?? 0),
      students_grades_2_9: Number(row.students_grades_2_9 ?? row.grade_2_9_enrollment ?? row.enrollment?.grades_2_9 ?? 0),
      enrollment_source: source,
      quartile_analysis_1: String(q1),
      quartile_analysis_2: String(q2),
      quartile_category: row.q4_segment || row.quartile_category || campus.q4_segment || getSchoolSubquartileMeta(q2).label,
      zone: row.zone || campus.zone || 'Unassigned',
      hex_id: row.hex_id || campus.hex_id || '',
      board: row.boards || row.board || campus.boards || 'Unknown',
      source_record_count: Number(row.source_row_count ?? row.source_record_count ?? 1)
    };
  }).filter(entity => Number.isFinite(entity.lat) && Number.isFinite(entity.lon));
}

function getSchoolSubquartileMeta(key) {
  return SCHOOL_SUBQUARTILES.find(item => item.key === key) || {
    key: key || 'Unclassified', label: 'Unclassified', color: '#64748b'
  };
}

function isSchoolQ4(entity) {
  return String(entity.quartile_analysis_1).toUpperCase() === 'Q4';
}

function getQ4SchoolEntities() {
  return schoolMarketState.entities.filter(isSchoolQ4);
}

function legacySchoolCategoryBuckets(categoryId = activeLegacyCategoryId) {
  const categoryBuckets = {
    super_premium: new Set(['super-premium']),
    premium: new Set(['premium']),
    affordable: new Set(['affordable']),
    budget: new Set(['budget']),
    premium_plus: new Set(['super-premium', 'premium']),
    affordable_plus: new Set(['super-premium', 'premium', 'affordable']),
    all_private: new Set(['super-premium', 'premium', 'affordable', 'budget'])
  };
  return categoryBuckets[categoryId] || categoryBuckets.premium_plus;
}

function getSchoolAudienceEntities() {
  const allowed = legacySchoolCategoryBuckets(activeLegacyCategoryId);
  return schoolMarketState.entities.filter(entity => {
    const bucket = String(entity.fee_bucket || entity.fee_tier || '').trim().toLowerCase().replaceAll('_', '-');
    return allowed.has(bucket);
  });
}

function getSchoolAudienceCampuses() {
  return groupSchoolEntitiesByCampus(getSchoolAudienceEntities());
}

function sumSchoolEnrollment(entities) {
  return entities.reduce((sum, entity) => sum + Number(entity.students_grades_2_9 || 0), 0);
}

function getSchoolSourceTotals(entities) {
  return entities.reduce((totals, entity) => {
    const source = ['udise', 'estimate'].includes(entity.enrollment_source) ? entity.enrollment_source : 'unknown';
    totals[source] += Number(entity.students_grades_2_9 || 0);
    return totals;
  }, { udise: 0, estimate: 0, unknown: 0 });
}

function groupSchoolEntitiesByCampus(entities) {
  const grouped = new Map();
  entities.forEach(entity => {
    if (!grouped.has(entity.campus_id)) grouped.set(entity.campus_id, []);
    grouped.get(entity.campus_id).push(entity);
  });
  return [...grouped.entries()].map(([campusId, campusEntities]) => {
    const physical = schoolMarketState.campuses.find(campus => String(campus.campus_id) === String(campusId)) || campusEntities[0];
    return { ...physical, campus_id: campusId, audience_entities: campusEntities, audience_entity_count: campusEntities.length, audience_enrollment: sumSchoolEnrollment(campusEntities) };
  });
}

function formatSchoolFee(value) {
  const fee = Number(value || 0);
  if (!fee) return 'Not reported';
  if (fee >= 100000) return `₹${(fee / 100000).toFixed(fee % 100000 === 0 ? 0 : 2)}L`;
  return `₹${Math.round(fee).toLocaleString('en-IN')}`;
}

function getSchoolCampusEntities(campusId) {
  const key = String(campusId);
  if (schoolEntitiesByCampusLookup.has(key)) return schoolEntitiesByCampusLookup.get(key);
  return (schoolMarketState.entities || []).filter(entity => String(entity.campus_id) === key);
}

function getSchoolCampusEvidence(campus) {
  const entities = Array.isArray(campus.audience_entities)
    ? campus.audience_entities
    : getSchoolCampusEntities(campus.campus_id);
  const q4Entities = entities.filter(isSchoolQ4);
  const sourceTotals = getSchoolSourceTotals(entities);
  const boards = [...new Set(entities.flatMap(entity => {
    const value = entity.board || entity.boards || [];
    return Array.isArray(value) ? value : String(value || '').split(/[,/|]/);
  }).map(value => String(value).trim()).filter(Boolean))];
  const q4Order = ['Q4-Sub-Q4', 'Q4-Sub-Q3', 'Q4-Sub-Q2', 'Q4-Sub-Q1'];
  const topQ4 = q4Entities.slice().sort((a, b) =>
    (q4Order.indexOf(a.quartile_analysis_2) < 0 ? q4Order.length : q4Order.indexOf(a.quartile_analysis_2))
      - (q4Order.indexOf(b.quartile_analysis_2) < 0 ? q4Order.length : q4Order.indexOf(b.quartile_analysis_2))
  )[0];
  const meta = topQ4 ? getSchoolSubquartileMeta(topQ4.quartile_analysis_2) : null;
  const enrollment = Number(campus.audience_enrollment ?? sumSchoolEnrollment(entities) ?? campus.students_grades_2_9 ?? 0);
  const sourceLabel = sourceTotals.udise > 0 && sourceTotals.estimate > 0
    ? 'UDISE-backed + estimated'
    : sourceTotals.udise > 0
      ? 'UDISE-backed'
      : sourceTotals.estimate > 0
        ? 'Estimated'
        : 'Source not reported';
  const feeMin = Number(campus.fee_min || Math.min(...entities.map(entity => Number(entity.fee_min || Infinity))));
  const feeMax = Number(campus.fee_max || Math.max(0, ...entities.map(entity => Number(entity.fee_max || 0))));
  return {
    entities,
    q4Entities,
    q4Meta: meta,
    boards,
    enrollment,
    sourceLabel,
    feeMin: Number.isFinite(feeMin) ? feeMin : 0,
    feeMax: Number.isFinite(feeMax) ? feeMax : 0
  };
}

function schoolAreaDistanceKm(lat1, lon1, lat2, lon2) {
  const values = [lat1, lon1, lat2, lon2].map(Number);
  if (!values.every(Number.isFinite)) return null;
  const [aLat, aLon, bLat, bLon] = values.map(value => value * Math.PI / 180);
  const dLat = bLat - aLat;
  const dLon = bLon - aLon;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(aLat) * Math.cos(bLat) * Math.sin(dLon / 2) ** 2;
  return 6371.0088 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)));
}

function getSchoolCampusZone(campus) {
  const assigned = String(campus?.zone || '').trim();
  if (assigned && assigned.toLowerCase() !== 'unassigned') return assigned;
  return String(getHexPropsById(campus?.hex_id)?.zone || 'Unassigned');
}

function getSchoolAudienceZoneRollups() {
  const rollups = new Map();
  getSchoolAudienceCampuses().forEach(campus => {
    const zone = getSchoolCampusZone(campus);
    if (!rollups.has(zone)) rollups.set(zone, { campuses: 0, entities: 0, enrollment: 0 });
    const row = rollups.get(zone);
    row.campuses += 1;
    row.entities += Number(campus.audience_entity_count || 0);
    row.enrollment += Number(campus.audience_enrollment || 0);
  });
  return rollups;
}

function getAudienceZoneEntries() {
  const rollups = getSchoolAudienceZoneRollups();
  return Object.entries(layerData.report?.zones || {}).map(([zoneName, baseStats]) => {
    const audience = rollups.get(zoneName) || { campuses: 0, entities: 0, enrollment: 0 };
    return [zoneName, {
      ...baseStats,
      school_count: audience.campuses,
      students_grade_2_9: audience.enrollment,
      premium_plus_students_grade_2_9: audience.enrollment,
      audience_school_count: audience.campuses,
      audience_entity_count: audience.entities,
      audience_students_grade_2_9: audience.enrollment
    }];
  });
}

function getAudienceZoneStats(zoneName) {
  return getAudienceZoneEntries().find(([name]) => name === zoneName)?.[1]
    || layerData.report?.zones?.[zoneName]
    || {};
}

function getAreaSchoolCenter(hexIds, fallback = null) {
  const requested = new Set((hexIds || []).map(String));
  const points = (layerData.hexes?.features || [])
    .map(feature => feature.properties || {})
    .filter(props => requested.has(String(props.hex_id)))
    .map(props => [Number(props.centroid_lat), Number(props.centroid_lon)])
    .filter(point => point.every(Number.isFinite));
  if (!points.length && fallback && [fallback.lat, fallback.lon].every(value => Number.isFinite(Number(value)))) {
    return { lat: Number(fallback.lat), lon: Number(fallback.lon) };
  }
  if (!points.length) return null;
  return {
    lat: points.reduce((sum, point) => sum + point[0], 0) / points.length,
    lon: points.reduce((sum, point) => sum + point[1], 0) / points.length
  };
}

function getAreaSchoolEvidence({ type, zone = null, hexIds = [], center = null }) {
  const campusRows = getSchoolAudienceCampuses().filter(campus =>
    Number.isFinite(Number(campus.lat)) && Number.isFinite(Number(campus.lon))
  );
  const ids = new Set((hexIds || []).map(String));
  const isInside = campus => type === 'zone'
    ? getSchoolCampusZone(campus) === String(zone || '')
    : ids.has(String(campus.hex_id || ''));
  const resolvedCenter = center || getAreaSchoolCenter(hexIds);
  const decorate = (campus, context) => ({
    ...campus,
    area_context: context,
    area_distance_km: resolvedCenter
      ? schoolAreaDistanceKm(resolvedCenter.lat, resolvedCenter.lon, campus.lat, campus.lon)
      : null
  });
  const evidenceCache = new Map();
  const cachedEvidence = campus => {
    const key = String(campus.campus_id);
    if (!evidenceCache.has(key)) evidenceCache.set(key, getSchoolCampusEvidence(campus));
    return evidenceCache.get(key);
  };
  const rank = (a, b) => {
    const aEvidence = cachedEvidence(a);
    const bEvidence = cachedEvidence(b);
    return Number(Boolean(bEvidence.q4Entities.length)) - Number(Boolean(aEvidence.q4Entities.length))
      || bEvidence.feeMax - aEvidence.feeMax
      || bEvidence.enrollment - aEvidence.enrollment
      || String(a.name).localeCompare(String(b.name));
  };
  const allInside = campusRows.filter(isInside).map(campus => decorate(campus, 'inside')).sort(rank);
  const allInsideStudents = allInside.reduce((sum, campus) => sum + Number(campus.audience_enrollment || 0), 0);
  const insideLimit = type === 'zone' ? 30 : 20;
  const inside = allInside.slice(0, insideLimit);
  const nearbyLimit = type === 'hex' ? 12 : 8;
  const nearby = campusRows.filter(campus => !isInside(campus))
    .map(campus => decorate(campus, 'nearby'))
    .filter(campus => campus.area_distance_km !== null)
    .sort((a, b) => a.area_distance_km - b.area_distance_km || rank(a, b))
    .slice(0, nearbyLimit);
  return {
    type,
    center: resolvedCenter,
    allInside,
    allInsideCount: allInside.length,
    allInsideStudents,
    inside,
    nearby,
    displayed: [...inside, ...nearby]
  };
}

function buildAreaSchoolEvidenceHtml(evidence, areaLabel) {
  const renderRows = rows => rows.map(campus => {
    const detail = getSchoolCampusEvidence(campus);
    const q4Label = detail.q4Meta
      ? `${detail.q4Meta.label} · ${activeLegacyCategory().label}`
      : (campus.fee_bucket || campus.fee_tier || activeLegacyCategory().label);
    const feeRange = campus.fee_tier || campus.fee_bucket || 'Bucket unavailable';
    const boardLabel = detail.boards.length ? detail.boards.join(', ') : 'Board not reported';
    const distanceLabel = campus.area_distance_km == null
      ? ''
      : `${campus.area_distance_km.toFixed(1)} km from ${evidence.type === 'hex' ? 'hex' : 'area'} centroid`;
    const contextLabel = campus.area_context === 'inside' ? `Inside ${areaLabel}` : 'Nearby context';
    const campusId = String(campus.campus_id).replace(/'/g, "\\'");
    return `<button class="area-school-row" onclick="focusAreaSchoolCampus('${escapeHTML(campusId)}')" type="button">
      <span class="area-school-row-head"><strong>${escapeHTML(campus.name)}</strong><i class="${detail.q4Meta ? 'q4' : ''}">${escapeHTML(q4Label)}</i></span>
      <span>${escapeHTML(contextLabel)}${distanceLabel ? ` · ${escapeHTML(distanceLabel)}` : ''}</span>
      <span>${escapeHTML(feeRange)} · ${escapeHTML(boardLabel)} · ${formatNumber(detail.entities.length)} entit${detail.entities.length === 1 ? 'y' : 'ies'}</span>
      <span>${formatNumber(detail.enrollment)} grade 2–9 enrollment · ${escapeHTML(detail.sourceLabel)}</span>
    </button>`;
  }).join('');
  const insideNote = evidence.allInsideCount > evidence.inside.length
    ? `Showing ${evidence.inside.length} of ${evidence.allInsideCount} campuses inside, ranked by ${activeLegacyCategory().label} enrollment.`
    : `${evidence.allInsideCount} campus${evidence.allInsideCount === 1 ? '' : 'es'} physically inside the selected geography.`;
  return `<div class="area-school-evidence-note">
      <strong>${escapeHTML(activeLegacyCategory().label)} school evidence</strong>
      <span>${escapeHTML(insideNote)} Nearby rows are context only; no students are assigned to this area.</span>
      <label><input checked onchange="toggleAreaSchoolContext(this.checked)" type="checkbox"/> Show these campuses on the map</label>
    </div>
    ${evidence.displayed.length ? `<div class="area-school-list">${renderRows(evidence.displayed)}</div>` : '<div class="school-empty-state" role="status">No canonical campus with valid coordinates is available for this area.</div>'}`;
}

function makeAreaSchoolMarker(campus) {
  const detail = getSchoolCampusEvidence(campus);
  const marker = L.marker([Number(campus.lat), Number(campus.lon)], {
    icon: L.divIcon({
      className: 'area-school-marker-wrap',
      html: `<span class="area-school-marker${detail.q4Meta ? ' q4' : ''}${campus.area_context === 'nearby' ? ' nearby' : ''}" aria-hidden="true"></span>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
      popupAnchor: [0, -10]
    }),
    riseOnHover: true,
    title: `${campus.name} — ${campus.area_context === 'inside' ? 'inside area' : 'nearby context'}`
  });
  marker.bindTooltip(`${escapeHTML(campus.name)} · ${detail.q4Meta ? escapeHTML(detail.q4Meta.label) : escapeHTML(campus.fee_bucket || campus.fee_tier || 'Non-premium bucket')} · ${formatNumber(detail.enrollment)} grade 2–9`, { sticky: true });
  marker.on('click', () => focusAreaSchoolCampus(campus.campus_id));
  return marker;
}

function setAreaSchoolContext(campuses) {
  clearAreaSchoolContext();
  areaSchoolContextCampuses = campuses || [];
  areaSchoolContextVisible = true;
  if (!map || !window.L || !areaSchoolContextCampuses.length) return;
  areaSchoolContextLayer = L.layerGroup(areaSchoolContextCampuses.map(makeAreaSchoolMarker));
  areaSchoolContextLayer.addTo(map);
}

function clearAreaSchoolContext() {
  if (areaSchoolContextLayer && map?.hasLayer(areaSchoolContextLayer)) map.removeLayer(areaSchoolContextLayer);
  areaSchoolContextLayer = null;
  areaSchoolContextCampuses = [];
}

function toggleAreaSchoolContext(visible) {
  areaSchoolContextVisible = Boolean(visible);
  if (!map || !areaSchoolContextLayer) return;
  if (areaSchoolContextVisible && !map.hasLayer(areaSchoolContextLayer)) areaSchoolContextLayer.addTo(map);
  if (!areaSchoolContextVisible && map.hasLayer(areaSchoolContextLayer)) map.removeLayer(areaSchoolContextLayer);
}

function focusAreaSchoolCampus(campusId) {
  const campus = (schoolMarketState.campuses || []).find(item => String(item.campus_id) === String(campusId));
  if (!campus || !map) return;
  if (areaSchoolContextLayer && !map.hasLayer(areaSchoolContextLayer)) {
    areaSchoolContextVisible = true;
    areaSchoolContextLayer.addTo(map);
  }
  map.flyTo([Number(campus.lat), Number(campus.lon)], Math.max(map.getZoom(), 14), { duration: 0.65 });
  const matchingMarker = areaSchoolContextLayer?.getLayers?.().find(marker =>
    marker.getLatLng && Math.abs(marker.getLatLng().lat - Number(campus.lat)) < 1e-7 && Math.abs(marker.getLatLng().lng - Number(campus.lon)) < 1e-7
  );
  matchingMarker?.openTooltip?.();
  showSchoolCampusDetails(campus.campus_id);
}

function getSchoolModeLabel() {
  return `${activeLegacyCategory().label} bucket audience`;
}

function initializeSchoolMarket() {
  schoolMarketState.campuses = layerData.schools || [];
  schoolMarketState.entities = normalizeSchoolEntityCollection(layerData.school_entities || [], schoolMarketState.campuses);
  if (!schoolMarketState.entities.length) {
    schoolMarketState.entities = normalizeSchoolEntityCollection(schoolMarketState.campuses.map((campus, index) => ({
      ...campus, entity_id: campus.entity_id || `fallback-entity-${index}`, source_row_count: campus.source_record_count || 1
    })), schoolMarketState.campuses);
  }
  schoolEntitiesByCampusLookup = new Map();
  schoolMarketState.entities.forEach(entity => {
    const key = String(entity.campus_id);
    if (!schoolEntitiesByCampusLookup.has(key)) schoolEntitiesByCampusLookup.set(key, []);
    schoolEntitiesByCampusLookup.get(key).push(entity);
  });
  schoolMarketState.summary = layerData.school_market_summary || null;
  schoolMarketState.audit = layerData.school_market_audit || null;
  schoolMarketState.available = schoolMarketState.campuses.length > 0 && schoolMarketState.entities.length > 0;

  const search = new URLSearchParams(window.location.search);
  schoolMarketState.mode = 'q4';

  initializeAccessibleTabs();
  renderClientSummary();
  renderSchoolMarket();
  renderSchoolExecutiveSurfaces();
  renderZonesTab();
}

function getSchoolDirectoryRows() {
  const audienceCampuses = new Map(getSchoolAudienceCampuses().map(campus => [String(campus.campus_id), campus]));
  return (schoolMarketState.campuses || []).map(campus => {
    const entities = getSchoolCampusEntities(campus.campus_id);
    const audienceCampus = audienceCampuses.get(String(campus.campus_id));
    const evidence = getSchoolCampusEvidence(campus);
    const buckets = [...new Set(entities.map(entity =>
      String(entity.fee_bucket || entity.fee_tier || '').trim()
    ).filter(Boolean))];
    const area = String(campus.area || campus.locality || campus.neighborhood || campus.address || '').trim();
    const zone = getSchoolCampusZone(campus);
    const enrollment = Number(campus.students_grades_2_9 || evidence.enrollment || 0);
    const audienceEnrollment = Number(audienceCampus?.audience_enrollment || 0);
    const searchable = [
      campus.name,
      area,
      zone,
      evidence.boards.join(' '),
      buckets.join(' '),
      ...entities.map(entity => entity.name)
    ].join(' ').toLowerCase();
    return {
      campus,
      entities,
      evidence,
      buckets,
      area,
      zone,
      enrollment,
      audienceEnrollment,
      inAudience: Boolean(audienceCampus),
      hasCoordinates: Number.isFinite(Number(campus.lat)) && Number.isFinite(Number(campus.lon)),
      searchable
    };
  });
}

function renderSchoolDirectory() {
  const body = document.getElementById('school-directory-body');
  const meta = document.getElementById('school-directory-meta');
  const count = document.getElementById('school-directory-count');
  const pageLabel = document.getElementById('school-directory-page');
  const previousButton = document.getElementById('school-directory-prev');
  const nextButton = document.getElementById('school-directory-next');
  if (!body || !meta || !count || !pageLabel || !previousButton || !nextButton) return;

  const searchInput = document.getElementById('school-directory-search');
  const audienceOnlyInput = document.getElementById('school-directory-audience-only');
  const sortInput = document.getElementById('school-directory-sort');
  if (searchInput && document.activeElement !== searchInput) searchInput.value = schoolDirectoryState.query;
  if (audienceOnlyInput) audienceOnlyInput.checked = schoolDirectoryState.audienceOnly;
  if (sortInput) sortInput.value = schoolDirectoryState.sort;

  if (!schoolMarketState.available) {
    count.textContent = 'No school data';
    meta.textContent = 'The canonical campus index is unavailable for this city.';
    body.innerHTML = '<tr><td class="decision-empty" colspan="6">No school campuses are available.</td></tr>';
    pageLabel.textContent = 'Page 0 of 0';
    previousButton.disabled = true;
    nextButton.disabled = true;
    return;
  }

  const allRows = getSchoolDirectoryRows();
  const query = schoolDirectoryState.query.trim().toLowerCase();
  const rows = allRows.filter(row =>
    (!schoolDirectoryState.audienceOnly || row.inAudience)
    && (!query || row.searchable.includes(query))
  );
  rows.sort((a, b) => {
    if (schoolDirectoryState.sort === 'enrollment') {
      return b.enrollment - a.enrollment || String(a.campus.name).localeCompare(String(b.campus.name));
    }
    if (schoolDirectoryState.sort === 'zone') {
      return a.zone.localeCompare(b.zone) || String(a.campus.name).localeCompare(String(b.campus.name));
    }
    return String(a.campus.name).localeCompare(String(b.campus.name));
  });

  const pageCount = Math.max(1, Math.ceil(rows.length / schoolDirectoryState.pageSize));
  schoolDirectoryState.page = Math.min(Math.max(1, schoolDirectoryState.page), pageCount);
  const start = (schoolDirectoryState.page - 1) * schoolDirectoryState.pageSize;
  const visibleRows = rows.slice(start, start + schoolDirectoryState.pageSize);
  const audienceCampusCount = allRows.filter(row => row.inAudience).length;
  count.textContent = `${formatNumber(allRows.length)} campuses`;
  meta.textContent = `${formatNumber(rows.length)} matching campuses · ${formatNumber(audienceCampusCount)} in ${activeLegacyCategory().label} · showing ${rows.length ? formatNumber(start + 1) : 0}–${formatNumber(Math.min(start + visibleRows.length, rows.length))}`;
  pageLabel.textContent = `Page ${schoolDirectoryState.page} of ${rows.length ? pageCount : 0}`;
  previousButton.disabled = schoolDirectoryState.page <= 1;
  nextButton.disabled = schoolDirectoryState.page >= pageCount || !rows.length;

  body.innerHTML = visibleRows.map(row => {
    const campus = row.campus;
    const campusId = escapeHTML(String(campus.campus_id));
    const boards = row.evidence.boards.join(', ') || 'Not reported';
    const buckets = row.buckets.join(', ') || 'Not reported';
    const areaLabel = row.area && row.area !== row.zone ? `${row.zone} · ${row.area}` : row.zone;
    const selected = String(schoolMarketState.selectedCampusId) === String(campus.campus_id);
    const audienceLine = row.inAudience
      ? `<small>${escapeHTML(activeLegacyCategory().label)}: ${formatNumber(row.audienceEnrollment)}</small>`
      : `<small>Outside ${escapeHTML(activeLegacyCategory().label)}</small>`;
    return `<tr aria-label="Locate ${escapeHTML(campus.name)} on map" class="${selected ? 'selected' : ''}" data-directory-campus-id="${campusId}" tabindex="0">
      <td><strong>${escapeHTML(campus.name)}</strong><small>${formatNumber(row.entities.length)} canonical entit${row.entities.length === 1 ? 'y' : 'ies'}</small></td>
      <td>${escapeHTML(areaLabel || 'Unassigned')}</td>
      <td>${escapeHTML(boards)}</td>
      <td>${escapeHTML(buckets)}</td>
      <td class="num-col"><strong>${formatNumber(row.enrollment)}</strong>${audienceLine}</td>
      <td><button class="school-directory-locate" ${row.hasCoordinates ? '' : 'disabled'} type="button">${row.hasCoordinates ? 'Show on map' : 'No coordinates'}</button></td>
    </tr>`;
  }).join('') || '<tr><td class="decision-empty" colspan="6">No schools match this search and audience filter.</td></tr>';
}

function setSchoolDirectoryQuery(value) {
  schoolDirectoryState.query = String(value || '');
  schoolDirectoryState.page = 1;
  renderSchoolDirectory();
}

function setSchoolDirectoryAudienceOnly(value) {
  schoolDirectoryState.audienceOnly = Boolean(value);
  schoolDirectoryState.page = 1;
  renderSchoolDirectory();
}

function setSchoolDirectorySort(value) {
  schoolDirectoryState.sort = value || 'name';
  schoolDirectoryState.page = 1;
  renderSchoolDirectory();
}

function changeSchoolDirectoryPage(delta) {
  schoolDirectoryState.page += Number(delta || 0);
  renderSchoolDirectory();
}

function focusSchoolDirectoryCampus(campusId) {
  const campus = (schoolMarketState.campuses || []).find(item => String(item.campus_id) === String(campusId));
  if (!campus || !map || !Number.isFinite(Number(campus.lat)) || !Number.isFinite(Number(campus.lon))) return;

  schoolMarketState.selectedCampusId = campus.campus_id;
  if (schoolMarketState.directoryFocusLayer && map.hasLayer(schoolMarketState.directoryFocusLayer)) {
    map.removeLayer(schoolMarketState.directoryFocusLayer);
  }
  const marker = L.circleMarker([Number(campus.lat), Number(campus.lon)], {
    radius: 10,
    color: '#7c2d12',
    fillColor: '#f59e0b',
    fillOpacity: 0.95,
    weight: 3
  });
  marker.bindTooltip(`${escapeHTML(campus.name)} · selected from school directory`, {
    permanent: false,
    direction: 'top',
    offset: [0, -8]
  });
  marker.on('click', () => showSchoolCampusDetails(campus.campus_id));
  schoolMarketState.directoryFocusLayer = L.layerGroup([marker]).addTo(map);
  syncSchoolMapVisibility(true);
  map.flyTo([Number(campus.lat), Number(campus.lon)], Math.max(map.getZoom(), 15), { duration: 0.65 });
  marker.openTooltip();
  showSchoolCampusDetails(campus.campus_id);
}

function getLuxuryResidentialLedger() {
  const included = new Set(['luxury', 'super luxury', 'ultra luxury']);
  const rows = (layerData.societies || []).filter(society => included.has(String(society.category || '').trim().toLowerCase()));
  return {
    societyCount: rows.length,
    units: rows.reduce((sum, society) => sum + Number(society.units || 0), 0)
  };
}

function renderSchoolExecutiveSurfaces() {
  const clientTitle = document.getElementById('client-school-market-title');
  const clientBody = document.getElementById('client-school-market-body');
  const residentialTarget = document.getElementById('school-residential-ledger');
  const auditTarget = document.getElementById('school-audit-reconciliation');
  if (!schoolMarketState.available) {
    const unavailable = '<div class="school-surface-error"><strong>School evidence unavailable</strong><span>The society and location analysis remains usable; no legacy school metric has been substituted.</span></div>';
    if (clientBody) clientBody.innerHTML = unavailable;
    if (residentialTarget) residentialTarget.innerHTML = unavailable;
    if (auditTarget) auditTarget.innerHTML = unavailable;
    ['landing-slide1-q4-students', 'landing-slide2-school-entities', 'landing-slide2-school-campuses'].forEach(id => setTextIfExists(id, 'Unavailable'));
    return;
  }
  if (clientTitle) clientTitle.textContent = `${activeLegacyCategory().label} school audience`;

  const audienceEntities = getSchoolAudienceEntities();
  const audienceCampuses = groupSchoolEntitiesByCampus(audienceEntities);
  const audienceEnrollment = sumSchoolEnrollment(audienceEntities);
  const audienceSource = getSchoolSourceTotals(audienceEntities);
  const summaryBucket = schoolMarketState.summary?.bucket_summaries?.[activeLegacyCategoryId] || {};
  const audit = schoolMarketState.audit || {};
  const entityCount = Number(audit.published_entity_count || schoolMarketState.entities.length);
  const campusCount = Number(audit.published_campus_count || schoolMarketState.campuses.length);
  const primaryEntityCount = Number(summaryBucket.school_entity_count_all ?? audienceEntities.length);
  const primaryCampusCount = Number(summaryBucket.campus_count_context ?? audienceCampuses.length);
  const primaryEnrollment = Number(summaryBucket.students_grades_2_9_expanded ?? audienceEnrollment);
  const source = summaryBucket.students_grades_2_9_by_source || { udise_backed: audienceSource.udise, estimated: audienceSource.estimate };
  const residential = getLuxuryResidentialLedger();
  const capacity = summaryBucket.capacity || [];
  const capacityRow = rate => capacity.find(row => Number(row.capture_rate) === rate) || {};
  const sensitivities = (schoolMarketState.summary?.fee_max_sensitivity || []).filter(row => [175000, 180000, 200000].includes(Number(row.threshold_fee_max)));
  const caveat = schoolMarketState.summary?.methodology?.sensitivity_caveat || 'Enrollment is associated with qualifying canonical entities; it is not proof that each student pays the reported fee maximum.';
  const rawQ4 = audit.raw_preclean_benchmarks?.q4 || {};
  const qualityText = `${formatNumber(audit.input_row_count || 0)} raw rows → ${formatNumber(entityCount)} canonical entities → ${formatNumber(campusCount)} physical campuses; ${formatNumber(audit.duplicate_rows_collapsed || 0)} duplicate rows collapsed, ${formatNumber(audit.quarantined_row_count || 0)} quarantined, ${formatNumber(audit.multi_entity_campus_count || 0)} multi-entity campuses.`;
  const q4DerivedBoundary = Number(audit.q4_fee_max_cutoff || 0);

  const directDecisionMetrics = activeDecisionMetrics(null);
  if (clientBody) {
    clientBody.innerHTML = `
      <div class="client-school-primary-grid" style="grid-template-columns: repeat(3, 1fr);">
       <article><span>${escapeHTML(activeLegacyCategory().label)} schools</span><strong>${formatNumber(directDecisionMetrics.metrics.school_count || primaryEntityCount)}</strong><small>Canonical school entities in the selected bucket</small></article>
       <article><span>Source-reported all-grade</span><strong>${directDecisionMetrics.reportedTotal ? formatNumber(directDecisionMetrics.reportedTotal) : 'Unavailable'}</strong><small>Primary city-ranking demand input</small></article>
       <article><span>Derived reported Grade 2–9</span><strong>${directDecisionMetrics.reportedGrade29 ? formatNumber(directDecisionMetrics.reportedGrade29) : 'Unavailable'}</strong><small>${directDecisionMetrics.modeled ? `+${formatNumber(directDecisionMetrics.modeled)} modeled separately` : 'Reported rows only'}</small></article>
      </div>`;
  }


  if (residentialTarget) {
    residentialTarget.innerHTML = '';
  }
  if (auditTarget) {
    auditTarget.innerHTML = '';
  }

  setTextIfExists('landing-slide1-q4-students', formatNumber(primaryEnrollment));
  setTextIfExists('landing-slide1-school-label', `${activeLegacyCategory().label} grade 2–9 enrollment`);
  setTextIfExists('landing-slide1-school-scope', `${formatNumber(primaryEntityCount)} ${activeLegacyCategory().label} entities · ${formatNumber(primaryCampusCount)} campuses · not resident students`);
  setTextIfExists('landing-slide2-school-entities', formatNumber(entityCount));
  setTextIfExists('landing-slide2-school-campuses', formatNumber(campusCount));
}

function initializeAccessibleTabs() {
  const nav = document.getElementById('sidebar-tabs');
  if (!nav) return;
  nav.setAttribute('role', 'tablist');
  document.querySelectorAll('.nav-tab').forEach(button => {
    const tabId = button.id.replace('tab-btn-', '');
    const pane = document.getElementById(`pane-${tabId}`);
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', `pane-${tabId}`);
    button.setAttribute('aria-selected', button.classList.contains('active') ? 'true' : 'false');
    button.setAttribute('tabindex', button.classList.contains('active') ? '0' : '-1');
    if (pane) {
      pane.setAttribute('role', 'tabpanel');
      pane.setAttribute('aria-labelledby', button.id);
    }
    if (!button.dataset.keyboardBound) {
      button.dataset.keyboardBound = 'true';
      button.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const tabs = [...document.querySelectorAll('.nav-tab')];
        let index = tabs.indexOf(button);
        if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = tabs.length - 1;
        else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
        tabs[index].focus();
        tabs[index].click();
      });
    }
  });
}

function renderSchoolMarket() {
  const status = document.getElementById('school-market-status');
  const kpis = document.getElementById('school-market-kpis');
  if (!status || !kpis) return;

  syncSchoolModeControls();
  if (!schoolMarketState.available) {
    status.className = 'school-market-status error';
    status.textContent = 'School-market data is unavailable. Other dashboard modules remain available.';
    kpis.setAttribute('aria-busy', 'false');
    kpis.innerHTML = '<div class="school-empty-state">Canonical campus files could not be loaded.</div>';
    setHtmlIfExists('school-source-disclosure', '');
    setHtmlIfExists('school-tier-grid', '');
    setHtmlIfExists('school-zone-list', '');
    renderSchoolDirectory();
    syncSchoolMapVisibility(false);
    return;
  }

  const audience = getSchoolAudienceEntities();
  const audienceCampuses = groupSchoolEntitiesByCampus(audience);
  const sensitivitySummary = schoolMarketState.mode === 'sensitivity'
    ? (schoolMarketState.summary?.fee_max_sensitivity || []).find(item => Number(item.threshold_fee_max) === Number(schoolMarketState.cutoff))
    : null;
  const publishedMetrics = schoolMarketState.summary?.bucket_summaries?.[activeLegacyCategoryId]
    || sensitivitySummary
    || {};
  const entityCountDisplay = Number(publishedMetrics?.school_entity_count_all ?? audience.length);
  const campusCountDisplay = Number(publishedMetrics?.campus_count_context ?? audienceCampuses.length);
  const totalEnrollment = Number(publishedMetrics?.students_grades_2_9_expanded ?? sumSchoolEnrollment(audience));
  const eligibleCount = Number(publishedMetrics?.school_entity_count_grade_2_9_positive ?? audience.filter(entity => entity.students_grades_2_9 > 0).length);
  const derivedSources = getSchoolSourceTotals(audience);
  const publishedSources = publishedMetrics?.students_grades_2_9_by_source;
  const sourceTotals = publishedSources ? { udise: Number(publishedSources.udise_backed || 0), estimate: Number(publishedSources.estimated || 0), unknown: 0 } : derivedSources;
  const comparisonMetrics = activeLegacyCitySummary()?.category_metrics?.[activeLegacyCategoryId] || {};
  const reportedEnrollment = firstFiniteNumber(
    comparisonMetrics.reported_students_grade_2_9,
    comparisonMetrics.reported_grade_2_9_students,
    publishedMetrics.reported_students_grade_2_9,
    publishedSources?.reported,
    publishedSources?.udise_backed,
    sourceTotals.udise
  ) || 0;
  const modeledEnrollment = firstFiniteNumber(
    comparisonMetrics.modeled_students_grade_2_9,
    comparisonMetrics.estimated_students_grade_2_9,
    publishedMetrics.modeled_students_grade_2_9,
    publishedSources?.modeled,
    publishedSources?.estimated,
    sourceTotals.estimate
  ) || 0;
  const baselineEnrollment = reportedEnrollment;
  const crossingCount = Number(sensitivitySummary?.fee_range_crossing_entity_count ?? audience.filter(entity => entity.fee_min < schoolMarketState.cutoff && entity.fee_max >= schoolMarketState.cutoff).length);
  const delta = totalEnrollment - baselineEnrollment;
  const deltaText = schoolMarketState.mode === 'sensitivity'
    ? ` · ${delta >= 0 ? '+' : '−'}${Math.abs(delta).toLocaleString('en-IN')} vs selected bucket`
    : '';

  status.className = 'school-market-status ready';
  const bucketNote = ' Annual-fee thresholds are not used; this page uses supplied school buckets only.';
  status.textContent = `${getSchoolModeLabel()}: ${reportedEnrollment.toLocaleString('en-IN')} directly reported Grade 2–9 enrollments across ${entityCountDisplay.toLocaleString('en-IN')} school entities and ${campusCountDisplay.toLocaleString('en-IN')} physical campuses. ${modeledEnrollment.toLocaleString('en-IN')} modeled enrollments are disclosed separately.${schoolMarketState.mode === 'sensitivity' ? ` ${crossingCount.toLocaleString('en-IN')} school fee ranges cross this cutoff.` : bucketNote}`;
  kpis.setAttribute('aria-busy', 'false');
  kpis.innerHTML = `
    <article class="primary"><span>Reported Grade 2–9</span><strong>${reportedEnrollment ? reportedEnrollment.toLocaleString('en-IN') : 'Unavailable'}</strong><small>Primary demand evidence</small></article>
    <article><span>Audience school entities</span><strong>${entityCountDisplay.toLocaleString('en-IN')}</strong><small>${eligibleCount.toLocaleString('en-IN')} with Grade 2–9 evidence</small></article>
    <article><span>Physical campuses</span><strong>${campusCountDisplay.toLocaleString('en-IN')}</strong><small>Partnership and map locations</small></article>
    <article class="modeled"><span>Modeled addition</span><strong>${modeledEnrollment ? `+${modeledEnrollment.toLocaleString('en-IN')}` : 'None shown'}</strong><small>Secondary; not in reported headline</small></article>
  `;

  renderSchoolSourceDisclosure(audience, sourceTotals);
  renderSchoolBoardBreakdown(audience);
  renderSchoolTierGrid(audience);
  renderSchoolZones(audience);
  renderSchoolHierarchyDetail(audience);
  renderSchoolCapacityPlanner();
  renderSchoolPortfolio();
  renderSchoolDirectory();
  rebuildSchoolMapLayers();
  updateSchoolUrlState();
}

function renderSchoolBoardBreakdown(audience) {
  const target = document.getElementById('school-board-grid');
  if (!target) return;
  const grouped = new Map();
  audience.forEach(entity => {
    const boards = Array.isArray(entity.board) ? entity.board : String(entity.board || 'Unknown').split(/[,/]/);
    [...new Set(boards.map(board => String(board).trim().toUpperCase()).filter(Boolean))].forEach(board => {
      if (!grouped.has(board)) grouped.set(board, { entities: new Set(), campuses: new Set(), enrollment: 0 });
      const row = grouped.get(board);
      row.entities.add(entity.entity_id);
      row.campuses.add(entity.campus_id);
      row.enrollment += Number(entity.students_grades_2_9 || 0);
    });
  });
  const rows = [...grouped.entries()].sort((a, b) => b[1].entities.size - a[1].entities.size || a[0].localeCompare(b[0]));
  target.innerHTML = rows.slice(0, 12).map(([board, row]) => `<article><strong>${escapeHTML(board)}</strong><span>${formatNumber(row.entities.size)} entities · ${formatNumber(row.campuses.size)} campuses</span><small>${formatNumber(row.enrollment)} associated enrollment</small></article>`).join('') || '<div class="school-empty-state">No board affiliations reported for this cohort.</div>';
  target.insertAdjacentHTML('beforeend', '<p class="school-method-note">Multi-board entities appear in each applicable board; board rows are not additive.</p>');
}

function syncSchoolModeControls() {
  document.querySelectorAll('.school-mode-btn').forEach(button => {
    if (button.dataset.mode === 'sensitivity') button.hidden = true;
    const active = button.dataset.mode === schoolMarketState.mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-checked', String(active));
  });
  document.getElementById('school-sensitivity-panel')?.classList.toggle('hidden', schoolMarketState.mode !== 'sensitivity');
  document.querySelectorAll('.school-fee-presets button').forEach(button => {
    const active = Number(button.dataset.cutoff) === schoolMarketState.cutoff;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  const custom = document.getElementById('school-custom-cutoff-input');
  if (custom && document.activeElement !== custom) custom.value = (schoolMarketState.cutoff / 100000).toFixed(2);
}

function setSchoolAudienceMode(mode) {
  if (mode !== 'q4') {
    const status = document.getElementById('school-market-status');
    if (status) status.textContent = 'Annual-fee thresholds are not supported. Select a supplied school bucket instead.';
    return;
  }
  clearSchoolLiveEvaluation();
  schoolMarketState.mode = mode;
  renderSchoolMarket();
}

function setSchoolSensitivityCutoff(cutoff) {
  const status = document.getElementById('school-market-status');
  if (status) status.textContent = 'Annual-fee thresholds are not supported because comparable fee amounts are unavailable.';
}

function clearSchoolLiveEvaluation() {
  schoolMarketState.evaluationRequestId += 1;
  schoolMarketState.evaluationData = null;
  if (schoolMarketState.isochroneLayer && map) map.removeLayer(schoolMarketState.isochroneLayer);
  schoolMarketState.isochroneLayer = null;
  const target = document.getElementById('school-candidate-results');
  if (target) target.innerHTML = 'Choose a society-led candidate hex above to evaluate its live drive-time school and residential evidence.';
}

function applyCustomSchoolCutoff() {
  const input = document.getElementById('school-custom-cutoff-input');
  const lakhs = Number(input?.value);
  if (!Number.isFinite(lakhs) || lakhs < 0 || lakhs > 20) {
    input?.setCustomValidity('Enter a value from 0 to 20 lakh.');
    input?.reportValidity();
    return;
  }
  input.setCustomValidity('');
  setSchoolSensitivityCutoff(Math.round(lakhs * 100000));
}

function updateSchoolUrlState() {
  if (!window.history?.replaceState) return;
  const url = new URL(window.location.href);
  url.searchParams.delete('school_view');
  url.searchParams.delete('school_fee');
  window.history.replaceState({}, '', url);
}

function renderSchoolSourceDisclosure(audience, totals) {
  const target = document.getElementById('school-source-disclosure');
  if (!target) return;
  const total = totals.udise + totals.estimate + totals.unknown;
  const width = value => total ? `${(value / total) * 100}%` : '0%';
  const rawAudit = schoolMarketState.audit?.q4 || schoolMarketState.audit?.raw?.q4 || schoolMarketState.summary?.audit?.q4;
  const sensitivityAudit = schoolMarketState.mode === 'sensitivity'
    ? (schoolMarketState.summary?.fee_max_sensitivity || []).find(row => Number(row.threshold_fee_max) === Number(schoolMarketState.cutoff))
    : null;
  const auditText = sensitivityAudit
    ? `${formatNumber(sensitivityAudit.school_entity_count_all || 0)} cutoff-qualified entities · ${formatNumber(sensitivityAudit.school_entity_count_grade_2_9_positive || 0)} grade-positive · ${formatNumber(sensitivityAudit.campus_count_context || 0)} campus locations`
    : rawAudit
      ? `${formatNumber(rawAudit.school_entity_count_all || rawAudit.rows || rawAudit.source_rows || 0)} canonical Premium+ entities · ${formatNumber(rawAudit.school_entity_count_grade_2_9_positive || rawAudit.grade_eligible_rows || rawAudit.eligible_rows || 0)} grade-positive · ${formatNumber(rawAudit.campus_count_context || 0)} campus locations`
      : `${audience.reduce((sum, entity) => sum + entity.source_record_count, 0).toLocaleString('en-IN')} source records represented`;
  target.innerHTML = `
    <div class="school-source-header"><strong>Enrollment provenance</strong><span>${escapeHTML(auditText)}</span></div>
    <div aria-label="Enrollment source composition" class="school-source-bar" role="img">
      <span class="udise" style="width:${width(totals.udise)}"></span>
      <span class="estimate" style="width:${width(totals.estimate)}"></span>
      <span class="unknown" style="width:${width(totals.unknown)}"></span>
    </div>
    <div class="school-source-legend"><span><i class="udise"></i>UDISE-backed ${totals.udise.toLocaleString('en-IN')}</span><span><i class="estimate"></i>Estimated ${totals.estimate.toLocaleString('en-IN')}</span>${totals.unknown ? `<span><i class="unknown"></i>Unknown ${totals.unknown.toLocaleString('en-IN')}</span>` : ''}</div>
  `;
}

function renderSchoolTierGrid(audience) {
  const target = document.getElementById('school-tier-grid');
  if (!target) return;
  const buckets = [
    { key: 'super-premium', label: 'Super-Premium', color: '#7c3aed' },
    { key: 'premium', label: 'Premium', color: '#2563eb' },
    { key: 'affordable', label: 'Affordable', color: '#0891b2' },
    { key: 'budget', label: 'Budget', color: '#64748b' }
  ];
  const tierCards = buckets.map(meta => {
    const rows = schoolMarketState.entities.filter(entity =>
      String(entity.fee_bucket || entity.fee_tier || '').trim().toLowerCase().replaceAll('_', '-') === meta.key
    );
    const enrollment = sumSchoolEnrollment(rows);
    const isActive = legacySchoolCategoryBuckets(activeLegacyCategoryId).has(meta.key);
    return `
      <article class="school-tier-card${isActive ? ' active' : ''}" style="--school-tier-color:${meta.color}">
       <span class="school-tier-dot"></span><div><strong>${meta.label}</strong><small>${isActive ? 'Included in active view' : 'Not included in active view'}</small></div>
       <b>${rows.length.toLocaleString('en-IN')} entities</b><span>${enrollment.toLocaleString('en-IN')} entity-associated enrollment</span>
      </article>`;
  });
  target.innerHTML = tierCards.join('');
}

function schoolPeerThreshold(values, percentile) {
  const sorted = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return 0;
  return sorted[Math.max(0, Math.ceil(percentile * sorted.length) - 1)];
}

function classifyStaticSchoolReadiness(schoolValue, residentialValue, schoolMedian, schoolQ3, residentialMedian, residentialQ3) {
  const schoolTop = schoolValue >= schoolQ3;
  const residentialTop = residentialValue >= residentialQ3;
  const schoolMid = schoolValue >= schoolMedian;
  const residentialMid = residentialValue >= residentialMedian;
  if (schoolTop && residentialTop) return 'A';
  if ((schoolTop && residentialMid) || (residentialTop && schoolMid)) return 'B';
  if (schoolMid && residentialMid) return 'C';
  return 'D';
}

function getStaticSchoolReadiness(kind) {
  const audience = getSchoolAudienceEntities();
  const luxuryCategories = new Set(['luxury', 'super luxury', 'ultra luxury']);
  const societies = (layerData.societies || []).filter(society => luxuryCategories.has(String(society.category || '').trim().toLowerCase()));
  let peers = [];
  if (kind === 'zone') {
    const zoneNames = [...new Set([
      ...audience.map(entity => entity.zone),
      ...societies.map(society => society.zone)
    ].filter(Boolean))];
    peers = zoneNames.map(id => ({
      id,
      school: sumSchoolEnrollment(audience.filter(entity => entity.zone === id)),
      residential: societies.filter(society => society.zone === id).reduce((sum, society) => sum + Number(society.units || 0), 0)
    }));
  } else {
    peers = (layerData.microMarkets?.disjoint_micro_markets || []).map((market, index) => {
      const ids = new Set(market.hex_ids || []);
      return {
        id: String(index),
        school: sumSchoolEnrollment(audience.filter(entity => ids.has(entity.hex_id))),
        residential: societies.filter(society => ids.has(society.hex_id)).reduce((sum, society) => sum + Number(society.units || 0), 0)
      };
    });
  }
  const schoolMedian = schoolPeerThreshold(peers.map(peer => peer.school), 0.5);
  const schoolQ3 = schoolPeerThreshold(peers.map(peer => peer.school), 0.75);
  const residentialMedian = schoolPeerThreshold(peers.map(peer => peer.residential), 0.5);
  const residentialQ3 = schoolPeerThreshold(peers.map(peer => peer.residential), 0.75);
  return new Map(peers.map(peer => [peer.id, {
    ...peer,
    tier: classifyStaticSchoolReadiness(peer.school, peer.residential, schoolMedian, schoolQ3, residentialMedian, residentialQ3),
    thresholds: { schoolMedian, schoolQ3, residentialMedian, residentialQ3 }
  }]));
}

function renderSchoolZones(audience) {
  const target = document.getElementById('school-zone-list');
  if (!target) return;
  const grouped = new Map();
  audience.forEach(campus => {
    const zone = campus.zone || 'Unassigned';
    if (!grouped.has(zone)) grouped.set(zone, []);
    grouped.get(zone).push(campus);
  });
  const rows = [...grouped.entries()].sort((a, b) => sumSchoolEnrollment(b[1]) - sumSchoolEnrollment(a[1]));
  const readiness = getStaticSchoolReadiness('zone');
  if (!rows.length) {
    target.innerHTML = '<div class="school-empty-state">No campuses match this audience view.</div>';
    return;
  }
  target.innerHTML = rows.map(([zone, campuses]) => `
    <button aria-pressed="${schoolMarketState.selectedZone === zone}" class="school-zone-card${schoolMarketState.selectedZone === zone ? ' active' : ''}" data-zone="${escapeHTML(zone)}" type="button">
      <span>${escapeHTML(zone)} <i class="school-static-tier tier-${readiness.get(zone)?.tier?.toLowerCase() || 'd'}">Tier ${readiness.get(zone)?.tier || 'D'}</i></span><strong>${sumSchoolEnrollment(campuses).toLocaleString('en-IN')}</strong><small>${campuses.length.toLocaleString('en-IN')} active-view entities · ${groupSchoolEntitiesByCampus(campuses).length} campuses</small><small>${formatNumber(readiness.get(zone)?.residential || 0)} known residential units · tier uses ${escapeHTML(activeLegacyCategory().label)}</small>
    </button>`).join('');
  target.querySelectorAll('[data-zone]').forEach(button => button.addEventListener('click', () => selectSchoolZone(button.dataset.zone)));
}

function selectSchoolZone(zone) {
  clearSchoolLiveEvaluation();
  schoolMarketState.selectedZone = zone;
  schoolMarketState.selectedMarketIndex = null;
  schoolMarketState.selectedHexId = null;
  renderSchoolMarket();
}

function getSchoolMarketsForZone(zone) {
  const markets = layerData.microMarkets?.disjoint_micro_markets || [];
  return markets.map((market, index) => ({ market, index })).filter(({ market }) =>
    (market.hex_ids || []).some(hexId => getHexPropsById(hexId)?.zone === zone)
  );
}

function selectSchoolMarket(index) {
  clearSchoolLiveEvaluation();
  schoolMarketState.selectedMarketIndex = Number(index);
  schoolMarketState.selectedHexId = null;
  renderSchoolMarket();
  const market = layerData.microMarkets?.disjoint_micro_markets?.[schoolMarketState.selectedMarketIndex];
  if (market?.hex_ids) highlightMarketHexes(market.hex_ids);
}

function getSocietyLedCandidateHexes() {
  const market = layerData.microMarkets?.disjoint_micro_markets?.[schoolMarketState.selectedMarketIndex];
  let ids = market?.hex_ids || [];
  if (!ids.length && schoolMarketState.selectedZone) {
    ids = (layerData.hexes?.features || [])
      .filter(feature => feature.properties?.zone === schoolMarketState.selectedZone)
      .map(feature => feature.properties.hex_id);
  }
  const allowedCategories = new Set(['luxury', 'super luxury', 'ultra luxury']);
  return ids.map(hexId => {
    const props = getHexPropsById(hexId);
    if (!props) return null;
    const societies = (layerData.societies || []).filter(society =>
      society.hex_id === hexId && allowedCategories.has(String(society.category || '').trim().toLowerCase())
    );
    return {
      ...props,
      premium_residential_units: societies.reduce((sum, society) => sum + Number(society.units || 0), 0),
      premium_residential_projects: societies.length
    };
  }).filter(Boolean).sort((a, b) =>
    Number(b.premium_residential_units || 0) - Number(a.premium_residential_units || 0) ||
    Number(b.premium_residential_projects || 0) - Number(a.premium_residential_projects || 0) ||
    String(a.hex_id).localeCompare(String(b.hex_id))
  ).slice(0, 5);
}

function renderSchoolHierarchyDetail(audience) {
  const detail = document.getElementById('school-hierarchy-detail');
  const breadcrumb = document.getElementById('school-market-breadcrumb');
  if (!detail || !breadcrumb) return;
  if (!schoolMarketState.selectedZone) {
    detail.classList.add('hidden');
    breadcrumb.textContent = legacyCityLabel();
    return;
  }

  const marketRows = getSchoolMarketsForZone(schoolMarketState.selectedZone);
  const marketReadiness = getStaticSchoolReadiness('market');
  const selectedMarket = layerData.microMarkets?.disjoint_micro_markets?.[schoolMarketState.selectedMarketIndex];
  const selectedName = selectedMarket ? `${getMarketCoreAreaName(selectedMarket.hex_ids)} market` : '';
  breadcrumb.innerHTML = `<button type="button" onclick="clearSchoolGeography()">${escapeHTML(legacyCityLabel())}</button><span>/</span><button type="button" onclick="selectSchoolZone('${escapeHTML(schoolMarketState.selectedZone).replace(/'/g, "\\'")}')">${escapeHTML(schoolMarketState.selectedZone)}</button>${selectedName ? `<span>/</span><span>${escapeHTML(selectedName)}</span>` : ''}`;

  const marketButtons = marketRows.length ? marketRows.map(({ market, index }) => {
    const name = getMarketCoreAreaName(market.hex_ids);
    const schoolRows = audience.filter(campus => market.hex_ids?.includes(campus.hex_id));
    const zones = new Set((market.hex_ids || []).map(id => getHexPropsById(id)?.zone).filter(Boolean));
    const peer = marketReadiness.get(String(index));
    return `<button aria-pressed="${schoolMarketState.selectedMarketIndex === index}" class="school-market-card${schoolMarketState.selectedMarketIndex === index ? ' active' : ''}" onclick="selectSchoolMarket(${index})" type="button"><strong>${escapeHTML(name)} <i class="school-static-tier tier-${peer?.tier?.toLowerCase() || 'd'}">Tier ${peer?.tier || 'D'}</i></strong><span>${schoolRows.length} entities · ${groupSchoolEntitiesByCampus(schoolRows).length} campuses · ${sumSchoolEnrollment(schoolRows).toLocaleString('en-IN')} entity-associated enrollment</span><small>${zones.size > 1 ? `Spans ${zones.size} zones` : schoolMarketState.selectedZone} · ${escapeHTML(activeLegacyCategory().label)} ${formatNumber(peer?.school || 0)} enrollment · ${formatNumber(peer?.residential || 0)} known residential units</small></button>`;
  }).join('') : '<div class="school-empty-state">No defined micro-market intersects this zone.</div>';

  const candidates = getSocietyLedCandidateHexes();
  const candidateHtml = schoolMarketState.selectedMarketIndex !== null || !marketRows.length ? `
    <div class="school-candidate-list"><h4>Top five residential-project candidate areas</h4>${candidates.map((hex, index) => `
      <button class="school-candidate-card${schoolMarketState.selectedHexId === hex.hex_id ? ' active' : ''}" onclick="selectSchoolCandidateHex('${escapeHTML(hex.hex_id)}')" type="button">
       <span>#${index + 1}</span><div><strong>${escapeHTML(hex.name || hex.hex_id)}</strong><small>${formatNumber(hex.premium_residential_units || 0)} known units · ${formatNumber(hex.premium_residential_projects || 0)} residential projects</small></div><em>${schoolMarketState.selectedHexId === hex.hex_id ? 'Selected' : 'Evaluate'}</em>
      </button>`).join('')}</div>` : '';

  detail.classList.remove('hidden');
  detail.innerHTML = `<div class="school-market-list"><h4>Intersecting micro-markets</h4>${marketButtons}</div>${candidateHtml}`;
}

function clearSchoolGeography() {
  clearSchoolLiveEvaluation();
  schoolMarketState.selectedZone = null;
  schoolMarketState.selectedMarketIndex = null;
  schoolMarketState.selectedHexId = null;
  schoolMarketState.evaluationData = null;
  resetHexHighlights();
  renderSchoolMarket();
}

function selectSchoolCandidateHex(hexId) {
  clearSchoolLiveEvaluation();
  schoolMarketState.selectedHexId = hexId;
  highlightSingleHex(hexId);
  renderSchoolHierarchyDetail(getSchoolAudienceEntities());
  renderSchoolCandidateEvaluation();
  document.getElementById('school-candidate-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSchoolCandidateEvaluation() {
  const target = document.getElementById('school-candidate-results');
  const hex = getHexPropsById(schoolMarketState.selectedHexId);
  if (!target || !hex) return;
  target.innerHTML = `
    <div class="school-candidate-selected"><div><strong>${escapeHTML(hex.name || hex.hex_id)}</strong><span>Society-led candidate · live routing not yet evaluated</span></div><span class="school-readiness pending">Readiness pending</span></div>
    <div aria-label="Drive time" class="school-drive-time-options">
      ${[15, 30, 45, 60].map(minutes => `<button aria-pressed="${schoolMarketState.evaluationMinutes === minutes}" class="${schoolMarketState.evaluationMinutes === minutes ? 'active' : ''}" onclick="setSchoolEvaluationMinutes(${minutes})" type="button">${minutes} min</button>`).join('')}
    </div>
    <button class="school-evaluate-btn" onclick="evaluateSchoolCandidate('${escapeHTML(hex.hex_id)}', ${schoolMarketState.evaluationMinutes})" type="button">Evaluate live drive-time evidence</button>
    <p class="school-method-note">The API counts campuses physically reachable inside the isochrone and reports residential evidence separately. It does not allocate students to this hex.</p>`;
}

function setSchoolEvaluationMinutes(minutes) {
  schoolMarketState.evaluationMinutes = Number(minutes);
  renderSchoolCandidateEvaluation();
}

function getSchoolPlannerScopeCampuses() {
  let campuses = getSchoolAudienceEntities();
  const market = layerData.microMarkets?.disjoint_micro_markets?.[schoolMarketState.selectedMarketIndex];
  if (market?.hex_ids) {
    campuses = campuses.filter(campus => market.hex_ids.includes(campus.hex_id));
  } else if (schoolMarketState.selectedZone) {
    campuses = campuses.filter(campus => campus.zone === schoolMarketState.selectedZone);
  }
  return campuses;
}

function getSchoolCapacityInputs() {
  return {
    capacity: Math.max(1, Number(document.getElementById('school-center-capacity')?.value || 200)),
    utilizationPct: Math.min(100, Math.max(1, Number(document.getElementById('school-target-utilization')?.value || 80)))
  };
}

function setSchoolCaptureRate(rate) {
  schoolMarketState.captureRate = Number(rate);
  document.querySelectorAll('.school-capture-presets button').forEach(button => {
    const active = Number(button.dataset.capture) === schoolMarketState.captureRate;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  renderSchoolCapacityPlanner();
}

function renderSchoolCapacityPlanner() {
  const target = document.getElementById('school-planner-results');
  if (!target || !schoolMarketState.available) return;
  const { capacity, utilizationPct: utilization } = getSchoolCapacityInputs();
  const campuses = getSchoolPlannerScopeCampuses();
  const total = sumSchoolEnrollment(campuses);
  const captured = total * (schoolMarketState.captureRate / 100);
  const fullCenters = Math.floor(captured / capacity);
  const residual = captured - fullCenters * capacity;
  const minimumRequired = captured ? Math.ceil(captured / capacity) : 0;
  const maximumAtTarget = Math.floor(captured / (capacity * utilization / 100));
  const utilizationAtMinimum = minimumRequired ? (captured / (minimumRequired * capacity)) * 100 : 0;
  const belowTarget = minimumRequired > 0 && utilizationAtMinimum < utilization;
  const theoretical = total ? Math.ceil(total / capacity) : 0;
  const market = layerData.microMarkets?.disjoint_micro_markets?.[schoolMarketState.selectedMarketIndex];
  const scope = market ? getMarketCoreAreaName(market.hex_ids) : (schoolMarketState.selectedZone || legacyCityLabel());
  setTextIfExists('school-capacity-scope', `${scope} · ${getSchoolModeLabel()}`);
  target.innerHTML = `
    <article><span>Captured enrollment scenario (${schoolMarketState.captureRate}%)</span><strong>${formatNumber(captured, 1)}</strong></article>
    <article><span>Full ${capacity}-seat centers</span><strong>${fullCenters.toLocaleString('en-IN')}</strong><small>${formatNumber(residual, 1)} residual students</small></article>
    <article><span>Minimum centers required</span><strong>${minimumRequired.toLocaleString('en-IN')}</strong><small>${utilizationAtMinimum.toFixed(1)}% utilization · ${belowTarget ? 'below target' : 'at/above target'}</small></article>
    <article><span>Maximum supportable at ${utilization}%</span><strong>${maximumAtTarget.toLocaleString('en-IN')}</strong><small>floor(captured ÷ effective capacity)</small></article>
    <article><span>100% theoretical ceiling</span><strong>${theoretical.toLocaleString('en-IN')}</strong><small>Not a forecast</small></article>`;
}

function rebuildSchoolMapLayers() {
  if (!map || !schoolMarketState.available) return;
  if (!schoolMarketState.allHeatLayer) {
    const points = schoolMarketState.campuses.map(campus => [
      campus.lat, campus.lon, Math.max(0.2, Math.min(1, Math.log10(campus.students_grades_2_9 + 10) / 3))
    ]);
    schoolMarketState.allHeatLayer = L.heatLayer(points, { radius: 18, blur: 22, minOpacity: 0.2, gradient: { 0.2: '#bfdbfe', 0.55: '#38bdf8', 1: '#0f172a' } });
  }
  [schoolMarketState.q4ContextLayer, schoolMarketState.audienceMarkerLayer].forEach(layer => {
    if (layer && map.hasLayer(layer)) map.removeLayer(layer);
  });

  const q4 = getQ4SchoolEntities();
  if (schoolMarketState.mode === 'sensitivity') {
    schoolMarketState.q4ContextLayer = L.layerGroup(groupSchoolEntitiesByCampus(q4).map(campus => makeSchoolMarker(campus, true)));
  } else {
    schoolMarketState.q4ContextLayer = null;
  }
  schoolMarketState.audienceMarkerLayer = L.layerGroup(groupSchoolEntitiesByCampus(getSchoolAudienceEntities()).map(campus => makeSchoolMarker(campus, false)));
  syncSchoolMapVisibility(activeTab === 'schoolmarket');
}

function makeSchoolMarker(campus, muted) {
  const markerEntities = campus.audience_entities || [];
  const meta = getSchoolSubquartileMeta(markerEntities[0]?.quartile_analysis_2 || campus.quartile_analysis_2);
  const sensitivity = schoolMarketState.mode === 'sensitivity' && !muted;
  const marker = L.circleMarker([campus.lat, campus.lon], {
    radius: sensitivity ? 6 : 5,
    color: muted ? '#94a3b8' : '#ffffff',
    fillColor: sensitivity ? '#ea580c' : meta.color,
    fillOpacity: muted ? 0.28 : 0.88,
    opacity: muted ? 0.5 : 1,
    weight: sensitivity ? 2.5 : 1.5,
    pane: 'overlayPane'
  });
  marker.bindTooltip(`${escapeHTML(campus.name)} · ${formatNumber(campus.audience_enrollment ?? campus.students_grades_2_9)} grade 2–9 · ${campus.audience_entity_count || campus.entity_count || 1} entit${(campus.audience_entity_count || campus.entity_count || 1) === 1 ? 'y' : 'ies'}`, { sticky: true });
  marker.on('click', () => showSchoolCampusDetails(campus.campus_id));
  marker.on('add', () => {
    const path = marker.getElement?.();
    if (!path) return;
    path.setAttribute('tabindex', '0');
    path.setAttribute('role', 'button');
    path.setAttribute('aria-label', `${campus.name}, ${campus.audience_entity_count || campus.entity_count || 1} school entities, ${campus.audience_enrollment ?? campus.students_grades_2_9} grade 2 to 9 students`);
    path.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        showSchoolCampusDetails(campus.campus_id);
      }
    });
  });
  return marker;
}

function syncSchoolMapVisibility(visible) {
  if (!map) return;
  const layers = [
    schoolMarketState.allHeatLayer,
    schoolMarketState.q4ContextLayer,
    schoolMarketState.audienceMarkerLayer,
    schoolMarketState.directoryFocusLayer
  ];
  layers.forEach(layer => {
    if (!layer) return;
    if (visible && !map.hasLayer(layer)) layer.addTo(map);
    if (!visible && map.hasLayer(layer)) map.removeLayer(layer);
  });
  document.getElementById('school-map-legend')?.classList.toggle('hidden', !visible || !schoolMarketState.available);
  document.getElementById('hex-legend')?.classList.toggle('hidden', Boolean(visible));
  const sensitivityRow = document.getElementById('school-sensitivity-legend-row');
  sensitivityRow?.classList.toggle('hidden', schoolMarketState.mode !== 'sensitivity');
  setTextIfExists('school-sensitivity-legend-label', `fee_max ≥ ${formatSchoolFee(schoolMarketState.cutoff)}`);
}

function showSchoolCampusDetails(campusId) {
  const campus = schoolMarketState.campuses.find(item => String(item.campus_id) === String(campusId));
  const panel = document.getElementById('school-market-details-panel');
  if (!campus || !panel) return;
  schoolMarketState.selectedCampusId = campus.campus_id;
  const entities = schoolMarketState.entities.filter(entity => String(entity.campus_id) === String(campusId));
  const audienceIds = new Set(getSchoolAudienceEntities().map(entity => entity.entity_id));
  const audienceEntities = entities.filter(entity => audienceIds.has(entity.entity_id));
  const representative = audienceEntities[0] || entities[0] || campus;
  const meta = getSchoolSubquartileMeta(representative.quartile_analysis_2);
  const feeRange = campus.fee_tier || campus.fee_bucket || 'Unavailable';
  const entityEnrollment = sumSchoolEnrollment(audienceEntities.length ? audienceEntities : entities);
  const entityRows = entities.map(entity => `<li><strong>${escapeHTML(entity.name)}</strong><span>${formatNumber(entity.students_grades_2_9)} students · ${escapeHTML(entity.fee_tier || entity.fee_bucket || 'Bucket unavailable')} · ${entity.enrollment_source === 'udise' ? 'UDISE-backed' : entity.enrollment_source === 'estimate' ? 'Estimated' : 'Unknown source'}</span></li>`).join('');
  const url = /^https?:\/\//i.test(campus.url || '') ? `<a class="notion-link" href="${escapeHTML(campus.url)}" rel="noopener noreferrer" target="_blank">Open source ↗</a>` : 'No source link';
  renderStandardDetails(panel, {
    title: campus.name,
    titleId: 'school-campus-details-title',
    badge: `${meta.label} · ${meta.key}`,
    onClose: 'clearSchoolCampusDetails()',
    kpis: [
      { value: formatNumber(entityEnrollment), label: audienceEntities.length ? `${activeLegacyCategory().label} enrollment` : 'Campus enrollment (outside audience)' },
      { value: formatNumber(entities.length), label: 'Canonical entities at campus' },
      { value: feeRange, label: 'Supplied fee bucket' },
      { value: campus.zone, label: 'Zone' }
    ],
    metadata: {
      'Board(s)': Array.isArray(campus.board) ? campus.board.join(', ') : campus.board,
      'Hex': campus.hex_id || 'Not assigned',
      'Geocode confidence': campus.google_geocode_confidence != null ? `${(Number(campus.google_geocode_confidence) * 100).toFixed(0)}%` : 'Not reported',
      'Audit lineage': `${campus.campus_enrollment_rule || campus.dedupe_status || 'Canonical campus'} · ${entities.reduce((sum, entity) => sum + entity.source_record_count, 0)} source record(s)`
    },
    mainContent: `<div class="notion-block info-block"><strong>Evidence boundary</strong><p>School entities are grouped at this physical campus marker. Enrollment is not assigned to a residential hex or proposed center.</p><p>${url}</p></div><h4 class="notion-heading-4">Canonical entities at this campus</h4><ul class="school-evaluation-campus-list">${entityRows || '<li>No linked entity record.</li>'}</ul>`
  });
  showDetailsPanel('school-market-details-panel');
  renderSchoolDirectory();
  requestAnimationFrame(() => document.getElementById('school-campus-details-title')?.focus?.());
}

function clearSchoolCampusDetails() {
  document.getElementById('school-market-details-panel')?.classList.add('hidden');
  schoolMarketState.selectedCampusId = null;
  renderSchoolDirectory();
  updateRightPanelVisibility();
}

async function evaluateSchoolCandidate(hexId, minutes = 30) {
  const hex = getHexPropsById(hexId);
  const target = document.getElementById('school-candidate-results');
  if (!hex || !target) return;
  const lat = Number(hex.centroid_lat);
  const lon = Number(hex.centroid_lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    target.innerHTML = '<div class="school-evaluation-error">This candidate has no valid centroid coordinates.</div>';
    return;
  }
  if (!isValidCatchmentGoogleApiKey(getCatchmentGoogleApiKey())) {
    switchTab('catchment');
    setCatchmentKeyStatus('Connect a restricted Google Maps key before running a live school catchment.', 'error');
    document.getElementById('catchment-google-api-key')?.focus();
    return;
  }
  const requestId = ++schoolMarketState.evaluationRequestId;
  schoolMarketState.evaluationMinutes = Number(minutes);
  target.setAttribute('aria-busy', 'true');
  target.innerHTML = `<div class="school-evaluation-loading"><span class="spinner"></span><strong>Computing ${minutes}-minute live drive catchment…</strong><small>Requesting schema v2 school and residential ledgers.</small></div>`;
  const { capacity, utilizationPct } = getSchoolCapacityInputs();
  const params = new URLSearchParams({
    schema_version: '2', city: activeLegacyCityId, category: activeLegacyCategoryId,
    lat: String(lat), lon: String(lon), travel_time_mins: String(minutes),
    travel_mode: 'DRIVE', live_traffic: 'true', catchment_mode: 'time',
    capture_rates: String(schoolMarketState.captureRate / 100),
    center_capacity: String(capacity), target_utilization: String(utilizationPct / 100)
  });
  try {
    const response = await fetch(`/api/catchment?${params.toString()}`, catchmentRequestOptions());
    const payload = await response.json();
    if (requestId !== schoolMarketState.evaluationRequestId) return;
    if (!response.ok || payload.status === 'error') throw new Error(payload.message || `HTTP ${response.status}`);
    schoolMarketState.evaluationData = payload;
    renderSchoolEvaluationResult(payload, hex, minutes);
  } catch (error) {
    if (requestId !== schoolMarketState.evaluationRequestId) return;
    target.removeAttribute('aria-busy');
    target.innerHTML = `<div class="school-evaluation-error"><strong>Live evaluation unavailable</strong><span>${escapeHTML(error.message || 'The catchment service could not be reached.')}</span><button onclick="evaluateSchoolCandidate('${escapeHTML(hexId)}', ${minutes})" type="button">Retry</button></div>`;
  }
}

function renderSchoolEvaluationResult(payload, hex, minutes) {
  const target = document.getElementById('school-candidate-results');
  if (!target) return;
  const root = payload.data || payload;
  const school = root.school_market || root.schoolMarket || null;
  const residential = root.residential_market || root.residentialMarket || {};
  if (!school) {
    target.removeAttribute('aria-busy');
    target.innerHTML = '<div class="school-evaluation-error"><strong>Routing completed without school schema v2 evidence.</strong><span>The previous result was not substituted with legacy or synthetic school metrics.</span></div>';
    renderSchoolIsochroneGeometry(root, minutes);
    return;
  }

  const sensitivityItems = school.absolute_fee_sensitivity?.items || [];
  const sensitivityItem = sensitivityItems.find(item => Number(item.threshold_inr) === Number(schoolMarketState.cutoff));
  const activeAggregate = schoolMarketState.mode === 'sensitivity' && sensitivityItem ? sensitivityItem.reachable : (school.reachable || {});
  const campuses = schoolMarketState.mode === 'sensitivity' ? (sensitivityItem?.campuses || []) : (school.campuses || []);
  const excluded = schoolMarketState.mode === 'sensitivity' ? [] : (school.excluded_non_adjacent_entities || []);
  const enrollment = Number(activeAggregate.grade_2_9_enrollment ?? 0);
  const entityCount = Number(activeAggregate.entity_count ?? 0);
  const campusCount = Number(activeAggregate.campus_count ?? campuses.length);
  const residentialInside = residential.inside_isochrone || residential;
  const knownUnits = Number(residentialInside.known_units ?? residentialInside.direct_total_units ?? residentialInside.total_units ?? residentialInside.units ?? 0);
  const projectCount = Number(residentialInside.project_count ?? residentialInside.residential_project_count ?? residentialInside.society_count ?? 0);
  const readiness = root.readiness?.tier || root.readiness_tier || school.readiness_tier || null;
  const routingMethod = root.routing_method || payload.routing_method || 'live routing';
  const source = activeAggregate.source_composition || {};
  const { capacity: liveCapacity, utilizationPct: liveTargetPct } = getSchoolCapacityInputs();
  const capture = enrollment * (schoolMarketState.captureRate / 100);
  const liveFullCenters = Math.floor(capture / liveCapacity);
  const liveResidual = capture - liveFullCenters * liveCapacity;
  const liveMinimumRequired = capture ? Math.ceil(capture / liveCapacity) : 0;
  const liveMaximumAtTarget = Math.floor(capture / (liveCapacity * liveTargetPct / 100));
  const liveUtilizationAtMinimum = liveMinimumRequired ? (capture / (liveMinimumRequired * liveCapacity)) * 100 : 0;
  const liveBelowTarget = liveMinimumRequired > 0 && liveUtilizationAtMinimum < liveTargetPct;
  const campusRows = campuses.slice(0, 12).map(item => {
    const campus = typeof item === 'string' ? schoolMarketState.campuses.find(row => row.campus_id === item) : item;
    return campus ? `<li><strong>${escapeHTML(campus.name || campus.campus_name || 'Campus')}</strong><span>${formatNumber(campus.grade_2_9_enrollment ?? campus.students_grades_2_9 ?? 0)} students · ${formatNumber(campus.entity_count || campus.entity_ids?.length || 0)} entities</span></li>` : '';
  }).join('');
  const readinessLabel = readiness ? `Tier ${escapeHTML(String(readiness))}` : 'Evidence loaded · no synthetic score';
  const sourceUdise = Number(source.udise_backed?.enrollment ?? source.udise?.enrollment ?? 0);
  const sourceEstimated = Number(source.estimated?.enrollment ?? source.estimate?.enrollment ?? 0);
  const portfolioEntities = schoolMarketState.mode === 'sensitivity' ? (sensitivityItem?.entities || []) : (school.entities || []);
  const portfolioKey = `${hex.hex_id}-${minutes}-${schoolMarketState.mode}-${schoolMarketState.mode === 'sensitivity' ? schoolMarketState.cutoff : 'q4'}`;
  const alreadyAdded = schoolMarketState.portfolioCenters.some(center => center.key === portfolioKey);
  const canAddToPortfolio = portfolioEntities.length > 0 && schoolMarketState.portfolioCenters.length < 10 && !alreadyAdded;
  target.removeAttribute('aria-busy');
  target.innerHTML = `
    <div class="school-candidate-selected"><div><strong>${escapeHTML(hex.name || hex.hex_id)}</strong><span>${minutes} min · ${escapeHTML(routingMethod)} · live traffic requested · ${escapeHTML(getSchoolModeLabel())}</span></div><span class="school-readiness${readiness ? ` tier-${escapeHTML(String(readiness).toLowerCase())}` : ''}">${readinessLabel}</span></div>
    <div class="school-evaluation-grid"><article><span>Reachable entity-associated enrollment</span><strong>${enrollment.toLocaleString('en-IN')}</strong><small>${entityCount} entities · ${campusCount} unique campuses</small></article><article><span>Known residential units</span><strong>${knownUnits.toLocaleString('en-IN')}</strong><small>${projectCount.toLocaleString('en-IN')} named residential projects</small></article><article><span>Enrollment provenance</span><strong>${formatNumber(sourceUdise)}</strong><small>Directly reported · modeled addition kept separate</small></article><article><span>${schoolMarketState.captureRate}% capacity scenario</span><strong>${liveMinimumRequired} min / ${liveMaximumAtTarget} max@${liveTargetPct}%</strong><small>${liveFullCenters} packed full at ${formatNumber(liveCapacity)} seats · ${formatNumber(liveResidual, 1)} residual · ${liveUtilizationAtMinimum.toFixed(1)}% at minimum${liveBelowTarget ? ' · below target' : ''}</small></article></div>
    <button class="school-portfolio-add" ${canAddToPortfolio ? '' : 'disabled'} onclick="addSchoolEvaluationToPortfolio()" type="button">${canAddToPortfolio ? 'Add evaluated center to portfolio' : (alreadyAdded ? 'Already in portfolio' : schoolMarketState.portfolioCenters.length >= 10 ? 'Portfolio limit reached' : 'Sensitivity entity list unavailable')}</button>
    <details open><summary>${schoolMarketState.mode === 'sensitivity' ? `Absolute-fee sensitivity campuses (${campuses.length})` : `Included reachable campuses (${campuses.length})`}</summary><ul class="school-evaluation-campus-list">${campusRows || `<li>${schoolMarketState.mode === 'sensitivity' ? 'No qualifying threshold campus list was returned; Q4 campuses are not substituted.' : 'No qualifying campus returned.'}</li>`}</ul></details>
    <details><summary>Excluded non-adjacent ${schoolMarketState.mode === 'sensitivity' ? 'fee-cohort' : 'Q4'} entities (${excluded.length})</summary><p class="school-method-note">These entities fall inside the travel polygon but outside the declared origin-plus-adjacent-zone rule.</p></details>
    <div class="school-drive-time-options">${[15, 30, 45, 60].map(value => `<button aria-pressed="${minutes === value}" class="${minutes === value ? 'active' : ''}" onclick="evaluateSchoolCandidate('${escapeHTML(hex.hex_id)}', ${value})" type="button">${value} min</button>`).join('')}</div>`;
  renderSchoolIsochroneGeometry(root, minutes);
}

function renderSchoolIsochroneGeometry(data, minutes) {
  if (!map) return;
  if (schoolMarketState.isochroneLayer) {
    map.removeLayer(schoolMarketState.isochroneLayer);
    schoolMarketState.isochroneLayer = null;
  }
  const geometries = data.isochrone_geometries || data.isochrones || {};
  const geometry = geometries[String(minutes)] || data.isochrone_geometry || data.geometry;
  if (!geometry) return;
  schoolMarketState.isochroneLayer = L.geoJSON(geometry, {
    style: { color: '#ea580c', fillColor: '#fb923c', fillOpacity: 0.14, opacity: 0.95, weight: 3 }
  }).addTo(map);
  const bounds = schoolMarketState.isochroneLayer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [28, 28] });
}

function getPortfolioEntitiesFromEvaluation() {
  const payload = schoolMarketState.evaluationData;
  const root = payload?.data || payload || {};
  const school = root.school_market || root.schoolMarket || {};
  if (schoolMarketState.mode === 'sensitivity') {
    const item = (school.absolute_fee_sensitivity?.items || []).find(row => Number(row.threshold_inr) === Number(schoolMarketState.cutoff));
    return item?.entities || [];
  }
  return school.entities || [];
}

function addSchoolEvaluationToPortfolio() {
  if (!schoolMarketState.evaluationData || !schoolMarketState.selectedHexId || schoolMarketState.portfolioCenters.length >= 10) return;
  const entities = getPortfolioEntitiesFromEvaluation();
  if (!entities.length) return;
  const hex = getHexPropsById(schoolMarketState.selectedHexId) || {};
  const evaluationRoot = schoolMarketState.evaluationData?.data || schoolMarketState.evaluationData || {};
  const evaluationSchool = evaluationRoot.school_market || {};
  const evaluationSensitivity = (evaluationSchool.absolute_fee_sensitivity?.items || []).find(row => Number(row.threshold_inr) === Number(schoolMarketState.cutoff));
  const evaluationAggregate = schoolMarketState.mode === 'sensitivity' ? (evaluationSensitivity?.reachable || {}) : (evaluationSchool.reachable || {});
  const evaluationCohort = schoolMarketState.mode === 'sensitivity' ? evaluationSensitivity?.cohort : evaluationSchool.cohort;
  const evaluationResidential = evaluationRoot.residential_market?.inside_isochrone || {};
  const key = `${schoolMarketState.selectedHexId}-${schoolMarketState.evaluationMinutes}-${schoolMarketState.mode}-${schoolMarketState.mode === 'sensitivity' ? schoolMarketState.cutoff : 'q4'}`;
  if (schoolMarketState.portfolioCenters.some(center => center.key === key)) return;
  schoolMarketState.portfolioCenters.push({
    key,
    center_id: key,
    label: hex.name || schoolMarketState.selectedHexId,
    minutes: schoolMarketState.evaluationMinutes,
    audience: getSchoolModeLabel(),
    reachable_enrollment: Number(evaluationAggregate.grade_2_9_enrollment || 0),
    residential_units: Number(evaluationResidential.known_units ?? evaluationResidential.direct_total_units ?? evaluationResidential.total_units ?? evaluationResidential.units ?? 0),
    center_result: { center_id: key, school_market: { cohort: evaluationCohort, entities } }
  });
  schoolMarketState.portfolioResult = null;
  renderSchoolPortfolio();
  analyzeSchoolPortfolio();
}

function removeSchoolPortfolioCenter(index) {
  schoolMarketState.portfolioCenters.splice(Number(index), 1);
  schoolMarketState.portfolioResult = null;
  renderSchoolPortfolio();
  if (schoolMarketState.portfolioCenters.length) analyzeSchoolPortfolio();
}

function moveSchoolPortfolioCenter(index, delta) {
  const from = Number(index);
  const to = from + Number(delta);
  if (from < 0 || to < 0 || from >= schoolMarketState.portfolioCenters.length || to >= schoolMarketState.portfolioCenters.length) return;
  const [item] = schoolMarketState.portfolioCenters.splice(from, 1);
  schoolMarketState.portfolioCenters.splice(to, 0, item);
  schoolMarketState.portfolioResult = null;
  renderSchoolPortfolio();
  analyzeSchoolPortfolio();
}

function renderSchoolPortfolio() {
  const list = document.getElementById('school-portfolio-list');
  const results = document.getElementById('school-portfolio-results');
  if (!list || !results) return;
  setTextIfExists('school-portfolio-count', `${schoolMarketState.portfolioCenters.length} / 10 centers`);
  if (!schoolMarketState.portfolioCenters.length) {
    list.innerHTML = '<div class="school-empty-state">Evaluate a candidate and add it to begin.</div>';
    results.innerHTML = '';
    return;
  }
  const rankedCenters = [...schoolMarketState.portfolioCenters].sort((a, b) =>
    Number(b.reachable_enrollment || 0) - Number(a.reachable_enrollment || 0) ||
    Number(b.residential_units || 0) - Number(a.residential_units || 0) ||
    String(a.label).localeCompare(String(b.label))
  );
  const rankingHtml = `<div class="school-portfolio-ranking"><h4>Evaluated candidate ranking</h4>${rankedCenters.map((center, index) => `<div><span>#${index + 1} ${escapeHTML(center.label)}</span><b>${formatNumber(center.reachable_enrollment)} entity-associated enrollment · ${formatNumber(center.residential_units)} known units</b></div>`).join('')}<small>Sorted by reachable active-cohort enrollment, then known residential units. No weighted score.</small></div><h4 class="school-portfolio-order-heading">Chosen launch order</h4>`;
  list.innerHTML = rankingHtml + schoolMarketState.portfolioCenters.map((center, index) => `
    <article class="school-portfolio-item"><span class="school-portfolio-order">${index + 1}</span><div><strong>${escapeHTML(center.label)}</strong><small>${center.minutes} min · ${escapeHTML(center.audience)}</small></div><div class="school-portfolio-actions"><button aria-label="Move ${escapeHTML(center.label)} earlier" ${index === 0 ? 'disabled' : ''} onclick="moveSchoolPortfolioCenter(${index}, -1)" type="button">↑</button><button aria-label="Move ${escapeHTML(center.label)} later" ${index === schoolMarketState.portfolioCenters.length - 1 ? 'disabled' : ''} onclick="moveSchoolPortfolioCenter(${index}, 1)" type="button">↓</button><button aria-label="Remove ${escapeHTML(center.label)}" onclick="removeSchoolPortfolioCenter(${index})" type="button">×</button></div></article>`).join('');
  if (schoolMarketState.portfolioLoading) {
    results.innerHTML = '<div class="school-evaluation-loading"><span class="spinner"></span><strong>Reconciling unique portfolio evidence…</strong></div>';
    return;
  }
  if (!schoolMarketState.portfolioResult) {
    results.innerHTML = '<button class="school-evaluate-btn" onclick="analyzeSchoolPortfolio()" type="button">Calculate unique portfolio evidence</button>';
    return;
  }
  const portfolio = schoolMarketState.portfolioResult;
  if (portfolio.error) {
    results.innerHTML = `<div class="school-evaluation-error"><strong>Portfolio analysis unavailable</strong><span>${escapeHTML(portfolio.error)}</span><button onclick="analyzeSchoolPortfolio()" type="button">Retry</button></div>`;
    return;
  }
  const incremental = portfolio.incremental_by_request_order || [];
  const pairwise = portfolio.pairwise_overlap || [];
  results.innerHTML = `
    <div class="school-evaluation-grid"><article><span>Unique reachable entities</span><strong>${formatNumber(portfolio.unique_reachable_entity_count || 0)}</strong></article><article><span>Unique physical campuses</span><strong>${formatNumber(portfolio.unique_reachable_campus_count || 0)}</strong></article><article><span>Unique grade 2–9 enrollment</span><strong>${formatNumber(portfolio.unique_reachable_grade_2_9_enrollment || 0)}</strong></article><article><span>Portfolio centers</span><strong>${formatNumber(portfolio.center_count || 0)}</strong><small>Order controls incremental evidence</small></article></div>
    <div class="school-portfolio-table"><strong>Incremental evidence by chosen order</strong>${incremental.map((row, index) => `<div><span>${index + 1}. ${escapeHTML(schoolMarketState.portfolioCenters[index]?.label || row.center_id)}</span><b>+${formatNumber(row.incremental_entity_count || 0)} entities · +${formatNumber(row.incremental_campus_count || 0)} campuses · +${formatNumber(row.incremental_grade_2_9_enrollment || 0)} students</b></div>`).join('')}</div>
    <details><summary>Pairwise overlap (${pairwise.length})</summary><div class="school-portfolio-table">${pairwise.map(row => `<div><span>${escapeHTML(row.center_a)} ↔ ${escapeHTML(row.center_b)}</span><b>${formatNumber(row.shared_entity_count || 0)} entities · ${formatNumber(row.shared_campus_count || 0)} campuses · ${formatNumber(row.shared_grade_2_9_enrollment || 0)} students</b></div>`).join('') || '<div>No center pair yet.</div>'}</div></details>`;
}

async function analyzeSchoolPortfolio() {
  if (!schoolMarketState.portfolioCenters.length || schoolMarketState.portfolioLoading) return;
  schoolMarketState.portfolioLoading = true;
  renderSchoolPortfolio();
  const { capacity, utilizationPct } = getSchoolCapacityInputs();
  try {
    const response = await fetch('/api/catchment', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        city: activeLegacyCityId,
        category: activeLegacyCategoryId,
        center_results: schoolMarketState.portfolioCenters.map(center => center.center_result),
        capture_rates: [0.05, 0.1, 0.2],
        center_capacity: capacity,
        target_utilization: utilizationPct / 100
      })
    });
    const payload = await response.json();
    if (!response.ok || payload.status === 'error') throw new Error(payload.error?.message || payload.message || `HTTP ${response.status}`);
    schoolMarketState.portfolioResult = payload.portfolio || payload.data?.portfolio || null;
  } catch (error) {
    schoolMarketState.portfolioResult = { error: error.message || 'Portfolio service unavailable' };
  } finally {
    schoolMarketState.portfolioLoading = false;
  }
  if (schoolMarketState.portfolioResult?.error) {
    const results = document.getElementById('school-portfolio-results');
    if (results) results.innerHTML = `<div class="school-evaluation-error"><strong>Portfolio analysis unavailable</strong><span>${escapeHTML(schoolMarketState.portfolioResult.error)}</span><button onclick="analyzeSchoolPortfolio()" type="button">Retry</button></div>`;
    return;
  }
  renderSchoolPortfolio();
}

window.setSchoolAudienceMode = setSchoolAudienceMode;
window.setSchoolSensitivityCutoff = setSchoolSensitivityCutoff;
window.applyCustomSchoolCutoff = applyCustomSchoolCutoff;
window.selectSchoolZone = selectSchoolZone;
window.selectSchoolMarket = selectSchoolMarket;
window.selectSchoolCandidateHex = selectSchoolCandidateHex;
window.clearSchoolGeography = clearSchoolGeography;
window.setSchoolCaptureRate = setSchoolCaptureRate;
window.renderSchoolCapacityPlanner = renderSchoolCapacityPlanner;
window.showSchoolCampusDetails = showSchoolCampusDetails;
window.clearSchoolCampusDetails = clearSchoolCampusDetails;
window.setSchoolEvaluationMinutes = setSchoolEvaluationMinutes;
window.evaluateSchoolCandidate = evaluateSchoolCandidate;
window.addSchoolEvaluationToPortfolio = addSchoolEvaluationToPortfolio;
window.removeSchoolPortfolioCenter = removeSchoolPortfolioCenter;
window.moveSchoolPortfolioCenter = moveSchoolPortfolioCenter;
window.analyzeSchoolPortfolio = analyzeSchoolPortfolio;
