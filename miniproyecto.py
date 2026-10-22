"""
=====================================================================
  INFLACIÓN PERSONAL DE ESTUDIANTES  —  proyecto completo en un archivo
=====================================================================
Guarda este archivo como  proyecto_inflacion.py  y desde la terminal:

  1) Instalar librerías (una sola vez):
        pip install streamlit pandas matplotlib pdfplumber requests gspread

  2) Abrir la calculadora con encuesta:
        streamlit run proyecto_inflacion.py

  3) Analizar respuestas y crear gráficos (carpeta "salidas"):
        python proyecto_inflacion.py analisis --demo      <- datos inventados para practicar
        python proyecto_inflacion.py analisis             <- respuestas reales
        python proyecto_inflacion.py analisis --csv hoja.csv

  4) Actualizar el IPC cada mes (cuando el DANE publique, ~día 7):
        python proyecto_inflacion.py actualizar --mes 10 --anio 2026 --medellin 7.10

Las respuestas se guardan en "respuestas.csv" junto a este archivo, o en Google Sheets
si creas ".streamlit/secrets.toml" (ver README del proyecto, paso 7).
Fuente de datos: DANE, Boletín técnico IPC septiembre 2026.
"""
import argparse
import copy
import csv
import json
import re
from datetime import date, datetime
from pathlib import Path

CARPETA = Path(__file__).parent
ARCHIVO_IPC = CARPETA / "ipc_actualizado.json"      # lo crea el comando "actualizar"
ARCHIVO_CSV = CARPETA / "respuestas.csv"
ARCHIVO_SECRETOS = CARPETA / ".streamlit" / "secrets.toml"
SALIDAS = CARPETA / "salidas"

# =====================================================================
# 1. DATOS DEL IPC (DANE, variación anual septiembre 2025 → septiembre 2026)
# =====================================================================
IPC_BASE = {
    "periodo": "Septiembre 2026",
    "comparacion": "septiembre 2025 → septiembre 2026",
    "nacional": 6.29,
    "medellin": 7.04,
    "fuente": "https://www.dane.gov.co/files/operaciones/IPC/sep2026/bol-IPC-sep2026.pdf",
    "actualizado": "2026-10-20",
    # División del IPC: peso en la canasta del hogar promedio (%) y variación anual (%)
    "divisiones": {
        "Alimentos y bebidas no alcohólicas": {"peso": 15.05, "variacion": 6.74},
        "Bebidas alcohólicas y tabaco": {"peso": 1.70, "variacion": 6.05},
        "Prendas de vestir y calzado": {"peso": 3.98, "variacion": 3.12},
        "Alojamiento, agua, electricidad, gas y otros combustibles": {"peso": 33.12, "variacion": 5.74},
        "Muebles, artículos para el hogar y para la conservación ordinaria del hogar": {"peso": 4.19, "variacion": 6.75},
        "Salud": {"peso": 1.71, "variacion": 7.79},
        "Transporte": {"peso": 12.93, "variacion": 5.27},
        "Información y comunicación": {"peso": 4.33, "variacion": 4.45},
        "Recreación y cultura": {"peso": 3.79, "variacion": 4.91},
        "Educación": {"peso": 4.41, "variacion": 7.49},
        "Restaurantes y hoteles": {"peso": 9.43, "variacion": 9.44},
        "Bienes y servicios diversos": {"peso": 5.36, "variacion": 5.63},
    },
    # Subclases más precisas para los gastos típicos de un estudiante
    "subclases": {
        "Arriendo efectivo": 5.12,
        "Electricidad": 6.92,
        "Comidas en establecimientos de servicio a la mesa y autoservicio": 9.44,
        "Comidas preparadas fuera del hogar para consumo inmediato": 9.41,
        "Transporte urbano": 10.65,
    },
    # Rubros que ve el estudiante -> subclase (si existe) y división del DANE
    "rubros": {
        "arriendo":  {"nombre": "Arriendo o pieza", "subclase": "Arriendo efectivo",
                      "division": "Alojamiento, agua, electricidad, gas y otros combustibles"},
        "servicios": {"nombre": "Servicios: luz, agua, gas", "subclase": "Electricidad",
                      "division": "Alojamiento, agua, electricidad, gas y otros combustibles"},
        "mercado":   {"nombre": "Mercado para cocinar", "subclase": None,
                      "division": "Alimentos y bebidas no alcohólicas"},
        "almuerzo":  {"nombre": "Almuerzos y restaurante",
                      "subclase": "Comidas en establecimientos de servicio a la mesa y autoservicio",
                      "division": "Restaurantes y hoteles"},
        "rapidas":   {"nombre": "Comidas rápidas, mecato, domicilios",
                      "subclase": "Comidas preparadas fuera del hogar para consumo inmediato",
                      "division": "Restaurantes y hoteles"},
        "metro":     {"nombre": "Metro y bus", "subclase": "Transporte urbano", "division": "Transporte"},
        "moto":      {"nombre": "Moto, gasolina, apps de transporte", "subclase": None, "division": "Transporte"},
        "cel":       {"nombre": "Plan de celular, internet, streaming", "subclase": None,
                      "division": "Información y comunicación"},
        "u":         {"nombre": "Universidad y materiales", "subclase": None, "division": "Educación"},
        "ocio":      {"nombre": "Salidas, cine, deporte", "subclase": None, "division": "Recreación y cultura"},
        "licor":     {"nombre": "Cerveza, licor, cigarrillo", "subclase": None,
                      "division": "Bebidas alcohólicas y tabaco"},
        "ropa":      {"nombre": "Ropa y zapatos", "subclase": None, "division": "Prendas de vestir y calzado"},
        "salud":     {"nombre": "Farmacia y salud", "subclase": None, "division": "Salud"},
        "aseo":      {"nombre": "Aseo personal y otros", "subclase": None, "division": "Bienes y servicios diversos"},
    },
}

PERFILES = {
    "Vivo con mis papás": dict(almuerzo=220_000, rapidas=120_000, metro=150_000, cel=60_000, u=150_000,
                               ocio=100_000, licor=60_000, ropa=60_000, salud=20_000, aseo=30_000),
    "Vivo solo en una pieza": dict(arriendo=750_000, servicios=90_000, mercado=400_000, almuerzo=180_000,
                                   rapidas=80_000, metro=120_000, cel=55_000, u=150_000, ocio=80_000,
                                   licor=50_000, ropa=50_000, salud=30_000, aseo=50_000),
    "Estudio y trabajo, con moto": dict(mercado=150_000, almuerzo=300_000, rapidas=150_000, moto=350_000,
                                        cel=80_000, u=250_000, ocio=150_000, licor=80_000, ropa=100_000,
                                        salud=40_000, aseo=50_000),
}

CLAVES_RUBROS = list(IPC_BASE["rubros"])
COLUMNAS = (["fecha", "periodo_ipc", "vivienda", "trabaja", "estrato", "semestre", "carrera",
             "universidad", "subida_ingreso", "inflacion_personal", "gasto_total"]
            + [f"g_{k}" for k in CLAVES_RUBROS])


# =====================================================================
# 2. CÁLCULO ECONÓMICO
# =====================================================================
def cargar_ipc() -> dict:
    """Usa ipc_actualizado.json si existe (lo crea 'actualizar'); si no, los datos de arriba.
    A cada rubro le asigna su variación: la subclase si hay dato, si no la división."""
    ipc = json.loads(ARCHIVO_IPC.read_text(encoding="utf-8")) if ARCHIVO_IPC.exists() else copy.deepcopy(IPC_BASE)
    for r in ipc["rubros"].values():
        sub = r.get("subclase")
        if sub and sub in ipc["subclases"]:
            r["variacion"], r["fuente"] = ipc["subclases"][sub], sub
        else:
            r["variacion"], r["fuente"] = ipc["divisiones"][r["division"]]["variacion"], "División " + r["division"]
    return ipc


def calcular(gastos: dict, ipc: dict) -> dict:
    """Inflación personal a partir del gasto mensual de HOY en cada rubro.
        Hace un año la misma canasta costaba G / (1 + π).
        inflación personal = Σ G / Σ G/(1+π) - 1
        aporte del rubro   = (G - G/(1+π)) / costo de hace un año   (los aportes suman la inflación)"""
    rubros = ipc["rubros"]
    hoy = sum(gastos.get(k, 0) for k in rubros)
    antes = sum(gastos.get(k, 0) / (1 + rubros[k]["variacion"] / 100) for k in rubros)
    if antes == 0:
        return {"hoy": 0.0, "antes": 0.0, "inflacion": 0.0, "aportes": []}
    aportes = [(r["nombre"], (gastos[k] - gastos[k] / (1 + r["variacion"] / 100)) / antes * 100)
               for k, r in rubros.items() if gastos.get(k, 0) > 0]
    aportes.sort(key=lambda x: x[1], reverse=True)
    return {"hoy": hoy, "antes": antes, "inflacion": (hoy / antes - 1) * 100, "aportes": aportes}


def cambio_real(subida_ingreso_pct: float, inflacion_pct: float) -> float:
    """Cambio del poder de compra (%): (1 + n) / (1 + π) - 1."""
    return ((1 + subida_ingreso_pct / 100) / (1 + inflacion_pct / 100) - 1) * 100


def pesos(v: float) -> str:
    return "$" + f"{v:,.0f}".replace(",", ".")


def coma(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


# =====================================================================
# 3. ALMACENAMIENTO DE RESPUESTAS (CSV local o Google Sheets)
# =====================================================================
def leer_secretos() -> dict:
    if not ARCHIVO_SECRETOS.exists():
        return {}
    import tomllib
    return tomllib.loads(ARCHIVO_SECRETOS.read_text(encoding="utf-8"))


class Almacen:
    def __init__(self, secretos: dict | None = None):
        secretos = dict(secretos or {})
        self.usa_google = "gcp_service_account" in secretos and "sheet_url" in secretos
        if self.usa_google:
            import gspread
            cliente = gspread.service_account_from_dict(dict(secretos["gcp_service_account"]))
            self.hoja = cliente.open_by_url(secretos["sheet_url"]).sheet1
            if not self.hoja.row_values(1):
                self.hoja.append_row(COLUMNAS)

    @property
    def descripcion(self) -> str:
        return "Google Sheets" if self.usa_google else ARCHIVO_CSV.name

    def guardar(self, respuesta: dict) -> None:
        fila = {c: respuesta.get(c, "") for c in COLUMNAS}
        fila["fecha"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if self.usa_google:
            self.hoja.append_row([fila[c] for c in COLUMNAS], value_input_option="USER_ENTERED")
            return
        nuevo = not ARCHIVO_CSV.exists()
        with ARCHIVO_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS)
            if nuevo:
                w.writeheader()
            w.writerow(fila)

    def leer(self):
        import pandas as pd
        if self.usa_google:
            return pd.DataFrame(self.hoja.get_all_records())
        return pd.read_csv(ARCHIVO_CSV) if ARCHIVO_CSV.exists() else pd.DataFrame(columns=COLUMNAS)


# =====================================================================
# 4. APP WEB (Streamlit): calculadora + encuesta anónima
# =====================================================================
def app():
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Mi inflación personal", page_icon="📈", layout="wide")
    ipc = cargar_ipc()
    rubros = ipc["rubros"]

    @st.cache_resource
    def obtener_almacen():
        try:
            secretos = dict(st.secrets)
        except Exception:
            secretos = {}
        try:
            return Almacen(secretos)
        except Exception as e:
            st.warning(f"No se pudo conectar a Google Sheets ({e}). Se guardará en un archivo local.")
            return Almacen({})

    st.title("¿Cuánto te subió a ti la vida?")
    st.write(f"El DANE dice que la inflación anual fue **{coma(ipc['nacional'])}%** y en Medellín "
             f"**{coma(ipc['medellin'])}%** ({ipc['comparacion']}). Pero tu canasta no es la del hogar "
             "promedio. Pon lo que gastas en un mes normal.")

    perfil = st.selectbox("Empieza con un ejemplo o en blanco", ["En blanco"] + list(PERFILES))
    base = PERFILES.get(perfil, {})

    izq, der = st.columns([3, 2], gap="large")
    gastos = {}
    with izq:
        st.subheader("Tu gasto de un mes")
        st.caption("Si pagas la matrícula por semestre, divídela entre 6.")
        c1, c2 = st.columns(2)
        for i, (k, r) in enumerate(rubros.items()):
            with (c1 if i % 2 == 0 else c2):
                gastos[k] = st.number_input(f"{r['nombre']} (subió {coma(r['variacion'])}%)", min_value=0,
                                            step=5_000, value=int(base.get(k, 0)), key=f"{perfil}-{k}",
                                            help=f"Dato DANE: {r['fuente']}")
    res = calcular(gastos, ipc)

    with der:
        st.subheader("Tu resultado")
        if res["hoy"] == 0:
            st.info("Pon al menos un gasto para ver tu inflación.")
            st.stop()
        st.metric("Tu inflación personal (12 meses)", f"{coma(res['inflacion'])}%",
                  delta=f"{res['inflacion'] - ipc['nacional']:+.2f} puntos frente al DANE", delta_color="inverse")
        a, b = st.columns(2)
        a.metric("Lo mismo hace un año costaba", pesos(res["antes"]))
        b.metric("Hoy pagas de más cada mes", pesos(res["hoy"] - res["antes"]))
        st.write(f"En un año eso suma **{pesos((res['hoy'] - res['antes']) * 12)}** de más.")
        st.markdown("**De dónde sale tu cifra** (puntos porcentuales)")
        st.bar_chart(pd.DataFrame(res["aportes"][:6], columns=["Rubro", "Puntos"]).set_index("Rubro"),
                     horizontal=True, height=260)

        subida = st.number_input("En el último año mi mesada o sueldo subió (%)", value=0.0, step=0.5)
        real = cambio_real(subida, res["inflacion"])
        if real < 0:
            st.error(f"Tu poder de compra cayó {coma(-real)}%. Para quedar igual, tu plata debía subir "
                     f"{coma(res['inflacion'])}%.")
        else:
            st.success(f"Tu poder de compra subió {coma(real)}%. Le ganaste a tu propia inflación.")
        st.code(f"Mi inflación personal es {coma(res['inflacion'])}% (el DANE dice {coma(ipc['nacional'])}%). "
                f"Lo que más me sube la vida: {res['aportes'][0][0].lower()}. Calcula la tuya.", language=None)

    st.divider()
    st.subheader("Ayúdanos con la investigación")
    st.write("Estamos estudiando cómo afecta la inflación a los estudiantes de Medellín. Si quieres, guarda tus "
             "gastos de forma **anónima**: no pedimos nombre, correo ni documento.")
    with st.form("encuesta"):
        f1, f2, f3 = st.columns(3)
        vivienda = f1.selectbox("¿Con quién vives?", ["Con mi familia", "Solo", "Con amigos o roomies",
                                                      "Residencia estudiantil"])
        trabaja = f2.selectbox("¿Trabajas?", ["No", "Medio tiempo", "Tiempo completo"])
        estrato = f3.selectbox("Estrato de tu vivienda", ["1", "2", "3", "4", "5", "6", "Prefiero no decir"])
        f4, f5, f6 = st.columns(3)
        semestre = f4.number_input("Semestre", min_value=1, max_value=14, value=2)
        carrera = f5.text_input("Carrera (opcional)")
        universidad = f6.text_input("Universidad (opcional)")
        acepto = st.checkbox("Autorizo usar estos datos anónimos con fines académicos (Ley 1581 de 2012).")
        enviar = st.form_submit_button("Guardar mis respuestas")

    if enviar:
        if not acepto:
            st.warning("Marca la autorización para poder guardar tus respuestas.")
        elif st.session_state.get("ya_envio"):
            st.info("Ya guardamos tus respuestas en esta visita. ¡Gracias!")
        else:
            fila = dict(periodo_ipc=ipc["periodo"], vivienda=vivienda, trabaja=trabaja, estrato=estrato,
                        semestre=semestre, carrera=carrera.strip(), universidad=universidad.strip(),
                        subida_ingreso=subida, inflacion_personal=round(res["inflacion"], 4),
                        gasto_total=res["hoy"], **{f"g_{k}": v for k, v in gastos.items()})
            try:
                obtener_almacen().guardar(fila)
                st.session_state["ya_envio"] = True
                st.success("¡Listo! Tus respuestas quedaron guardadas. Gracias por aportar.")
            except Exception as e:
                st.error(f"No pudimos guardar tus respuestas ({e}). Intenta de nuevo en un momento.")

    with st.expander("Cómo se calcula y de dónde salen los datos"):
        st.write("Cada rubro usa la variación anual del IPC del DANE: por subclase cuando existe (arriendo, "
                 "electricidad, comidas fuera, transporte urbano) y por división en el resto. Tu gasto de hoy se "
                 "lleva a precios de hace un año con G/(1+π), y tu inflación es ΣG / Σ[G/(1+π)] − 1.")
        st.dataframe(pd.DataFrame([{"Rubro": r["nombre"], "Dato DANE": r["fuente"], "Variación %": r["variacion"]}
                                   for r in rubros.values()]), hide_index=True, width="stretch")
        st.caption(f"Fuente: {ipc['fuente']} · Actualizado el {ipc['actualizado']}")


# =====================================================================
# 5. ANÁLISIS DE LAS RESPUESTAS + GRÁFICOS PARA REDES
# =====================================================================
VERDE, NARANJA, TINTA, GRIS = "#0b7a5c", "#c2410c", "#14231f", "#8a9a94"


def datos_demo(ipc, n=150, semilla=7):
    """Respuestas INVENTADAS a partir de los perfiles, con ruido. Solo para practicar."""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(semilla)
    mapa = {"Vivo con mis papás": "Con mi familia", "Vivo solo en una pieza": "Solo",
            "Estudio y trabajo, con moto": "Con mi familia"}
    filas = []
    for _ in range(n):
        nombre = rng.choice(list(PERFILES))
        g = {k: max(0, round(v * rng.lognormal(0, 0.35), -3)) for k, v in PERFILES[nombre].items()}
        vivienda = mapa[nombre]
        if nombre == "Vivo solo en una pieza" and rng.random() < 0.4:
            vivienda, g["arriendo"] = "Con amigos o roomies", round(g.get("arriendo", 0) * 0.7, -3)
        r = calcular(g, ipc)
        filas.append({"periodo_ipc": ipc["periodo"], "vivienda": vivienda,
                      "trabaja": "Medio tiempo" if "trabajo" in nombre else rng.choice(["No", "No", "Medio tiempo"]),
                      "estrato": str(rng.choice([1, 2, 3, 3, 4, 5])), "semestre": int(rng.integers(1, 11)),
                      "subida_ingreso": float(rng.choice([0, 0, 5, 9.5, 10])),
                      "inflacion_personal": r["inflacion"], "gasto_total": r["hoy"],
                      **{f"g_{k}": g.get(k, 0) for k in CLAVES_RUBROS}})
    return pd.DataFrame(filas)


def analisis(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": GRIS, "axes.labelcolor": TINTA, "xtick.color": TINTA,
                         "ytick.color": TINTA})
    ipc = cargar_ipc()

    if args.demo:
        df, origen = datos_demo(ipc), "datos de prueba inventados"
    elif args.csv:
        df, origen = pd.read_csv(args.csv), f"archivo {args.csv}"
    else:
        alm = Almacen(leer_secretos())
        df, origen = alm.leer(), alm.descripcion
    if df.empty:
        print("Todavía no hay respuestas. Prueba con:  python proyecto_inflacion.py analisis --demo")
        return
    if "periodo_ipc" in df and (df["periodo_ipc"] == ipc["periodo"]).any():
        df = df[df["periodo_ipc"] == ipc["periodo"]].copy()
    df["inflacion_personal"] = pd.to_numeric(df["inflacion_personal"], errors="coerce")
    df = df.dropna(subset=["inflacion_personal"])
    SALIDAS.mkdir(exist_ok=True)
    nota = f"Fuente: encuesta propia ({origen}) e IPC DANE {ipc['comparacion']}."

    # --- cifras clave
    infl = df["inflacion_personal"]
    sub = pd.to_numeric(df.get("subida_ingreso", 0), errors="coerce").fillna(0)
    real = ((1 + sub / 100) / (1 + infl / 100) - 1) * 100
    r = {"n": len(infl), "media": infl.mean(), "mediana": infl.median(), "min": infl.min(), "max": infl.max(),
         "sobre_dane": (infl > ipc["nacional"]).mean() * 100, "sobre_med": (infl > ipc["medellin"]).mean() * 100,
         "pierde": (real < 0).mean() * 100,
         "gasto_med": pd.to_numeric(df["gasto_total"], errors="coerce").median()}

    def referencias(ax):
        for valor, txt, estilo in [(ipc["nacional"], "DANE", "--"), (ipc["medellin"], "Medellín", ":")]:
            ax.axvline(valor, color=NARANJA, ls=estilo, lw=1.4, label=f"{txt} {coma(valor)}%")
        ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=9)

    def guardar(fig, archivo):
        fig.text(0.01, 0.01, nota, fontsize=8, color=GRIS)
        fig.tight_layout(rect=(0, 0.05, 1, 1))
        fig.savefig(SALIDAS / archivo, dpi=160)
        plt.close(fig)

    # --- inflación por grupo
    for columna, titulo, archivo in [("vivienda", "Inflación personal según con quién vive", "por_vivienda.png"),
                                     ("trabaja", "Inflación personal según si trabaja", "por_trabajo.png")]:
        g = df.groupby(columna)["inflacion_personal"].agg(["mean", "count"]).sort_values("mean")
        fig, ax = plt.subplots(figsize=(8, 4.5))
        barras = ax.barh(g.index.astype(str), g["mean"], color=VERDE)
        for b, (m, n) in zip(barras, g.values):
            ax.text(b.get_width() - 0.1, b.get_y() + b.get_height() / 2, f"{coma(m)}%  (n={int(n)})",
                    va="center", ha="right", fontsize=9, color="white", fontweight="bold")
        referencias(ax)
        ax.set_xlim(0, max(g["mean"].max(), ipc["medellin"]) * 1.15)
        ax.set_xlabel("Inflación personal promedio (%)")
        ax.set_title(titulo, loc="left", fontsize=13, fontweight="bold")
        guardar(fig, archivo)

    # --- distribución
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(infl, bins=20, color=VERDE, edgecolor="white")
    referencias(ax)
    ax.set_xlabel("Inflación personal (%)")
    ax.set_ylabel("Estudiantes")
    ax.set_title("Cada estudiante vive una inflación distinta", loc="left", fontsize=13, fontweight="bold")
    guardar(fig, "distribucion.png")

    # --- canasta del estudiante vs hogar promedio del DANE
    gasto = pd.DataFrame(index=df.index)
    for k, rb in ipc["rubros"].items():
        if f"g_{k}" in df:
            gasto[rb["division"]] = gasto.get(rb["division"], 0) + pd.to_numeric(df[f"g_{k}"], errors="coerce").fillna(0)
    total = gasto.sum(axis=1).replace(0, np.nan)
    tabla = pd.DataFrame({"Estudiantes": (gasto.div(total, axis=0) * 100).mean(),
                          "Hogar promedio DANE": {d: v["peso"] for d, v in ipc["divisiones"].items()}}
                         ).fillna(0).sort_values("Estudiantes")
    fig, ax = plt.subplots(figsize=(9, 6))
    y = np.arange(len(tabla))
    ax.barh(y + 0.2, tabla["Estudiantes"], height=0.4, color=VERDE, label="Estudiantes")
    ax.barh(y - 0.2, tabla["Hogar promedio DANE"], height=0.4, color=GRIS, label="Hogar promedio (DANE)")
    ax.set_yticks(y, [d if len(d) < 34 else d[:32] + "…" for d in tabla.index], fontsize=9)
    ax.set_xlabel("% del gasto total")
    ax.set_title("La canasta de un estudiante no es la del hogar promedio", loc="left", fontsize=13, fontweight="bold")
    ax.legend(frameon=False, loc="lower right")
    guardar(fig, "canasta_vs_dane.png")

    # --- post cuadrado para Instagram
    fig = plt.figure(figsize=(6, 6), dpi=180)
    fig.patch.set_facecolor("#eef2f0")
    fig.text(0.08, 0.86, f"IPC {ipc['periodo'].upper()}", fontsize=11, color=VERDE, fontweight="bold")
    fig.text(0.08, 0.60, f"{r['sobre_dane']:.0f}%", fontsize=64, color=TINTA, fontweight="bold")
    fig.text(0.08, 0.50, "de los estudiantes sienten una inflación\nmayor a la que reporta el DANE",
             fontsize=17, color=TINTA, linespacing=1.3, va="top")
    fig.text(0.08, 0.30, f"Promedio estudiantes: {coma(r['media'])}%", fontsize=14, color=NARANJA, fontweight="bold")
    fig.text(0.08, 0.24, f"DANE nacional: {coma(ipc['nacional'])}%   ·   Medellín: {coma(ipc['medellin'])}%",
             fontsize=11, color=TINTA)
    fig.text(0.08, 0.10, f"Calcula la tuya · {r['n']} respuestas\n"
             f"{'Datos de prueba' if args.demo else 'Encuesta anónima a estudiantes'}",
             fontsize=9, color=GRIS, linespacing=1.4)
    fig.savefig(SALIDAS / "post_instagram.png", dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)

    # --- tablas y resumen
    por_grupo = df.groupby("vivienda")["inflacion_personal"].agg(["count", "mean", "median"]).round(2)
    por_grupo.to_csv(SALIDAS / "por_vivienda.csv")
    tabla.round(2).to_csv(SALIDAS / "canasta_vs_dane.csv")
    lineas = [
        "# Resultados: inflación personal de estudiantes",
        f"Origen de los datos: {origen}",
        f"Periodo IPC: {ipc['comparacion']}", "",
        f"- Respuestas analizadas: {r['n']}",
        f"- Inflación personal promedio: {coma(r['media'])}% (mediana {coma(r['mediana'])}%, "
        f"rango {coma(r['min'])}% a {coma(r['max'])}%)",
        f"- IPC DANE nacional: {coma(ipc['nacional'])}% · Medellín: {coma(ipc['medellin'])}%",
        f"- Estudiantes por encima del DANE: {r['sobre_dane']:.0f}% · por encima de Medellín: {r['sobre_med']:.0f}%",
        f"- Estudiantes que perdieron poder de compra: {r['pierde']:.0f}%",
        f"- Gasto mensual mediano: {pesos(r['gasto_med'])}", "",
        "## Por tipo de vivienda", por_grupo.to_string(), "",
        "## Peso en el gasto (%): estudiantes vs hogar promedio", tabla.round(1).iloc[::-1].to_string(),
    ]
    (SALIDAS / "resumen.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n".join(lineas[:10]))
    print(f"\nListo. Gráficos y tablas en: {SALIDAS}")


# =====================================================================
# 6. ACTUALIZAR EL IPC CON EL BOLETÍN MENSUAL DEL DANE
# =====================================================================
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
NOMBRES_MES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
               "septiembre", "octubre", "noviembre", "diciembre"]
NUM = r"(-?\d+,\d+)"


def a_float(s):
    return float(s.replace("−", "-").replace(",", "."))


def extraer_boletin(texto: str, ipc: dict) -> dict:
    """Lee la sección '3. RESULTADO ANUAL' del boletín: Cuadro 5 (divisiones) y Cuadro 6 (subclases)."""
    plano = re.sub(r"\s+", " ", texto.replace("−", "-"))
    ini = re.search(r"3\.\s*RESULTADO ANUAL", plano, re.I)
    fin = re.search(r"4\.\s*IPC SEG[ÚU]N NIVELES", plano, re.I)
    if not ini:
        raise SystemExit("No encontré la sección '3. RESULTADO ANUAL' en el boletín.")
    anual = plano[ini.end(): fin.start() if fin else None]
    out = {"divisiones": {}, "subclases": {}, "faltan": []}
    m = re.search(r"registr[óo] una variaci[óo]n de\s+" + NUM + r"\s*%", anual)
    out["nacional"] = a_float(m.group(1)) if m else None
    if m is None:
        out["faltan"].append("IPC total nacional")
    for nombre in ipc["divisiones"]:   # Nombre Peso Var_ant Contrib_ant Var_act Contrib_act
        m = re.search(re.escape(nombre) + rf"\s+{NUM}\s+{NUM}\s+{NUM}\s+{NUM}\s+{NUM}", anual)
        if m:
            out["divisiones"][nombre] = {"peso": a_float(m.group(1)), "variacion": a_float(m.group(4))}
        else:
            out["faltan"].append(f"División: {nombre}")
    cuadro6 = anual[anual.find("Cuadro 6"):] if "Cuadro 6" in anual else anual
    for nombre in ipc["subclases"]:
        m = re.search(re.escape(nombre) + rf"\s+{NUM}\s+{NUM}", cuadro6, re.I)
        if m:
            out["subclases"][nombre] = a_float(m.group(1))
        else:
            out["faltan"].append(f"Subclase: {nombre}")
    return out


def actualizar(args):
    ipc = json.loads(ARCHIVO_IPC.read_text(encoding="utf-8")) if ARCHIVO_IPC.exists() else copy.deepcopy(IPC_BASE)
    m3 = MESES[args.mes - 1]
    url = f"https://www.dane.gov.co/files/operaciones/IPC/{m3}{args.anio}/bol-IPC-{m3}{args.anio}.pdf"

    if args.texto:
        texto = Path(args.texto).read_text(encoding="utf-8")
    else:
        import io
        import pdfplumber
        if args.pdf:
            fuente = args.pdf
        else:
            import requests
            print(f"Descargando {url} ...")
            resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                raise SystemExit(f"El DANE respondió {resp.status_code}. ¿Ya publicó ese mes? "
                                 "Descarga el PDF a mano y usa --pdf archivo.pdf")
            fuente = io.BytesIO(resp.content)
        with pdfplumber.open(fuente) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

    nuevo = extraer_boletin(texto, ipc)
    print(f"\nCambios para {NOMBRES_MES[args.mes - 1]} {args.anio}:")
    print(f"  {'IPC nacional':<62} {ipc['nacional']:>6.2f} -> {nuevo['nacional']}")
    for d, v in nuevo["divisiones"].items():
        print(f"  {d[:62]:<62} {ipc['divisiones'][d]['variacion']:>6.2f} -> {v['variacion']:.2f}")
    for s, v in nuevo["subclases"].items():
        print(f"  {s[:62]:<62} {ipc['subclases'][s]:>6.2f} -> {v:.2f}")
    print(f"  Medellín: {ipc['medellin']:.2f} -> {args.medellin if args.medellin is not None else 'sin cambio (usa --medellin)'}")
    if nuevo["faltan"]:
        print("\n  OJO, no los encontré y quedan con el valor anterior:")
        for f in nuevo["faltan"]:
            print(f"   - {f}")
    if not args.si and input("\n¿Guardar estos cambios? (s/n): ").strip().lower() != "s":
        print("No se guardó nada.")
        return

    if nuevo["nacional"] is not None:
        ipc["nacional"] = nuevo["nacional"]
    for d, v in nuevo["divisiones"].items():
        ipc["divisiones"][d].update(v)
    ipc["subclases"].update(nuevo["subclases"])
    if args.medellin is not None:
        ipc["medellin"] = args.medellin
    mes = NOMBRES_MES[args.mes - 1]
    ipc.update(periodo=f"{mes.capitalize()} {args.anio}", comparacion=f"{mes} {args.anio - 1} → {mes} {args.anio}",
               fuente=url, actualizado=date.today().isoformat())
    for r in ipc["rubros"].values():          # no guardar campos calculados
        r.pop("variacion", None)
        r.pop("fuente", None)
    ARCHIVO_IPC.write_text(json.dumps(ipc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardado en {ARCHIVO_IPC.name}. La calculadora ya usa los datos nuevos.")


# =====================================================================
# 7. PUNTO DE ENTRADA
# =====================================================================
def _en_streamlit() -> bool:
    try:
        from streamlit import runtime
        return runtime.exists()
    except ImportError:
        return False


if _en_streamlit():
    app()
elif __name__ == "__main__":
    p = argparse.ArgumentParser(description="Proyecto inflación personal de estudiantes")
    sp = p.add_subparsers(dest="comando")
    pa = sp.add_parser("analisis", help="analizar respuestas y crear gráficos")
    pa.add_argument("--demo", action="store_true", help="usar respuestas inventadas para practicar")
    pa.add_argument("--csv", help="CSV descargado de Google Sheets")
    pu = sp.add_parser("actualizar", help="actualizar el IPC con el boletín del DANE")
    pu.add_argument("--mes", type=int, required=True)
    pu.add_argument("--anio", type=int, required=True)
    pu.add_argument("--medellin", type=float, help="inflación anual de Medellín del mes")
    pu.add_argument("--pdf", help="boletín ya descargado")
    pu.add_argument("--texto", help="texto del boletín (para pruebas)")
    pu.add_argument("--si", action="store_true", help="guardar sin preguntar")
    args = p.parse_args()

    if args.comando == "analisis":
        analisis(args)
    elif args.comando == "actualizar":
        actualizar(args)
    else:
        print("Ejemplo con los tres perfiles:\n")
        ipc = cargar_ipc()
        for nombre, g in PERFILES.items():
            r = calcular(g, ipc)
            print(f"  {nombre}: {coma(r['inflacion'])}%  (DANE {coma(ipc['nacional'])}%)  "
                  f"pagas {pesos(r['hoy'] - r['antes'])} más al mes")
        print("\nPara abrir la calculadora:  streamlit run proyecto_inflacion.py")
        print("Para el análisis de prueba: python proyecto_inflacion.py analisis --demo")