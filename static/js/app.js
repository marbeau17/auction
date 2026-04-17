/**
 * CVLPOS - Commercial Vehicle Leaseback Pricing Optimizer
 * Main application JS - HTMX does the heavy lifting.
 */

// ===== Invoice Status Color Mapping =====
var STATUS_COLORS = {
  created: '#999',
  pending_review: '#CCB366',
  approved: '#2B6CB0',
  pdf_ready: '#2B6CB0',
  sent: '#38A169',
  paid: '#38A169',
  overdue: '#E53E3E',
  cancelled: '#999'
};

// ===== Cookie reader (for CSRF fallback) =====
function getCookie(name) {
  var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
  return match ? decodeURIComponent(match[2]) : null;
}

document.addEventListener('DOMContentLoaded', function () {

  // -- CSRF token injection for every HTMX request --
  document.body.addEventListener('htmx:configRequest', function (event) {
    var csrfToken = document.querySelector('meta[name="csrf-token"]')?.content
                 || getCookie('csrf_token');
    if (csrfToken) {
      event.detail.headers['X-CSRF-Token'] = csrfToken;
    }
  });

  // -- Global HTTP error handling --
  document.body.addEventListener('htmx:responseError', function (event) {
    var status = event.detail.xhr.status;
    if (status === 401) {
      window.location.href = '/auth/login';
      return;
    }
    if (status === 403) {
      showToast('権限がありません', 'error');
      return;
    }
    if (status >= 500) {
      showToast('サーバーエラーが発生しました', 'error');
    }
  });

  // -- Re-initialise charts after every HTMX swap --
  document.body.addEventListener('htmx:beforeSwap', function (event) {
    destroyCharts(event.detail.target);
  });

  document.body.addEventListener('htmx:afterSettle', function (event) {
    initCharts(event.detail.target);
  });

  // -- Mobile hamburger toggle --
  var hamburger = document.querySelector('.hamburger');
  var sidebar = document.querySelector('.sidebar');
  var overlay = document.querySelector('.sidebar-overlay');

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.classList.remove('active');
  }

  if (hamburger) {
    hamburger.addEventListener('click', function () {
      sidebar.classList.toggle('open');
      if (overlay) overlay.classList.toggle('active');
    });
  }

  if (overlay) {
    overlay.addEventListener('click', closeSidebar);
  }

  // Close sidebar on navigate (mobile)
  document.body.addEventListener('htmx:beforeRequest', closeSidebar);

  // -- Initial chart boot --
  initCharts(document);
});

// ===== Toast =====
function showToast(message, type) {
  type = type || 'success';
  var container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(function () {
    if (toast.parentNode) toast.parentNode.removeChild(toast);
  }, 4200);
}

// ===== Chart.js helpers =====
function initCharts(container) {
  if (typeof Chart === 'undefined') return;
  var canvases = container.querySelectorAll('canvas[data-chart]');
  canvases.forEach(function (canvas) {
    if (canvas._chartInstance) return;
    try {
      var config = JSON.parse(canvas.getAttribute('data-chart'));
      canvas._chartInstance = new Chart(canvas, config);
    } catch (e) {
      console.error('Chart init error:', e);
    }
  });
}

function destroyCharts(container) {
  if (!container) return;
  var canvases = container.querySelectorAll('canvas[data-chart]');
  canvases.forEach(function (canvas) {
    if (canvas._chartInstance) {
      canvas._chartInstance.destroy();
      canvas._chartInstance = null;
    }
  });
}

// ===== Number formatting (Japanese locale) =====
function formatYen(amount) {
  return '\u00a5' + Number(amount).toLocaleString('ja-JP');
}

// Keep legacy alias
function formatCurrency(value) {
  return formatYen(value);
}

function formatNumber(value) {
  return Number(value).toLocaleString('ja-JP');
}

// ===== Financial Analysis Form Enhancements =====
// Auto-calculate equity_ratio and current_ratio as user fills in numbers.
function initFinancialFormCalc(container) {
  container = container || document;
  var form = container.querySelector('[data-financial-form]');
  if (!form) return;

  var fields = {
    totalAssets:      form.querySelector('[name="total_assets"]'),
    totalEquity:      form.querySelector('[name="total_equity"]'),
    currentAssets:    form.querySelector('[name="current_assets"]'),
    currentLiabilities: form.querySelector('[name="current_liabilities"]'),
    equityRatioOut:   form.querySelector('[data-ratio="equity_ratio"]'),
    currentRatioOut:  form.querySelector('[data-ratio="current_ratio"]')
  };

  function recalc() {
    var totalAssets = parseFloat((fields.totalAssets || {}).value) || 0;
    var totalEquity = parseFloat((fields.totalEquity || {}).value) || 0;
    var currentAssets = parseFloat((fields.currentAssets || {}).value) || 0;
    var currentLiabilities = parseFloat((fields.currentLiabilities || {}).value) || 0;

    // Equity ratio = total_equity / total_assets * 100
    if (fields.equityRatioOut) {
      fields.equityRatioOut.textContent = totalAssets > 0
        ? (totalEquity / totalAssets * 100).toFixed(1) + '%'
        : '--%';
    }

    // Current ratio = current_assets / current_liabilities * 100
    if (fields.currentRatioOut) {
      fields.currentRatioOut.textContent = currentLiabilities > 0
        ? (currentAssets / currentLiabilities * 100).toFixed(1) + '%'
        : '--%';
    }
  }

  // Attach listeners to all numeric inputs inside the form
  var inputs = form.querySelectorAll('input[type="number"], input[type="text"]');
  inputs.forEach(function (input) {
    input.addEventListener('input', recalc);
  });

  // Initial calculation on load
  recalc();
}

// Boot financial form calc on DOMContentLoaded and after HTMX swaps
document.addEventListener('DOMContentLoaded', function () {
  initFinancialFormCalc(document);
});
document.body.addEventListener('htmx:afterSettle', function (event) {
  initFinancialFormCalc(event.detail.target);
});
