#!/usr/bin/env python3
"""Genera apps.json a partir de fuentes.json leyendo la ultima release de cada repo.

Solo usa la biblioteca estandar. Si existe la variable GITHUB_TOKEN se usa para
la API de GitHub (mas limite de peticiones); los repos leidos son publicos.

Uso: python scripts/generar_catalogo.py [--raiz CARPETA] [--base-url URL]
"""

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

BASE_URL_POR_DEFECTO = "https://raw.githubusercontent.com/Yuk1Katsume/yukistore-catalog/main"
API = "https://api.github.com"


# --------------------------------------------------------------------------
# Red
# --------------------------------------------------------------------------

def _peticion(url, acepta="application/json"):
    cabeceras = {"Accept": acepta, "User-Agent": "yukistore-catalog"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API):
        cabeceras["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=cabeceras)


def obtener_json(url):
    with urllib.request.urlopen(_peticion(url), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def descargar(url, destino):
    """Descarga url en destino y devuelve el sha256."""
    h = hashlib.sha256()
    with urllib.request.urlopen(_peticion(url, "application/octet-stream"), timeout=300) as r, open(destino, "wb") as f:
        while True:
            bloque = r.read(1 << 16)
            if not bloque:
                break
            h.update(bloque)
            f.write(bloque)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Lectura minima del AndroidManifest.xml binario (AXML) de un APK
# --------------------------------------------------------------------------

RES_VERSION_CODE = 0x0101021B
RES_VERSION_NAME = 0x0101021C


def _leer_string_pool(datos, inicio):
    _tipo, tam_cab, _tam = struct.unpack_from("<HHI", datos, inicio)
    n, _estilos, flags, ini_strings, _ini_estilos = struct.unpack_from("<IIIII", datos, inicio + 8)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{n}I", datos, inicio + tam_cab)
    base = inicio + ini_strings
    cadenas = []
    for off in offsets:
        p = base + off
        if utf8:
            # longitud en caracteres (se ignora) y longitud en bytes
            for _ in range(2):
                largo = datos[p]
                p += 1
                if largo & 0x80:
                    largo = ((largo & 0x7F) << 8) | datos[p]
                    p += 1
            cadenas.append(datos[p:p + largo].decode("utf-8", "replace"))
        else:
            largo = struct.unpack_from("<H", datos, p)[0]
            p += 2
            if largo & 0x8000:
                largo = ((largo & 0x7FFF) << 16) | struct.unpack_from("<H", datos, p)[0]
                p += 2
            cadenas.append(datos[p:p + largo * 2].decode("utf-16-le", "replace"))
    return cadenas


def leer_manifest(ruta_apk):
    """Devuelve (paquete, versionCode, versionName) del APK."""
    with zipfile.ZipFile(ruta_apk) as z:
        datos = z.read("AndroidManifest.xml")
    cadenas, mapa_res = [], []
    p = 8  # cabecera del documento XML
    while p < len(datos):
        tipo, tam_cab, tam = struct.unpack_from("<HHI", datos, p)
        if tipo == 0x0001:
            cadenas = _leer_string_pool(datos, p)
        elif tipo == 0x0180:
            mapa_res = list(struct.unpack_from(f"<{(tam - tam_cab) // 4}I", datos, p + tam_cab))
        elif tipo == 0x0102:
            _ns, nombre, ini_attr, tam_attr, n_attr = struct.unpack_from("<IIHHH", datos, p + 16)
            if cadenas[nombre] == "manifest":
                paquete = codigo = version = None
                for i in range(n_attr):
                    a = p + 16 + ini_attr + i * tam_attr
                    _ans, anombre, crudo, _s, _r, tipo_dato, dato = struct.unpack_from("<IIIHBBI", datos, a)
                    clave = cadenas[anombre] if anombre < len(cadenas) else ""
                    resid = mapa_res[anombre] if anombre < len(mapa_res) else 0
                    texto = cadenas[crudo] if crudo != 0xFFFFFFFF else (cadenas[dato] if tipo_dato == 0x03 else None)
                    if clave == "package":
                        paquete = texto
                    elif clave == "versionCode" or resid == RES_VERSION_CODE:
                        codigo = dato if tipo_dato in (0x10, 0x11) else int(texto)
                    elif clave == "versionName" or resid == RES_VERSION_NAME:
                        version = texto
                return paquete, codigo, version
        p += tam
    raise ValueError("AndroidManifest.xml sin elemento <manifest>")


# --------------------------------------------------------------------------
# Catalogo
# --------------------------------------------------------------------------

def procesar_app(fuente, previa, base_url, tmp):
    repo = fuente["repo"]
    rel = obtener_json(f"{API}/repos/{repo}/releases/latest")
    apks = [a for a in rel.get("assets", []) if a["name"].lower().endswith(".apk")]
    if not apks:
        raise ValueError(f"la release {rel.get('tag_name')} de {repo} no tiene APK")
    apk = apks[0]
    url = apk["browser_download_url"]
    notas = (rel.get("body") or "").strip()
    publicado = rel.get("published_at")

    if fuente.get("tipo") == "version_json":
        vj = next((a for a in rel["assets"] if a["name"] == "version.json"), None)
        if vj:
            info = obtener_json(vj["browser_download_url"])
            url = info.get("url", url)
            notas = info.get("notes", notas)
            publicado = info.get("publishedAt", publicado)

    # Si el APK no ha cambiado desde la ultima vez, no se vuelve a descargar.
    if previa and previa.get("url") == url and previa.get("sha256") and previa.get("paquete"):
        paquete, codigo, version, sha = previa["paquete"], previa["versionCode"], previa["versionName"], previa["sha256"]
    else:
        ruta = os.path.join(tmp, f"{fuente['id']}.apk")
        print(f"  descargando {url}")
        sha = descargar(url, ruta)
        paquete, codigo, version = leer_manifest(ruta)
        os.remove(ruta)

    return {
        "id": fuente["id"],
        "nombre": fuente["nombre"],
        "descripcion": fuente.get("descripcion", ""),
        "icono": f"{base_url}/{fuente['icono']}" if fuente.get("icono") else None,
        "paquete": paquete,
        "versionCode": codigo,
        "versionName": version,
        "url": url,
        "sha256": sha,
        "tamano": apk.get("size"),
        "notas": notas,
        "publicado": publicado,
        "oculta": bool(fuente.get("oculta", False)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--base-url", default=BASE_URL_POR_DEFECTO)
    args = ap.parse_args()

    ruta_fuentes = os.path.join(args.raiz, "fuentes.json")
    ruta_salida = os.path.join(args.raiz, "apps.json")
    with open(ruta_fuentes, encoding="utf-8") as f:
        fuentes = json.load(f)["apps"]

    anterior = {}
    if os.path.exists(ruta_salida):
        with open(ruta_salida, encoding="utf-8") as f:
            anterior = {a["id"]: a for a in json.load(f).get("apps", [])}

    apps, errores = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for fuente in fuentes:
            print(f"- {fuente['id']} ({fuente['repo']})")
            try:
                app = procesar_app(fuente, anterior.get(fuente["id"]), args.base_url, tmp)
                print(f"  {app['paquete']} {app['versionName']} ({app['versionCode']})")
                apps.append(app)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    print("  sin releases todavia: se omite")
                else:
                    errores += 1
                    print(f"  ERROR HTTP {e.code}", file=sys.stderr)
                # Si falla, se conserva la entrada anterior para no perder la app.
                if fuente["id"] in anterior and e.code != 404:
                    apps.append(anterior[fuente["id"]])
            except Exception as e:  # noqa: BLE001
                errores += 1
                print(f"  ERROR {e}", file=sys.stderr)
                if fuente["id"] in anterior:
                    apps.append(anterior[fuente["id"]])

    if apps == list(anterior.values()):
        print("Sin cambios.")
        return 1 if errores else 0

    salida = {
        "version": 1,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "apps": apps,
    }
    with open(ruta_salida, "w", encoding="utf-8", newline="\n") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"apps.json actualizado ({len(apps)} apps).")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
