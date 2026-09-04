(() => {
  "use strict";

  // Ayuda visual del Django Admin: muestra/oculta campos según el tipo
  // elegido (tipo_fecha, tipo_horario, tipo_costo, tipo_ubicacion). No
  // valida nada — Evento.clean() sigue siendo la única autoridad.

  const CAMPOS_FECHA = {
    exacta: ["fecha_inicio"],
    rango: ["fecha_inicio", "fecha_fin"],
    anual_fija: ["dia_inicio_anual", "mes_inicio_anual", "dia_fin_anual", "mes_fin_anual"],
    anual_relativa: ["orden_semana_relativa", "dia_semana_relativa", "mes_relativa", "dia_ancla_relativa"],
    pascua_relativa: ["offset_dias_pascua"],
    mes_aproximado: ["mes_aproximado", "anio_aproximado"],
    por_confirmar: [],
  };
  const TODOS_CAMPOS_FECHA = [
    "fecha_inicio", "fecha_fin",
    "dia_inicio_anual", "mes_inicio_anual", "dia_fin_anual", "mes_fin_anual",
    "orden_semana_relativa", "dia_semana_relativa", "mes_relativa", "dia_ancla_relativa",
    "offset_dias_pascua",
    "mes_aproximado", "anio_aproximado",
  ];

  const CAMPOS_HORARIO = {
    exacta: ["hora_inicio"],
    rango: ["hora_inicio", "hora_fin"],
    todo_el_dia: [],
    variable: [],
    por_confirmar: [],
    no_aplica: [],
  };
  const TODOS_CAMPOS_HORARIO = ["hora_inicio", "hora_fin"];

  const CAMPOS_COSTO = {
    gratis: [],
    pagado: ["precio_desde", "precio_hasta"],
    consultar: [],
    no_aplica: [],
  };
  const TODOS_CAMPOS_COSTO = ["precio_desde", "precio_hasta"];

  const CAMPOS_UBICACION = {
    lugar_exacto: ["lugar", "direccion", "referencia", "latitud", "longitud"],
    varios_lugares: ["lugar", "descripcion_ubicacion"],
    itinerante: ["descripcion_ubicacion"],
    ambito_general: [],
  };
  const TODOS_CAMPOS_UBICACION = [
    "lugar", "direccion", "referencia", "latitud", "longitud", "descripcion_ubicacion",
  ];

  function fila(nombreCampo) {
    return document.querySelector(".form-row.field-" + nombreCampo);
  }

  function aplicarVisibilidad(mapa, todos, valorActual) {
    const visibles = mapa[valorActual] || [];
    todos.forEach((nombreCampo) => {
      const el = fila(nombreCampo);
      if (!el) return;
      el.style.display = visibles.includes(nombreCampo) ? "" : "none";
    });
  }

  function conectar(idSelect, mapa, todos) {
    const select = document.getElementById(idSelect);
    if (!select) return;
    const actualizar = () => aplicarVisibilidad(mapa, todos, select.value);
    select.addEventListener("change", actualizar);
    actualizar();
  }

  document.addEventListener("DOMContentLoaded", () => {
    conectar("id_tipo_fecha", CAMPOS_FECHA, TODOS_CAMPOS_FECHA);
    conectar("id_tipo_horario", CAMPOS_HORARIO, TODOS_CAMPOS_HORARIO);
    conectar("id_tipo_costo", CAMPOS_COSTO, TODOS_CAMPOS_COSTO);
    conectar("id_tipo_ubicacion", CAMPOS_UBICACION, TODOS_CAMPOS_UBICACION);
  });
})();
