"""Informe mensual descargable: una nota Markdown (estilo Obsidian) con las
tablas armadas y los enlaces a los gráficos, para revisar y completar a mano.

Los gráficos no se generan acá: la nota enlaza ``img/<nombre>.png`` con el
nombre que la app le pone a cada gráfico al descargarlo (ícono de descarga
de cada tarjeta), así alcanza con guardarlos en ``img/`` junto a la nota.

Sigue la plantilla del reporte de actividad (el primero fue septiembre
2026). Los números salen de:
- Consultas: los reportes del bot del mes, ya procesados y clasificados.
- Negocios: sólo los creados en el mes, con su etapa actual (los de meses
  anteriores que se movieron en el mes quedan para los análisis semestrales
  o anuales).

Los textos de conclusiones quedan como borrador marcado para revisar.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from . import funnel, geo, periods
from .branding import BITRIX_STAGE_ORDER, _plain, canonical_motivo, canonical_source
from .charts import fmt_dec, pct_label
from .machinery import OTHER as MACHINE_OTHER
from .phone_ar import province_of

# Descripción de cada clasificación, en el orden fijo de la tabla del informe
CLASS_DESCRIPTIONS = {
    "DERIVADO A BITRIX": "Necesidad identificada y negocio generado.",
    "DERIVADO A TÉCNICA": "Consultas derivadas al área técnica.",
    "VENTA DE REPUESTOS": "Generó una venta de repuestos.",
    "DERIVADO A RRHH": "Búsqueda laboral, presentación de CV o propuestas comerciales.",
    "SIN RESPUESTAS": "Nunca se pudo identificar la necesidad (abandono temprano).",
    "SIN INTERES": "Ofrecimiento de servicios o spam comercial.",
    "NECESIDAD INCOMPATIBLE": "Necesidad real fuera del catálogo de la empresa.",
    "SIN CLASIFICAR": "Todavía sin clasificar.",
}
CLASS_ORDER = list(CLASS_DESCRIPTIONS)
# Consultas con una necesidad compatible derivada a un área interna
DERIVADAS = ["DERIVADO A BITRIX", "DERIVADO A TÉCNICA", "DERIVADO A RRHH", "VENTA DE REPUESTOS"]
SIN_INTERES_REAL = ["SIN RESPUESTAS", "SIN INTERES"]
NO_MOTIVO = "Sin motivo cargado"
REVISAR = "> [!todo] Revisar\n> "


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
def month_deals(deals: pd.DataFrame, year_month: str) -> pd.DataFrame:
    """Negocios creados en el mes, con fuente y motivo unificados, zona y
    marca de perdido. ``deals`` puede traer otros meses (el snapshot del mes
    incluye los negocios viejos que se movieron): se descartan."""
    if deals.empty:
        return deals.assign(Zona=[], _perdido=[])
    created = pd.to_datetime(deals["Fecha creacion"], format="%d-%m-%y", errors="coerce")
    d = deals[created.dt.strftime("%Y-%m") == year_month].copy()
    if d.empty:
        return d.assign(Zona=[], _perdido=[])
    d["Fuente"] = (d["Fuente"] if "Fuente" in d else pd.Series("", index=d.index)) \
        .map(canonical_source)
    d["Motivo de baja"] = (d["Motivo de baja"] if "Motivo de baja" in d
                           else pd.Series("", index=d.index)).map(canonical_motivo)
    d["Zona"] = d["Telefono"].map(province_of)
    d["_perdido"] = d["Etapa"].map(_plain).str.startswith("cerrado perdido")
    return d


def _pct(n: float, total: float) -> float:
    return round(n / total * 100, 1) if total else 0.0


def class_table(df: pd.DataFrame) -> pd.DataFrame:
    """[Clasificación | Cantidad | Porcentaje | Descripción] en el orden fijo de
    ``CLASS_ORDER`` (sólo las que tienen consultas; las desconocidas al final).
    "Porcentaje" con el nombre completo para que la columna tenga ancho."""
    counts = df["Clasificacion interna"].astype(str).value_counts()
    order = [c for c in CLASS_ORDER if c in counts] + \
        [c for c in counts.index if c not in CLASS_ORDER]
    total = int(counts.sum())
    return pd.DataFrame({
        "Clasificación": order,
        "Cantidad": [int(counts[c]) for c in order],
        "Porcentaje": [_pct(counts[c], total) for c in order],
        "Descripción": [CLASS_DESCRIPTIONS.get(c, "") for c in order],
    })


def source_table(d: pd.DataFrame) -> pd.DataFrame:
    """[Fuente | Cantidad | %], de mayor a menor."""
    counts = d["Fuente"].value_counts()
    total = int(counts.sum())
    return pd.DataFrame({"Fuente": counts.index.tolist(),
                         "Cantidad": [int(v) for v in counts.values],
                         "%": [_pct(v, total) for v in counts.values]})


def zone_table(d: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Provincias agrupando las más chicas en "Otros" (como la app: hasta el
    10 % del total), con Extranjero / Sin identificar aparte al final, y los
    nombres de las agrupadas. El % es sobre el total."""
    zones = d["Zona"].fillna("").astype(str)
    total = len(zones)
    prov = zones[~zones.isin(geo.NON_PROVINCE_ZONES)]
    full = geo.zone_counts(prov, threshold=0)
    grouped = geo.zone_counts(prov, threshold=0.10 * total / len(prov)) if len(prov) else full
    others = [z for z in full["Zona"] if z not in set(grouped["Zona"])]
    rest = geo.zone_counts(zones[zones.isin(geo.NON_PROVINCE_ZONES)], threshold=0)
    out = pd.concat([grouped, rest], ignore_index=True)
    out["%"] = [_pct(n, total) for n in out["Cantidad"]]
    return out.rename(columns={"Zona": "Provincia"}), others


def motivos_table(d: pd.DataFrame) -> pd.DataFrame:
    lost = d.loc[d["_perdido"], "Motivo de baja"].replace("", NO_MOTIVO)
    counts = lost.value_counts()
    total = int(counts.sum())
    return pd.DataFrame({"Motivo de baja": counts.index.tolist(),
                         "Cantidad": [int(v) for v in counts.values],
                         "% sobre perdidos": [_pct(v, total) for v in counts.values]})


def is_no_response(motivo: str) -> bool:
    """"Sin respuestas", "Sin repuestas" (así está en Bitrix) o "Sin respuesta inicial"."""
    m = _plain(motivo)
    return m.startswith("sin respuesta") or m.startswith("sin repuesta")


def efficiency_table(d: pd.DataFrame) -> pd.DataFrame:
    """Por fuente: negocios en desarrollo (no perdidos), perdidos y tasa de pérdida."""
    g = d.groupby("Fuente")["_perdido"].agg(["size", "sum"])
    g = g.sort_values("size", ascending=False, kind="stable")
    return pd.DataFrame({
        "Fuente": g.index.tolist(),
        "En desarrollo": [int(t - p) for t, p in zip(g["size"], g["sum"])],
        "Perdidos": [int(p) for p in g["sum"]],
        "Tasa de pérdida": [_pct(p, t) for t, p in zip(g["size"], g["sum"])],
        "Total": [int(t) for t in g["size"]],
    })


def machinery_table(d: pd.DataFrame) -> pd.DataFrame:
    counts = d["Tipo maquinaria"].value_counts()
    # "Otro / Sin clasificar" al final aunque sea grande
    order = [c for c in counts.index if c != MACHINE_OTHER] + \
        [c for c in counts.index if c == MACHINE_OTHER]
    total = int(counts.sum())
    return pd.DataFrame({"Tipo de máquina": order,
                         "Cantidad": [int(counts[c]) for c in order],
                         "%": [_pct(counts[c], total) for c in order]})


def stage_table(d: pd.DataFrame) -> pd.DataFrame:
    """Etapa actual en el orden del pipeline (las desconocidas al final)."""
    counts = d["Etapa"].astype(str).value_counts()
    rank = {_plain(s): i for i, s in enumerate(BITRIX_STAGE_ORDER)}

    def key(stage: str) -> int:
        p = _plain(stage)
        return next((i for s, i in rank.items() if p.startswith(s)), len(rank))

    order = sorted(counts.index, key=key)
    total = int(counts.sum())
    return pd.DataFrame({"Etapa": order,
                         "Cantidad": [int(counts[s]) for s in order],
                         "%": [_pct(counts[s], total) for s in order]})


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def _cell(v) -> str:
    if isinstance(v, float):
        return fmt_dec(v)
    return str(v).replace("|", "\\|")


def md_table(df: pd.DataFrame, pct_cols: tuple[str, ...] = (),
             total_row: dict | None = None) -> str:
    """Tabla Markdown; las columnas de ``pct_cols`` van como "13,2 %" y las
    numéricas alineadas a la derecha."""
    cols = list(df.columns)
    numeric = [pd.api.types.is_numeric_dtype(df[c]) for c in cols]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join("---:" if n else "---" for n in numeric) + "|"]
    for row in df.itertuples(index=False):
        cells = [("—" if pd.isna(v) else pct_label(v)) if c in pct_cols else _cell(v)
                 for c, v in zip(cols, row)]
        lines.append("| " + " | ".join(cells) + " |")
    if total_row:
        lines.append("| " + " | ".join(f"**{total_row[c]}**" if c in total_row else ""
                                       for c in cols) + " |")
    return "\n".join(lines)


def chart_names(year_month: str) -> dict[str, str]:
    """Nombre del PNG que descarga la app para cada gráfico del informe
    (mismos nombres que usan las páginas: ``clasificaciones_2026-10``,
    ``negocios_por_fuente_01-10-26_a_31-10-26``, ...)."""
    label = periods.range_label(*periods.month_bounds(year_month))
    return {
        "clasificacion": f"clasificaciones_{year_month}.png",
        "embudo": f"embudo_{year_month}.png",
        "fuentes": f"negocios_por_fuente_{label}.png",
        "provincias": f"provincias_negocios_{label}.png",
        "motivos": f"motivos_baja_{label}.png",
        "fuentes_etapa": f"fuentes_etapa_{label}.png",
        "maquinas": f"demanda_productos_{label}.png",
    }


def _img(name: str, alt: str, where: str) -> list[str]:
    """Enlace a la imagen y, como comentario de Obsidian (no se ve al leer
    ni al exportar), de qué tarjeta de la app descargarla."""
    return [f"![{alt}](img/{name})", f"%% Descargar de: {where} %%"]


def _list_es(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def funnel_table(counts: list[int]) -> pd.DataFrame:
    """[Etapa | Cantidad | % de las consultas | % de la etapa anterior]."""
    first = counts[0]
    return pd.DataFrame({
        "Etapa": funnel.STAGES,
        "Cantidad": counts,
        "% de las consultas": [_pct(c, first) for c in counts],
        "% de la etapa anterior": [None] + [_pct(c, p) if p else None
                                            for p, c in zip(counts, counts[1:])],
    })


def build(bot: pd.DataFrame, deals: pd.DataFrame, year_month: str,
          funnel_counts: list[int] | None = None) -> str:
    """Markdown del informe del mes. ``funnel_counts``: etapas del embudo
    (``funnel.funnel_counts``); sin ellas no va la 1.2."""
    month_txt = periods.month_label(year_month, full=True)
    d = month_deals(deals, year_month)
    img = chart_names(year_month)
    month_name = month_txt.split()[0].lower()
    out: list[str] = [f"# REPORTE DE ACTIVIDAD COMERCIAL - {month_txt.upper()}", ""]

    # --- tablas ------------------------------------------------------------
    n_bot = len(bot)
    classes = class_table(bot)
    by_class = dict(zip(classes["Clasificación"], classes["Cantidad"]))
    n_derivadas = sum(by_class.get(c, 0) for c in DERIVADAS)
    n_sin_interes = sum(by_class.get(c, 0) for c in SIN_INTERES_REAL)
    n_incompatible = by_class.get("NECESIDAD INCOMPATIBLE", 0)
    n_deals = len(d)
    sources = source_table(d) if n_deals else None
    motivos = motivos_table(d) if n_deals else None
    n_lost = int(d["_perdido"].sum()) if n_deals else 0
    no_resp = int(motivos.loc[motivos["Motivo de baja"].map(is_no_response), "Cantidad"].sum()) \
        if motivos is not None else 0
    machines = machinery_table(d) if n_deals else None

    # --- resumen -----------------------------------------------------------
    out += ["## Resumen y highlights", "",
            REVISAR + "Borrador armado con los datos del mes: revisar y completar.", ""]
    if n_bot:
        out.append(f"- **Calidad de las consultas:** el {pct_label(_pct(n_derivadas, n_bot))} "
                   "de las consultas tuvo una necesidad compatible "
                   f"y se derivó a un área interna; el {pct_label(_pct(n_sin_interes, n_bot))} "
                   "no mostró interés real (sin respuestas o sin interés / spam).")
    if sources is not None and len(sources):
        top = sources.head(2)
        names = " y ".join(f"**{s}**" for s in top["Fuente"])
        out.append(f"- **Canales clave:** {names} "
                   f"{'representan' if len(top) > 1 else 'representa'} el "
                   f"{pct_label(_pct(top['Cantidad'].sum(), n_deals))} de los negocios del mes.")
    if n_lost:
        out.append(f"- **Motivo crítico de pérdida:** el {pct_label(_pct(no_resp, n_lost))} de "
                   "los negocios perdidos se cerró por **falta de respuesta** del interesado "
                   "(sin respuestas o sin respuesta inicial).")
    if machines is not None and len(machines):
        m0 = machines.iloc[0]
        out.append(f"- **Demanda concentrada:** **{m0['Tipo de máquina']}** encabeza la demanda "
                   f"con el {pct_label(m0['%'])} de los negocios.")
    out += ["", "---", ""]

    # --- 1. Consultas --------------------------------------------------------
    out += ["## 1. Análisis de consultas entrantes", "",
            f"Se registraron **{n_bot} consultas** en frío a través del canal de Redes Sociales "
            f"durante el mes de {month_name}.", "",
            "### 1.1 Calidad del tráfico inicial", ""]
    if n_bot:
        out += [*_img(img["clasificacion"], "Calidad de las consultas",
                      "Reporte mensual · Por clasificación (barras)"), "",
                md_table(classes, pct_cols=("Porcentaje",),
                         total_row={"Clasificación": "TOTAL", "Cantidad": n_bot}), "",
                f"> [!note] Filtro previo\n> El {pct_label(_pct(n_sin_interes + n_incompatible, n_bot))} "
                "de las consultas fue spam, sin respuesta o una necesidad incompatible.", ""]
    else:
        out += ["Sin consultas en el mes.", ""]

    if funnel_counts and funnel_counts[0]:
        ganadas = funnel_counts[-1]
        out += ["### 1.2 De la consulta a la venta", "",
                *_img(img["embudo"], "Embudo de consultas",
                      "Análisis preliminar · Embudo de consultas"), "",
                md_table(funnel_table(funnel_counts),
                         pct_cols=("% de las consultas", "% de la etapa anterior")), "",
                "> [!note] Cómo se cruzan consultas y negocios",
                "> Las consultas derivadas se buscan por teléfono entre los negocios con "
                "actividad en el mes o en el siguiente; si hay varios, cuenta el más avanzado. "
                "**Cotizadas:** el negocio llegó a \"Cotizado aguardando devolución\" o más "
                "(un perdido cuenta si se perdió después de cotizar). **Ganadas:** \"Ganado en "
                "Desarrollo\" o \"Cerrado Ganado\".", "",
                f"- *(Completar: el {pct_label(_pct(ganadas, funnel_counts[0]))} de las "
                "consultas terminó en venta; dónde está la caída más grande.)*", ""]

    if not n_deals:
        out += ["## 2. Fuentes de origen (pipeline Bitrix)", "",
                "Sin negocios de Bitrix en el mes.", ""]
        return "\n".join(out)

    # --- 2. Fuentes ------------------------------------------------------------
    out += ["## 2. Fuentes de origen (pipeline Bitrix)", "",
            f"Se crearon **{n_deals} negocios** de venta de máquinas en {month_name}.", "",
            "### 2.1 Distribución por canales", ""]
    out += [*_img(img["fuentes"], "Negocios por fuente",
                  "Negocios Bitrix24 (período Mes) · Por fuente (barras sólidas)"), "",
            md_table(sources, pct_cols=("%",),
                     total_row={"Fuente": "TOTAL", "Cantidad": n_deals}), ""]

    zones, others = zone_table(d)
    if others:
        zones["Provincia"] = zones["Provincia"].replace(
            geo.OTHERS, f"Otras ({', '.join(others)})")
    out += ["### 2.2 Distribución geográfica", "",
            "A partir del código de área del teléfono de los negocios:", "",
            *_img(img["provincias"], "Negocios por provincia",
                  "Negocios Bitrix24 · Por provincia (vista barras; el mapa no se "
                  "descarga, se puede reemplazar por una captura)"), ""]
    top3 = zones[~zones["Provincia"].isin(geo.NON_PROVINCE_ZONES)
                 & ~zones["Provincia"].str.startswith("Otras")].head(3)
    out += [md_table(zones, pct_cols=("%",)), "",
            "**Conclusiones de captación geográfica:**", ""]
    if len(top3):
        out.append(f"- **Zona principal:** {_list_es(top3['Provincia'].tolist())} agrupan el "
                   f"{pct_label(_pct(top3['Cantidad'].sum(), n_deals))} de los negocios.")
    out += ["- *(Completar: mercados secundarios, ciudades destacadas.)*", "", "---", ""]

    # --- 3. Motivos de baja ----------------------------------------------------
    out += ["## 3. Motivos de baja", "", "### 3.1 Negocios perdidos", "",
            f"A la fecha de corte, hay **{n_lost} negocios en etapa \"Cerrado Perdido\"** "
            f"({pct_label(_pct(n_lost, n_deals))}).", ""]
    if n_lost:
        out += [*_img(img["motivos"], "Motivos de baja",
                      "Negocios Bitrix24 · Motivos de baja (torta)"), "",
                md_table(motivos, pct_cols=("% sobre perdidos",)), "",
                "> [!warning] Abandono",
                f"> Los negocios cerrados por falta de respuesta o sin respuesta inicial "
                f"agrupan el **{pct_label(_pct(no_resp, n_lost))}** de las pérdidas.", ""]

    eff = efficiency_table(d)
    out += ["### 3.2 Eficiencia por fuente de origen", "",
            *_img(img["fuentes_etapa"], "Negocios por fuente y etapa",
                  "Negocios Bitrix24 · Por fuente (barras segmentadas por etapa)"), "",
            md_table(eff, pct_cols=("Tasa de pérdida",)), "",
            "**Observaciones:**", "",
            "- *(Completar: qué canales pierden más y cuáles tienen mejor efectividad.)*",
            "", "---", ""]

    # --- 4. Demanda ------------------------------------------------------------
    out += ["## 4. Demanda de productos", "",
            *_img(img["maquinas"], "Demanda por tipo de máquina",
                  "Negocios Bitrix24 · Por máquina y etapa (Total)"), "",
            md_table(machines, pct_cols=("%",),
                     total_row={"Tipo de máquina": "TOTAL", "Cantidad": n_deals}), "",
            "> Tipo de máquina según el nombre del negocio. "
            f"\"{MACHINE_OTHER}\": nombres sin un tipo reconocible (revisar a mano).",
            "", "---", ""]

    # --- 5. Estado actual --------------------------------------------------------
    stages = stage_table(d)
    out += ["## 5. Estado actual", "", "### 5.1 Vista general del pipeline (Bitrix)", "",
            md_table(stages, pct_cols=("%",),
                     total_row={"Etapa": "TOTAL", "Cantidad": n_deals}), "",
            "> [!note] Acumulación",
            f"> El {pct_label(_pct(n_lost, n_deals))} de los negocios de {month_name} "
            "ya terminó en negocio perdido.", "",
            "## Recomendaciones finales", "",
            "1. *(Completar)*", "2. *(Completar)*", "3. *(Completar)*", ""]
    return "\n".join(out)


def file_name(year_month: str) -> str:
    return f"Reporte de actividad {year_month}.md"


def md_builder(bot: pd.DataFrame, deals: pd.DataFrame, year_month: str,
               funnel_counts: list[int] | None = None) -> Callable[[], bytes]:
    """Función sin argumentos para ``st.download_button`` (arma la nota recién
    al hacer clic)."""
    return lambda: build(bot, deals, year_month, funnel_counts).encode("utf-8")
