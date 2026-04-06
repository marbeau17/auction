/**
 * CVLPOS - Commercial Vehicle Leaseback Pricing Optimizer
 * Minimal JS - HTMX does the heavy lifting.
 */
document.addEventListener('DOMContentLoaded', function () {

  // -- CSRF token injection for every HTMX request --
  document.body.addEventListener('htmx:configRequest', function (event) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) {
      event.detail.headers['X-CSRF-Token'] = meta.content;
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
function formatCurrency(value) {
  return '\u00a5' + Number(value).toLocaleString('ja-JP');
}

function formatNumber(value) {
  return Number(value).toLocaleString('ja-JP');
}
