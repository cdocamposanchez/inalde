/**
 * Multiselect con buscador integrado, sin dependencias.
 *
 * Renderiza dentro de `container` un input de búsqueda, una lista de
 * opciones filtrables con checkbox y un área de "chips" con lo seleccionado.
 *
 * Uso:
 *   const ms = crearMultiselect(document.getElementById("mi-div"), {
 *     opciones: [{ id: 1, nombre: "Uno" }, ...],
 *     seleccionados: [1],            // ids preseleccionados (opcional)
 *     placeholder: "Buscar...",      // opcional
 *     vacio: "No hay opciones",      // texto si no hay opciones (opcional)
 *     onChange: (ids) => {...},      // callback opcional
 *   });
 *   ms.getSeleccionados();           // -> [ids]
 *   ms.setSeleccionados([1,2]);      // fija selección
 *   ms.setOpciones([...]);           // reemplaza opciones
 *
 * No usa innerHTML con datos del servidor: construye nodos con textContent
 * para evitar inyección.
 */
function crearMultiselect(container, opts = {}) {
  const estado = {
    opciones: Array.isArray(opts.opciones) ? opts.opciones.slice() : [],
    seleccionados: new Set((opts.seleccionados || []).map(Number)),
    filtro: "",
    onChange: typeof opts.onChange === "function" ? opts.onChange : null,
    placeholder: opts.placeholder || "Buscar...",
    vacio: opts.vacio || "No hay opciones disponibles.",
  };

  container.classList.add("ms-root");
  container.innerHTML = "";

  // ── Chips de seleccionados ──
  const chips = document.createElement("div");
  chips.className = "ms-chips";

  // ── Buscador ──
  const buscadorWrap = document.createElement("div");
  buscadorWrap.className = "ms-search-wrap";
  const buscador = document.createElement("input");
  buscador.type = "text";
  buscador.className = "input-x ms-search";
  buscador.placeholder = estado.placeholder;
  buscador.autocomplete = "off";
  buscadorWrap.appendChild(buscador);

  // ── Lista de opciones ──
  const lista = document.createElement("div");
  lista.className = "ms-list";

  container.appendChild(chips);
  container.appendChild(buscadorWrap);
  container.appendChild(lista);

  function notificar() {
    if (estado.onChange) estado.onChange(getSeleccionados());
  }

  function getSeleccionados() {
    // Preserva el orden de `opciones`.
    return estado.opciones
      .filter((o) => estado.seleccionados.has(Number(o.id)))
      .map((o) => Number(o.id));
  }

  function quitar(id) {
    estado.seleccionados.delete(Number(id));
    render();
    notificar();
  }

  function toggle(id) {
    id = Number(id);
    if (estado.seleccionados.has(id)) estado.seleccionados.delete(id);
    else estado.seleccionados.add(id);
    render();
    notificar();
  }

  function renderChips() {
    chips.innerHTML = "";
    const sel = estado.opciones.filter((o) =>
      estado.seleccionados.has(Number(o.id))
    );
    if (!sel.length) {
      const vacio = document.createElement("span");
      vacio.className = "ms-chips-empty";
      vacio.textContent = "Ninguno seleccionado.";
      chips.appendChild(vacio);
      return;
    }
    sel.forEach((o) => {
      const chip = document.createElement("span");
      chip.className = "ms-chip";
      const txt = document.createElement("span");
      txt.textContent = o.nombre;
      const x = document.createElement("button");
      x.type = "button";
      x.className = "ms-chip-x";
      x.setAttribute("aria-label", "Quitar");
      x.textContent = "×";
      x.addEventListener("click", () => quitar(o.id));
      chip.appendChild(txt);
      chip.appendChild(x);
      chips.appendChild(chip);
    });
  }

  function renderLista() {
    lista.innerHTML = "";
    if (!estado.opciones.length) {
      const vacio = document.createElement("div");
      vacio.className = "ms-list-empty";
      vacio.textContent = estado.vacio;
      lista.appendChild(vacio);
      return;
    }
    const f = estado.filtro.trim().toLowerCase();
    const visibles = estado.opciones.filter((o) =>
      !f ? true : String(o.nombre).toLowerCase().includes(f)
    );
    if (!visibles.length) {
      const vacio = document.createElement("div");
      vacio.className = "ms-list-empty";
      vacio.textContent = "Sin coincidencias.";
      lista.appendChild(vacio);
      return;
    }
    visibles.forEach((o) => {
      const id = Number(o.id);
      const row = document.createElement("label");
      row.className = "ms-option";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "checkbox checkbox-sm checkbox-primary";
      cb.checked = estado.seleccionados.has(id);
      cb.addEventListener("change", () => toggle(id));
      const txt = document.createElement("span");
      txt.className = "ms-option-text";
      txt.textContent = o.nombre;
      row.appendChild(cb);
      row.appendChild(txt);
      if (o.descripcion) {
        const desc = document.createElement("span");
        desc.className = "ms-option-desc";
        desc.textContent = o.descripcion;
        row.appendChild(desc);
      }
      lista.appendChild(row);
    });
  }

  function render() {
    renderChips();
    renderLista();
  }

  buscador.addEventListener("input", (e) => {
    estado.filtro = e.target.value;
    renderLista();
  });

  render();

  return {
    getSeleccionados,
    setSeleccionados(ids) {
      estado.seleccionados = new Set((ids || []).map(Number));
      render();
    },
    setOpciones(opciones) {
      estado.opciones = Array.isArray(opciones) ? opciones.slice() : [];
      // Limpia seleccionados que ya no existen.
      const validos = new Set(estado.opciones.map((o) => Number(o.id)));
      estado.seleccionados = new Set(
        [...estado.seleccionados].filter((id) => validos.has(id))
      );
      render();
    },
    limpiar() {
      estado.seleccionados.clear();
      estado.filtro = "";
      buscador.value = "";
      render();
    },
  };
}
