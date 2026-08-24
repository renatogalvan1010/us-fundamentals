# US Fundamentals

Dashboard de fundamentals de empresas de EEUU. Los datos se bajan de Yahoo Finance
mediante GitHub Actions (no necesitás Python en tu máquina) y se muestran en una
página estática servida por GitHub Pages.

## Estructura

```
scripts/fetch_data.py          → baja datos de Yahoo, escribe docs/data.json
.github/workflows/update.yml   → corre el script (schedule + botón manual)
docs/index.html                → la página (lee data.json)
docs/data.json                 → datos generados (se sobrescribe en cada corrida)
```

## Setup (una sola vez, todo desde el navegador)

1. **Crear el repo** en GitHub y subir estos archivos (respetando las carpetas).
2. **Activar Pages:** Settings → Pages → Source: "Deploy from a branch" →
   Branch: `main`, carpeta `/docs` → Save. La URL aparece ahí en un minuto.
3. **Correr la primera vez:** pestaña Actions → "Actualizar fundamentals" →
   Run workflow. Esperá que termine (~1 min) y recargá tu página de Pages.

Después corre solo de lunes a viernes a las 8 AM de Buenos Aires. Para forzar
una actualización, usás Run workflow cuando quieras.

## Cambiar las empresas

Editá la lista `TICKERS` arriba de todo en `scripts/fetch_data.py`, commiteá,
y corré el workflow. La página se actualiza sola.

## Nota sobre los datos

Yahoo Finance no es una fuente oficial. Para valuación seria cruzá las cifras
clave contra el 10-K / 10-Q en SEC EDGAR. Los campos `.info` de yfinance
ocasionalmente cambian o vienen vacíos; el script omite lo que no puede leer
en vez de romperse.
