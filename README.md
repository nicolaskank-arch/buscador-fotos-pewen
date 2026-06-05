# Buscador de Fotos Pewen

Buscador unificado de fotos de **Google Drive** + **pewenpisos.com.ar**.
Permite buscar por nombre/categoría/tono y armar selecciones compartibles.

## Cómo funciona

1. **Indexador** (`indexador.py`): lista fotos del Drive (carpeta pública) y scrapea las categorías del sitio, calcula color dominante, genera thumbnails y guarda todo en `fotos.db` (SQLite).
2. **App Streamlit** (`app.py`): UI con filtros, color picker y selección compartible vía URL.
3. **GitHub Actions** (`.github/workflows/indexar.yml`): re-corre el indexador cada 12 hs y commitea los cambios.

## Probar local

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows
pip install -r requirements.txt

# Indexar (primera vez tarda — descarga todas las fotos)
python indexador.py

# Levantar el dashboard
streamlit run app.py
```

Opciones útiles del indexador:

```bash
python indexador.py --rebuild      # tira la DB y empieza de cero
python indexador.py --solo-drive   # salta el scraper del sitio
python indexador.py --solo-web     # salta el sync del Drive
```

## Deploy a Streamlit Cloud

1. Subir el repo a GitHub (público o privado, ambos sirven).
2. Ir a [share.streamlit.io](https://share.streamlit.io) → "New app".
3. Apuntar a `tu-usuario/buscador-fotos-pewen`, branch `main`, archivo `app.py`.
4. Listo. Streamlit Cloud lee `requirements.txt` automáticamente.

La URL queda tipo `buscador-fotos-pewen.streamlit.app`. Ese es el link compartible.

### Indexado en GitHub Actions

El workflow se dispara solo cada 12 hs y commitea `fotos.db` + `thumbs/`. Cuando hay commit nuevo, Streamlit Cloud redeploya automático.

Para forzar un re-indexado manual: pestaña **Actions** del repo → **Reindexar fotos** → **Run workflow**.

## Cómo armar y compartir selecciones

1. Cualquier usuario marca con ✓ las fotos que le interesan.
2. En la barra lateral aparece un **link compartible** tipo `?sel=drive_abc,web_def,...`.
3. Copia ese link y se lo manda al cliente. El cliente abre y ve solo esa selección.

## Cuándo conviene tocar `src/config.py`

- **Cambiar la carpeta del Drive**: editar `DRIVE_FOLDER_URL` (o setear la env var `DRIVE_FOLDER_URL` en el workflow).
- **Agregar / sacar categorías del sitio**: editar `SITE_CATEGORIES`.
- **Subir o bajar el tamaño de los thumbs**: `THUMB_SIZE` (400px por default).

## Estructura

```
buscador-fotos-pewen/
├─ app.py                    # Streamlit
├─ indexador.py              # orquestador
├─ requirements.txt
├─ fotos.db                  # SQLite (lo genera el indexador)
├─ thumbs/                   # JPGs 400px (los genera el indexador)
├─ src/
│  ├─ config.py
│  ├─ drive_sync.py          # listado de Drive público
│  ├─ web_scraper.py         # scraper de pewenpisos.com.ar
│  └─ analyzer.py            # color dominante + thumbs
└─ .github/workflows/
   └─ indexar.yml            # re-indexado cada 12 hs
```

## Limitaciones / cosas a tener en cuenta

- **Drive**: la carpeta tiene que ser "cualquiera con el link, lector". Si en algún momento se cierra, hay que setear una Service Account (puedo guiar el setup cuando haga falta).
- **Repo público vs privado**: si el repo es público, las URLs de Drive y los thumbs son visibles para cualquiera que vea el repo. Si querés privacidad → repo privado + Streamlit Cloud "private app" (requiere plan pago de Streamlit) o cambiar a Render/Railway.
- **Tamaño del repo**: con thumbs a 400px, ~10k fotos pesan ~250 MB. GitHub lo banca, pero si crece mucho conviene mudar los thumbs a S3/Cloudflare R2.
- **Búsqueda semántica** ("cocina luminosa", "balcón con vista"): no está incluida. Si la querés, se suma con CLIP embeddings — me avisás y la agrego.

## Soporte

Issues y pedidos: abrir un issue en el repo de GitHub.
