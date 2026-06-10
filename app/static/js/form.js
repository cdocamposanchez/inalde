/* ============================================================
   INALDE · Motor de Curaduría Ejecutiva — formulario público
   ============================================================ */
(() => {
  "use strict";

  const CFG = window.INALDE_CFG || {};
  const MAX_FORM = CFG.maxFormaciones || 5;
  const MAX_EXP = CFG.maxExperiencias || 10;
  const MAX_HAB = CFG.maxHabilidades || 20;
  const MAX_IDI = CFG.maxIdiomas || 6;
  const MAX_TEC = 20;

  const PASOS = 6;
  let pasoActual = 1;

  const $ = (s, ctx = document) => ctx.querySelector(s);
  const $$ = (s, ctx = document) => Array.from(ctx.querySelectorAll(s));

  // Etiqueta legible de un campo, para los mensajes de validación.
  const labelDe = (inp) => {
    const f = inp.closest(".field");
    const l = f && f.querySelector(".label-x");
    return l ? l.textContent.replace("*", "").trim() : "este campo";
  };

  // Sugerencias para autocompletado (datalists).
  const SUG_HAB = ["Liderazgo de equipos", "Liderazgo comercial", "Manejo de P&L",
    "Planeación estratégica", "Negociación", "Gestión de proyectos", "Transformación digital",
    "Gestión del cambio", "Desarrollo de negocio", "Análisis financiero", "Gestión de operaciones",
    "Servicio al cliente", "Toma de decisiones", "Comunicación ejecutiva", "Gestión de presupuestos"];
  const SUG_TEC = ["SAP", "Oracle", "Microsoft Power BI", "Tableau", "Salesforce", "HubSpot",
    "Microsoft Excel avanzado", "Python", "SQL", "Google Analytics", "Jira", "Asana",
    "Microsoft Project", "QuickBooks", "Workday", "Looker", "Power Automate", "Notion"];
  const SUG_IDI = ["Inglés", "Portugués", "Francés", "Italiano", "Alemán", "Mandarín"];

  // Estado en memoria de las colecciones
  const state = {
    habilidades: [],   // {nombre, nivel}
    tecnologias: [],   // {nombre, nivel}
    idiomas: [],       // {idioma, nivel}
    sectores: [],      // string
    cvFile: null,
  };

  // -------------------- Catálogos --------------------
  async function cargarCatalogos() {
    const fetchJson = (u) => fetch(u).then((r) => r.json()).catch(() => []);
    const [tipos, nac, niveles, sectores] = await Promise.all([
      fetchJson("/api/tipos-documento"),
      fetchJson("/api/nacionalidades"),
      fetchJson("/api/niveles-formacion"),
      fetchJson("/api/sectores"),
    ]);
    fillSelect("#tipo_documento", tipos, "codigo", "nombre", "Seleccione…");
    fillSelect("#nacionalidad", nac, "codigo", "nombre", "Seleccione…", "nombre");
    window.__niveles = niveles;
    window.__sectores = sectores;
    fillDatalist("#sectores-datalist", sectores.map((s) => s.nombre));
    fillDatalist("#habilidades-datalist", SUG_HAB);
    fillDatalist("#tecnologias-datalist", SUG_TEC);
    fillDatalist("#idiomas-datalist", SUG_IDI);
  }

  function fillDatalist(sel, valores) {
    const dl = $(sel);
    if (!dl) return;
    dl.innerHTML = "";
    valores.forEach((v) => {
      const o = document.createElement("option");
      o.value = v; dl.appendChild(o);
    });
  }

  function fillSelect(sel, items, valKey, txtKey, placeholder, useValAs) {
    const el = $(sel);
    if (!el) return;
    el.innerHTML = `<option value="">${placeholder}</option>`;
    items.forEach((it) => {
      const o = document.createElement("option");
      o.value = useValAs ? it[useValAs] : it[valKey];
      o.textContent = it[txtKey];
      el.appendChild(o);
    });
  }

  function nivelesOptions(selected) {
    const niveles = window.__niveles || [];
    return niveles.map((n) =>
      `<option value="${n.codigo}" ${n.codigo === selected ? "selected" : ""}>${n.nombre}</option>`
    ).join("");
  }

  // -------------------- Stepper --------------------
  function mostrarPaso(n) {
    pasoActual = Math.max(1, Math.min(PASOS, n));
    $$(".paso-content").forEach((p) => {
      p.classList.toggle("is-visible", Number(p.dataset.paso) === pasoActual);
    });
    $$(".step-item").forEach((s) => {
      const i = Number(s.dataset.step);
      s.classList.toggle("is-active", i === pasoActual);
      s.classList.toggle("is-done", i < pasoActual);
    });
    $("#btn-prev").disabled = pasoActual === 1;
    $("#btn-next").style.display = pasoActual < PASOS ? "inline-flex" : "none";
    $("#btn-submit").style.display = pasoActual === PASOS ? "inline-flex" : "none";
    if (pasoActual === PASOS) construirResumen();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Lleva el foco al primer campo inválido del paso (corrige el "no me
  // lleva al campo que falta").
  function enfocarCampo(inp) {
    const field = inp.closest(".field");
    if (field) field.classList.add("has-error");
    inp.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => { try { inp.focus({ preventScroll: true }); } catch (_) {} }, 250);
  }

  // Valida un paso. Si `enfocar` es true, resalta y enfoca el primer
  // campo faltante. Devuelve true/false.
  function validarPaso(n, enfocar = true) {
    let primerInvalido = null;
    const cont = $(`.paso-content[data-paso="${n}"]`);
    if (cont) {
      $$("[data-required]", cont).forEach((inp) => {
        const field = inp.closest(".field");
        const vacio = !String(inp.value || "").trim();
        if (field) field.classList.toggle("has-error", vacio);
        if (vacio && !primerInvalido) primerInvalido = inp;
      });
    }
    if (n === 3 && state.habilidades.length === 0) {
      if (enfocar) {
        toast("Registra al menos una habilidad.", true);
        enfocarCampo($("#hab-input"));
      }
      return false;
    }
    if (n === PASOS && !state.cvFile) {
      if (enfocar) toast("Adjunta tu hoja de vida en PDF.", true);
      return false;
    }
    if (primerInvalido) {
      if (enfocar) {
        toast(`Completa el campo: ${labelDe(primerInvalido)}.`, true);
        enfocarCampo(primerInvalido);
      }
      return false;
    }
    return true;
  }

  // Valida todos los pasos; si falla, navega al paso y enfoca el campo.
  function validarTodo() {
    for (let n = 1; n <= PASOS; n++) {
      if (!validarPaso(n, false)) {
        mostrarPaso(n);
        setTimeout(() => validarPaso(n, true), 350);
        return false;
      }
    }
    return true;
  }

  // Limpiar el resalte de error al escribir.
  document.addEventListener("input", (e) => {
    const f = e.target.closest && e.target.closest(".field.has-error");
    if (f && String(e.target.value || "").trim()) f.classList.remove("has-error");
  });

  // -------------------- Colecciones de tags --------------------
  function renderTags(listEl, arr, render, onRemove) {
    listEl.innerHTML = "";
    arr.forEach((item, idx) => {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.innerHTML = render(item);
      const btn = document.createElement("button");
      btn.type = "button"; btn.textContent = "×";
      btn.addEventListener("click", () => { onRemove(idx); });
      tag.appendChild(btn);
      listEl.appendChild(tag);
    });
  }

  function setupColeccionNivel(prefijo, arr, campoNombre, max, msgMax) {
    const input = $(`#${prefijo}-input`), nivel = $(`#${prefijo}-nivel`),
          add = $(`#${prefijo}-add`), list = $(`#${prefijo}-list`);
    const draw = () => renderTags(list, arr,
      (it) => `${it[campoNombre]} ${it.nivel ? `<span class="nivel-badge">· ${it.nivel}</span>` : ""}`,
      (i) => { arr.splice(i, 1); draw(); });
    add.addEventListener("click", () => {
      const v = input.value.trim();
      if (!v) return;
      if (arr.length >= max) { toast(msgMax, true); return; }
      const obj = { nivel: nivel.value || null }; obj[campoNombre] = v;
      arr.push(obj);
      input.value = ""; if (nivel) nivel.value = ""; draw();
    });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add.click(); } });
  }

  function setupSectores() {
    const input = $("#sec-input"), add = $("#sec-add"), list = $("#sec-list");
    const draw = () => renderTags(list, state.sectores,
      (s) => `${s}`,
      (i) => { state.sectores.splice(i, 1); draw(); });
    add.addEventListener("click", () => {
      const v = input.value.trim();
      if (!v || state.sectores.includes(v)) { input.value = ""; return; }
      state.sectores.push(v); input.value = ""; draw();
    });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add.click(); } });
  }

  // -------------------- Formación --------------------
  function bloqueFormacion(idx) {
    const div = document.createElement("div");
    div.className = "repeat-block";
    div.dataset.kind = "formacion";
    div.innerHTML = `
      <div class="block-head"><h4>Formación ${idx + 1}</h4>
        <button type="button" class="btn-remove">Eliminar</button></div>
      <div class="grid-2">
        <div class="field"><label class="label-x">Nivel académico</label>
          <select class="input-x" data-f="nivel">${nivelesOptions()}</select></div>
        <div class="field"><label class="label-x">Título obtenido</label>
          <input class="input-x" data-f="titulo" placeholder="Ej. MBA, Ingeniería Industrial"></div>
        <div class="field col-2"><label class="label-x">Institución</label>
          <input class="input-x" data-f="institucion" placeholder="Universidad / escuela"></div>
        <div class="field"><label class="label-x">Año inicio</label>
          <input class="input-x" type="number" data-f="anio_inicio" min="1950" max="2035" placeholder="2014"></div>
        <div class="field"><label class="label-x">Año fin</label>
          <input class="input-x" type="number" data-f="anio_fin" min="1950" max="2035" placeholder="2016"></div>
      </div>
      <div class="check-row"><input type="checkbox" data-f="en_curso" id="enc-${idx}-${Date.now()}">
        <label>Actualmente en curso</label></div>`;
    div.querySelector(".btn-remove").addEventListener("click", () => { div.remove(); renumerar("formacion"); });
    return div;
  }

  // -------------------- Experiencia --------------------
  function bloqueExperiencia(idx) {
    const div = document.createElement("div");
    div.className = "repeat-block";
    div.dataset.kind = "experiencia";
    const uid = `${idx}-${Date.now()}`;
    div.innerHTML = `
      <div class="block-head"><h4>Experiencia ${idx + 1}</h4>
        <button type="button" class="btn-remove">Eliminar</button></div>
      <div class="grid-2">
        <div class="field"><label class="label-x">Empresa</label>
          <input class="input-x" data-f="empresa" placeholder="Nombre de la empresa"></div>
        <div class="field"><label class="label-x">Cargo</label>
          <input class="input-x" data-f="cargo" placeholder="Ej. Gerente Comercial"></div>
        <div class="field"><label class="label-x">Sector</label>
          <input class="input-x" data-f="sector" list="sectores-datalist" placeholder="Sector económico" autocomplete="off"></div>
        <div class="field"><label class="label-x">País</label>
          <input class="input-x" data-f="pais" placeholder="Colombia" value="Colombia"></div>
        <div class="field"><label class="label-x">Fecha inicio</label>
          <input class="input-x" type="date" data-f="fecha_inicio"></div>
        <div class="field"><label class="label-x">Fecha fin</label>
          <input class="input-x" type="date" data-f="fecha_fin"></div>
        <div class="field"><label class="label-x">Nivel jerárquico</label>
          <select class="input-x" data-f="nivel_jerarquico">
            <option value="">Seleccione…</option>
            <option value="operativo">Operativo</option>
            <option value="coordinacion">Coordinación</option>
            <option value="jefatura">Jefatura</option>
            <option value="gerencia">Gerencia</option>
            <option value="direccion">Dirección</option>
            <option value="alta_direccion">Alta dirección</option>
          </select></div>
        <div class="field"><label class="label-x">Tamaño del equipo a cargo</label>
          <input class="input-x" type="number" data-f="tam_equipo" min="0" placeholder="0"></div>
        <div class="field col-2"><label class="label-x">Funciones y logros</label>
          <textarea class="input-x" data-f="funciones" placeholder="Describa responsabilidades y logros (incluya cifras: % de crecimiento, presupuesto, equipos…)."></textarea></div>
      </div>
      <div class="grid-3">
        <div class="check-row"><input type="checkbox" data-f="actual" id="act-${uid}"><label>Trabajo actual</label></div>
        <div class="check-row"><input type="checkbox" data-f="lidero_equipo" id="lid-${uid}"><label>Lideré equipos</label></div>
        <div class="check-row"><input type="checkbox" data-f="manejo_pyl" id="pyl-${uid}"><label>Manejé P&amp;L</label></div>
      </div>`;
    div.querySelector(".btn-remove").addEventListener("click", () => { div.remove(); renumerar("experiencia"); });
    return div;
  }

  function renumerar(kind) {
    $$(`.repeat-block[data-kind="${kind}"]`).forEach((b, i) => {
      const label = kind === "formacion" ? "Formación" : "Experiencia";
      b.querySelector(".block-head h4").textContent = `${label} ${i + 1}`;
    });
    actualizarBotonesAdd();
  }

  function actualizarBotonesAdd() {
    const nf = $$('.repeat-block[data-kind="formacion"]').length;
    const ne = $$('.repeat-block[data-kind="experiencia"]').length;
    $("#add-formacion").disabled = nf >= MAX_FORM;
    $("#add-experiencia").disabled = ne >= MAX_EXP;
  }

  function leerBloques(kind) {
    return $$(`.repeat-block[data-kind="${kind}"]`).map((b) => {
      const o = {};
      $$("[data-f]", b).forEach((el) => {
        const k = el.dataset.f;
        if (el.type === "checkbox") o[k] = el.checked;
        else o[k] = el.value.trim() || null;
      });
      return o;
    });
  }

  // -------------------- CV dropzone --------------------
  function setupDropzone() {
    const dz = $("#dropzone"), input = $("#cv-file"), pill = $("#file-pill"), name = $("#fp-name");
    const set = (file) => {
      if (!file) return;
      if (file.type !== "application/pdf") { toast("Solo se permiten archivos PDF.", true); return; }
      state.cvFile = file;
      name.textContent = file.name;
      pill.classList.add("is-visible");
      dz.style.display = "none";
    };
    dz.addEventListener("click", () => input.click());
    input.addEventListener("change", (e) => set(e.target.files[0]));
    ["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("is-drag"); }));
    ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("is-drag"); }));
    dz.addEventListener("drop", (e) => set(e.dataTransfer.files[0]));
    $("#fp-remove").addEventListener("click", () => {
      state.cvFile = null; input.value = ""; pill.classList.remove("is-visible"); dz.style.display = "block";
    });
  }

  // -------------------- Resumen --------------------
  function val(id) { const el = $(id); return el ? el.value.trim() : ""; }
  function chips(arr, campo) {
    return arr.map((h) => `<span class="tag">${h[campo]}${h.nivel ? ` <span class="nivel-badge">· ${h.nivel}</span>` : ""}</span>`).join("")
      || '<span class="hint">—</span>';
  }
  function construirResumen() {
    const cont = $("#resumen");
    const fmts = leerBloques("formacion");
    const exps = leerBloques("experiencia");
    const row = (k, v) => v ? `<div class="summary-row"><span class="k">${k}</span><span class="v">${v}</span></div>` : "";
    cont.innerHTML = `
      <div class="summary-section">
        <h4>Datos personales</h4>
        ${row("Nombre", `${val("#nombres")} ${val("#apellidos")}`)}
        ${row("Documento", `${val("#tipo_documento")} ${val("#numero_documento")}`)}
        ${row("Correo", val("#correo"))}
        ${row("Celular", val("#telefono_celular"))}
        ${row("LinkedIn", val("#linkedin"))}
        ${row("Ubicación", `${val("#ciudad")}${val("#pais") ? ", " + val("#pais") : ""}`)}
      </div>
      <div class="summary-section">
        <h4>Perfil ejecutivo</h4>
        ${row("Titular", val("#titular"))}
        ${row("Años de experiencia", val("#anos_experiencia"))}
        ${row("Pretensión salarial", val("#pretension_salarial"))}
        ${row("Alumni INALDE", $("#es_alumni").checked ? "Sí" + (val("#programa_inalde") ? " · " + val("#programa_inalde") : "") : "No")}
      </div>
      <div class="summary-section">
        <h4>Habilidades</h4>
        <div class="tag-list">${chips(state.habilidades, "nombre")}</div>
      </div>
      <div class="summary-section">
        <h4>Tecnologías</h4>
        <div class="tag-list">${chips(state.tecnologias, "nombre")}</div>
      </div>
      <div class="summary-section">
        <h4>Idiomas</h4>
        <div class="tag-list">${chips(state.idiomas, "idioma")}</div>
      </div>
      <div class="summary-section">
        <h4>Sectores</h4>
        <div class="tag-list">${state.sectores.map((s) => `<span class="tag">${s}</span>`).join("") || '<span class="hint">—</span>'}</div>
      </div>
      <div class="summary-section">
        <h4>Formación (${fmts.length})</h4>
        ${fmts.map((f) => row(f.titulo || "—", `${f.institucion || ""}`)).join("") || '<span class="hint">Sin registros</span>'}
      </div>
      <div class="summary-section">
        <h4>Experiencia (${exps.length})</h4>
        ${exps.map((e) => row(e.cargo || "—", `${e.empresa || ""}`)).join("") || '<span class="hint">Sin registros</span>'}
      </div>`;
  }

  // -------------------- Envío --------------------
  function buildPayload() {
    return {
      nombres: val("#nombres"), apellidos: val("#apellidos"),
      tipo_documento: val("#tipo_documento"), numero_documento: val("#numero_documento"),
      fecha_nacimiento: val("#fecha_nacimiento") || null,
      nacionalidad: val("#nacionalidad") || null,
      correo: val("#correo"), telefono_celular: val("#telefono_celular"),
      linkedin: val("#linkedin") || null, ciudad: val("#ciudad") || null,
      pais: val("#pais") || "Colombia",
      titular: val("#titular") || null,
      resumen_profesional: val("#resumen_profesional") || null,
      anos_experiencia: val("#anos_experiencia") || null,
      pretension_salarial: val("#pretension_salarial") || null,
      disponibilidad_viaje: $("#disp_viaje").checked,
      disponibilidad_reubicacion: $("#disp_reub").checked,
      es_alumni: $("#es_alumni").checked,
      programa_inalde: val("#programa_inalde") || null,
      habilidades: state.habilidades,
      tecnologias: state.tecnologias,
      idiomas: state.idiomas,
      sectores: state.sectores,
      formaciones: leerBloques("formacion"),
      experiencias: leerBloques("experiencia"),
    };
  }

  async function enviar() {
    if (!validarTodo()) return;
    const btn = $("#btn-submit");
    btn.disabled = true; btn.textContent = "Enviando…";
    const fd = new FormData();
    fd.append("payload", JSON.stringify(buildPayload()));
    fd.append("cv", state.cvFile);
    try {
      const r = await fetch("/api/candidatos", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok) {
        const msg = Array.isArray(data.detail)
          ? data.detail.map((d) => `${d.loc?.join(".")}: ${d.msg}`).join(" · ")
          : (data.detail || "Error al registrar.");
        toast(msg, true);
        btn.disabled = false; btn.textContent = "Enviar hoja de vida";
        return;
      }
      mostrarExito(data.consecutivo);
    } catch (e) {
      toast("Error de conexión. Intente de nuevo.", true);
      btn.disabled = false; btn.textContent = "Enviar hoja de vida";
    }
  }

  function mostrarExito(consecutivo) {
    $("#form-card").innerHTML = `
      <div class="success">
        <div class="check">✓</div>
        <h2>Hoja de vida registrada</h2>
        <p>Gracias por postularte. Tu hoja de vida fue recibida y entrará al proceso de curaduría ejecutiva mediante nuestro sistema ATS.</p>
        <p>Conserva tu número de radicado para futuras consultas.</p>
        <div class="radicado">${consecutivo}</div>
      </div>`;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // -------------------- Toast --------------------
  let toastTimer;
  function toast(msg, isError) {
    let t = $("#toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
    t.textContent = msg;
    t.classList.toggle("is-error", !!isError);
    t.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("is-visible"), 3800);
  }

  // -------------------- Init --------------------
  document.addEventListener("DOMContentLoaded", async () => {
    await cargarCatalogos();
    setupColeccionNivel("hab", state.habilidades, "nombre", MAX_HAB, `Máximo ${MAX_HAB} habilidades.`);
    setupColeccionNivel("tec", state.tecnologias, "nombre", MAX_TEC, `Máximo ${MAX_TEC} tecnologías.`);
    setupColeccionNivel("idi", state.idiomas, "idioma", MAX_IDI, `Máximo ${MAX_IDI} idiomas.`);
    setupSectores(); setupDropzone();

    $("#formaciones").appendChild(bloqueFormacion(0));
    $("#experiencias").appendChild(bloqueExperiencia(0));
    actualizarBotonesAdd();

    $("#add-formacion").addEventListener("click", () => {
      const n = $$('.repeat-block[data-kind="formacion"]').length;
      if (n >= MAX_FORM) return;
      $("#formaciones").appendChild(bloqueFormacion(n)); actualizarBotonesAdd();
    });
    $("#add-experiencia").addEventListener("click", () => {
      const n = $$('.repeat-block[data-kind="experiencia"]').length;
      if (n >= MAX_EXP) return;
      $("#experiencias").appendChild(bloqueExperiencia(n)); actualizarBotonesAdd();
    });

    $("#es_alumni").addEventListener("change", (e) => {
      $("#programa-wrap").style.display = e.target.checked ? "block" : "none";
    });

    $("#btn-next").addEventListener("click", () => { if (validarPaso(pasoActual)) mostrarPaso(pasoActual + 1); });
    $("#btn-prev").addEventListener("click", () => mostrarPaso(pasoActual - 1));
    $("#btn-submit").addEventListener("click", enviar);
    $$(".step-item").forEach((s) => s.addEventListener("click", () => {
      const target = Number(s.dataset.step);
      if (target < pasoActual) mostrarPaso(target);
    }));

    mostrarPaso(1);
  });
})();
