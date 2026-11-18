# COTEAR — Informe de Actividad Comercial

Aplicación Streamlit para analizar los reportes del bot de WhatsApp
(Neurolinks) y las negociaciones de Bitrix24 de Cotear SRL.

## Setup local

1. Crear entorno virtual e instalar dependencias:
   ```
   python -m venv .venv
   .venv\Scripts\activate            # Windows
   pip install -r requirements.txt
   ```
2. Completar `.streamlit/secrets.toml` (ver `secrets.example.toml`).
3. Crear el libro de destino (una vez):
   ```
   python -m scripts.create_destination_sheet "COTEAR - Persistencia"
   ```
   Pegar el `spreadsheet_id` que imprime en la sección `[google_sheets.dest]`
   del `secrets.toml`.
4. Ejecutar:
   ```
   streamlit run app.py
   ```

## Estructura

```
app.py                      Punto de entrada: estilos, datos comunes, barra lateral y navegación
docs/ayuda/                 Notas de la Ayuda (Markdown estilo Obsidian, índice en Ayuda.md)
views/
  reporte.py                Página "Reporte de consultas" (consultas del bot)
  negocios.py               Página "Negocios Bitrix24"
  clasificacion.py          Página "Clasificación manual"
  analisis.py               Página "Análisis preliminar" (embudo e informe del período)
  ayuda.py                  Página "Ayuda": muestra las notas de docs/ayuda/
  common.py                 Filtros de período y de mes, tarjeta de provincias (mapa + ranking)
utils/
  data.py                   Carga con caché (bot, Bitrix, índice) y armado del mes / período
  ui.py                     CSS y componentes: KPI, tarjeta gráfico ⇄ datos, datos crudos
  charts.py                 Opciones de ECharts (torta, barras, columnas apiladas)
  kpis.py                   Variación de KPIs contra el período anterior
  sheets.py                 gspread I/O (fuente, pestañas mensuales, índice de teléfonos)
  bitrix.py                 Cliente REST Bitrix24 (batch, rate limit) + normalización de deals
  phone_ar.py               Formato '+54 9 <area> <local>', provincia y localidad (ENACOM) por código de área
  geo.py                    Conteo por provincia y localidad, mapa de provincias y de burbujas por localidad
  cache.py                  Limpieza, unificación mensual, reglas automáticas, áreas
  informe.py                Informe del período descargable (nota Markdown)
  machinery.py              Clasificación de maquinaria por nombre del negocio
  pending.py                Cola de clasificaciones sin sincronizar
  periods.py                Período elegido (mes / trimestre / semestre / año / rango), anterior y textos
  branding.py, styling.py   Colores Cotear y coloreo de tablas
data/
  codigos_area_argentina.json   Código de área → provincia
  localidades_ar.json           Código de área → localidad cabecera y centroide (ENACOM + Georef)
  departamentos_ar.geojson      Departamentos y partidos (IGN vía Georef) para el detalle por provincia
  provincias_argentina.geojson  Contornos de provincias para el mapa (CABA dentro de Buenos Aires)
scripts/                    Diagnóstico de Bitrix y creación del libro destino
tests/                      Pruebas de funciones puras (pytest)
.streamlit/
  config.toml               Tema visual claro (fondo gris, tarjetas blancas, azul #01498E)
  secrets.toml              (NO commitear)
```

## Páginas

Navegación y filtros en la barra lateral; sólo se ejecuta la página abierta.
El período (mes, trimestre T1–T4, semestre S1–S2, año o rango de fechas) es el
mismo en Reporte de consultas, Negocios Bitrix24 y Análisis preliminar y se
conserva al cambiar de página; Clasificación manual usa sólo el mes.

- **Reporte de consultas**: KPIs con variación contra el período anterior de
  igual duración (mini línea de 6 meses sólo con período Mes) (consultas,
  provincia y área principal, % sin interés real = sin respuestas + sin
  interés), distribución por clasificación (barras ⇄ torta), área de interés
  (barras sólidas por derivación interna ⇄ segmentadas por clasificación), mapa + ranking de provincias (clic en una
  provincia: detalle por localidad), día de la semana, día × hora y datos crudos del período.
- **Negocios Bitrix24**: mismo período compartido. Sólo
  cuenta los negocios **creados** dentro del período (con su etapa actual). Los
  KPIs se comparan con el período anterior de igual duración (mes, trimestre o
  año anterior; en un rango, los mismos días justo antes). Tipo de máquina ×
  etapa (total ⇄ etapas), motivos de baja (torta ⇄ barras), fuentes (sólidas ⇄
  apiladas por etapa), mapa + ranking de provincias (con detalle por localidad), campañas de anuncios
  (total ⇄ por red ⇄ por etapa) y lista de negocios (columna Tipo maquinaria oculta).
- **Clasificación manual**: selección de un reporte y guardado en cola; el
  botón *Sincronizar* de la barra lateral lo escribe en Sheets.
- **Análisis preliminar**: embudo consultas → derivadas → cotizadas → ganadas
  y "Descargar informe (.md)": borrador del reporte de actividad del período en
  Markdown (estilo Obsidian) que enlaza los gráficos descargados de la app. El
  título lleva el período y debajo un recuadro "Período analizado" lo detalla
  (nombre, meses, fechas y, si sigue en curso, hasta qué día hay datos).

### Diseño

- Gráficos con ECharts nativo (`st.echarts_chart`, dibujados en SVG): etiquetas
  en porcentaje, tooltip con la cantidad al pasar el mouse, sin controles de
  zoom y un ícono para descargar en SVG (vectorial) a 800 × 600 fijo, sin
  importar la pantalla. Torta con leyenda a la derecha; nombres largos de
  barras en 2 renglones; leyendas de barras en columnas parejas. El mapa de
  provincias usa Plotly sin barra de herramientas (ECharts nativo no admite
  contornos propios); al hacer clic en una provincia muestra su mapa político (departamentos) con
  burbujas por localidad y etiquetas con flecha.
- Tarjetas blancas con borde suave y esquinas de 8 px, sin sombra ni acentos
  de color. Sin emojis: íconos Material sólo en las acciones principales.
- Números con coma decimal ("14,3 %") en gráficos, mapa y KPIs; las tablas
  conservan el punto para seguir siendo ordenables.
- Cada tarjeta tiene el botón Gráfico ⇄ Datos: el gráfico se desliza y aparece
  la tabla. Es sólo CSS (`on_change="ignore"`), no vuelve a ejecutar la app.
  Cambiar el tipo de gráfico re-ejecuta sólo esa tarjeta (`st.fragment`).
- KPIs: verde/rojo según la polaridad del indicador. Indicadores negativos
  (bajar es bueno): % sin interés real y motivo de baja más frecuente. "En
  curso" y "Vida de negocio" son neutros y se informan en gris.
- Datos crudos al final, en un desplegable con su botón de descarga (CSV UTF-8
  con BOM).

## Reglas automáticas de clasificación

Se aplican al cargar los reportes del mes:

- Todos los reportes de un mismo número dentro del mismo mes calendario se
  **unifican** sobre el último (los resúmenes previos quedan debajo).
- Número extranjero → `SIN INTERES`.
- Teléfono presente en algún negocio de venta de Bitrix → `DERIVADO A BITRIX`,
  y el nombre se reemplaza por el de Bitrix. El cruce usa el índice
  `_bitrix_telefonos` (todos los negocios, refresco semanal) más los negocios
  del mes.
- `Tipo de contacto = SI_RESUMEN_G2` → `DERIVADO A TÉCNICA`.
- Resto → `SIN CLASIFICAR` (placeholder: no se guarda en Sheets, así una
  coincidencia posterior con Bitrix lo reclasifica sola).

La clasificación manual sobrescribe cualquier valor previo y persiste en la
pestaña `YYYY-MM_Bot` del libro destino; sólo se escriben las filas que cambian.

## Tests

```
pip install -r requirements-dev.txt
pytest
```
