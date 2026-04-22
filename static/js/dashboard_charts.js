/**
 * CVLPOS Dashboard Charts
 * Fetches KPI data and renders Chart.js charts with navy/gold theme.
 * Auto-refreshes every 5 minutes.
 */
(function () {
  'use strict';

  // 松プラン design tokens (see static/css/style.css :root)
  var NAVY = '#0E2747';
  var GOLD = '#C9A24A';
  var GOLD_LIGHT = 'rgba(201, 162, 74, 0.25)';
  var API_URL = '/api/v1/dashboard/kpi/json';
  var REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

  // Chart instances for destroy-on-refresh
  var charts = {};

  // ---- Helpers ----

  function fmt(n) {
    if (n == null || isNaN(n)) return '--';
    return Number(n).toLocaleString('ja-JP');
  }

  function fmtYen(n) {
    if (n == null || isNaN(n)) return '--';
    if (n >= 100000000) return (n / 100000000).toFixed(1) + '\u5104';
    if (n >= 10000) return fmt(Math.round(n / 10000)) + '\u4E07';
    return fmt(n);
  }

  function invoiceStatusBadge(status) {
    var map = {
      paid: '<span class="badge badge--success">\u5165\u91D1\u6E08</span>',
      pending: '<span class="badge badge--warning">\u672A\u5165\u91D1</span>',
      overdue: '<span class="badge badge--danger">\u5EF6\u6EDE</span>',
      cancelled: '<span class="badge">\u30AD\u30E3\u30F3\u30BB\u30EB</span>'
    };
    return map[status] || '<span class="badge">' + (status || '-') + '</span>';
  }

  function showLoading(canvasId) {
    var el = document.getElementById(canvasId);
    if (el && el.parentElement) {
      el.parentElement.style.opacity = '0.5';
    }
  }

  function hideLoading(canvasId) {
    var el = document.getElementById(canvasId);
    if (el && el.parentElement) {
      el.parentElement.style.opacity = '1';
    }
  }

  function destroyChart(key) {
    if (charts[key]) {
      charts[key].destroy();
      charts[key] = null;
    }
  }

  // ---- Chart Renderers ----

  function renderMonthlyIncomeChart(trend) {
    var canvasId = 'monthly-income-chart';
    var ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === 'undefined') return;

    destroyChart(canvasId);

    var labels = trend.map(function (t) { return t.month; });
    var amounts = trend.map(function (t) { return t.amount; });

    charts[canvasId] = new Chart(ctx.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: '\u30EA\u30FC\u30B9\u53CE\u5165 (\u5186)',
          data: amounts,
          backgroundColor: NAVY,
          hoverBackgroundColor: GOLD,
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) { return '\u00A5' + Number(ctx.raw).toLocaleString('ja-JP'); }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: function (v) {
                if (v >= 10000) return (v / 10000) + '\u4E07';
                return v;
              }
            },
            grid: { color: 'rgba(0,0,0,0.06)' }
          },
          x: {
            grid: { display: false }
          }
        }
      }
    });
    hideLoading(canvasId);
  }

  function renderInvoiceStatusChart(breakdown) {
    var canvasId = 'invoice-status-chart';
    var ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === 'undefined') return;

    destroyChart(canvasId);

    var statusLabels = ['\u5165\u91D1\u6E08', '\u672A\u5165\u91D1', '\u5EF6\u6EDE', '\u30AD\u30E3\u30F3\u30BB\u30EB'];
    var statusKeys = ['paid', 'pending', 'overdue', 'cancelled'];
    var statusValues = statusKeys.map(function (k) { return breakdown[k] || 0; });
    var statusColors = [GOLD, NAVY, '#dc3545', '#94a3b8'];

    charts[canvasId] = new Chart(ctx.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: statusLabels,
        datasets: [{
          data: statusValues,
          backgroundColor: statusColors,
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: '60%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { boxWidth: 12, padding: 12, font: { size: 12 } }
          }
        }
      }
    });
    hideLoading(canvasId);
  }

  function renderNavTrendChart(navTrend) {
    var canvasId = 'nav-trend-chart';
    var ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === 'undefined') return;
    if (!navTrend || navTrend.length === 0) {
      // Hide the card if no data
      var card = ctx.closest('.card');
      if (card) card.style.display = 'none';
      return;
    }

    destroyChart(canvasId);

    // Show the card if data is present
    var card = ctx.closest('.card');
    if (card) card.style.display = '';

    var labels = navTrend.map(function (t) { return t.month || t.date; });
    var values = navTrend.map(function (t) { return t.nav || t.amount; });

    charts[canvasId] = new Chart(ctx.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'NAV',
          data: values,
          borderColor: NAVY,
          backgroundColor: GOLD_LIGHT,
          fill: true,
          tension: 0.3,
          pointBackgroundColor: GOLD,
          pointBorderColor: NAVY,
          pointRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) { return '\u00A5' + Number(ctx.raw).toLocaleString('ja-JP'); }
            }
          }
        },
        scales: {
          y: {
            ticks: {
              callback: function (v) {
                if (v >= 10000) return (v / 10000) + '\u4E07';
                return v;
              }
            },
            grid: { color: 'rgba(0,0,0,0.06)' }
          },
          x: {
            grid: { display: false }
          }
        }
      }
    });
    hideLoading(canvasId);
  }

  // ---- KPI population ----

  function populateKPIs(d) {
    var setTxt = function (id, val) {
      var el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    setTxt('kpi-vehicles-leased', fmt(d.total_vehicles_leased));
    setTxt('kpi-total-investment', fmtYen(d.total_investment_amount));
    setTxt('kpi-monthly-billing', fmtYen(d.monthly_billing_amount));
    setTxt('kpi-collection-rate', d.collection_rate != null ? d.collection_rate.toFixed(1) : '--');
    setTxt('kpi-overdue-count', fmt(d.overdue_count));
    if (d.average_yield_rate != null) {
      setTxt('kpi-avg-yield', d.average_yield_rate.toFixed(1) + '%');
    }
    setTxt('kpi-profit-conversion', fmt(d.profit_conversion_funds));

    // Overdue highlight
    if (d.overdue_count > 0) {
      var el = document.getElementById('kpi-overdue-count');
      if (el) el.style.color = 'var(--danger, #dc3545)';
    }

    // Recent invoices table
    var invoices = d.recent_invoices || [];
    var tbody = document.getElementById('recent-invoices-body');
    if (tbody) {
      if (invoices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">\u8ACB\u6C42\u30C7\u30FC\u30BF\u304C\u3042\u308A\u307E\u305B\u3093\u3002</td></tr>';
      } else {
        tbody.innerHTML = invoices.map(function (inv) {
          return '<tr>'
            + '<td>' + (inv.invoice_number || '-') + '</td>'
            + '<td>' + (inv.customer_name || '-') + '</td>'
            + '<td class="text-right">&yen;' + fmt(inv.amount) + '</td>'
            + '<td>' + (inv.due_date || '-') + '</td>'
            + '<td>' + invoiceStatusBadge(inv.status) + '</td>'
            + '</tr>';
        }).join('');
      }
    }
  }

  // ---- Main fetch & render ----

  function loadDashboard() {
    showLoading('monthly-income-chart');
    showLoading('invoice-status-chart');
    showLoading('nav-trend-chart');

    fetch(API_URL)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        populateKPIs(d);
        renderMonthlyIncomeChart(d.monthly_income_trend || []);
        renderInvoiceStatusChart(d.invoice_status_breakdown || {});
        renderNavTrendChart(d.nav_trend || []);
      })
      .catch(function (err) {
        console.warn('Dashboard KPI fetch error:', err);
        hideLoading('monthly-income-chart');
        hideLoading('invoice-status-chart');
        hideLoading('nav-trend-chart');
      });
  }

  // Initial load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadDashboard);
  } else {
    loadDashboard();
  }

  // Auto-refresh
  setInterval(loadDashboard, REFRESH_INTERVAL);

})();
