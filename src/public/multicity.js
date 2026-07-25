(() => {
  'use strict';

  const CITY_ORDER = ['delhi_ncr', 'bengaluru', 'hyderabad', 'mumbai'];
  const DEFAULT_CITY = 'mumbai';
  const DEFAULT_CATEGORY = 'premium_plus';
  const SCENARIOS = [
    { id: 'conservative', label: 'Conservative', capture: 1 },
    { id: 'base', label: 'Base', capture: 2 },
    { id: 'upside', label: 'Upside', capture: 3 },
  ];
  const CAMPUS_SEATS = 200;
  const TARGET_UTILIZATION = 0.8;

  const state = {
    manifest: null,
    comparison: null,
    city: DEFAULT_CITY,
    category: DEFAULT_CATEGORY,
    mapLayer: 'schools',
    bundles: new Map(),
    map: null,
    evidenceLayer: null,
  };

  const $ = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
  const compact = value => {
    const number = Number(value);
    if (!Number.isFinite(number)) return '—';
    const absolute = Math.abs(number);
    if (absolute >= 1e7) return `${(number / 1e7).toFixed(1)}Cr`;
    if (absolute >= 1e5) return `${(number / 1e5).toFixed(1)}L`;
    if (absolute >= 1e3) return `${(number / 1e3).toFixed(number >= 1e5 ? 0 : 1)}K`;
    return fmt.format(number);
  };
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[character]));
  const numberFrom = (...values) => {
    for (const value of values) {
      if (value == null || value === '') continue;
      const number = Number(value);
      if (Number.isFinite(number)) return number;
    }
    return 0;
  };
  const textFrom = (...values) => values.find(value => value != null && String(value).trim()) ?? '';

  async function json(path) {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
    return response.json();
  }

  async function optionalJson(path, fallback) {
    try {
      return await json(path);
    } catch (_error) {
      return fallback;
    }
  }

  async function api(action, params = {}) {
    const query = new URLSearchParams({ action, ...params });
    const response = await fetch(`/api/multicity?${query.toString()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Could not load ${action} (${response.status})`);
    const payload = await response.json();
    if (response.redirected && payload && !Object.prototype.hasOwnProperty.call(payload, 'status')) {
      return payload;
    }
    if (payload.status !== 'success') throw new Error(payload.error?.message || `Could not load ${action}`);
    return payload.data;
  }

  async function apiOrStatic(action, params, staticPath) {
    try {
      return await api(action, params);
    } catch (_error) {
      return json(staticPath);
    }
  }

  function cleanName(value) {
    const name = String(value || 'Unnamed record').replace(/\s+/g, ' ').trim();
    if (!name || name !== name.toUpperCase()) return name;
    return name.toLowerCase().replace(/\b\p{L}/gu, letter => letter.toUpperCase());
  }

  function categoryDefinition() {
    return state.manifest.categories.find(item => item.id === state.category) || { label: state.category, tiers: [] };
  }

  function cityRows() {
    const byId = new Map((state.comparison.cities || []).map(row => [row.canonical_city_id, row]));
    return CITY_ORDER.map(city => byId.get(city)).filter(Boolean).map(row => ({
      ...row,
      metrics: row.category_metrics?.[state.category] || {},
    }));
  }

  function directStudents(metrics) {
    return numberFrom(
      metrics.reported_students_grade_2_9,
      metrics.coverage?.reported_grade_2_9_students,
      Number(metrics.students_grade_2_9 || 0) - modeledStudents(metrics),
    );
  }

  function modeledStudents(metrics) {
    return numberFrom(
      metrics.modeled_students_grade_2_9,
      metrics.coverage?.estimated_grade_2_9_students,
    );
  }

  function allGradeReported(metrics) {
    return numberFrom(metrics.reported_enrollment_total);
  }

  function primaryCityStudents(metrics) {
    return allGradeReported(metrics) || directStudents(metrics);
  }

  function candidateRanks(rows = cityRows()) {
    const candidates = rows
      .filter(row => row.canonical_city_id !== 'delhi_ncr')
      .sort((left, right) => primaryCityStudents(right.metrics) - primaryCityStudents(left.metrics));
    return new Map(candidates.map((row, index) => [row.canonical_city_id, index + 1]));
  }

  function recommendedCandidate(rows = cityRows()) {
    return rows
      .filter(row => row.canonical_city_id !== 'delhi_ncr')
      .sort((left, right) => primaryCityStudents(right.metrics) - primaryCityStudents(left.metrics))[0];
  }

  function cityRole(city, rows = cityRows()) {
    if (city === 'delhi_ncr') return 'Benchmark';
    return city === recommendedCandidate(rows)?.canonical_city_id ? 'Recommended' : 'Candidate';
  }

  function currentRow() {
    return cityRows().find(row => row.canonical_city_id === state.city) || cityRows().find(row => row.canonical_city_id === DEFAULT_CITY);
  }

  function parseUrlState() {
    const citySet = new Set(CITY_ORDER);
    const categorySet = new Set(state.manifest.categories.map(item => item.id));
    const params = new URLSearchParams(location.search);
    const pathMatch = location.pathname.match(/^\/(?:city|cities)\/([^/]+)\/?$/i);
    const pathCity = pathMatch ? decodeURIComponent(pathMatch[1]).toLowerCase() : null;
    const queryCity = params.get('city');
    const nextCity = citySet.has(queryCity) ? queryCity : citySet.has(pathCity) ? pathCity : DEFAULT_CITY;
    const nextCategory = categorySet.has(params.get('category')) ? params.get('category') : DEFAULT_CATEGORY;
    state.city = nextCity;
    state.category = nextCategory;
  }

  function syncUrl(mode = 'replace') {
    const url = new URL(location.href);
    url.pathname = `/city/${state.city}`;
    url.searchParams.delete('city');
    url.searchParams.set('category', state.category);
    const method = mode === 'push' ? 'pushState' : 'replaceState';
    history[method]({ city: state.city, category: state.category }, '', `${url.pathname}${url.search}${url.hash}`);
  }

  function cityLabel(city) {
    return state.manifest.cities.find(item => item.canonical_city_id === city)?.label || city;
  }

  function deepDivePath(city = state.city) {
    const query = new URLSearchParams({ from: 'multicity', city, category: state.category });
    return `/bangalore?${query.toString()}`;
  }

  function updateWorkspaceLinks(city = state.city) {
    const path = deepDivePath(city);
    ['sidebar-deep-dive-link', 'topbar-deep-dive-link', 'deep-dive-cta', 'legacy-link'].forEach(id => {
      const link = $(id);
      if (link) link.href = path;
    });
    if ($('deep-dive-city-select')) $('deep-dive-city-select').value = city;
    if ($('deep-dive-cta')) $('deep-dive-cta').innerHTML = `Open ${esc(cityLabel(city))} deep dive <span aria-hidden="true">↗</span>`;
  }

  function hydrateControls() {
    $('category-select').innerHTML = state.manifest.categories.map(category => (
      `<option value="${esc(category.id)}">${esc(category.label)}</option>`
    )).join('');
    $('city-select').innerHTML = CITY_ORDER.map(city => {
      const manifestCity = state.manifest.cities.find(item => item.canonical_city_id === city);
      const label = manifestCity?.label || city;
      const initialRole = city === 'delhi_ncr' ? 'Benchmark' : city === DEFAULT_CITY ? 'Recommended' : 'Candidate';
      return `<option value="${city}">${esc(label)} · ${esc(initialRole)}</option>`;
    }).join('');
    $('deep-dive-city-select').innerHTML = CITY_ORDER.map(city => (
      `<option value="${city}">${esc(cityLabel(city))}</option>`
    )).join('');
  }

  function listFromContract(value) {
    if (Array.isArray(value)) return value;
    if (!value || typeof value !== 'object') return [];
    if (Array.isArray(value[state.category])) return value[state.category];
    if (Array.isArray(value.items)) return value.items;
    if (Array.isArray(value.rows)) return value.rows;
    return [];
  }

  function isSchoolInCategory(school) {
    const tiers = new Set(categoryDefinition().tiers.map(tier => tier.toLowerCase()));
    const tier = String(textFrom(school.fee_tier, school.fee_bucket, school.quartile)).toLowerCase();
    return !tiers.size || tiers.has(tier);
  }

  function schoolEnrollment(school) {
    return numberFrom(
      school.reported_students_grade_2_9,
      school.grade_2_9_enrollment,
      school.students_grades_2_9,
    );
  }

  function isReportedSchool(school) {
    const source = String(school.enrollment_source || school.evidence_basis || '').toLowerCase();
    return schoolEnrollment(school) > 0 && !/(estimate|model|benchmark|fallback|synthetic)/.test(source);
  }

  function dedupe(items, keyGetter) {
    const seen = new Set();
    return items.filter(item => {
      const key = String(keyGetter(item) || '').toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function fallbackSchoolPartners(schools) {
    return dedupe(
      schools
        .filter(school => isSchoolInCategory(school) && isReportedSchool(school))
        .sort((left, right) => schoolEnrollment(right) - schoolEnrollment(left)),
      school => `${school.name}|${school.address || school.pincode || school.school_id}`,
    ).slice(0, 5);
  }

  function premiumProject(project) {
    const label = String(textFrom(project.category, project.q4_segment, project.quartile)).toLowerCase();
    return project.quartile === 'Q4' || /(luxury|premium|elite)/.test(label);
  }

  function projectUnits(project) {
    return numberFrom(project.known_units, project.units, project.total_units);
  }

  function projectLatitude(project) {
    return numberFrom(project.latitude, project.lat);
  }

  function projectLongitude(project) {
    return numberFrom(project.longitude, project.lon, project.lng);
  }

  function fallbackResidentialTargets(societies) {
    const eligible = societies.filter(project => premiumProject(project) && projectUnits(project) > 0);
    return dedupe(
      eligible.sort((left, right) => projectUnits(right) - projectUnits(left)),
      project => textFrom(project.canonical_society_id, project.society_id, `${project.name}|${project.locality}`),
    ).slice(0, 5);
  }

  function buildSchoolHexSummary(schools) {
    const summary = new Map();
    schools.filter(school => isSchoolInCategory(school) && isReportedSchool(school) && school.hex_id).forEach(school => {
      const row = summary.get(school.hex_id) || { reportedStudents: 0, schoolCount: 0 };
      row.reportedStudents += schoolEnrollment(school);
      row.schoolCount += 1;
      summary.set(school.hex_id, row);
    });
    return summary;
  }

  function buildProjectHexSummary(societies) {
    const summary = new Map();
    societies.filter(project => project.hex_id && projectUnits(project) > 0).forEach(project => {
      const row = summary.get(project.hex_id) || { knownUnits: 0, projectCount: 0 };
      row.knownUnits += projectUnits(project);
      row.projectCount += 1;
      summary.set(project.hex_id, row);
    });
    return summary;
  }

  function geographyNameMap(detail) {
    return new Map((detail.geographies?.h3_cells || []).map(row => [row.id || row.hex_id, cleanName(row.label || row.name)]));
  }

  function fallbackCatchments(bundle) {
    const schoolSummary = buildSchoolHexSummary(bundle.schools);
    const projectSummary = buildProjectHexSummary(bundle.societies);
    const names = geographyNameMap(bundle.detail);
    return [...schoolSummary.entries()].map(([hexId, school]) => ({
      id: hexId,
      name: names.get(hexId) || 'Priority school cluster',
      reported_students_grade_2_9: school.reportedStudents,
      school_count: school.schoolCount,
      known_residential_units: projectSummary.get(hexId)?.knownUnits || 0,
      residential_project_count: projectSummary.get(hexId)?.projectCount || 0,
    })).sort((left, right) => (
      right.reported_students_grade_2_9 - left.reported_students_grade_2_9
      || right.known_residential_units - left.known_residential_units
    )).slice(0, 5);
  }

  function decisionLists(bundle) {
    const support = bundle.detail.decision_support || {};
    const usePublishedPremiumLists = state.category === 'premium_plus';
    const schoolPartners = usePublishedPremiumLists ? listFromContract(support.priority_school_partners).slice().sort((left, right) => schoolEnrollment(right) - schoolEnrollment(left)) : [];
    const residentialTargets = usePublishedPremiumLists ? listFromContract(support.residential_project_targets)
      .filter(premiumProject)
      .slice()
      .sort((left, right) => projectUnits(right) - projectUnits(left)) : [];
    const candidateCatchments = usePublishedPremiumLists ? listFromContract(support.candidate_catchments).slice().sort((left, right) => (
      numberFrom(right.reported_students_grade_2_9, right.reported_grade_2_9_students)
      - numberFrom(left.reported_students_grade_2_9, left.reported_grade_2_9_students)
    )) : [];
    return {
      schools: schoolPartners.length ? schoolPartners : fallbackSchoolPartners(bundle.schools),
      projects: residentialTargets.length ? residentialTargets : fallbackResidentialTargets(bundle.societies),
      catchments: candidateCatchments.length ? candidateCatchments : fallbackCatchments(bundle),
    };
  }

  async function loadCityBundle(city) {
    if (state.bundles.has(city)) return state.bundles.get(city);
    const manifestCity = state.manifest.cities.find(item => item.canonical_city_id === city) || {};
    const detailPath = manifestCity.detail_path || `cities/${city}.json`;
    const promise = Promise.all([
      apiOrStatic('city', { city }, `/data/multicity/${detailPath}`),
      optionalJson(`/data/city_legacy/${city}/school_entities.json`, []),
      optionalJson(`/data/city_legacy/${city}/societies.json`, []),
    ]).then(([detail, schools, societies]) => ({ detail, schools, societies, hexes: new Map() }));
    state.bundles.set(city, promise);
    return promise;
  }

  async function loadCategoryHexes(bundle) {
    if (bundle.hexes.has(state.category)) return bundle.hexes.get(state.category);
    const path = `/data/multicity/hexes/${state.city}__${state.category}.geojson`;
    const data = await optionalJson(path, { type: 'FeatureCollection', features: [] });
    bundle.hexes.set(state.category, data);
    return data;
  }

  function metricMarkup(label, value) {
    return `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  }

  function renderExecutive() {
    const rows = cityRows();
    const winner = recommendedCandidate(rows);
    const benchmark = rows.find(row => row.canonical_city_id === 'delhi_ncr');
    const winnerReported = primaryCityStudents(winner.metrics);
    const benchmarkReported = primaryCityStudents(benchmark.metrics);
    const winnerProjects = winner.context_layers?.projects || {};
    const benchmarkProjects = benchmark.context_layers?.projects || {};

    $('winner-city').textContent = winner.city_label;
    $('winner-rank').textContent = '#1';
    $('winner-reason').textContent = `${winner.city_label} has the largest source-reported all-grade enrollment among the candidate cities. Its known residential inventory and school-partnership pool make it the clearest market to validate next.`;
    $('winner-metrics').innerHTML = [
      metricMarkup('Reported enrollment · all grades', compact(winnerReported)),
      metricMarkup('Derived Grades 2–9', compact(directStudents(winner.metrics))),
      metricMarkup('Modeled addition · separate', compact(modeledStudents(winner.metrics))),
      metricMarkup('Known residential units', compact(winnerProjects.known_residential_units)),
    ].join('');

    $('benchmark-copy').textContent = `${benchmark.city_label} remains the operating reference point. It is not included in the candidate ranking.`;
    $('benchmark-metrics').innerHTML = [
      metricMarkup('Reported enrollment · all grades', compact(benchmarkReported)),
      metricMarkup('Derived Grades 2–9', compact(directStudents(benchmark.metrics))),
    ].join('');
  }

  function renderPlatformSnapshot() {
    const rows = state.comparison.cities || [];
    const total = getter => rows.reduce((sum, row) => sum + numberFrom(getter(row)), 0);
    const privateSchoolRecords = total(row => row.category_metrics?.all_private?.school_count);
    const reportedSchools = total(row => row.category_metrics?.all_private?.coverage?.source_reported_school_count);
    const reportedEnrollment = total(row => row.category_metrics?.all_private?.reported_enrollment_total);
    const projectRecords = total(row => row.context_layers?.projects?.record_count);
    const knownUnits = total(row => row.context_layers?.projects?.known_residential_units);
    const hospitalRecords = total(row => row.context_layers?.hospitals?.record_count);
    const officeRecords = total(row => row.context_layers?.offices?.record_count);
    const localityRecords = total(row => row.context_layers?.localities?.record_count);
    const cards = [
      ['Markets covered', fmt.format(rows.length), 'Delhi NCR, Bengaluru, Hyderabad, and Mumbai'],
      ['Private-school records', fmt.format(privateSchoolRecords), `${fmt.format(reportedSchools)} use source-reported enrollment evidence`],
      ['Reported enrollment', fmt.format(reportedEnrollment), 'All-grade total across the complete private-school audience'],
      ['Residential projects', fmt.format(projectRecords), `${fmt.format(knownUnits)} source-listed units`],
      ['Hospital records', fmt.format(hospitalRecords), 'Healthcare context for catchment validation'],
      ['Office & SEZ records', fmt.format(officeRecords), 'Employment anchors used as supporting context'],
      ['Locality records', fmt.format(localityRecords), 'Naming, location, and neighbourhood context'],
      ['School audiences', fmt.format(state.manifest.categories.length), 'From Super-Premium through all private schools'],
    ];
    $('platform-kpis').innerHTML = cards.map(([label, value, note]) => (
      `<article class="platform-kpi"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`
    )).join('');
  }

  function demandRankLabel(city, ranks) {
    return city === 'delhi_ncr' ? 'Benchmark' : `#${ranks.get(city) || '—'}`;
  }

  function renderComparison() {
    const rows = cityRows();
    const ranks = candidateRanks(rows);
    $('comparison-table').innerHTML = rows.map(row => {
      const role = cityRole(row.canonical_city_id, rows);
      const roleClass = role === 'Recommended' ? ' recommended' : '';
      return `<tr data-city="${row.canonical_city_id}" tabindex="0" role="button" aria-label="Open ${esc(row.city_label)} city plan" class="${row.canonical_city_id === state.city ? 'active' : ''}">
        <td><strong>${esc(row.city_label)}</strong></td>
        <td><span class="role-tag${roleClass}">${esc(role)}</span></td>
        <td><strong>${fmt.format(primaryCityStudents(row.metrics))}</strong></td>
        <td>${fmt.format(directStudents(row.metrics))}</td>
        <td class="modeled-value">+${fmt.format(modeledStudents(row.metrics))}</td>
        <td>${fmt.format(row.metrics.school_count || 0)}</td>
        <td>${fmt.format(row.context_layers?.projects?.known_residential_units || 0)}</td>
        <td class="rank-value">${esc(demandRankLabel(row.canonical_city_id, ranks))}</td>
      </tr>`;
    }).join('');
    $('comparison-table').querySelectorAll('tr').forEach(row => {
      const open = () => selectCity(row.dataset.city, { history: 'push', scroll: true });
      row.addEventListener('click', open);
      row.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          open();
        }
      });
    });
  }

  function renderCityControls() {
    $('category-select').value = state.category;
    $('city-select').value = state.city;
    document.querySelectorAll('.city-nav').forEach(button => {
      const active = button.dataset.city === state.city;
      const role = cityRole(button.dataset.city);
      const roleLabel = button.querySelector('small');
      if (roleLabel) roleLabel.textContent = role;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    [...$('city-select').options].forEach(option => {
      const manifestCity = state.manifest.cities.find(item => item.canonical_city_id === option.value);
      option.textContent = `${manifestCity?.label || option.value} · ${cityRole(option.value)}`;
    });
    updateWorkspaceLinks(state.city);
  }

  function renderKpis(row) {
    const projects = row.context_layers?.projects || {};
    const reportedAllGrades = allGradeReported(row.metrics);
    $('city-kpis').innerHTML = [
      ['Reported enrollment · all grades', fmt.format(reportedAllGrades || directStudents(row.metrics)), 'Primary city recommendation evidence'],
      ['Derived Grades 2–9', fmt.format(directStudents(row.metrics)), `${fmt.format(row.metrics.school_count || 0)} schools · planning base`],
      ['Modeled addition', fmt.format(modeledStudents(row.metrics)), 'Shown separately · excluded from rank'],
      ['Known residential units', fmt.format(projects.known_residential_units || 0), `${fmt.format(projects.record_count || 0)} project records`],
    ].map(([label, value, note]) => `<article class="kpi-card"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`).join('');
  }

  function schoolItemMarkup(item) {
    const name = cleanName(textFrom(item.name, item.school_name, item.label));
    const enrollment = numberFrom(item.reported_students_grade_2_9, item.grade_2_9_enrollment, item.students_grades_2_9, item.enrollment);
    const boardValue = item.board || item.boards || item.board_name;
    const board = Array.isArray(boardValue) ? boardValue.join(', ') : boardValue;
    const place = textFrom(item.locality, item.area, item.zone, item.pincode, item.address);
    return `<li><strong>${esc(name)}</strong><span>${esc([board, place].filter(Boolean).join(' · '))}</span><small>${fmt.format(enrollment)} derived Grades 2–9 students</small></li>`;
  }

  function projectItemMarkup(item) {
    const name = cleanName(textFrom(item.name, item.project_name, item.label));
    const place = textFrom(item.locality, item.zone, item.pincode);
    const developer = textFrom(item.developer, item.builder);
    const content = `<strong>${esc(name)}</strong><span>${esc([developer, place].filter(Boolean).join(' · '))}</span><small>${fmt.format(projectUnits(item))} known units</small>`;
    const url = textFrom(item.source_url, item.url);
    return url ? `<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${content}</a></li>` : `<li>${content}</li>`;
  }

  function catchmentItemMarkup(item) {
    const name = cleanName(textFrom(item.name, item.label, item.neighborhood_name, item.locality, 'Candidate catchment'));
    const students = numberFrom(item.reported_students_grade_2_9, item.reported_grade_2_9_students, item.students_grade_2_9);
    const schools = numberFrom(item.school_count, item.reported_school_count);
    const units = numberFrom(item.known_residential_units, item.known_units);
    const detail = `${fmt.format(students)} derived Grades 2–9 · ${fmt.format(schools)} ${schools === 1 ? 'school' : 'schools'}`;
    return `<li><strong>${esc(name)}</strong><span>${esc(detail)}</span><small>${units ? `${fmt.format(units)} known units nearby` : 'Validate residential reach and travel time'}</small></li>`;
  }

  function renderActionList(id, items, markup, emptyMessage) {
    $(id).innerHTML = items.length ? items.slice(0, 5).map(markup).join('') : `<li class="empty-row">${esc(emptyMessage)}</li>`;
  }

  function renderPlanSummary(row, lists) {
    const firstCatchment = lists.catchments[0];
    const firstSchool = lists.schools[0];
    const baseCenters = Math.floor(directStudents(row.metrics) * 0.02 / (CAMPUS_SEATS * TARGET_UTILIZATION));
    $('plan-summary-title').textContent = `${row.city_label} decision brief`;
    $('plan-summary').innerHTML = [
      ['Demand', `${fmt.format(primaryCityStudents(row.metrics))} source-reported all-grade enrollment; ${fmt.format(directStudents(row.metrics))} derived Grades 2–9 for campus planning.`],
      ['First area to validate', firstCatchment ? cleanName(textFrom(firstCatchment.name, firstCatchment.label, firstCatchment.neighborhood_name)) : 'Complete catchment validation.'],
      ['First partnership lead', firstSchool ? cleanName(textFrom(firstSchool.name, firstSchool.school_name, firstSchool.label)) : 'Build the school outreach shortlist.'],
      ['Base capacity equivalent', `${fmt.format(baseCenters)} fully supportable campuses at 2% capture, before overlap and economics.`],
    ].map(([label, value]) => `<div><strong>${esc(label)}</strong><span>${esc(value)}</span></div>`).join('');
  }

  function renderDecisionQuestions(row, lists) {
    const ranks = candidateRanks();
    const topCatchment = lists.catchments[0];
    const baseCenters = Math.floor(directStudents(row.metrics) * .02 / (CAMPUS_SEATS * TARGET_UTILIZATION));
    $('decision-questions').innerHTML = [
      ['Which city next?', recommendedCandidate()?.city_label || 'Mumbai'],
      [`How many students in ${row.city_label}?`, `${fmt.format(primaryCityStudents(row.metrics))} reported · all grades`],
      ['Where is demand strongest?', topCatchment ? cleanName(textFrom(topCatchment.name, topCatchment.label, topCatchment.neighborhood_name)) : 'See city plan'],
      ['How many campuses?', `${fmt.format(baseCenters)} fully supportable · base case`],
    ].map(([question, answer]) => `<div><span>${esc(question)}</span><strong>${esc(answer)}</strong></div>`).join('');
    $('winner-rank').textContent = `#${ranks.get(recommendedCandidate()?.canonical_city_id) || 1}`;
  }

  function renderScenarios(row) {
    const direct = directStudents(row.metrics);
    const contractScenarios = row.campus_scenarios || {};
    $('scenario-cards').innerHTML = SCENARIOS.map(scenario => {
      const contract = contractScenarios[scenario.id] || listFromContract(contractScenarios).find(item => Number(item.capture_rate_pct ?? item.capture_pct) === scenario.capture) || {};
      const potentialStudents = numberFrom(contract.captured_students, contract.potential_students, direct * scenario.capture / 100);
      const centers = numberFrom(contract.campuses_supported, contract.supportable_campuses, contract.campus_count, Math.floor(potentialStudents / (CAMPUS_SEATS * TARGET_UTILIZATION)));
      return `<article class="scenario-card ${scenario.id}">
        <div class="scenario-head"><strong>${esc(scenario.label)}</strong><span>${scenario.capture}% capture</span></div>
        <div class="scenario-result"><strong>${fmt.format(Math.floor(centers))}</strong><span>fully supported campuses</span></div>
        <p>${fmt.format(Math.round(potentialStudents))} potential students ÷ 160 occupied seats, rounded down.</p>
      </article>`;
    }).join('');
  }

  function initMap(row) {
    if (state.map || !window.L) return;
    state.map = L.map('market-map', { zoomControl: true, attributionControl: true, scrollWheelZoom: false });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap &copy; CARTO',
    }).addTo(state.map);
    const center = row.map?.center || { latitude: 19.08, longitude: 72.88 };
    state.map.setView([center.latitude, center.longitude], row.map?.zoom || 10);
  }

  function clearMapEvidence() {
    if (state.evidenceLayer && state.map) state.map.removeLayer(state.evidenceLayer);
    state.evidenceLayer = null;
  }

  function featureHexId(feature) {
    return textFrom(feature.properties?.hex_id, feature.properties?.id, feature.id);
  }

  function featureName(feature, names) {
    const properties = feature.properties || {};
    return cleanName(textFrom(properties.name, properties.neighborhood_name, properties.label, names.get(featureHexId(feature)), 'School demand area'));
  }

  async function renderMap(row, bundle) {
    initMap(row);
    if (!state.map) {
      $('map-layer-summary').textContent = 'Map library unavailable. The ranked action lists remain available below.';
      return;
    }
    clearMapEvidence();
    document.querySelectorAll('[data-map-layer]').forEach(button => button.classList.toggle('active', button.dataset.mapLayer === state.mapLayer));

    if (state.mapLayer === 'projects') {
      const projectSource = bundle.societies.length
        ? bundle.societies
        : listFromContract(bundle.detail.decision_support?.residential_project_targets);
      const targets = dedupe(
        projectSource.filter(project => premiumProject(project) && projectUnits(project) > 0 && projectLatitude(project) && projectLongitude(project))
          .sort((left, right) => projectUnits(right) - projectUnits(left)),
        project => textFrom(project.canonical_society_id, project.society_id, `${project.name}|${project.locality}`),
      ).slice(0, 140);
      const max = Math.max(...targets.map(projectUnits), 1);
      const group = L.featureGroup();
      targets.forEach(project => {
        const radius = 4 + Math.sqrt(projectUnits(project) / max) * 12;
        L.circleMarker([projectLatitude(project), projectLongitude(project)], {
          radius,
          color: '#087d74',
          weight: 1,
          fillColor: '#35b6a7',
          fillOpacity: .55,
        }).bindPopup(`<div class="map-popup"><strong>${esc(cleanName(project.name))}</strong><span>${fmt.format(projectUnits(project))} known units · ${esc(project.locality || project.zone || '')}</span></div>`).addTo(group);
      });
      state.evidenceLayer = group.addTo(state.map);
      if (targets.length) state.map.fitBounds(group.getBounds(), { padding: [24, 24], maxZoom: 12 });
      $('map-title').textContent = 'Premium residential targets';
      $('map-subtitle').textContent = 'Known project units shown as marketing reach';
      $('map-layer-summary').textContent = `${fmt.format(targets.length)} high-priority projects shown. Circle size represents source-listed units.`;
      return;
    }

    const hexes = await loadCategoryHexes(bundle);
    const schoolSummary = buildSchoolHexSummary(bundle.schools);
    const names = geographyNameMap(bundle.detail);
    const features = (hexes.features || []).map(feature => {
      const properties = feature.properties || {};
      const id = featureHexId(feature);
      const categoryMetric = properties.category_metrics?.[state.category] || {};
      const contractValue = numberFrom(categoryMetric.reported_students_grade_2_9, categoryMetric.reported_grade_2_9_students, properties.reported_students_grade_2_9, properties.reported_grade_2_9_students);
      const direct = contractValue || schoolSummary.get(id)?.reportedStudents || 0;
      return { ...feature, properties: { ...properties, __direct: direct, __schools: schoolSummary.get(id)?.schoolCount || properties.reported_school_count || properties.school_count || 0 } };
    }).filter(feature => feature.properties.__direct > 0);
    const max = Math.max(...features.map(feature => feature.properties.__direct), 1);
    const color = value => {
      const ratio = value / max;
      if (ratio > .65) return '#0b4162';
      if (ratio > .35) return '#1261a6';
      if (ratio > .15) return '#4097cb';
      return '#9dcae6';
    };
    const geoLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
      style: feature => ({ color: '#ffffff', weight: 1, fillColor: color(feature.properties.__direct), fillOpacity: .78 }),
      onEachFeature: (feature, layer) => {
        const name = featureName(feature, names);
        layer.bindPopup(`<div class="map-popup"><strong>${esc(name)}</strong><span>${fmt.format(feature.properties.__direct)} derived Grades 2–9 students · ${fmt.format(feature.properties.__schools)} schools</span></div>`);
      },
    });
    state.evidenceLayer = geoLayer.addTo(state.map);
    if (features.length) state.map.fitBounds(geoLayer.getBounds(), { padding: [20, 20], maxZoom: 12 });
    else {
      const center = row.map?.center;
      if (center) state.map.setView([center.latitude, center.longitude], row.map?.zoom || 10);
    }
    const citywideTotal = directStudents(row.metrics);
    $('map-title').textContent = 'Reported school demand';
    $('map-subtitle').textContent = `Where ${categoryDefinition().label.toLowerCase()} students are enrolled`;
    $('map-layer-summary').textContent = `${fmt.format(citywideTotal)} citywide Grades 2–9 students derived from source-reported enrollment; distribution shown across ${fmt.format(features.length)} mapped school-demand areas.`;
  }

  async function renderSelectedCity() {
    const requestedCity = state.city;
    renderCityControls();
    renderComparison();
    const row = currentRow();
    const bundle = await loadCityBundle(state.city);
    if (state.city !== requestedCity) return;
    const lists = decisionLists(bundle);
    $('selected-city-label').textContent = row.city_label;
    renderKpis(row);
    renderActionList('school-partners', lists.schools, schoolItemMarkup, 'No source-reported school partner list is available for this audience.');
    renderActionList('residential-targets', lists.projects, projectItemMarkup, 'No named premium residential targets are available.');
    renderActionList('candidate-catchments', lists.catchments, catchmentItemMarkup, 'No area-level demand shortlist is available.');
    renderPlanSummary(row, lists);
    renderDecisionQuestions(row, lists);
    const publishedScenarios = row.metrics.campus_scenarios || (
      state.category === 'premium_plus'
        ? bundle.detail.campus_scenarios || bundle.detail.decision_support?.campus_scenarios
        : null
    );
    renderScenarios({ ...row, campus_scenarios: publishedScenarios });
    updateLegacyLink();
    await renderMap(row, bundle);
    requestAnimationFrame(() => state.map?.invalidateSize());
  }

  function updateLegacyLink() {
    updateWorkspaceLinks(state.city);
  }

  function renderSources() {
    const generated = state.manifest.generated_at ? new Date(state.manifest.generated_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : 'Current build';
    $('source-register').innerHTML = [
      ['Schools & enrollment', 'Supplied curated school master, primarily UDISE-backed, with tier, enrollment, board and location fields.'],
      ['Projects & localities', 'Primarily Magicbricks records, with limited 99acres source links retained in the supplied residential inventory.'],
      ['Hospitals', 'Practo hospital listings with location and available facility fields.'],
      ['Access & built context', 'OpenStreetMap/OSRM route evidence and Overture building context.'],
      ['Offices & SEZ anchors', 'Supplied unified office and SEZ files used as supporting context.'],
      ['Portal build', `${generated} · methodology ${state.manifest.methodology_version || 'current'} · source observation dates not supplied.`],
    ].map(([title, detail]) => `<div class="source-item"><strong>${esc(title)}</strong><span>${esc(detail)}</span></div>`).join('');
  }

  async function selectCity(city, options = {}) {
    if (!CITY_ORDER.includes(city)) return;
    state.city = city;
    if (options.history) syncUrl(options.history);
    await renderSelectedCity();
    if (options.scroll) $('city-plan').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function bindEvents() {
    $('category-select').addEventListener('change', async event => {
      state.category = event.target.value;
      syncUrl('push');
      renderExecutive();
      await renderSelectedCity();
    });
    $('deep-dive-city-select').addEventListener('change', event => updateWorkspaceLinks(event.target.value));
    $('city-select').addEventListener('change', event => selectCity(event.target.value, { history: 'push' }));
    document.querySelectorAll('.city-nav').forEach(button => button.addEventListener('click', () => selectCity(button.dataset.city, { history: 'push', scroll: true })));
    document.querySelectorAll('[data-map-layer]').forEach(button => button.addEventListener('click', async () => {
      state.mapLayer = button.dataset.mapLayer;
      await renderMap(currentRow(), await loadCityBundle(state.city));
    }));
    addEventListener('popstate', async () => {
      parseUrlState();
      renderExecutive();
      await renderSelectedCity();
    });

    if ('IntersectionObserver' in window) {
      const links = [...document.querySelectorAll('.section-nav a')];
      const observer = new IntersectionObserver(entries => {
        const visible = entries.filter(entry => entry.isIntersecting).sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
        if (!visible) return;
        links.forEach(link => link.classList.toggle('active', link.hash === `#${visible.target.id}`));
      }, { rootMargin: '-20% 0px -65%', threshold: [0, .2, .5] });
      document.querySelectorAll('main section[id]').forEach(section => observer.observe(section));
    }
  }

  async function init() {
    try {
      state.manifest = await apiOrStatic('manifest', {}, '/data/multicity/manifest.json');
      const comparisonPath = state.manifest.city_comparison_path || state.manifest.artifacts?.comparison?.path || 'city_comparison.json';
      state.comparison = await apiOrStatic('summaries', {}, `/data/multicity/${comparisonPath}`);
      hydrateControls();
      parseUrlState();
      syncUrl('replace');
      renderExecutive();
      renderPlatformSnapshot();
      renderSources();
      bindEvents();
      await renderSelectedCity();
      const generated = state.manifest.generated_at ? new Date(state.manifest.generated_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : 'current build';
      $('generated-date').textContent = `Portal build · ${generated}`;
      $('loading').hidden = true;
      $('dashboard').hidden = false;
      requestAnimationFrame(() => state.map?.invalidateSize());
    } catch (error) {
      $('loading').hidden = true;
      $('error').hidden = false;
      $('error').innerHTML = `<strong>The expansion decision view could not load.</strong><br>${esc(error.message)}. Please verify the generated city artifacts and reload.`;
    }
  }

  init();
})();
