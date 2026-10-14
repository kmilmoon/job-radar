# job-radar

Descarga cada mañana los tablones públicos de empleo (Ashby, Greenhouse y Lever) de las empresas de `companies.json` y guarda en `data/jobs.json` las ofertas de seguridad, GRC, compliance y riesgo.

- Se ejecuta solo con GitHub Actions, de lunes a viernes, antes del radar diario de Claude.
- Para lanzarlo a mano: pestaña **Actions** → *Fetch job boards* → **Run workflow**.
- Para añadir una empresa: añade `{"name": "Nombre"}` a `companies.json`. Si conoces su tablón, añade `"ats": "ashby"` (o `greenhouse`, `lever`) y `"slugs": ["slug"]`.
- `data/run.json` dice cuántos tablones se leyeron y qué empresas no tienen tablón público.

Solo contiene ofertas públicas y nombres de empresas. Ningún dato personal.
