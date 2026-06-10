/* ============================================================
   Banco de Hojas de Vida — UBPD
   Diálogos custom (reemplazo de alert/confirm del navegador)
   ============================================================
   Cambios de performance vs versión anterior:

   1. SIN backdrop-blur (era costoso — el browser bluerea todo el
      documento de fondo cada frame). Ahora overlay sólido con
      opacidad sutil — visualmente similar pero ~10x más rápido
      en repaints.

   2. SINGLE INSTANCE: solo puede haber un modal abierto a la vez.
      Si llaman `confirmar()` mientras hay uno abierto, el viejo
      se cierra (resolve false) antes de abrir el nuevo. Evita
      apilamiento de listeners y nodos DOM huérfanos.

   3. CLEANUP SÍNCRONO: el listener de keydown se quita en el
      momento que se elige una opción, no cuando termina la
      animación. Evita que tecleos durante la animación de cierre
      provoquen efectos raros.

   4. CSS estático en vez de inline animations: clases reusables
      en lugar de `style.animation = "..."`. El browser las cachea
      y las reusa sin recalcular.

   API global expuesta:
   - confirmar({titulo, mensaje, confirmar, cancelar, tipo}) → Promise<bool>
   - aviso({titulo, mensaje, confirmar, tipo})                → Promise<void>
   - toast(mensaje, tipo)  ← notificación efímera abajo a la derecha
*/
(function () {

  // ── Estado: modal único activo ──
  // Si abrimos otro mientras hay uno, el viejo se cierra primero.
  let _activo = null;

  // ── Configuración por tipo ──
  const TIPOS = {
    info: {
      accent:    "from-ubpd-500 to-ubpd-700",
      iconColor: "text-ubpd-600",
      iconBg:    "bg-ubpd-50",
      btnColor:  "bg-ubpd-600 hover:bg-ubpd-700",
      icon: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    },
    success: {
      accent:    "from-teal-500 to-teal-600",
      iconColor: "text-teal-600",
      iconBg:    "bg-teal-50",
      btnColor:  "bg-teal-600 hover:bg-teal-700",
      icon: '<polyline points="20 6 9 17 4 12"/>',
    },
    warning: {
      accent:    "from-amber-500 to-amber-600",
      iconColor: "text-amber-600",
      iconBg:    "bg-amber-50",
      btnColor:  "bg-amber-500 hover:bg-amber-600",
      icon: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    },
    danger: {
      accent:    "from-red-500 to-red-600",
      iconColor: "text-red-600",
      iconBg:    "bg-red-50",
      btnColor:  "bg-red-500 hover:bg-red-600",
      icon: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    },
  };
  TIPOS.error = TIPOS.danger;

  function escapeHTML(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function abrirDialogo({
    titulo, mensaje,
    confirmarTxt = "Continuar",
    cancelarTxt  = "Cancelar",
    tipo = "warning",
    soloConfirmar = false,
  }) {
    // Si ya hay un modal activo, cerrarlo primero. Esto evita el
    // apilamiento que causaba lentitud cuando se llamaba varias
    // veces seguidas.
    if (_activo) _activo.cerrar(false, true);

    const cfg = TIPOS[tipo] || TIPOS.warning;

    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      // CLAVE: sin backdrop-blur. Era el causante principal del lag.
      // Un fondo oscuro semitransparente se ve igual de bien y se
      // pinta en una fracción del tiempo.
      overlay.className = "ubpd-dialog-overlay";

      const botones = soloConfirmar
        ? `<button type="button" data-rol="confirmar"
                   class="${cfg.btnColor} text-white font-medium px-4 py-2 rounded-lg text-sm transition-colors">
             ${escapeHTML(confirmarTxt)}
           </button>`
        : `<button type="button" data-rol="cancelar" class="btn-ghost-x">
             ${escapeHTML(cancelarTxt)}
           </button>
           <button type="button" data-rol="confirmar"
                   class="${cfg.btnColor} text-white font-medium px-4 py-2 rounded-lg text-sm transition-colors">
             ${escapeHTML(confirmarTxt)}
           </button>`;

      overlay.innerHTML = `
        <div class="ubpd-dialog-card">
          <div class="h-1 bg-gradient-to-r ${cfg.accent}"></div>
          <div class="p-7">
            <div class="flex items-start gap-4 mb-4">
              <div class="w-11 h-11 rounded-xl ${cfg.iconBg} flex items-center justify-center flex-shrink-0">
                <svg class="w-5 h-5 ${cfg.iconColor}" viewBox="0 0 24 24"
                     fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  ${cfg.icon}
                </svg>
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="font-display text-lg font-semibold text-neutral-800 mb-1">
                  ${escapeHTML(titulo || "Confirmar acción")}
                </h3>
                <p class="text-sm text-neutral-600 leading-relaxed whitespace-pre-line">
                  ${escapeHTML(mensaje || "")}
                </p>
              </div>
            </div>
            <div class="flex items-center justify-end gap-2 mt-5 pt-4 border-t border-neutral-100">
              ${botones}
            </div>
          </div>
        </div>
      `;

      let cerrado = false;

      function cerrar(resultado, inmediato = false) {
        if (cerrado) return;
        cerrado = true;

        // Limpieza SÍNCRONA de listeners (no esperamos animación).
        // Esto evita que tecleos posteriores caigan en el listener
        // de un modal que ya se está cerrando.
        document.removeEventListener("keydown", onKey, true);

        // El modal _activo siguiente borra esto
        if (_activo === api) _activo = null;

        if (inmediato) {
          // Cierre forzado (otro modal nos reemplaza): sin animación.
          overlay.remove();
          resolve(resultado);
          return;
        }

        // Cierre normal con animación suave.
        overlay.classList.add("ubpd-dialog-cerrando");
        setTimeout(() => {
          overlay.remove();
          resolve(resultado);
        }, 150);
      }

      function onKey(e) {
        if (e.key === "Escape") {
          e.stopPropagation();
          cerrar(soloConfirmar ? true : false);
        } else if (e.key === "Enter") {
          e.stopPropagation();
          cerrar(true);
        }
      }

      overlay.addEventListener("click", (e) => {
        if (e.target === overlay && !soloConfirmar) {
          cerrar(false);
          return;
        }
        const rol = e.target.closest("[data-rol]")?.dataset.rol;
        if (rol === "confirmar") cerrar(true);
        else if (rol === "cancelar") cerrar(false);
      });

      // useCapture=true para que Esc/Enter no caigan en otros
      // listeners de la página antes de que los procesemos aquí.
      document.addEventListener("keydown", onKey, true);

      document.body.appendChild(overlay);

      // Foco diferido para que la animación arranque visible
      requestAnimationFrame(() => {
        overlay.querySelector('[data-rol="confirmar"]')?.focus();
      });

      // Guardar referencia para cierre forzado
      const api = { cerrar };
      _activo = api;
    });
  }

  // ── API pública ──
  window.confirmar = function (opts = {}) {
    return abrirDialogo({
      titulo:       opts.titulo,
      mensaje:      opts.mensaje,
      confirmarTxt: opts.confirmar || "Continuar",
      cancelarTxt:  opts.cancelar  || "Cancelar",
      tipo:         opts.tipo      || "warning",
      soloConfirmar: false,
    });
  };

  window.aviso = function (opts = {}) {
    if (typeof opts === "string") opts = { mensaje: opts };
    return abrirDialogo({
      titulo:       opts.titulo || "Aviso",
      mensaje:      opts.mensaje,
      confirmarTxt: opts.confirmar || "Entendido",
      tipo:         opts.tipo || "info",
      soloConfirmar: true,
    });
  };

  // ── Toast: notificación efímera ──
  // Buffer para evitar acumular toasts simultáneos. Si llegan 3 en
  // 500ms, solo el último permanece.
  let _toastActivo = null;
  window.toast = function (mensaje, tipo = "info") {
    const colores = {
      info:    "bg-ubpd-600",
      success: "bg-teal-600",
      warning: "bg-amber-600",
      error:   "bg-red-600",
      danger:  "bg-red-600",
    };

    // Si hay otro toast, reemplazarlo en lugar de apilar.
    if (_toastActivo) {
      _toastActivo.remove();
      _toastActivo = null;
    }

    const div = document.createElement("div");
    div.className = `ubpd-toast ${colores[tipo] || colores.info}`;
    div.textContent = mensaje;
    document.body.appendChild(div);
    _toastActivo = div;

    setTimeout(() => {
      div.classList.add("ubpd-toast-cerrando");
      setTimeout(() => {
        div.remove();
        if (_toastActivo === div) _toastActivo = null;
      }, 280);
    }, 3500);
  };
})();
