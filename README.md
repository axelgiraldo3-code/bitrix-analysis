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
views/
  reporte.py                Página "Reporte mensual" (consultas del bot)
  negocios.py               Página "Negocios Bitrix24"
  clasificacion.py          Página "Clasificación manual"
  common.py                 Filtro de mes y tarjeta de provincias (mapa + ranking)
utils/
  data.py                   Carga con caché (bot, Bitrix, índice) y armado del mes / período
  ui.py                     CSS y componentes: KPI, tarjeta gráfico ⇄ datos, datos crudos
  charts.py                 Opciones de ECharts (torta, barras, columnas apiladas)
  kpis.py                   Variación de KPIs contra el período anterior
  sheets.py                 gspread I/O (fuente, pestañas mensuales, índice de teléfonos)
  bitrix.py                 Cliente REST Bitrix24 (batch, rate limit) + normalización de deals
  phone_ar.py               Formato '+54 9 <area> <local>' y provincia por código de área
  geo.py                    Conteo por provincia con agrupación en "Otros"
  cache.py                  Limpieza, unificación mensual, reglas automáticas, áreas
  machinery.py              Clasificación de maquinaria por nombre del negocio
  pending.py                Cola de clasificaciones sin sincronizar
  periods.py                Rangos de mes / trimestre / año y período anterior
  branding.py, styling.py   Colores Cotear y coloreo de tablas
data/
  codigos_area_argentina.json   Código de área → provincia
  provincias_argentina.geojson  Contornos de provincias para el mapa (CABA dentro de Buenos Aires)
scripts/                    Diagnóstico de Bitrix y creación del libro destino
tests/                      Pruebas de funciones puras (pytest)
.streamlit/
  config.toml               Tema visual claro (fondo gris, tarjetas blancas, azul #01498E)
  secrets.toml              (NO commitear)
```

## Páginas

Navegación y filtros (mes o período) en la barra lateral; sólo se ejecuta la
página abierta.

- **Reporte mensual**: KPIs con variación contra el mes anterior (consultas,
  provincia y área principal, % sin interés real = sin respuestas + sin
  interés), distribución por clasificación (torta ⇄ barras), área de interés
  (barras sólidas por derivación interna ⇄ segmentadas por clasificación), mapa + ranking de provincias y datos crudos del mes.
- **Negocios Bitrix24**: período libre (mes, trimestre, año, rango). Sólo
  cuenta los negocios **creados** dentro del período (con su etapa actual). Los
  KPIs se comparan con el período anterior de igual duración (mes, trimestre o
  año anterior; en un rango, los mismos días justo antes). Tipo de máquina ×
  etapa (cantidad ⇄ %), motivos de baja (torta ⇄ barras), mapa + ranking de
  provincias y lista de negocios (columna Tipo maquinaria oculta).
- **Clasificación manual**: selección de un reporte y guardado en cola; el
  botón *Sincronizar* de la barra lateral lo escribe en Sheets.

### Diseño

- Gráficos con ECharts nativo (`st.echarts_chart`): tooltip al pasar el mouse,
  sin controles de zoom y un ícono para descargar en PNG. El mapa de
  provincias usa Plotly sin barra de herramientas (ECharts nativo no admite
  contornos propios).
- Cada tarjeta tiene el botón Gráfico ⇄ Datos: el gráfico se desliza y aparece
  la tabla. Es sólo CSS (`on_change="ignore"`), no vuelve a ejecutar la app.
  Cambiar el tipo de gráfico re-ejecuta sólo esa tarjeta (`st.fragment`).
- KPIs: verde/rojo según la polaridad del indicador. Indicadores negativos
  (bajar es bueno): % sin interés real, motivo de baja más frecuente y vida de
  negocio. "En curso" se informa en gris.
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
