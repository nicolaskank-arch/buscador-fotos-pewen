# Stock de Tinturas — Yellow · Color Master

App de escritorio/web (Streamlit + SQLite) para llevar el stock de tinturas del salón:
**lotes con vencimiento**, **mezclador de fórmulas** y **verificación de stock** contra el conteo físico.

> **Nota**: este proyecto está pensado para vivir en su propio repo. Por ahora viaja como carpeta
> dentro de `buscador-fotos-pewen` porque no tenía permiso para crear repos nuevos desde la sesión.
> Para independizarlo alcanza con copiar esta carpeta a un repo vacío — no depende de nada de afuera.

## Qué resuelve

| Problema | Cómo lo resuelve |
|---|---|
| Pomos que se vencen en el estante | Cada lote tiene su vencimiento y el tablero lo marca con semáforo (🔴 vencido, 🟠 <30 días, 🟡 <90 días) |
| Usar mercadería vencida sin darse cuenta | El stock vencido no cuenta como disponible ni lo propone el mezclador |
| "¿Cuánto pongo de cada tono?" | El mezclador pasa la receta en partes a gramos, ml de oxidante y pomos |
| El sistema dice una cosa y el estante otra | Verificación: se cuenta lo físico y se ajusta con un click, dejando rastro |
| Quedarse sin un tono | Stock mínimo por producto y panel de "Reponer" |

## Cómo se usa

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

La primera vez se crea `tinturas.db` y se siembra el catálogo (marcas Yellow y Color Master,
tonos, oxidantes y decolorante).

### Páginas

- **Tablero** (`app.py`) — vencimientos próximos, qué reponer, stock por producto.
- **📦 Stock** — ingreso de mercadería con lote y vencimiento, corrección de lotes, descarte de vencidos.
- **🧪 Mezclador** — fórmula por partes + proporción de oxidante, chequeo de stock y descuento.
- **✅ Verificación** — conteo físico, diferencias y ajuste.
- **📚 Catálogo** — alta y edición de tonos, presentaciones y stock mínimo.
- **📜 Movimientos** — historial completo, exportable a CSV.

## Cómo funciona por dentro

### Unidades

El stock se cuenta en **unidades** (pomos, botellas). Cada producto sabe cuánto contiene una
unidad (`contenido`): un pomo Yellow trae 100 g, uno de Color Master 60 g, una botella de
oxidante 900 ml. Así el mezclador puede pedir "90 g de 7.3" y traducirlo a 1,5 pomos de Color
Master o 0,9 de Yellow sin ambigüedad. Las fracciones son válidas — medio pomo abierto es `0.5`.

### FEFO

Todo consumo sale del lote que **vence primero** (*first expired, first out*), no del más viejo.
Los lotes sin fecha van al final de la cola. Los lotes vencidos quedan afuera: no se pueden
consumir por accidente, hay que descartarlos explícitamente.

### Mezclador

La receta se carga en **partes**: `7.3 ×2 + 8.1 ×1` con 90 g totales da 60 g y 30 g. La
proporción tintura:oxidante (1:1 a 1:3) define los ml de oxidante — con 1:1.5 y 90 g de color,
son 135 ml, 225 g de mezcla lista.

Antes de aplicar, la app contrasta cada componente contra el stock disponible y muestra de qué
lotes va a salir. Si falta un solo componente **no se descuenta ninguno**: no quedan fórmulas
aplicadas a medias.

El expander "¿Qué volumen usar?" da una guía orientativa (10 vol tono sobre tono, 20 vol canas
y 1-2 tonos, 30 vol 2-3 tonos, 40 vol super aclarantes). Es una referencia, no reemplaza la
tabla del fabricante.

### Verificación

Al abrir una verificación se congela lo que el sistema cree que hay en cada lote. Se cuenta en
varias tandas — mientras está abierta el stock no se toca, así el salón sigue trabajando. Al
cerrarla se generan los ajustes, uno por lote con diferencia. **Los lotes que quedaron sin
contar no se tocan**: un conteo parcial nunca borra stock que nadie revisó.

## Catálogo precargado

Los tonos vienen con la numeración internacional que usan ambas marcas: primer dígito = altura
(1 negro → 10 rubio extra claro), decimales = reflejo (`.0` natural, `.1` ceniza, `.2` irisado,
`.3` dorado, `.4` cobrizo, `.5` caoba, `.6` rojo), más super aclarantes (11.x) y correctores (0.x).

Es un punto de partida, no la carta completa de cada proveedor: presentaciones y tonos se editan
desde **Catálogo**. Las presentaciones sembradas son 100 g para Yellow y 60 g para Color Master —
si tu proveedor maneja otro gramaje, cambialo ahí y el mezclador se acomoda solo.

## Estructura

```
tinturas-stock/
├─ app.py                    # tablero
├─ pages/
│  ├─ 1_Stock.py
│  ├─ 2_Mezclador.py
│  ├─ 3_Verificacion.py
│  ├─ 4_Catalogo.py
│  └─ 5_Movimientos.py
├─ src/
│  ├─ db.py                  # esquema SQLite
│  ├─ catalogo.py            # marcas, productos, seed de tonos
│  ├─ stock.py               # lotes, FEFO, vencimientos, alertas
│  ├─ mezclador.py           # cálculo y aplicación de fórmulas
│  ├─ verificacion.py        # conteo físico y ajustes
│  └─ ui.py                  # helpers de Streamlit
└─ tests/                    # pytest — 55 casos (lógica + smoke de las páginas)
```

## Tests

```bash
pip install pytest
pytest -q
```

Cubren FEFO, exclusión de vencidos, alertas por vencimiento y mínimo, cálculo de mezclas,
conversión a pomos, aplicación atómica y el ciclo de verificación. `test_app.py` además corre
cada página con `AppTest` (Streamlit sin browser) contra una base temporal y contra una base
vacía, así el primer arranque también está cubierto.

## Deploy

Igual que el buscador de fotos: [share.streamlit.io](https://share.streamlit.io) → New app →
apuntar a este repo, branch `main`, archivo `app.py`.

**Ojo con la base**: `tinturas.db` está en `.gitignore` y Streamlit Cloud reinicia el
contenedor cada tanto, así que el stock cargado se perdería. Para uso real conviene una de
estas dos:

- **Local** — correr `streamlit run app.py` en la máquina del salón. Es lo más simple y la base
  queda en el disco.
- **En la nube con base persistente** — mover `tinturas.db` a Turso/LiteFS o pasar a Postgres
  (Supabase/Neon). Es un cambio acotado: toda la escritura pasa por `src/db.py`.
