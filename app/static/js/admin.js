/* ============================================================
   INALDE · Motor de Curaduría — JS del módulo administrativo (v3)
   ------------------------------------------------------------
   Vanilla JS, sin dependencias. Todo es declarativo por atributos
   data-* para que las plantillas queden limpias. Pensado para
   sentirse premium y fluido (60fps): solo se anima transform/opacity
   y se respeta prefers-reduced-motion.

   Capacidades:
     · Modales            → Alpine.js (x-show + x-transition) en las plantillas
     · Búsqueda en tabla  → [data-table-search="tablaId"]
     · Pestañas de eval.  → .eval-tab[data-eval-target="panelId"]
     · Medidor animado    → .gauge[data-gauge][data-p]
     · Reveal al entrar    → .panel / .metric (IntersectionObserver)
   ============================================================ */
(function () {
  "use strict";

  var REDUCED = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ──────────────────────────────────────────────────────────
  // 1) MODALES → ahora los gestiona Alpine.js (x-show + x-transition).
  //    El bloqueo de scroll y las transiciones viven en las plantillas/CSS;
  //    aquí ya no hay lógica de modales.
  // ──────────────────────────────────────────────────────────

  // ──────────────────────────────────────────────────────────
  // 2) BÚSQUEDA INSTANTÁNEA EN TABLAS
  // ──────────────────────────────────────────────────────────
  function setupTableSearch(input) {
    var tableId = input.getAttribute("data-table-search");
    var table = document.getElementById(tableId);
    if (!table) return;
    var tbody = table.tBodies[0] || table;
    var countEl = document.querySelector('[data-search-count="' + tableId + '"]');
    var countTpl = countEl ? (countEl.getAttribute("data-count-tpl") || "{n}") : null;

    // Fila "sin resultados" reutilizable.
    var cols = (table.tHead && table.tHead.rows[0]) ? table.tHead.rows[0].cells.length : 1;
    var noRow = document.createElement("tr");
    noRow.className = "no-results-row";
    noRow.hidden = true;
    var td = document.createElement("td");
    td.colSpan = cols;
    td.textContent = "Sin coincidencias para la búsqueda.";
    noRow.appendChild(td);
    tbody.appendChild(noRow);

    var rows = [];
    function indexRows() {
      rows = [];
      var trs = tbody.querySelectorAll("tr");
      for (var i = 0; i < trs.length; i++) {
        var tr = trs[i];
        if (tr === noRow) continue;
        rows.push({ tr: tr, text: (tr.textContent || "").toLowerCase() });
      }
    }
    indexRows();

    var raf = null;
    function apply() {
      raf = null;
      var q = input.value.trim().toLowerCase();
      var shown = 0;
      for (var i = 0; i < rows.length; i++) {
        var hit = !q || rows[i].text.indexOf(q) !== -1;
        rows[i].tr.hidden = !hit;
        if (hit) shown++;
      }
      noRow.hidden = shown !== 0;
      if (countEl) countEl.textContent = countTpl.replace("{n}", shown);
    }

    input.addEventListener("input", function () {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(apply);
    });
  }

  // ──────────────────────────────────────────────────────────
  // 3) MEDIDOR (gauge): relleno animado + conteo del número
  // ──────────────────────────────────────────────────────────
  function animateGauge(gauge) {
    if (!gauge) return;
    var target = parseFloat(gauge.getAttribute("data-p")) || 0;
    var valEl = gauge.querySelector(".g-val");

    if (REDUCED) {
      gauge.style.setProperty("--p", target);
      if (valEl) valEl.textContent = Math.round(target);
      return;
    }

    // Relleno del aro: 0 → target (la transición CSS de --p lo suaviza).
    gauge.style.setProperty("--p", 0);
    void gauge.offsetWidth;
    requestAnimationFrame(function () {
      gauge.style.setProperty("--p", target);
    });

    // Conteo del número.
    if (valEl) {
      var dur = 700, start = null;
      var ease = function (t) { return 1 - Math.pow(1 - t, 3); };
      var step = function (ts) {
        if (start === null) start = ts;
        var p = Math.min((ts - start) / dur, 1);
        valEl.textContent = Math.round(ease(p) * target);
        if (p < 1) requestAnimationFrame(step);
        else valEl.textContent = Math.round(target);
      };
      requestAnimationFrame(step);
    }
  }

  // ──────────────────────────────────────────────────────────
  // 4) PESTAÑAS DE EVALUACIÓN
  // ──────────────────────────────────────────────────────────
  function setupEvalTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".eval-tab"));
    if (!tabs.length) return;
    var panels = Array.prototype.slice.call(document.querySelectorAll(".eval-panel"));

    function activate(targetId, animate) {
      tabs.forEach(function (t) {
        t.classList.toggle("active", t.getAttribute("data-eval-target") === targetId);
      });
      panels.forEach(function (p) {
        var on = p.id === targetId;
        p.hidden = !on;
        if (on) {
          p.classList.add("is-in");
          if (animate) animateGauge(p.querySelector(".gauge"));
        }
      });
    }

    tabs.forEach(function (t) {
      t.addEventListener("click", function () {
        activate(t.getAttribute("data-eval-target"), true);
        // Llevar el panel a la vista sin saltos bruscos.
        var sw = document.querySelector(".eval-switch");
        if (sw) sw.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
      });
    });

    // Activar la primera pestaña (la de mayor puntuación) al cargar.
    activate(tabs[0].getAttribute("data-eval-target"), true);
    return true;
  }

  // ──────────────────────────────────────────────────────────
  // 5) REVEAL ESCALONADO AL ENTRAR EN VISTA
  // ──────────────────────────────────────────────────────────
  function setupReveal() {
    document.body.classList.add("js-anim");
    if (REDUCED || !("IntersectionObserver" in window)) {
      // Sin animación: mostrar todo de inmediato.
      document.querySelectorAll(".panel, .metric").forEach(function (el) {
        el.classList.add("is-in");
      });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      var batch = 0;
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        el.style.transitionDelay = (batch * 60) + "ms";
        batch++;
        el.classList.add("is-in");
        io.unobserve(el);
        // Limpiar el delay tras animar para que futuras transiciones (hover) no lo hereden.
        setTimeout(function () { el.style.transitionDelay = ""; }, 60 * batch + 600);
      });
    }, { threshold: 0.06, rootMargin: "0px 0px -8% 0px" });

    document.querySelectorAll(".panel:not(.eval-panel), .metric").forEach(function (el) {
      io.observe(el);
    });
  }

  // ──────────────────────────────────────────────────────────
  // Arranque
  // ──────────────────────────────────────────────────────────
  function init() {
    setupReveal();
    document.querySelectorAll("[data-table-search]").forEach(setupTableSearch);
    var hasTabs = setupEvalTabs();
    // Si no hay pestañas pero sí un gauge suelto, animarlo igual.
    if (!hasTabs) {
      document.querySelectorAll(".gauge[data-gauge]").forEach(animateGauge);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
