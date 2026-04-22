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

  // -- Mobile drawer toggle (Phase 5) --
  // The new shell uses body[data-drawer="open"] + .mx-sidebar. The legacy
  // .hamburger / .sidebar selectors below stay so existing pages that still
  // render the old shell (none in main) keep working.
  var menuBtn = document.getElementById('cvl-mobile-menu-btn');

  function closeDrawer() {
    document.body.removeAttribute('data-drawer');
    if (menuBtn) menuBtn.setAttribute('aria-expanded', 'false');
  }

  function openDrawer() {
    document.body.setAttribute('data-drawer', 'open');
    if (menuBtn) menuBtn.setAttribute('aria-expanded', 'true');
  }

  if (menuBtn) {
    menuBtn.addEventListener('click', function () {
      if (document.body.getAttribute('data-drawer') === 'open') closeDrawer();
      else openDrawer();
    });
  }

  // Tap outside the sidebar closes the drawer (mobile only).
  document.addEventListener('click', function (ev) {
    if (document.body.getAttribute('data-drawer') !== 'open') return;
    var sb = document.getElementById('cvl-sidebar');
    if (!sb || sb.contains(ev.target) || menuBtn.contains(ev.target)) return;
    closeDrawer();
  });

  // Close on ESC + on HTMX nav.
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') closeDrawer();
  });
  document.body.addEventListener('htmx:beforeRequest', closeDrawer);

  // Legacy hamburger (old shell — safe no-op if not present).
  var legacyHamburger = document.querySelector('.hamburger');
  var legacySidebar = document.querySelector('.sidebar');
  var legacyOverlay = document.querySelector('.sidebar-overlay');
  if (legacyHamburger && legacySidebar) {
    legacyHamburger.addEventListener('click', function () {
      legacySidebar.classList.toggle('open');
      if (legacyOverlay) legacyOverlay.classList.toggle('active');
    });
  }
  if (legacyOverlay) {
    legacyOverlay.addEventListener('click', function () {
      if (legacySidebar) legacySidebar.classList.remove('open');
      legacyOverlay.classList.remove('active');
    });
  }

  // -- Fund switcher (Phase 5) --
  var fundSwitch = document.getElementById('cvl-fund-switch');
  if (fundSwitch) {
    var fundNameEl = document.getElementById('cvl-fund-name');
    var fundDotEl = document.getElementById('cvl-fund-dot');
    var opts = fundSwitch.querySelectorAll('.opt');

    // Restore last selection from localStorage.
    var stored = localStorage.getItem('cvl_fund');
    if (stored) {
      opts.forEach(function (o) {
        var selected = o.dataset.fundId === stored;
        o.setAttribute('aria-selected', selected ? 'true' : 'false');
        if (selected) {
          fundNameEl.textContent = o.dataset.fundName;
          fundDotEl.style.background = o.dataset.fundColor;
        }
      });
    }

    function toggleMenu(open) {
      var current = fundSwitch.getAttribute('aria-expanded') === 'true';
      var next = typeof open === 'boolean' ? open : !current;
      fundSwitch.setAttribute('aria-expanded', next ? 'true' : 'false');
    }

    fundSwitch.addEventListener('click', function (ev) {
      // Ignore clicks on individual options — they handle themselves.
      if (ev.target.closest('.opt')) return;
      toggleMenu();
    });
    fundSwitch.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggleMenu(); }
      else if (ev.key === 'Escape') toggleMenu(false);
    });
    document.addEventListener('click', function (ev) {
      if (!fundSwitch.contains(ev.target)) toggleMenu(false);
    });

    opts.forEach(function (opt) {
      opt.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var id = opt.dataset.fundId;
        var name = opt.dataset.fundName;
        var color = opt.dataset.fundColor;
        localStorage.setItem('cvl_fund', id);
        fundNameEl.textContent = name;
        fundDotEl.style.background = color;
        opts.forEach(function (o) {
          o.setAttribute('aria-selected', o === opt ? 'true' : 'false');
        });
        toggleMenu(false);
        window.dispatchEvent(new CustomEvent('cvl:fund-change', { detail: { fund: id, name: name } }));
      });
    });
  }

  // -- Notification bell (Phase 5) --
  var bellBtn = document.getElementById('cvl-bell-btn');
  var bellPanel = document.getElementById('cvl-bell-panel');
  var bellClose = document.getElementById('cvl-bell-close');
  if (bellBtn && bellPanel) {
    function toggleBell(open) {
      var current = !bellPanel.hasAttribute('hidden');
      var next = typeof open === 'boolean' ? open : !current;
      if (next) bellPanel.removeAttribute('hidden');
      else bellPanel.setAttribute('hidden', '');
      bellBtn.setAttribute('aria-expanded', next ? 'true' : 'false');
    }
    bellBtn.addEventListener('click', function (ev) { ev.stopPropagation(); toggleBell(); });
    if (bellClose) bellClose.addEventListener('click', function () { toggleBell(false); });
    document.addEventListener('click', function (ev) {
      if (!bellPanel.contains(ev.target) && ev.target !== bellBtn && !bellBtn.contains(ev.target)) toggleBell(false);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') toggleBell(false);
    });
  }

  // -- Theme toggle (Phase 5+) --
  (function initTheme() {
    var stored = localStorage.getItem('cvl_theme');
    var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    var initial = stored || (prefersDark ? 'dark' : 'light');
    document.body.setAttribute('data-theme', initial);
    var btn = document.getElementById('cvl-theme-toggle');
    if (btn) {
      btn.setAttribute('aria-pressed', initial === 'dark' ? 'true' : 'false');
      btn.addEventListener('click', function () {
        var current = document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.body.setAttribute('data-theme', current);
        localStorage.setItem('cvl_theme', current);
        btn.setAttribute('aria-pressed', current === 'dark' ? 'true' : 'false');
        window.dispatchEvent(new CustomEvent('cvl:theme-change', { detail: { theme: current } }));
      });
    }
  })();

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
