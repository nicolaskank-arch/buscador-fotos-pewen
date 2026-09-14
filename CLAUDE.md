# CLAUDE.md

Guía para asistentes de IA que trabajen en este repositorio.

> El código, los comentarios y la UI están **en español (rioplatense)**. Mantené ese
> idioma en todo lo que agregues: nombres de funciones (`buscar`, `procesar`,
> `persistir`), comentarios, prints, labels de Streamlit y mensajes de commit.

## Qué es esto

Buscador unificado de fotos de producto de Pewen: junta las imágenes de una **carpeta
pública de Google Drive** con las que scrapea de **pewenpisos.com.ar**, las indexa en
SQLite con thumbnail y color dominante, y las expone en un dashboard Streamlit donde
un asesor arma una selección y le pasa el link al cliente.

Tres piezas y un ciclo de vida particular: **el repo es la base de datos**. `fotos.db`
y `thumbs/` están versionados y se commitean solos — desde GitHub Actions (re-indexado)
y desde la app misma (ocultar/restaurar fotos).

## Estructura

```
buscador-fotos-pewen/
├─ app.py                     # UI Streamlit (543 líneas, monolito)
├─ indexador.py               # orquestador CLI + esquema SQLite
├─ fotos.db                   # SQLite VERSIONADO (~3 MB, 4607 filas hoy)
├─ thumbs/                    # JPGs 400px VERSIONADOS (~79 MB, 4607 archivos)
├─ requirements.txt
├─ src/
│  ├─ config.py               # rutas, URL del Drive, categorías del sitio, tamaños
│  ├─ drive_sync.py           # lista la carpeta pública del Drive vía gdown
│  ├─ web_scraper.py          # scraper de pewenpisos.com.ar
│  ├─ analyzer.py             # descarga + thumbnail + color dominante + tono
│  ├─ persistencia.py         # commit+push de fotos.db desde la app corriendo
│  └─ sincronizacion.py       # dispara el workflow de Actions vía API de GitHub
├─ .github/workflows/indexar.yml   # cron cada 12 hs + workflow_dispatch
└─ .devcontainer/devcontainer.json # Codespaces: levanta streamlit en el puerto 8501
```

No hay tests, ni linters, ni CI de calidad. El único workflow es el de indexado.

## Comandos

```bash
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate en Windows
pip install -r requirements.txt

python indexador.py               # incremental: reusa thumbs ya generados
python indexador.py --rebuild     # borra fotos.db y rehace todo (~25 min)
python indexador.py --solo-drive  # saltea el scraper del sitio
python indexador.py --solo-web    # saltea el sync del Drive

streamlit run app.py              # http://localhost:8501

# Los módulos de src/ corren sueltos para debug:
python -m src.web_scraper                        # scrapea todas las categorías
python -m src.web_scraper /pisos-flotantes-clasicos/   # una sola
python -m src.drive_sync                         # lista la carpeta del Drive
```

Python 3.11 (lo fijan el workflow y el devcontainer). Los imports son
`from src.config import ...`, así que **hay que correr todo desde la raíz del repo**.

## Esquema de la base

Definido como string `SCHEMA` en `indexador.py`. Tabla `fotos`:

| columna | notas |
|---|---|
| `id` | PK. `hash_id(source, clave)` = `{source}_{md5(source:clave)[:16]}` |
| `source` | `'drive'` \| `'web'` |
| `name`, `alt`, `categoria` | texto buscable |
| `url_original`, `url_view`, `url_download` | links a la foto grande |
| `thumb_path` | relativo a la raíz: `thumbs/drive_abc123.jpg` |
| `r,g,b` / `h,s,v` | color dominante (RGB entero, HSV con h en grados) |
| `tono` | nombre del color en español (`"Beige"`, `"Gris claro"`, …) |
| `width`, `height`, `indexed_at` | metadata |
| `hidden` | `0` visible / `1` en la papelera |

Índices en `tono`, `source`, `categoria`, `hidden`. Hay además una tabla FTS5
(`fotos_fts`, tokenize `unicode61`) que `upsert_foto()` mantiene al día — **pero
`app.py` no la usa**: la búsqueda actual es `LIKE %token%` sobre `name`/`alt`/
`categoria`. Si migrás a FTS, la tabla ya está poblada.

Reglas al tocar el esquema:

- `hash_id()` define la identidad de una foto. **Cambiarlo invalida los 4607 thumbs**
  y fuerza un `--rebuild` completo. No lo toques.
- `upsert_foto()` hace `ON CONFLICT(id) DO UPDATE` excluyendo `id` y **`hidden`**:
  re-indexar nunca pisa lo que el usuario ocultó. Si agregás una columna con estado
  de usuario, sumala a esa exclusión.
- `init_db()` tiene una migración inline (agrega `hidden` si falta). Ese es el patrón
  para nuevas columnas: `ALTER TABLE` condicional, no un sistema de migraciones.

## Flujo de indexado (`indexador.py`)

1. **Drive** (`src/drive_sync.py`): `gdown.download_folder(skip_download=True)` lista
   la carpeta recursivamente. Sin API key ni OAuth — la carpeta tiene que estar en
   "cualquiera con el link, lector". Filtra por extensión de imagen. La clave de
   identidad es el `id` del archivo de Drive.
2. **Sitio** (`src/web_scraper.py`): recorre `SITE_CATEGORIES` (19 paths), scrapea la
   grid y todos los `/producto/X/` linkeados (16 threads). El sitio es WordPress con
   lazy-load: las URLs reales viven en `data-src`, `data-lazy-src`, `srcset`.
   Dedup global normalizando el sufijo `-WxH` de WordPress. Filtra logos, íconos y
   promos bancarias con `EXCLUDE_PATTERNS`, y descarta imágenes < 200 px.
3. **Procesado** (`src/analyzer.py`): descarga, `exif_transpose`, thumbnail 400 px
   JPEG q82, color medio recortando el 10% de los bordes, y clasificación HSV → nombre
   de tono.

Concurrencia: `procesar_lista()` usa 8 workers, pero **los workers no tocan SQLite** —
devuelven la row y el main thread inserta. Mantené esa separación.

Incremental: `ya_procesado()` saltea una foto si ya está en la DB **y** el thumb existe
en disco. Borrar un thumb fuerza su re-procesado.

## Persistencia: el repo se auto-commitea

Dos caminos escriben al repo, y hay que tenerlos presentes al trabajar acá:

- **`.github/workflows/indexar.yml`** — cron `0 */12 * * *` + botón manual. Corre
  `python indexador.py` y commitea `fotos.db` + `thumbs/` como `github-actions[bot]`
  con mensaje `auto: reindexado YYYY-MM-DD`.
- **`src/persistencia.py`** — cuando un usuario oculta/restaura una foto en la app
  desplegada, `_persist_async()` lanza un thread daemon que hace
  `add fotos.db` → `commit` → `pull --rebase` → `push` a `main`, con el PAT de
  `st.secrets["github_pat"]` (o la env var `GITHUB_PAT`) inyectado en la URL del
  remote. Sin PAT no hace nada y la app avisa "modo efímero".

Consecuencias:

- **`main` se mueve solo.** Hacé `git fetch` antes de rebasear. Los commits
  `auto: reindexado` son datos, no código.
- Un cambio en el pipeline de indexado se propaga sólo al siguiente re-indexado (hasta
  12 hs), o disparando el workflow a mano desde la app o la pestaña Actions.
- `src/sincronizacion.py` dispara ese workflow vía `POST /actions/workflows/indexar.yml/dispatches`
  con `{"ref": "main"}`. Si renombrás el archivo del workflow, actualizá `WORKFLOW_FILE`.
- El PAT necesita scopes **Contents: read/write** y **Actions: read/write**. Nunca lo
  hardcodees: `.gitignore` ya excluye `.streamlit/secrets.toml`.

## La app (`app.py`)

- Conexión con `@st.cache_resource` y `check_same_thread=False`. Intenta
  `PRAGMA journal_mode=WAL` y **cae al journal default si falla** — Streamlit Cloud no
  siempre deja crear los `-shm`/`-wal`. No saques ese try/except.
- **`SINONIMOS`** (`app.py:63`) mapea alemán ↔ español en ambas direcciones: las fotos
  del Drive vienen con nombres originales de Kronotex (`Zement`, `Eiche`, `Nussbaum`)
  y el sitio está en castellano. Cada palabra del query debe matchear (AND) y acepta
  cualquiera de sus sinónimos (OR). Al agregar un par, cargá **las dos direcciones**.
- La búsqueda **no lleva `LIMIT` en el SQL a propósito** (comentario en `app.py:140`):
  con LIMIT el orden por rowid devolvía sólo fotos de Drive. Se ordena/intercala en
  Python y recién ahí se recorta a 600. No "optimices" moviendo el limit al SQL.
- `_intercalar()` alterna drive/web para que ninguna fuente domine la primera pantalla.
- Filtro por color: distancia HSV con el hue pesado x4 (`dist()` en `buscar()`).
- **La selección vive en la query string** (`?sel=id1,id2,...`), no en session_state —
  eso es lo que hace el link compartible. `get_seleccion()` / `set_seleccion()`.
- Descargas: ZIP de thumbs (lee de disco, rápido) o ZIP de originales (8 threads,
  lento). Los nombres se sanitizan con `_safe_filename()` y se desduplican con el
  prefijo del id.
- Ocultar no borra: pone `hidden=1`. El toggle "Modo papelera" muestra esas fotos para
  restaurarlas.

## Configuración (`src/config.py`)

Todo lo ajustable vive acá:

- `DRIVE_FOLDER_URL` — carpeta del Drive (overridable por env var del mismo nombre,
  que `indexador.py` lee con prioridad).
- `SITE_CATEGORIES` — los 19 paths que scrapea. Agregar/sacar categorías es editar
  esta lista.
- `THUMB_SIZE` (400) / `THUMB_QUALITY` (82) — subirlos infla el repo; ver abajo.
- `HTTP_HEADERS` — User-Agent identificado como `PewenBuscadorBot`. Dejalo así.
- `REQUEST_TIMEOUT` (20 s).

## Convenciones

- Español en todo, incluidos docstrings de módulo (todos los archivos de `src/` abren
  con uno que explica el porqué, no el qué — seguí ese estilo).
- `from __future__ import annotations` + type hints modernos (`list[dict]`, `str | None`).
- Los helpers privados van con `_guion_bajo` al principio.
- Los scrapers **nunca lanzan excepciones hacia arriba**: atrapan, loguean a `stderr`
  con prefijo (`[scraper]`, `[drive]`) y devuelven vacío. Mantené ese contrato — una
  categoría caída no puede tirar abajo el indexado entero.
- `persistir()` devuelve `(ok, mensaje)` en vez de tirar. Mismo criterio.

## Trampas conocidas

- **`colorthief` y `pandas` están en `requirements.txt` pero no se importan en ningún
  lado.** `analyzer.py` calcula el color a mano. Son residuos; sacalos sólo si estás
  seguro de que no rompés el deploy de Streamlit Cloud.
- El repo pesa ~82 MB por `thumbs/`. El README avisa que a ~10k fotos serían ~250 MB y
  que ahí conviene mudar los thumbs a S3/R2. Tenelo en cuenta antes de subir
  `THUMB_SIZE`.
- Si la carpeta del Drive deja de ser pública, `drive_sync` devuelve `[]` en silencio
  (loguea a stderr) y el indexado sigue con las fotos del sitio nomás.
- `CACHE_DIR` está declarado en `config.py` y `cache/` está en `.gitignore`, pero hoy
  ningún módulo lo usa.
- El deploy es Streamlit Cloud apuntando a `main` / `app.py`; cada commit automático
  dispara un redeploy.
