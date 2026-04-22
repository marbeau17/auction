/**
 * CVLPOS Dashboard Charts — 松プラン integrated view
 *
 * Renders the 4 chart types from docs/CVLPOS_松プラン_ワイヤーフレーム.html:
 *   - NAVChart          line     (物理的価値 vs 累積回収 vs NFAV)
 *   - LTVBar            bar      (LTV 分布)
 *   - FundMixDonut      doughnut (ファンド別 AUM)
 *   - MonthlyIncomeChart bar(stacked) (月次 CF)
 *
 * Behaviour:
 *   - Reads body[data-dash-variant] (A | B | C) and only renders canvases that
 *     are present in the DOM (variant-dependent).
 *   - Exposes `window.CVLDashboard.reload()` for the 更新 button.
 *   - Auto-refreshes every 5 minutes.
 *   - Chart data uses inline fixtures that match the wireframe verbatim.
 *     The /api/v1/dashboard/kpi/json wiring is Phase 4.
 */
(function () {
  'use strict';

  // ---- Design tokens (mirror :root in style.css) ----
  var NAVY = '#0E2747';
  var GOLD = '#C9A24A';
  var GOLD_2 = '#C48A2A';
  var GOLD_LIGHT = 'rgba(201, 162, 74, 0.08)';
  var GREEN = '#3E8E5A';
  var AMBER = '#C48A2A';
  var RED = '#B5443A';
  var SLATE = '#7E9DBF';
  var TEXT_MUTED = '#6E6A5C';
  var GRID = 'rgba(14,39,71,.06)';

  var FONT_JP = 'Noto Sans JP';
  var REFRESH_INTERVAL = 5 * 60 * 1000; // 5 min

  // ---- Inline fixtures (spec-bearing values — see wireframe lines 243-266, 494-562) ----
  var FUNDS = [
    { id: 'f15', name: 'カーチスファンド15号', aum: 320, color: '#C9A24A' },
    { id: 'f14', name: 'カーチスファンド14号', aum: 280, color: '#7E9DBF' },
    { id: 'f13', name: 'カーチスファンド13号', aum: 230, color: '#3E8E5A' },
    { id: 'f12', name: 'カーチスファンド12号', aum: 160, color: '#B5443A' },
    { id: 'f11', name: 'カーチスファンド11号', aum: 130, color: '#6E6A5C' }
  ];

  var NAV_MONTHS = [];
  for (var _i = 0; _i < 37; _i++) NAV_MONTHS.push(_i);

  // ---- Chart registry ----
  var charts = {};

  function destroyChart(key) {
    if (charts[key]) {
      try { charts[key].destroy(); } catch (e) { /* ignore */ }
      charts[key] = null;
    }
  }

  function canvasAvailable(id) {
    var el = document.getElementById(id);
    if (!el || typeof Chart === 'undefined') return null;
    // Only render if visible (variant-dependent)
    if (el.offsetParent === null) return null;
    return el;
  }

  // ---- Chart builders ----

  function buildNavChartConfig() {
    var physical = NAV_MONTHS.map(function (m) { return 100 - m * 1.95; });
    var cashRecovered = NAV_MONTHS.map(function (m) { return Math.min(100, m * 2.22); });
    var nfav = NAV_MONTHS.map(function (m) {
      return Math.max(60, (100 - m * 1.95) + Math.min(100, m * 2.22) - 100 + 100 + m * 0.18);
    });

    return {
      type: 'line',
      data: {
        labels: NAV_MONTHS.map(function (m) { return 'M' + String(m).padStart(2, '0'); }),
        datasets: [
          {
            label: '物理的車両価値',
            data: physical,
            borderColor: SLATE,
            backgroundColor: 'rgba(126,157,191,0.1)',
            fill: true, tension: 0.25, borderWidth: 2, pointRadius: 0
          },
          {
            label: '累積キャッシュ回収',
            data: cashRecovered,
            borderColor: GOLD,
            backgroundColor: 'rgba(201,162,74,0.08)',
            fill: false, tension: 0.25, borderWidth: 2, pointRadius: 0
          },
          {
            label: 'Net Fund Asset Value',
            data: nfav,
            borderColor: NAVY,
            backgroundColor: 'rgba(14,39,71,0.12)',
            fill: true, tension: 0.25, borderWidth: 2.5, pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { font: { family: FONT_JP, size: 11 }, color: TEXT_MUTED, usePointStyle: true, pointStyle: 'rectRounded' }
          },
          tooltip: { mode: 'index', intersect: false }
        },
        scales: {
          y: {
            min: 0, max: 120,
            grid: { color: GRID },
            ticks: { callback: function (v) { return v + '%'; }, font: { size: 10 }, color: TEXT_MUTED }
          },
          x: {
            grid: { display: false },
            ticks: { autoSkip: true, maxTicksLimit: 10, font: { size: 10 }, color: TEXT_MUTED }
          }
        }
      }
    };
  }

  function buildLtvBarConfig() {
    return {
      type: 'bar',
      data: {
        labels: ['0-20%', '20-40%', '40-60%', '60-80%', '80-100%', '100%+'],
        datasets: [{
          data: [22, 44, 54, 18, 3, 1],
          backgroundColor: [GREEN, GREEN, GREEN, AMBER, RED, '#7A1F1A'],
          borderRadius: 4
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (ct) { return ct.parsed.x + '台'; } } }
        },
        scales: {
          x: { grid: { color: GRID }, ticks: { font: { size: 10 }, color: TEXT_MUTED } },
          y: { grid: { display: false }, ticks: { font: { size: 10, family: 'JetBrains Mono' }, color: '#52503F' } }
        }
      }
    };
  }

  function buildFundMixDonutConfig() {
    return {
      type: 'doughnut',
      data: {
        labels: FUNDS.map(function (f) { return f.name; }),
        datasets: [{
          data: FUNDS.map(function (f) { return f.aum; }),
          backgroundColor: FUNDS.map(function (f) { return f.color; }),
          borderWidth: 3,
          borderColor: '#fff'
        }]
      },
      options: {
        cutout: '70%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { font: { size: 10, family: FONT_JP }, color: '#52503F', boxWidth: 10, padding: 8 }
          }
        },
        responsive: true,
        maintainAspectRatio: false
      }
    };
  }

  function buildMonthlyIncomeConfig() {
    return {
      type: 'bar',
      data: {
        labels: ['11月', '12月', '1月', '2月', '3月', '4月'],
        datasets: [
          { label: 'リース料収入', data: [152, 162, 168, 175, 178, 182], backgroundColor: NAVY, borderRadius: 3, stack: 'a' },
          { label: 'メンテ・保険', data: [12, 13, 13, 14, 14, 15], backgroundColor: GOLD, borderRadius: 3, stack: 'a' }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { font: { size: 11, family: FONT_JP }, color: '#52503F', usePointStyle: true, pointStyle: 'rectRounded' }
          }
        },
        scales: {
          y: {
            stacked: true,
            grid: { color: GRID },
            ticks: { callback: function (v) { return '¥' + v + 'M'; }, font: { size: 10 }, color: TEXT_MUTED }
          },
          x: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 }, color: TEXT_MUTED } }
        }
      }
    };
  }

  // ---- Render helpers ----

  function renderCanvas(canvasId, configFn) {
    var el = canvasAvailable(canvasId);
    if (!el) return;
    destroyChart(canvasId);
    charts[canvasId] = new Chart(el.getContext('2d'), configFn());
  }

  // Map of canvas id -> builder fn
  var CHART_MAP = {
    'chart-nav-A': buildNavChartConfig,
    'chart-nav-B': buildNavChartConfig,
    'chart-nav-C': buildNavChartConfig,
    'chart-fundmix-A': buildFundMixDonutConfig,
    'chart-fundmix-B': buildFundMixDonutConfig,
    'chart-income-B': buildMonthlyIncomeConfig,
    'chart-income-C': buildMonthlyIncomeConfig,
    'chart-ltv-C': buildLtvBarConfig
  };

  function renderAll() {
    Object.keys(CHART_MAP).forEach(function (id) {
      renderCanvas(id, CHART_MAP[id]);
    });
  }

  function destroyAll() {
    Object.keys(charts).forEach(destroyChart);
  }

  function renderVariant(/* variant */) {
    // Variant swap is driven by CSS (display:none). We re-run renderAll so
    // newly visible canvases get a chart instance and hidden ones are cleared.
    destroyAll();
    // Defer so CSS display update settles before we measure offsetParent.
    setTimeout(renderAll, 0);
  }

  // ---- Init + public API ----

  function init() {
    renderAll();
  }

  window.CVLDashboard = {
    reload: renderVariant,
    renderVariant: renderVariant,
    destroyAll: destroyAll
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Re-render when variant changes (event dispatched by _var_bar / _tweaks_panel)
  window.addEventListener('cvl:variant-change', function () { renderVariant(); });

  // Auto-refresh every 5 minutes (keeps parity with Phase 1 behaviour)
  setInterval(renderVariant, REFRESH_INTERVAL);

})();
