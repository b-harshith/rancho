import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "src" / "public"


class FrontendMulticityStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_html = (PUBLIC / "index.html").read_text(encoding="utf-8")
        cls.index_js = (PUBLIC / "index.js").read_text(encoding="utf-8")
        cls.events_js = (PUBLIC / "events.js").read_text(encoding="utf-8")
        cls.multicity_html = (PUBLIC / "multicity.html").read_text(encoding="utf-8")
        cls.multicity_js = (PUBLIC / "multicity.js").read_text(encoding="utf-8")

    def test_legacy_deep_dive_has_fixed_four_city_selector_and_overview_panel(self):
        self.assertIn('id="legacy-city-select"', self.index_html)
        self.assertIn('id="legacy-city-overview"', self.index_html)
        for city in ("delhi_ncr", "bengaluru", "hyderabad", "mumbai"):
            self.assertIn(f'value="{city}"', self.index_html)
            self.assertIn(city, self.index_js)
        self.assertNotIn('value="pune"', self.index_html)
        self.assertIn('id="legacy-category-select"', self.index_html)
        self.assertIn("data/city_legacy/${activeLegacyCityId}/${filename}", self.index_js)
        self.assertIn('id="tab-btn-zones"', self.index_html)
        self.assertIn('id="tab-btn-catchment"', self.index_html)
        self.assertNotIn('id="tab-btn-commercial"', self.index_html)

    def test_deep_dive_restores_secure_client_key_catchment(self):
        self.assertIn('id="catchment-google-api-key"', self.index_html)
        self.assertIn('type="password"', self.index_html)
        self.assertIn("X-Google-Maps-Api-Key", self.index_js)
        self.assertIn("catchmentRequestOptions()", self.index_js)
        self.assertNotIn("google_maps_api_key:", self.index_js)
        self.assertIn("getCatchmentGoogleApiKey", self.index_js)
        self.assertIn("rl_onboarding_seen_v2", self.index_js)

    def test_deep_dive_integrates_metric_help_and_trust_onboarding(self):
        metric_js = (PUBLIC / "metric-help.js").read_text(encoding="utf-8")
        metric_css = (PUBLIC / "metric-help.css").read_text(encoding="utf-8")
        self.assertIn("metric-help.js", self.index_html)
        self.assertIn("metric-help.css", self.index_html)
        self.assertIn("['what', 'how', 'why']", metric_js)
        self.assertIn("MutationObserver", metric_js)
        self.assertIn("@container (max-width: 560px)", metric_css)
        self.assertIn("function renderTrustOnboardingMarkup", self.index_js)
        self.assertIn("What was fixed and verified", self.index_js)

    def test_legacy_deep_dive_uses_generated_category_h3_geojson(self):
        self.assertIn("legacyCityHexLayer", self.index_js)
        self.assertIn("data/multicity/hexes/${activeLegacyCityId}__${activeLegacyCategoryId}.geojson", self.index_js)
        self.assertIn("known units unavailable", self.index_js.lower())
        self.assertIn("Annual-fee thresholds are not supported", self.index_js)

    def test_legacy_deep_dive_removes_fee_url_parameters(self):
        self.assertIn("url.searchParams.delete('school_fee')", self.index_js)
        self.assertIn("url.searchParams.delete('school_view')", self.index_js)
        self.assertNotIn("fee_sensitivity_thresholds: String(schoolMarketState.cutoff)", self.index_js)
        self.assertIn("city: activeLegacyCityId", self.index_js)
        self.assertIn("category: activeLegacyCategoryId", self.index_js)

    def test_legacy_deep_dive_is_city_aware(self):
        self.assertIn("const cityAwareTabs", self.index_js)
        self.assertIn("button.classList.remove('bengaluru-only-tab')", self.index_js)
        self.assertIn("pane?.classList.remove('legacy-restricted-pane')", self.index_js)
        self.assertIn("'#pane-summary > .recommendation-card'", self.index_js)
        self.assertIn("'#pane-summary > .school-market-section'", self.index_js)
        self.assertIn("client-school-market-body", self.index_js)
        self.assertIn("office anchors are shown as workplace evidence", self.index_js)
        self.assertIn("fetchJsonResource(generatedLegacyDataResource('client_summary.json')", self.index_js)

    def test_zone_full_data_table_is_wired_and_bucket_based(self):
        self.assertIn("id=\"full-data-modal\"", self.index_html)
        self.assertIn("button-view-full-data-table-zone-details", self.index_js)
        self.assertIn("openFullDataView();", self.index_js)
        self.assertIn("function getFullDataHeaders", self.index_js)
        self.assertIn("id=\"full-data-pagination\"", self.index_html)
        self.assertIn("FULL_DATA_PAGE_SIZE = 100", self.index_js)
        self.assertIn("function renderFullDataPagination", self.index_js)
        self.assertIn("Fee Bucket", self.index_js)
        self.assertIn("fee_bucket: feeRange", self.index_js)
        self.assertNotIn("Custom annual fee", self.index_js)
        self.assertIn("normalizedSchoolCampuses = normalizeSchoolCampusCollection(normalizedSchoolEntities)", self.index_js)
        self.assertNotIn("Example: Indiranagar 100 Feet Road", self.index_html)
        self.assertIn("graph-network-help-text", self.index_html)

    def test_school_market_reacts_to_selected_bucket(self):
        self.assertIn("LEGACY_CATEGORY_IDS.includes(initialLegacyCategoryId)", self.index_js)
        self.assertIn("categorySelector.addEventListener('change', async () =>", self.index_js)
        self.assertIn("renderSchoolExecutiveSurfaces();", self.index_js)
        self.assertIn("renderSchoolMarket();", self.index_js)
        self.assertIn("const audienceEntities = getSchoolAudienceEntities();", self.index_js)
        self.assertIn("const audience = getSchoolAudienceEntities();", self.index_js)
        self.assertNotIn("const summaryQ4 = schoolMarketState.summary?.bucket_summaries?.[activeLegacyCategoryId]", self.index_js)
        self.assertIn("legacySchoolCategoryBuckets(activeLegacyCategoryId).has(meta.key)", self.index_js)

    def test_zone_school_rollups_follow_selected_audience(self):
        self.assertIn("function getSchoolAudienceCampuses()", self.index_js)
        self.assertIn("function getAudienceZoneEntries()", self.index_js)
        self.assertIn("const zoneEntries = getAudienceZoneEntries()", self.index_js)
        self.assertIn("const campusRows = getSchoolAudienceCampuses()", self.index_js)
        self.assertIn("activeDetailsData.zone.schools = zoneSchoolEvidence.allInside", self.index_js)
        self.assertIn("renderRolledUpAssetsMapLayers('zone');", self.index_js)
        self.assertIn("refreshSchoolAudienceDependentViews(previousRolledUpScope)", self.index_js)
        self.assertIn("schools: getSchoolAudienceCampuses()", self.index_js)

    def test_school_directory_search_and_map_focus_are_wired(self):
        for element_id in (
            "school-directory-search",
            "school-directory-audience-only",
            "school-directory-sort",
            "school-directory-body",
            "school-directory-prev",
            "school-directory-next",
        ):
            self.assertIn(f'id="{element_id}"', self.index_html)
        self.assertIn("function renderSchoolDirectory()", self.index_js)
        self.assertIn("function focusSchoolDirectoryCampus(campusId)", self.index_js)
        self.assertIn("map.flyTo([Number(campus.lat), Number(campus.lon)]", self.index_js)
        self.assertIn("setSchoolDirectoryQuery(event.target.value)", self.events_js)
        self.assertIn("focusSchoolDirectoryCampus(row.dataset.directoryCampusId)", self.events_js)

    def test_main_portal_has_unique_dom_ids_and_direct_evidence_map(self):
        ids = re.findall(r'id="([^"]+)"', self.multicity_html)
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        self.assertEqual(duplicates, [])
        self.assertIn('id="map-layer-summary"', self.multicity_html)
        self.assertIn('data-map-layer="schools"', self.multicity_html)
        self.assertIn('data-map-layer="projects"', self.multicity_html)
        self.assertIn("reported_enrollment_total", self.multicity_js)
        self.assertIn("reported_students_grade_2_9", self.multicity_js)
        self.assertIn("primaryCityStudents(right.metrics) - primaryCityStudents(left.metrics)", self.multicity_js)
        self.assertIn("/data/multicity/hexes/${state.city}__${state.category}.geojson", self.multicity_js)
        self.assertLess(
            self.multicity_js.index("categoryMetric.reported_students_grade_2_9"),
            self.multicity_js.index("properties.reported_students_grade_2_9", self.multicity_js.index("categoryMetric.reported_students_grade_2_9")),
        )
        self.assertIn("const citywideTotal = directStudents(row.metrics)", self.multicity_js)
        self.assertNotIn("Evidence snapshot", self.multicity_js)

    def test_main_portal_fixed_city_scope_and_deep_link_history(self):
        city_buttons = re.findall(r'data-city="([^"]+)"', self.multicity_html)
        self.assertEqual(city_buttons, ["delhi_ncr", "bengaluru", "hyderabad", "mumbai"])
        self.assertNotIn('data-city="pune"', self.multicity_html)
        self.assertIn("location.pathname.match", self.multicity_js)
        self.assertIn("addEventListener('popstate'", self.multicity_js)
        self.assertIn("url.pathname = `/city/${state.city}`", self.multicity_js)


if __name__ == "__main__":
    unittest.main()
