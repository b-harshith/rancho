/**
 * Reusable layout engine for details pages (Zone, Micro Market, Catchment, Commercial, Hex)
 */

window.renderStandardDetails = function(containerElement, data) {
  if (!containerElement) return;

  const title = data.title || 'Details';
  const badgeHtml = data.badge ? `<span class="std-details-badge" id="${data.badgeId || ''}">${data.badge}</span>` : '';
  const headerActionsHtml = data.headerActions || '';
  
  // Build KPI grid
  let kpisHtml = '';
  if (data.kpis && data.kpis.length > 0) {
    kpisHtml = `
      <div class="std-kpi-grid">
        ${data.kpis.map(kpi => {
          const lockedClass = kpi.locked ? ' blurred-item' : '';
          const clickAttr = kpi.locked ? 'onclick="openUnlockModal()"' : '';
          const cursorStyle = kpi.locked ? 'style="cursor: pointer;"' : '';
          return `
            <div class="std-kpi-card${lockedClass}" ${clickAttr} ${cursorStyle}>
              <span class="std-kpi-value" id="${kpi.id || ''}">${kpi.value}</span>
              <span class="std-kpi-label">${kpi.label}</span>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  // Build metadata bar
  let metadataHtml = '';
  if (data.metadata && Object.keys(data.metadata).length > 0) {
    metadataHtml = `
      <div class="std-metadata-list">
        ${Object.entries(data.metadata).map(([label, value]) => `
          <div class="std-metadata-item">
            <span class="std-metadata-label">${label}</span>
            <span class="std-metadata-value">${value}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  // Build accordion sections
  let sectionsHtml = '';
  if (data.sections && data.sections.length > 0) {
    sectionsHtml = `
      <div class="std-sections-wrapper">
        ${data.sections.map((section, idx) => {
          const openAttr = section.open ? 'open' : '';
          const copyBtnHtml = section.onCopy 
            ? `<button class="std-export-btn" onclick="${section.onCopy}">📋 Copy Top 25</button>` 
            : '';
          return `
            <details ${openAttr} class="std-details-accordion">
              <summary>
                <div class="std-summary-wrapper">
                  <span>${section.title} (<span id="${section.countId || ''}">${section.count || 0}</span>)</span>
                  ${copyBtnHtml}
                </div>
              </summary>
              <div class="std-details-content-scroll" id="${section.id || ''}">
                ${section.contentHtml || '<div style="padding: 10px; color:#6b7280;">No entries in this section</div>'}
              </div>
            </details>
          `;
        }).join('')}
      </div>
    `;
  }

  const mainContentHtml = data.mainContent || '';

  // Render unified HTML template
  containerElement.innerHTML = `
    <div class="standard-details-layout">
      <!-- Details Header -->
      <div class="std-details-header">
        <div class="std-title-group">
          <h3 class="std-details-title" id="${data.titleId || ''}">${title}</h3>
          ${badgeHtml}
        </div>
        <div class="std-header-actions">
          ${headerActionsHtml}
          <button class="std-close-btn" onclick="${data.onClose || ''}">✕ Close</button>
        </div>
      </div>

      <!-- Details Body -->
      <div class="std-details-body">
        <!-- Sidebar stats -->
        <div class="std-details-sidebar">
          ${kpisHtml}
          ${metadataHtml}
        </div>

        <!-- Main content area (Charts, Lists, Accordions) -->
        <div class="std-details-main">
          ${mainContentHtml}
          ${sectionsHtml}
        </div>
      </div>
    </div>
  `;
};
