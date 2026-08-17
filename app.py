import re
import pandas as pd
import plotly.express as px
import streamlit as st

from utils.config import OPCIONES_CLASIFICACION, BITRIX_STAGE_COLORS, REPORT_COLOR_MAP
from utils.helpers import (
    normalizar_etapa,
    classify_machine_type,
    format_phone_ar,
    hex_to_rgba,
    format_phone_full,
    format_mes_legible,
)
from utils.cache import (
    get_data_with_local_cache,
    apply_automatic_classifications,
    persist_automatic_classifications,
    get_saved_classifications,
    save_classification,
)

# ---------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# ---------------------------------------------------------
st.set_page_config(
    page_title="Gestión de Consultas & Bitrix24",
    page_icon="📊",
    layout="wide"
)

st.title("Control de Consultas de WhatsApp y CRM Bitrix24")

# Estilo global: mejora el contraste del texto en textareas deshabilitados
# (ej. "Resumen de la consulta"), que por defecto Streamlit renderiza en gris
# claro y no cumple con un contraste accesible sobre fondo blanco.
st.markdown(
    """
    <style>
    /* Fuerza el color del texto en textareas deshabilitados (ej. "Resumen de
       la consulta") a seguir el tema activo de Streamlit — negro en tema
       claro, blanco en tema oscuro. Antes se forzaba #111 fijo, lo que
       arreglaba el tema claro pero dejaba texto negro sobre fondo negro en
       modo oscuro. --text-color es una CSS variable que Streamlit inyecta y
       que refleja el tema activo, sin necesidad de detectarlo desde Python. */
    div[data-testid="stTextArea"] textarea:disabled {
        color: var(--text-color) !important;
        -webkit-text-fill-color: var(--text-color) !important;
        opacity: 1 !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ---------------------------------------------------------
# CONFIGURACIÓN DE SIDEBAR
# ---------------------------------------------------------
st.sidebar.header("Configuración y Conexiones")

# Google Sheets Config
# Los valores por defecto se leen de st.secrets (.streamlit/secrets.toml), NUNCA hardcodeados
# en el código fuente. Esto evita exponer el Spreadsheet ID y, sobre todo, la URL del
# webhook de Bitrix24 (que da acceso de lectura/escritura al CRM) dentro del repositorio.
st.sidebar.subheader("Google Sheets")
spreadsheet_id = st.sidebar.text_input(
    "ID o Nombre de la Spreadsheet",
    value=st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
)
worksheet_name = st.sidebar.text_input(
    "Nombre de la Pestaña",
    value=st.secrets.get("google_sheets", {}).get("worksheet_name", "Hoja1")
)

# Bitrix24 Config
st.sidebar.subheader("Bitrix24 Webhook")
bitrix_webhook_url = st.sidebar.text_input(
    "Webhook URL de Bitrix24",
    value=st.secrets.get("bitrix24", {}).get("webhook_url", ""),
    type="password"
)

st.sidebar.markdown("---")
st.sidebar.subheader("Sincronización de Datos")
btn_refresh = st.sidebar.button("🔄 Actualizar Datos desde APIs")

# ---------------------------------------------------------
# CARGA Y DESPLIEGUE PRINCIPAL
# ---------------------------------------------------------
if spreadsheet_id and bitrix_webhook_url:
    df_sheets, df_bitrix = get_data_with_local_cache(
        spreadsheet_id,
        worksheet_name,
        bitrix_webhook_url,
        force_refresh=btn_refresh
    )

    if not df_sheets.empty:
        df_class = get_saved_classifications()
        df_sheets = pd.merge(df_sheets, df_class, on="Enlace de Whatsapp", how="left")
        df_sheets["Clasificacion_Manual"] = df_sheets["Clasificacion_Manual"].fillna("Pendiente")

        # Aplicar automatizaciones integradas. Devuelve además la lista de
        # clasificaciones que la función derivó automáticamente en esta corrida,
        # para que las podamos persistir en la Sheet (columna Usuario = 'auto (...)').
        # Así el registro de la Sheet refleja también las clasificaciones automáticas
        # y no solo las manuales.
        df_sheets, auto_cambios = apply_automatic_classifications(df_sheets, df_bitrix)

        # Persistir en la Sheet solo lo que no esté ya registrado con el mismo valor.
        # Esto es idempotente: en el primer arranque escribe todo lo acumulado, en
        # los siguientes es no-op (0 escrituras).
        try:
            escritas = persist_automatic_classifications(auto_cambios, df_class)
            if escritas:
                st.toast(f"📝 {escritas} clasificación(es) automática(s) registrada(s) en la Sheet.", icon="⚡")
        except Exception as e:
            # No queremos que un fallo de persistencia impida usar la app: se muestra
            # el error en el sidebar y seguimos con las clasificaciones aplicadas
            # solo en memoria (comportamiento anterior).
            st.sidebar.warning(f"No se pudieron persistir las clasificaciones automáticas ({e}).")

        tab_clasif, tab_reporte_sheets, tab_bitrix = st.tabs([
            "Clasificación Manual (Contacto por Contacto)",
            "Reporte Mensual de Consultas",
            "Análisis de Negociaciones Bitrix24"
        ])

        # =========================================================
        # TAB 1: CLASIFICACIÓN MANUAL
        # =========================================================
        with tab_clasif:
            st.header("Módulo de Clasificación Manual")

            # Ordenamos los meses cronológicamente descendente y dejamos "Sin Fecha"
            # al final (si aparece), para que no compita como opción por defecto con
            # los meses reales. Un 'Sin Fecha' en el listado indica filas con la
            # columna FechaHora vacía o mal formateada en la Sheet fuente.
            meses_validos = sorted(
                [m for m in df_sheets["AñoMes"].dropna().unique() if m != "Sin Fecha"],
                reverse=True,
            )
            meses_disponibles = meses_validos + (["Sin Fecha"] if "Sin Fecha" in df_sheets["AñoMes"].dropna().unique() else [])

            if meses_disponibles:
                mes_sel = st.selectbox("Filtrar por Mes:", meses_disponibles, key="clasif_mes_select")
                df_mes = df_sheets[df_sheets["AñoMes"] == mes_sel].reset_index(drop=True)

                if not df_mes.empty:
                    total_mes = len(df_mes)
                    pendientes = (df_mes["Clasificacion_Manual"] == "Pendiente").sum()
                    clasificados = total_mes - pendientes

                    st.progress(clasificados / total_mes if total_mes > 0 else 0)
                    st.info(f"Progreso del mes **{mes_sel}**: **{clasificados}/{total_mes}** clasificados ({pendientes} pendientes).")

                    def generar_etiqueta_contacto(row):
                        tel = str(row.get("Telefono_Limpio", "")).strip()
                        tel_display = format_phone_ar(tel) if tel else str(row.get("Enlace de Whatsapp", "Sin Teléfono"))

                        nombre = str(row.get("Nombre", "")).strip()
                        clasif = str(row.get("Clasificacion_Manual", "Pendiente"))

                        nombre_display = nombre if nombre and nombre.lower() not in ["nan", "none", ""] else "Sin Nombre registrado"
                        indicador_estado = "⏳" if clasif == "Pendiente" else "✅"

                        return f"{indicador_estado} {tel_display} - {nombre_display} [{clasif}]"

                    opciones_contactos = [generar_etiqueta_contacto(row) for _, row in df_mes.iterrows()]

                    # --- Navegación de contactos ---
                    # El selectbox se controla únicamente a través de su propio "key"
                    # (selectbox_key). Streamlit ignora el parámetro `index` en los reruns
                    # siguientes si el widget ya tiene un valor guardado bajo su `key`; por
                    # eso los botones deben escribir directamente sobre st.session_state[selectbox_key]
                    # (y no sobre una variable de estado separada) para poder moverlo.
                    selectbox_key = f"clasif_selectbox_{mes_sel}"
                    pending_key = f"pending_{selectbox_key}"

                    # Streamlit (a partir de ~1.30) prohíbe escribir a la key de un widget
                    # DESPUÉS de que ese widget fue instanciado en el mismo rerun. Como el
                    # auto-avance al guardar una clasificación (más abajo) necesita mover
                    # el selectbox, no puede escribir directamente sobre `selectbox_key`
                    # en ese momento: en su lugar deja la intención en `pending_key` y
                    # llama a st.rerun(). Acá arriba, ANTES de instanciar el selectbox,
                    # transferimos ese valor al key real. Los botones Anterior/Siguiente no
                    # tienen este problema porque su on_click corre antes del render.
                    if pending_key in st.session_state:
                        st.session_state[selectbox_key] = st.session_state.pop(pending_key)

                    contacto_seleccionado_str = st.selectbox(
                        "Seleccionar Contacto:",
                        options=opciones_contactos,
                        key=selectbox_key
                    )

                    idx = opciones_contactos.index(contacto_seleccionado_str)

                    def _ir_a_indice(nuevo_idx, _opciones=opciones_contactos, _key=selectbox_key):
                        nuevo_idx = max(0, min(nuevo_idx, len(_opciones) - 1))
                        st.session_state[_key] = _opciones[nuevo_idx]

                    col_prev, col_actual, col_next = st.columns(3)
                    with col_prev:
                        st.button(
                            "← Anterior", width="stretch", disabled=(idx <= 0),
                            key=f"btn_prev_{mes_sel}", on_click=_ir_a_indice, args=(idx - 1,)
                        )
                    with col_actual:
                        st.button("Actual", width="stretch", disabled=True, key=f"btn_actual_{mes_sel}")
                    with col_next:
                        st.button(
                            "Siguiente →", width="stretch", disabled=(idx >= len(opciones_contactos) - 1),
                            key=f"btn_next_{mes_sel}", on_click=_ir_a_indice, args=(idx + 1,)
                        )

                    contacto = df_mes.iloc[idx]

                    st.markdown("---")
                    col_info, col_form = st.columns([2, 1])

                    with col_info:
                        nombre_contacto = contacto.get('Nombre')
                        nombre_valido = nombre_contacto if pd.notna(nombre_contacto) and str(nombre_contacto).strip() else "No registrado"

                        tel_contacto_raw = str(contacto.get('Telefono_Limpio', '')).strip()
                        tel_contacto_display = format_phone_ar(tel_contacto_raw) if tel_contacto_raw else "Sin número"

                        st.subheader(f"Contacto: {tel_contacto_display}")
                        st.write(f"👤 **Nombre:** {nombre_valido}")
                        st.write(f"📅 **Fecha y Hora:** {contacto.get('FechaHora')}")
                        st.write(f"🔗 **Enlace WhatsApp:** [{contacto.get('Enlace de Whatsapp')}]({contacto.get('Enlace de Whatsapp')})")
                        st.write(f"🏷️ **Área de Interés:** {contacto.get('Área de interés')}")
                        st.write(f"🤖 **Clasificación Bot:** `{contacto.get('Clasificación')}`")

                        # El resumen llega concatenado con separadores " | "; se reemplazan
                        # por saltos de línea para mejorar la legibilidad del bloque.
                        resumen_raw = str(contacto.get("Resumen de la consulta", ""))
                        resumen_formateado = re.sub(r"\s*\|\s*", "\n\n", resumen_raw)

                        st.text_area(
                            "Resumen de la Consulta (Multiagente IA):",
                            value=resumen_formateado,
                            height=180,
                            disabled=True
                        )

                    with col_form:
                        st.subheader("Asignar Clasificación Interna")
                        clasif_actual = contacto.get("Clasificacion_Manual", "Pendiente")

                        # Se usa el "Enlace de Whatsapp" como clave estable del form (identificador
                        # único real del contacto), en vez de "idx", que depende del orden/filtro
                        # de df_mes y puede repetirse entre sesiones para contactos distintos.
                        enlace_key = re.sub(r"[^0-9A-Za-z]", "_", str(contacto.get("Enlace de Whatsapp", idx)))
                        with st.form(key=f"form_clasif_{enlace_key}"):
                            nueva_clasif = st.selectbox(
                                "Clasificación interna:",
                                OPCIONES_CLASIFICACION,
                                index=OPCIONES_CLASIFICACION.index(clasif_actual) if clasif_actual in OPCIONES_CLASIFICACION else 0
                            )

                            btn_guardar = st.form_submit_button("💾 Guardar Clasificación")

                            if btn_guardar:
                                save_classification(contacto["Enlace de Whatsapp"], nueva_clasif)
                                st.success(f"¡Guardado correctamente como **{nueva_clasif}**!")

                                # En vez de volver al inicio de la lista, se avanza
                                # automáticamente al próximo contacto "Pendiente": primero
                                # buscando hacia adelante y, si no queda ninguno, dando la
                                # vuelta desde el principio del mes.
                                mask_pendientes = (df_mes["Clasificacion_Manual"] == "Pendiente") & (df_mes.index != idx)
                                siguientes = df_mes.index[(df_mes.index > idx) & mask_pendientes].tolist()
                                if siguientes:
                                    nuevo_idx = siguientes[0]
                                else:
                                    anteriores = df_mes.index[mask_pendientes].tolist()
                                    nuevo_idx = anteriores[0] if anteriores else idx

                                # Diferimos la escritura del selectbox al próximo rerun
                                # (ver comentario extenso donde se define pending_key). Escribir
                                # directamente sobre selectbox_key acá levanta StreamlitAPIException
                                # porque el widget ya fue renderizado más arriba en este rerun.
                                st.session_state[pending_key] = opciones_contactos[nuevo_idx]
                                st.rerun()
                else:
                    st.warning("No hay consultas registradas para el mes seleccionado.")
            else:
                st.warning("No se encontraron registros de fechas válidas en la hoja.")

        # =========================================================
        # TAB 2: REPORTE MENSUAL DE CONSULTAS
        # =========================================================
        with tab_reporte_sheets:
            st.header("Extracto Mensual y Distribución de Consultas")

            mes_reporte = st.selectbox("Seleccionar Mes para el Reporte:", meses_disponibles, key="rep_mes")
            df_reporte = df_sheets[df_sheets["AñoMes"] == mes_reporte].copy()

            st.subheader(f"Porcentaje por Clasificación Manual - {mes_reporte}")

            if not df_reporte.empty:
                df_counts = df_reporte["Clasificacion_Manual"].value_counts().reset_index()
                df_counts.columns = ["Clasificación", "Cantidad"]

                fig_pie = px.pie(
                    df_counts,
                    names="Clasificación",
                    values="Cantidad",
                    hole=0.4,
                    color="Clasificación",
                    color_discrete_map=REPORT_COLOR_MAP
                )
                # `automargin=True` deja que Plotly reserve espacio para las
                # etiquetas externas (percent+label) en vez de recortarlas o
                # empujar las porciones del pie. `uniformtext_mode="hide"`
                # oculta etiquetas que no entren en su porción en vez de
                # deformarlas. Los márgenes generosos evitan que texto largo
                # (ej. "Derivado al área técnica") choque contra el borde y
                # provoque que el gráfico "se quiebre".
                fig_pie.update_traces(
                    textinfo="percent+label",
                    textposition="outside",
                    automargin=True,
                )
                fig_pie.update_layout(
                    showlegend=True,
                    margin=dict(t=80, b=80, l=100, r=100),
                    height=500,
                    uniformtext_minsize=10,
                    uniformtext_mode="hide",
                )

                # En pantallas anchas el gráfico solo no llena la fila; se agrega al lado
                # una tabla comparativa contra el mes anterior para aprovechar el espacio.
                col_chart, col_compare = st.columns([2, 1])

                with col_chart:
                    st.plotly_chart(fig_pie, width="stretch")

                with col_compare:
                    st.markdown("**Comparativa vs. mes anterior**")
                    try:
                        periodo_anterior = str(pd.Period(mes_reporte, freq="M") - 1)
                    except Exception:
                        periodo_anterior = None

                    df_mes_anterior = df_sheets[df_sheets["AñoMes"] == periodo_anterior] if periodo_anterior else pd.DataFrame()

                    counts_actual = df_reporte["Clasificacion_Manual"].value_counts()
                    counts_anterior = df_mes_anterior["Clasificacion_Manual"].value_counts() if not df_mes_anterior.empty else pd.Series(dtype=int)

                    todas_categorias = sorted(set(counts_actual.index) | set(counts_anterior.index))

                    if todas_categorias:
                        tabla_comparativa = pd.DataFrame({
                            "Clasificación": todas_categorias,
                            "Actual": [int(counts_actual.get(c, 0)) for c in todas_categorias],
                            "Mes pasado": [int(counts_anterior.get(c, 0)) for c in todas_categorias],
                        })
                        tabla_comparativa["Diferencia"] = tabla_comparativa["Actual"] - tabla_comparativa["Mes pasado"]
                        tabla_comparativa = tabla_comparativa.sort_values("Actual", ascending=False)

                        st.dataframe(
                            tabla_comparativa[["Clasificación", "Mes pasado", "Diferencia"]],
                            width="stretch",
                            hide_index=True
                        )
                    else:
                        st.caption("Sin datos suficientes para comparar.")

                st.subheader("Tabla de Datos con Clasificación Agregada")

                # Estructura fija de columnas solicitada:
                # [Fecha | Nombre | Numero | Área de interés | Clasificación].
                df_display = pd.DataFrame({
                    "Fecha": pd.to_datetime(df_reporte["FechaHora"], errors="coerce").dt.strftime("%d-%m-%y"),
                    "Nombre": df_reporte["Nombre"],
                    "Numero": df_reporte["Telefono_Limpio"].apply(format_phone_ar),
                    "Área de interés": df_reporte["Área de interés"],
                    "Clasificación": df_reporte["Clasificacion_Manual"],
                })

                def estilo_fila(row):
                    """
                    Pinta toda la fila con el color de la clasificación a muy baja opacidad
                    (para identificar el grupo de un vistazo) y reserva el color sólido
                    fuerte únicamente para la celda de "Clasificación".
                    """
                    clasif = row["Clasificación"]
                    color = REPORT_COLOR_MAP.get(clasif, "#FFFFFF")
                    fondo_suave = hex_to_rgba(color, 0.08)
                    texto_fuerte = "#FFFFFF" if clasif in ["Spam/Servicios", "Derivado al área técnica", "Consulta incompatible"] else "#000000"

                    estilos = []
                    for col in row.index:
                        if col == "Clasificación":
                            estilos.append(f"background-color: {color}; color: {texto_fuerte}; font-weight: bold;")
                        else:
                            estilos.append(f"background-color: {fondo_suave};")
                    return estilos

                df_styled = df_display.style.apply(estilo_fila, axis=1)

                st.dataframe(df_styled, width="stretch", hide_index=True)

                col_csv, _ = st.columns(2)
                csv_bytes = df_reporte.to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
                col_csv.download_button(
                    label="📥 Descargar Extracto Mensual (CSV)",
                    data=csv_bytes,
                    file_name=f"consultas_whatsapp_{mes_reporte}.csv",
                    mime="text/csv"
                )

        # =========================================================
        # TAB 3: ANÁLISIS DE NEGOCIACIONES BITRIX24 (SALE)
        # =========================================================
        with tab_bitrix:
            st.header("Análisis de ventas de máquinas")

            if not df_bitrix.empty:
                meses_bitrix = sorted(df_bitrix["AñoMes"].dropna().unique(), reverse=True)

                if meses_bitrix:
                    mes_sel_bitrix = st.selectbox("Seleccionar Mes (Bitrix24):", meses_bitrix, key="bitrix_mes_select")
                    mes_bitrix_legible = format_mes_legible(mes_sel_bitrix)
                    df_bitrix_mes = df_bitrix[df_bitrix["AñoMes"] == mes_sel_bitrix].copy()

                    if not df_bitrix_mes.empty:
                        df_bitrix_mes["Tipo de máquina"] = df_bitrix_mes["TITLE"].apply(classify_machine_type)
                        # Normalizamos la etapa a su forma canónica para que coincida
                        # exactamente con las claves de BITRIX_STAGE_COLORS.
                        df_bitrix_mes["Etapa"] = df_bitrix_mes["Etapa"].apply(normalizar_etapa)

                        df_grouped = df_bitrix_mes.groupby(["Tipo de máquina", "Etapa"]).size().reset_index(name="Cantidad")

                        fig_bitrix = px.bar(
                            df_grouped,
                            x="Tipo de máquina",
                            y="Cantidad",
                            color="Etapa",
                            title=f"Negociaciones por etapa - {mes_bitrix_legible}",
                            labels={"Etapa": "Etapa (Pipeline)", "Tipo de máquina": "Tipo de Máquina"},
                            barmode="group",
                            color_discrete_map=BITRIX_STAGE_COLORS
                        )

                        fig_bitrix.update_layout(
                            xaxis_title="Tipo de Máquina",
                            yaxis_title="Cantidad de Negociaciones",
                            legend_title_text="Etapa del Pipeline"
                        )

                        st.plotly_chart(fig_bitrix, width="stretch")

                        st.subheader("Lista de negociaciones")

                        # La columna combinada "Datos del cliente" se separa en tres columnas
                        # propias (Nombre, Compañía, Tel) para que cada dato sea filtrable/legible
                        # por separado. El título del negocio (TITLE) se renombra a "Negociación"
                        # para no chocar con el nombre del contacto. Se conserva "Tipo de
                        # máquina" en el DataFrame base para que quede incluido en el CSV y
                        # siga disponible para el gráfico de barras (que se arma sobre
                        # df_bitrix_mes); en la vista se oculta más abajo.
                        df_bitrix_display = pd.DataFrame({
                            "Negociación": df_bitrix_mes["TITLE"].values,
                            "Etapa": df_bitrix_mes["Etapa"].values,
                            "Nombre": df_bitrix_mes["Nombre_Contacto"].values,
                            "Compañía": df_bitrix_mes["Compania"].values,
                            "Tel": df_bitrix_mes["Telefono"].apply(format_phone_full).values,
                            "Tipo de máquina": df_bitrix_mes["Tipo de máquina"].values,
                        })
                        # Guardamos el teléfono en su forma original (sin formatear) para
                        # usarlo como clave estable al buscar el historial del contacto.
                        # `format_phone_full` puede introducir espacios/formato que rompen
                        # una comparación directa contra df_bitrix["Telefono"].
                        _telefonos_raw = df_bitrix_mes["Telefono"].astype(str).str.strip().values

                        def estilo_fila_bitrix(row):
                            """
                            Colorea toda la fila según la etapa del negocio, a muy baja opacidad
                            (8%), usando el mismo mapeo de colores que el gráfico de barras.
                            """
                            color = BITRIX_STAGE_COLORS.get(row["Etapa"], "#FFFFFF")
                            fondo_suave = hex_to_rgba(color, 0.08)
                            return [f"background-color: {fondo_suave};" for _ in row.index]

                        # Vista: se oculta "Tipo de máquina" para que la tabla mostrada
                        # quede compacta, sin perderla ni del CSV ni del gráfico de barras
                        # (que se calcula sobre df_bitrix_mes).
                        columnas_visibles = ["Negociación", "Etapa", "Nombre", "Compañía", "Tel"]
                        df_bitrix_visible = df_bitrix_display[columnas_visibles].reset_index(drop=True)
                        df_bitrix_styled = df_bitrix_visible.style.apply(estilo_fila_bitrix, axis=1)

                        # Habilitamos selección de una fila para poder "expandir" el
                        # historial completo del contacto elegido, sin recargar la tabla.
                        seleccion_bitrix = st.dataframe(
                            df_bitrix_styled,
                            width="stretch",
                            hide_index=True,
                            on_select="rerun",
                            selection_mode="single-row",
                            key=f"tabla_bitrix_{mes_sel_bitrix}",
                        )

                        # `st.dataframe(on_select=...)` devuelve un objeto con .selection.rows
                        # (lista de índices de las filas seleccionadas). Cuando el usuario
                        # aún no hizo click, la lista viene vacía.
                        try:
                            filas_sel = list(seleccion_bitrix.selection.rows)
                        except AttributeError:
                            filas_sel = []

                        st.caption(
                            "💡 Hacé click sobre una fila para expandir el historial de "
                            "negocios del contacto en toda la base cargada."
                        )

                        if filas_sel:
                            idx_sel = filas_sel[0]
                            contacto_sel = df_bitrix_visible.iloc[idx_sel]
                            nombre_sel = str(contacto_sel.get("Nombre", "") or "").strip()
                            tel_sel = str(_telefonos_raw[idx_sel] or "").strip()

                            titulo_contacto = nombre_sel or contacto_sel.get("Tel") or "contacto seleccionado"
                            with st.expander(
                                f"📜 Historial de negocios de **{titulo_contacto}**",
                                expanded=True,
                            ):
                                # Buscamos en toda la base de Bitrix (no solo el mes filtrado)
                                # las negociaciones del mismo contacto. Preferimos matchear
                                # por teléfono (más único); si el contacto no tiene teléfono
                                # cargado, caemos a comparar por nombre (case-insensitive).
                                df_hist = df_bitrix.copy()
                                df_hist["Etapa"] = df_hist["Etapa"].apply(normalizar_etapa)

                                tel_valido = tel_sel and tel_sel.lower() not in ("nan", "none", "")
                                if tel_valido:
                                    mask_hist = df_hist["Telefono"].astype(str).str.strip() == tel_sel
                                elif nombre_sel:
                                    mask_hist = (
                                        df_hist["Nombre_Contacto"].astype(str).str.strip().str.lower()
                                        == nombre_sel.lower()
                                    )
                                else:
                                    mask_hist = pd.Series(False, index=df_hist.index)

                                df_hist = df_hist[mask_hist]

                                if df_hist.empty:
                                    st.caption(
                                        "No se encontraron negocios históricos para este contacto."
                                    )
                                else:
                                    # Estructura solicitada:
                                    # [Negociación | Nombre | Compañía | Etapa | Teléfono].
                                    df_hist_display = pd.DataFrame({
                                        "Negociación": df_hist["TITLE"].values,
                                        "Nombre": df_hist["Nombre_Contacto"].values,
                                        "Compañía": df_hist["Compania"].values,
                                        "Etapa": df_hist["Etapa"].values,
                                        "Teléfono": df_hist["Telefono"].apply(format_phone_full).values,
                                    })
                                    df_hist_styled = df_hist_display.style.apply(
                                        estilo_fila_bitrix, axis=1
                                    )
                                    st.caption(
                                        f"Total: **{len(df_hist_display)}** negocio(s) "
                                        f"encontrados en toda la base cargada."
                                    )
                                    st.dataframe(
                                        df_hist_styled,
                                        width="stretch",
                                        hide_index=True,
                                    )

                        # El CSV mantiene "Tipo de máquina" (df_bitrix_display, no df_bitrix_visible)
                        # para que el archivo descargado siga siendo compatible con análisis
                        # posteriores por tipo de máquina.
                        csv_bitrix = df_bitrix_display.to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
                        st.download_button(
                            label="📥 Descargar Negociaciones Filtradas (CSV)",
                            data=csv_bitrix,
                            file_name=f"negociaciones_bitrix_{mes_sel_bitrix}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning(f"No se encontraron negociaciones de venta para **{mes_bitrix_legible}**.")
                else:
                    st.warning("No hay registros con fechas válidas en los datos cargados de Bitrix24.")
            else:
                st.warning("No se obtuvieron datos de Bitrix24. Revisa la URL del Webhook o confirma que existan negociaciones de venta cargadas.")
else:
    st.info("👈 Por favor, ingresa el **Spreadsheet ID** y la **URL del Webhook de Bitrix24** en el panel izquierdo para comenzar.")
