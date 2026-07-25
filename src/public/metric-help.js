(function metricHelpModule(global) {
  'use strict';

  const POPOVER_ID = 'metric-help-popover';
  const ENHANCED_ATTR = 'data-metric-help-ready';
  const TABLE_ATTR = 'data-metric-help-table-ready';
  const MOBILE_TABLE_CLASS = 'metric-help-responsive';
  const CLOSE_DELAY_MS = 140;

  const definitions = new Map();
  const definitionOrder = [];

  function normalizeLabel(value) {
    return String(value || '')
      .normalize('NFKD')
      .toLowerCase()
      .replace(/[–—−]/g, '-')
      .replace(/\+/g, ' plus ')
      .replace(/[^a-z0-9%]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function addDefinition(key, definition) {
    if (!key || !definition) return;
    const record = Object.freeze({
      key,
      label: definition.label,
      kind: definition.kind,
      what: definition.what,
      how: definition.how,
      why: definition.why,
      patterns: Object.freeze([...(definition.patterns || [])])
    });
    if (!definitions.has(key)) definitionOrder.push(key);
    definitions.set(key, record);
  }

  addDefinition('source_reported_enrollment_total', {
    label: 'Source-reported enrollment',
    kind: 'Directly observed',
    what: 'All-grade student enrollment recorded in source-reported school rows for the selected school bucket.',
    how: 'Adds supplied total-enrollment values only from rows marked as source reported. Missing enrollment is left unavailable and modeled rows are excluded.',
    why: 'This is the primary school-demand input used in the city recommendation and ranking.',
    patterns: [
      /^source reported(?: premium plus)? enrollment$/,
      /^source reported school enrollment$/,
      /^reported enrollment total$/,
      /^reported total enrollment$/,
      /^reported all grade enrollment$/,
      /^source reported all grade$/
    ]
  });

  addDefinition('derived_reported_grade_2_9', {
    label: 'Derived reported Grade 2–9',
    kind: 'Directly calculated',
    what: 'The Grade 2–9 portion derived from source-reported school enrollment, kept separate from modeled school rows.',
    how: 'Prorates each supplied source-reported total using the grades covered by that school’s supplied grade span, then sums the qualifying Premium and Super-Premium rows.',
    why: 'It supports local catchment comparisons, school-partnership prioritization, and campus scenarios. It is not a second observed enrollment source and is not the primary city-ranking input.',
    patterns: [
      /^derived reported(?: premium plus)? grade 2 9$/,
      /^reported(?: premium plus)? grade 2 9$/,
      /^reported grade 2 9 students$/,
      /^reported students grade 2 9$/,
      /^premium plus students$/,
      /^total no of grade 2 9 students in selected bucket$/,
      /^reachable entity associated enrollment$/,
      /^unique grade 2 9 enrollment$/
    ]
  });

  addDefinition('modeled_enrollment_addition', {
    label: 'Modeled enrollment addition',
    kind: 'Modeled — separate',
    what: 'An estimated Grade 2–9 addition for school rows that do not carry source-reported enrollment.',
    how: 'Uses the documented enrollment model only for non-reported rows and reports the result separately from source-reported and derived-reported counts.',
    why: 'It provides sensitivity context but is excluded from the reported headline, primary city ranking, and reported-demand campus scenarios.',
    patterns: [
      /^modeled addition$/,
      /^modeled enrollment(?: addition)?$/,
      /^modeled students grade 2 9$/,
      /^estimated grade 2 9$/,
      /^estimated enrollment$/
    ]
  });

  addDefinition('known_residential_units', {
    label: 'Known residential units',
    kind: 'Directly observed rollup',
    what: 'Residential units explicitly supplied on named residential-project records.',
    how: 'Sums units only where a project record supplies a unit value. Unknown unit counts remain unavailable instead of being treated as zero or converted into households.',
    why: 'It indicates the depth of addressable residential-project inventory for marketing and operations; it is not a student, resident, family, or occupancy count.',
    patterns: [
      /^known residential units$/,
      /^known units$/,
      /^known project units$/,
      /^total residential units$/,
      /^residential units$/,
      /^residential units q4$/,
      /^total units$/
    ]
  });

  addDefinition('catchment_reported_students', {
    label: 'Catchment reported students',
    kind: 'Directly calculated',
    what: 'Derived reported Grade 2–9 enrollment attached to mapped qualifying schools inside the selected cell or catchment.',
    how: 'Sums the qualifying school values whose mapped campus or school point falls inside the selected geography. Overlapping catchments must be deduplicated.',
    why: 'It shows where school-based demand evidence is concentrated. It does not show where students live and must not be interpreted as residential demand.',
    patterns: [
      /^catchment reported students$/,
      /^reported students$/,
      /^reported students in catchment$/,
      /^reachable reported students$/,
      /^reachable grade 2 9 enrollment$/,
      /^reported premium plus grade 2 9 in catchment$/
    ]
  });

  addDefinition('school_count', {
    label: 'School count',
    kind: 'Directly counted',
    what: 'The number of qualifying school entities or source school records in the selected bucket and geography.',
    how: 'Counts distinct qualifying school entities after the platform’s canonical school-record handling. Physical campuses are reported separately where multiple entities share a location.',
    why: 'It indicates partnership breadth and market coverage; it does not measure enrollment size by itself.',
    patterns: [
      /^schools$/,
      /^school count$/,
      /^premium plus schools$/,
      /^private schools$/,
      /^selected bucket schools$/,
      /^canonical school entities$/,
      /^school entities$/,
      /^total no of private school listings$/,
      /^total no of schools$/
    ]
  });

  addDefinition('physical_campus_count', {
    label: 'Physical campuses',
    kind: 'Directly counted',
    what: 'Distinct mapped physical school locations after school entities at the same campus are grouped.',
    how: 'Groups qualifying school entities by their canonical campus identifier or shared mapped campus location, then counts those locations once.',
    why: 'It describes the number of physical partnership or map locations and prevents multi-entity campuses from being mistaken for separate sites.',
    patterns: [
      /^physical campuses$/,
      /^campus count$/,
      /^campuses in this hex$/,
      /^unique physical campuses$/
    ]
  });

  addDefinition('residential_project_count', {
    label: 'Residential projects',
    kind: 'Directly counted',
    what: 'Named residential-project or property-listing records in the selected geography.',
    how: 'Counts qualifying supplied project records once. The label “residential projects” is used unless a source explicitly establishes that a record is a residential society.',
    why: 'It provides a direct-marketing and operating shortlist. It is not a unit, household, resident, or premium-student count.',
    patterns: [
      /^residential projects$/,
      /^residential targets$/,
      /^residential project targets$/,
      /^project count$/,
      /^projects$/,
      /^premium societies$/,
      /^society count$/
    ]
  });

  addDefinition('campus_scenario', {
    label: 'Campus scenario',
    kind: 'Planning scenario',
    what: 'A planning range for fully supported campuses under a selected capture-rate assumption.',
    how: 'Multiplies derived reported Premium+ Grade 2–9 enrollment by 1%, 2%, or 3%, divides by 160 effective occupied seats (200 seats × 80% utilization), and rounds down to fully supported campuses.',
    why: 'It helps frame capacity discussions. It is not a forecast and excludes competition, overlap, pricing, site economics, and conversion uncertainty.',
    patterns: [
      /^campus scenario(?: range)?$/,
      /^campuses supported$/,
      /^centers supported$/,
      /^[123]% capture$/,
      /^campus capacity range$/,
      /^how many campuses could this market support$/,
      /^captured enrollment scenario [0-9.]+%$/,
      /^full [0-9]+ seat centers$/,
      /^minimum centers required$/,
      /^maximum supportable at [0-9.]+%$/,
      /^100% theoretical ceiling$/,
      /^[0-9.]+% capacity scenario$/
    ]
  });

  addDefinition('captured_students_scenario', {
    label: 'Captured students',
    kind: 'Planning scenario',
    what: 'The assumed share of derived reported Premium+ Grade 2–9 enrollment used in a capacity scenario.',
    how: 'Multiplies the derived reported Grade 2–9 count by the selected 1%, 2%, or 3% capture rate.',
    why: 'It is an input to scenario planning, not a prediction of how many students will enroll.',
    patterns: [
      /^captured students$/,
      /^captured demand$/,
      /^captured enrollment scenario(?: [123]%)?$/
    ]
  });

  addDefinition('workplace_anchor_count', {
    label: 'Workplace anchors',
    kind: 'Directly counted context',
    what: 'Supplied workplace or office-anchor records inside the selected geography.',
    how: 'Counts mapped workplace records that fall inside the city, cell, or catchment. Tier-1 counts use the supplied prominence tier where available.',
    why: 'It is directional operating context. It does not prove employee residence, premium-student demand, or school conversion.',
    patterns: [
      /^workplace anchors$/,
      /^office anchors$/,
      /^tier 1 offices$/,
      /^offices count$/,
      /^offices$/
    ]
  });

  addDefinition('hospital_count', {
    label: 'Hospital count',
    kind: 'Directly counted context',
    what: 'Supplied hospital records inside the selected geography.',
    how: 'Counts mapped hospital records that fall inside the selected city, cell, or catchment.',
    why: 'It is a supporting context and access signal, not a measure of premium students or residential demand.',
    patterns: [/^hospitals$/, /^hospital count$/]
  });

  addDefinition('concentration_share', {
    label: 'Demand concentration',
    kind: 'Directly calculated',
    what: 'The share of citywide derived reported Premium+ Grade 2–9 enrollment located at mapped schools in the selected top cells or geography.',
    how: 'Divides the qualifying mapped-school Grade 2–9 total in the selected geography by the corresponding citywide derived reported Grade 2–9 total.',
    why: 'It helps compare how clustered school evidence is. It describes school locations, not student homes.',
    patterns: [
      /^demand concentration$/,
      /^premium concentration$/,
      /^top 10 h3 share$/,
      /^top 10 concentration$/,
      /^student share$/
    ]
  });

  addDefinition('directional_score', {
    label: 'Directional score',
    kind: 'Directional indicator',
    what: 'A normalized comparison signal that combines or summarizes multiple evidence dimensions.',
    how: 'Applies the documented score components and weights, with normalization relative to the active market scope. Local context scores may use within-city normalization.',
    why: 'It supports prioritization but should always be read beside direct enrollment, school, project, and known-unit counts. It is not a demand count or forecast.',
    patterns: [
      /^score$/,
      /^final score$/,
      /^top score$/,
      /^context score$/,
      /^city evidence score$/,
      /^evidence score$/,
      /^school led score$/,
      /^affluence score$/,
      /^commercial score$/
    ]
  });

  addDefinition('candidate_rank', {
    label: 'Candidate rank',
    kind: 'Directional indicator',
    what: 'The selected city’s order among the active candidate markets for the current school audience.',
    how: 'Orders candidate cities by source-reported all-grade Premium+ enrollment. The benchmark market is kept separate, and any evidence score remains secondary context.',
    why: 'It gives a recommendation posture grounded in the most direct comparable student count, while local site choice still requires catchment validation.',
    patterns: [/^candidate rank$/, /^city posture$/, /^rank$/]
  });

  addDefinition('zone_count', {
    label: 'Zone count',
    kind: 'Directly counted',
    what: 'The number of supplied city zones represented in the current supporting-geography view.',
    how: 'Counts distinct named zone records in the active city dataset after the selected city and audience filters are applied.',
    why: 'It describes geographic coverage only; it is not a demand or market-size measure.',
    patterns: [/^zones$/, /^zone count$/]
  });

  addDefinition('enrollment_provenance', {
    label: 'Enrollment provenance',
    kind: 'Evidence lineage',
    what: 'The portion of the displayed school enrollment tied to source-reported school rows.',
    how: 'Groups qualifying enrollment by the supplied enrollment-source field. Modeled rows are counted separately.',
    why: 'It helps the client judge how much of a result is grounded in reported school evidence before acting on it.',
    patterns: [/^enrollment provenance$/]
  });

  const labelSelectors = [
    '[data-metric-key]',
    '.decision-question-card > span:first-child',
    '.legacy-city-grid article > span:first-child',
    '.school-kpi-grid article > span:first-child',
    '.client-summary-metric > span:first-child',
    '.client-school-primary-grid article > span:first-child',
    '.campus-scenario-grid article > span:first-child',
    '.school-planner-results article > span:first-child',
    '.school-evaluation-grid article > span:first-child',
    '.zone-summary-card > span:first-child',
    '.commercial-stat-label',
    '.commercial-catchment-metric > span:first-child',
    '.std-kpi-label',
    '.kpi-label',
    '.decision-table th',
    '.notion-table th',
    '.gumroad-table th'
  ];

  const tableSelectors = [
    '#app-sidebar table',
    '#app-right-panel table',
    '.full-page-data-overlay table',
    '.formulas-drawer table'
  ];

  let observer = null;
  let popover = null;
  let activeTrigger = null;
  let activeDefinition = null;
  let pinned = false;
  let closeTimer = null;
  let refreshFrame = null;

  function definitionFor(label, explicitKey) {
    if (explicitKey && definitions.has(explicitKey)) return definitions.get(explicitKey);
    const normalized = normalizeLabel(label);
    if (!normalized) return null;
    for (const key of definitionOrder) {
      const definition = definitions.get(key);
      if (definition.patterns.some(pattern => pattern.test(normalized))) return definition;
    }
    return null;
  }

  function textWithoutHelpControl(element) {
    const clone = element.cloneNode(true);
    clone.querySelectorAll('.metric-help-button').forEach(node => node.remove());
    return clone.textContent.replace(/\s+/g, ' ').trim();
  }

  function createTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  }

  function ensurePopover() {
    if (popover?.isConnected) return popover;
    popover = document.createElement('section');
    popover.id = POPOVER_ID;
    popover.className = 'metric-help-popover';
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-modal', 'false');
    popover.setAttribute('aria-live', 'polite');
    popover.hidden = true;

    const header = document.createElement('header');
    header.className = 'metric-help-popover-header';
    const titleGroup = document.createElement('div');
    titleGroup.className = 'metric-help-title-group';
    const kind = createTextElement('span', 'metric-help-kind', 'Metric');
    kind.id = `${POPOVER_ID}-kind`;
    const title = createTextElement('h3', 'metric-help-title', 'Metric details');
    title.id = `${POPOVER_ID}-title`;
    titleGroup.append(kind, title);
    const close = createTextElement('button', 'metric-help-close', 'Close');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close metric explanation');
    close.addEventListener('click', () => closePopover(true));
    header.append(titleGroup, close);

    const body = document.createElement('dl');
    body.className = 'metric-help-popover-body';
    ['what', 'how', 'why'].forEach(key => {
      const term = createTextElement('dt', `metric-help-term metric-help-${key}-term`, key[0].toUpperCase() + key.slice(1));
      const description = createTextElement('dd', `metric-help-description metric-help-${key}`, '');
      description.id = `${POPOVER_ID}-${key}`;
      body.append(term, description);
    });

    popover.setAttribute('aria-labelledby', title.id);
    popover.setAttribute('aria-describedby', `${POPOVER_ID}-what ${POPOVER_ID}-how ${POPOVER_ID}-why`);
    popover.append(header, body);
    popover.addEventListener('pointerenter', cancelScheduledClose);
    popover.addEventListener('pointerleave', scheduleClose);
    popover.addEventListener('focusin', cancelScheduledClose);
    popover.addEventListener('focusout', scheduleClose);
    document.body.appendChild(popover);
    return popover;
  }

  function fillPopover(definition) {
    const panel = ensurePopover();
    panel.querySelector(`#${POPOVER_ID}-kind`).textContent = definition.kind;
    panel.querySelector(`#${POPOVER_ID}-title`).textContent = definition.label;
    panel.querySelector(`#${POPOVER_ID}-what`).textContent = definition.what;
    panel.querySelector(`#${POPOVER_ID}-how`).textContent = definition.how;
    panel.querySelector(`#${POPOVER_ID}-why`).textContent = definition.why;
    panel.dataset.kind = normalizeLabel(definition.kind).replace(/\s+/g, '-');
  }

  function positionPopover() {
    if (!activeTrigger || !popover || popover.hidden || !activeTrigger.isConnected) return;
    const triggerRect = activeTrigger.getBoundingClientRect();
    const panelRect = popover.getBoundingClientRect();
    const margin = 10;
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;
    let left = triggerRect.left + triggerRect.width / 2 - panelRect.width / 2;
    left = Math.max(margin, Math.min(left, viewportWidth - panelRect.width - margin));
    const fitsBelow = triggerRect.bottom + margin + panelRect.height <= viewportHeight;
    const top = fitsBelow
      ? triggerRect.bottom + 8
      : Math.max(margin, triggerRect.top - panelRect.height - 8);
    popover.style.left = `${Math.round(left)}px`;
    popover.style.top = `${Math.round(top)}px`;
    popover.dataset.placement = fitsBelow ? 'bottom' : 'top';
  }

  function openPopover(trigger, definition, options) {
    cancelScheduledClose();
    if (activeTrigger && activeTrigger !== trigger) {
      activeTrigger.setAttribute('aria-expanded', 'false');
    }
    activeTrigger = trigger;
    activeDefinition = definition;
    pinned = Boolean(options?.pinned);
    fillPopover(definition);
    popover.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    requestAnimationFrame(positionPopover);
  }

  function closePopover(restoreFocus) {
    cancelScheduledClose();
    if (!popover || popover.hidden) return;
    const trigger = activeTrigger;
    popover.hidden = true;
    popover.removeAttribute('data-placement');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    activeTrigger = null;
    activeDefinition = null;
    pinned = false;
    if (restoreFocus && trigger?.isConnected) trigger.focus();
  }

  function cancelScheduledClose() {
    if (closeTimer) global.clearTimeout(closeTimer);
    closeTimer = null;
  }

  function scheduleClose() {
    cancelScheduledClose();
    closeTimer = global.setTimeout(() => {
      const focusInside = popover?.contains(document.activeElement) || activeTrigger === document.activeElement;
      if (!pinned && !focusInside) closePopover(false);
    }, CLOSE_DELAY_MS);
  }

  function createHelpButton(label, definition) {
    const button = createTextElement('button', 'metric-help-button', 'i');
    button.type = 'button';
    button.setAttribute('aria-label', `Explain ${label}`);
    button.setAttribute('aria-controls', POPOVER_ID);
    button.setAttribute('aria-expanded', 'false');
    button.dataset.metricHelpKey = definition.key;

    button.addEventListener('pointerenter', () => openPopover(button, definition, { pinned: false }));
    button.addEventListener('pointerleave', scheduleClose);
    button.addEventListener('focus', () => openPopover(button, definition, { pinned: false }));
    button.addEventListener('blur', scheduleClose);
    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      const shouldClose = activeTrigger === button && pinned && !popover.hidden;
      if (shouldClose) closePopover(false);
      else openPopover(button, definition, { pinned: true });
    });
    return button;
  }

  function enhanceLabel(element) {
    if (!(element instanceof Element)) return;
    if (element.closest('.welcome-landing-page, .metric-help-popover')) return;
    const label = textWithoutHelpControl(element);
    const explicitKey = element.getAttribute('data-metric-key');
    const definition = definitionFor(label, explicitKey);
    const nextKey = definition ? definition.key : 'unmatched';
    if (element.getAttribute(ENHANCED_ATTR) === nextKey) return;
    const previousButton = element.querySelector(':scope > .metric-help-button');
    if (previousButton === activeTrigger) closePopover(false);
    previousButton?.remove();
    element.classList.remove('metric-help-label');
    element.setAttribute(ENHANCED_ATTR, definition ? definition.key : 'unmatched');
    if (!definition) return;
    element.classList.add('metric-help-label');
    element.appendChild(createHelpButton(label, definition));
  }

  function headerText(header) {
    return textWithoutHelpControl(header).replace(/[↑↓]/g, '').trim();
  }

  function decorateTable(table) {
    if (!(table instanceof HTMLTableElement) || table.closest('.welcome-landing-page')) return;
    const headers = [...table.querySelectorAll('thead tr:last-child th')];
    if (!headers.length) return;
    const labels = headers.map(headerText);
    table.classList.add(MOBILE_TABLE_CLASS);
    table.setAttribute(TABLE_ATTR, 'true');
    table.querySelectorAll('tbody tr').forEach(row => {
      [...row.children].filter(cell => cell.tagName === 'TD').forEach((cell, index) => {
        const label = labels[index] || '';
        if (label) cell.setAttribute('data-label', label);
      });
    });
  }

  function descendantsIncludingRoot(root, selectors) {
    const output = [];
    if (root instanceof Element && selectors.some(selector => root.matches(selector))) output.push(root);
    if (root?.querySelectorAll) output.push(...root.querySelectorAll(selectors.join(',')));
    return output;
  }

  function enhance(root) {
    descendantsIncludingRoot(root, labelSelectors).forEach(enhanceLabel);
    descendantsIncludingRoot(root, tableSelectors).forEach(decorateTable);
    const ancestorTable = root instanceof Element ? root.closest('table') : null;
    if (ancestorTable && !ancestorTable.closest('.welcome-landing-page')) decorateTable(ancestorTable);
  }

  function refresh(root) {
    enhance(root || document);
  }

  function scheduleRefresh(root) {
    if (refreshFrame) return;
    refreshFrame = requestAnimationFrame(() => {
      refreshFrame = null;
      if (activeTrigger && !activeTrigger.isConnected) closePopover(false);
      refresh(root?.isConnected ? root : document);
    });
  }

  function handleDocumentKeydown(event) {
    if (event.key !== 'Escape' || !popover || popover.hidden) return;
    event.preventDefault();
    closePopover(true);
  }

  function handleDocumentPointerdown(event) {
    if (!popover || popover.hidden) return;
    if (popover.contains(event.target) || activeTrigger?.contains(event.target)) return;
    closePopover(false);
  }

  function handleViewportChange() {
    if (popover && !popover.hidden) positionPopover();
  }

  function init() {
    if (observer || !document.body) return;
    ensurePopover();
    refresh(document);
    observer = new MutationObserver(mutations => {
      const mutation = mutations.find(item => item.addedNodes?.length) || mutations[0];
      const target = mutation?.target?.nodeType === Node.TEXT_NODE
        ? mutation.target.parentElement
        : mutation?.target;
      scheduleRefresh(target || document);
    });
    observer.observe(document.body, { childList: true, characterData: true, subtree: true });
    document.addEventListener('keydown', handleDocumentKeydown);
    document.addEventListener('pointerdown', handleDocumentPointerdown, true);
    global.addEventListener('resize', handleViewportChange, { passive: true });
    global.addEventListener('scroll', handleViewportChange, { passive: true, capture: true });
  }

  function destroy() {
    observer?.disconnect();
    observer = null;
    if (refreshFrame) cancelAnimationFrame(refreshFrame);
    refreshFrame = null;
    cancelScheduledClose();
    document.removeEventListener('keydown', handleDocumentKeydown);
    document.removeEventListener('pointerdown', handleDocumentPointerdown, true);
    global.removeEventListener('resize', handleViewportChange);
    global.removeEventListener('scroll', handleViewportChange, true);
    document.querySelectorAll(`[${ENHANCED_ATTR}]`).forEach(element => {
      element.querySelectorAll(':scope > .metric-help-button').forEach(button => button.remove());
      element.classList.remove('metric-help-label');
      element.removeAttribute(ENHANCED_ATTR);
    });
    document.querySelectorAll(`[${TABLE_ATTR}]`).forEach(table => {
      table.classList.remove(MOBILE_TABLE_CLASS);
      table.removeAttribute(TABLE_ATTR);
      table.querySelectorAll('td[data-label]').forEach(cell => cell.removeAttribute('data-label'));
    });
    popover?.remove();
    popover = null;
    activeTrigger = null;
    activeDefinition = null;
    pinned = false;
  }

  function register(key, definition) {
    addDefinition(key, definition);
    if (document.body) refresh(document);
  }

  global.RanchoMetricHelp = Object.freeze({
    init,
    destroy,
    refresh,
    register,
    getDefinition(key) { return definitions.get(key) || null; },
    get registry() { return Object.freeze(Object.fromEntries(definitions)); }
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
}(window));
