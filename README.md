# YukiStore · catálogo

Catálogo público que lee la app **YukiStore**. Aquí solo hay metadatos, iconos y el APK de la propia tienda; el código de cada app sigue en su repo privado.

- `fuentes.json`: qué apps hay y en qué repo **público** se publican sus APK.
- `apps.json`: lo genera `scripts/generar_catalogo.py` (no editar a mano). Lee la última release de cada repo y saca del propio APK el paquete, `versionCode` y `versionName`, además del SHA-256.
- La GitHub Action lo regenera cada 3 horas, al tocar `fuentes.json` o a mano desde la pestaña *Actions*.

## Añadir una app

1. Publica sus APK en releases de un repo público (por ejemplo `mi-app-releases`).
2. Añade una entrada en `fuentes.json` y su icono en `iconos/`.
3. Haz push: la Action actualiza `apps.json`.

## Publicar una versión de YukiStore

Sube el APK firmado como release de este repo (`vX.Y.Z`). La tienda se actualiza a sí misma desde aquí.
