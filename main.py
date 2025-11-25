import logging
from datetime import datetime
from time import time

import requests
from telegram import (
    Update,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================
# CONFIGURACIÓN
# =========================

TELEGRAM_TOKEN = os.getenv("8509302212:AAGSFXLjWlEbUYHP237fe0OWiFMpVEosnv8")
API_BASE_URL   = "https://domiperez.com/wp-json/cr/v1"

# Un bot = una finca (V1)
FINCA_ID = 1

# Enlaces (ajústalos cuando tengas las páginas hechas)
URL_PANEL_CONTROL   = "https://domiperez.com/panelcasablanca232323/"
URL_AVANCE_PROYECTO = "https://domiperez.com/evolucioncasablanca232323/"
URL_DOCUMENTACION   = "https://domiperez.com/repocasablanca232323/"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================
# ESTADOS DE CONVERSACIÓN
# =========================

(
    MENU_PRINCIPAL,
    GESTION_MENU,
    SECTOR_SELECT,
    SECTOR_P_HID,
    SECTOR_P_FIN,
    SECTOR_Q,
    CABEZAL_SELECT,
    CABEZAL_P_ENT,
    CABEZAL_P_SAL,
    MANT_MENU,
    ALERTA_TEXTO,
    ALERTAS_SELECT,
    ALERTAS_COMENTARIO,
    MANT_ENSAYO_SECTOR_SELECT,
    MANT_ENSAYO_VALORES,
    BOMBA_MENU,
    BOMBA_TURNO_MENU,
    BOMBA_P_MENU,
    BOMBA_Q_MENU,
    BOMBA_ARRANQUE_MENU,
    BOMBA_VIBRACIONES_MENU,
    BOMBA_FUGAS_MENU,
    BOMBA_OBS_MENU,
) = range(23)

# =========================
# FUNCIONES AUXILIARES API WP
# =========================

def call_wp_lectura_sector(
    finca_id,
    sector_id,
    user_id,
    p_hidrante,
    p_final,
    q_sector,
    cv_goteros=None,
):
    """
    Envía una lectura de sector a WordPress.

    - Para lecturas hidráulicas normales: se mandan presiones y caudal.
    - Para ensayos de goteros (CV): se puede mandar solo cv_goteros y dejar
      p_hidrante, p_final y q_sector como None.
    """
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "finca_id": finca_id,
        "sector_id": sector_id,
        "user_id": user_id,
        "fecha": fecha,
        "p_hidrante": p_hidrante,
        "p_final": p_final,
        "q_sector": q_sector,
    }

    # Si viene CV de goteros, lo añadimos
    if cv_goteros is not None:
        payload["cv_goteros"] = cv_goteros

    r = requests.post(f"{API_BASE_URL}/lectura/sector", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()

def call_wp_lectura_cabezal(
    finca_id,
    cabezal_id,
    user_id,
    p_entrada,
    p_salida,
):
    """
    VERSIÓN SIMPLIFICADA:
    - Solo usa p_entrada, p_salida.
    - Envía también delta_p al WP.
    - NO envía q_cabezal ni n_sectores.
    """
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        delta_p = float(p_entrada) - float(p_salida)
    except Exception:
        delta_p = None

    payload = {
        "finca_id": finca_id,
        "cabezal_id": cabezal_id,
        "user_id": user_id,
        "fecha": fecha,
        "p_entrada": p_entrada,
        "p_salida": p_salida,
        "delta_p": delta_p,
    }
    r = requests.post(f"{API_BASE_URL}/lectura/cabezal", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def call_wp_mantenimiento(
    finca_id,
    user_id,
    tarea_codigo,
    tarea_descripcion,
    tipo="preventivo",
    sector_id=None,
    cabezal_id=None,
    alerta_id=None,
):
    payload = {
        "finca_id": finca_id,
        "user_id": user_id,
        "tarea_codigo": tarea_codigo,
        "tarea_descripcion": tarea_descripcion,
        "tipo": tipo,
    }
    if sector_id is not None:
        payload["sector_id"] = sector_id
    if cabezal_id is not None:
        payload["cabezal_id"] = cabezal_id
    if alerta_id is not None:
        payload["alerta_id"] = alerta_id

    r = requests.post(f"{API_BASE_URL}/mantenimiento", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def call_wp_incidencia(
    finca_id,
    user_id,
    descripcion,
    tipo="alerta_manual",
    sector_id=None,
    cabezal_id=None
):
    payload = {
        "finca_id": finca_id,
        "user_id": user_id,
        "descripcion": descripcion,
        "tipo": tipo,
    }
    if sector_id:
        payload["sector_id"] = sector_id
    if cabezal_id:
        payload["cabezal_id"] = cabezal_id

    r = requests.post(f"{API_BASE_URL}/incidencia", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def call_wp_get_alertas(finca_id, estado="abierta", limite=20):
    params = {
        "finca_id": finca_id,
        "estado": estado,
        "limite": limite,
        "_ts": int(time()),   # <-- para evitar posibles cachés HTTP
    }
    r = requests.get(f"{API_BASE_URL}/alertas", params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def call_wp_estado_finca(finca_id):
    """Llama al endpoint /estado_finca para obtener el resumen de la finca."""
    params = {
        "finca_id": finca_id,
        "_ts": int(time()),  # para evitar caché
    }
    r = requests.get(f"{API_BASE_URL}/estado_finca", params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def format_resumen_finca(data: dict) -> str:
    """Devuelve un resumen tipo semáforo de sectores, cabezales y bombas."""
    resumen = data.get("resumen", {})
    sect = resumen.get("sectores", {})
    cab  = resumen.get("cabezales", {})
    bom  = resumen.get("bombas", {})

    s_verde    = sect.get("verde", 0)
    s_amarillo = sect.get("amarillo", 0)
    s_rojo     = sect.get("rojo", 0)

    c_verde    = cab.get("verde", 0)
    c_amarillo = cab.get("amarillo", 0)
    c_rojo     = cab.get("rojo", 0)

    b_verde    = bom.get("verde", 0)
    b_amarillo = bom.get("amarillo", 0)
    b_rojo     = bom.get("rojo", 0)

    texto = (
        "Resumen rápido:\n"
        f"*Sectores*:  🟢 {s_verde} · 🟡 {s_amarillo} · 🔴 {s_rojo}\n"
        f"*Cabezales*: 🟢 {c_verde} · 🟡 {c_amarillo} · 🔴 {c_rojo}\n"
        f"*Bombas*:    🟢 {b_verde} · 🟡 {b_amarillo} · 🔴 {b_rojo}"
    )
    return texto

def format_alertas(resp_json: dict) -> str:
    status = resp_json.get("status")
    msg    = resp_json.get("mensaje")
    reg_id = resp_json.get("id_registro")

    # Mensaje base de registro
    if status == "ok":
        base = "✅ Lectura registrada correctamente."
        if reg_id:
            base += f" (ID {reg_id})"
        if msg:
            base += f"\n{msg}"
    else:
        base = f"❌ Algo ha fallado al registrar la lectura."
        if msg:
            base += f"\nDetalle: {msg}"

    # Detalle de alertas técnicas de esa lectura
    if resp_json.get("tiene_alerta"):
        alertas = resp_json.get("alertas", [])
        if alertas:
            lista = "\n".join(f"• {a}" for a in alertas)
            base += "\n\n⚠️ *Alertas detectadas en esta lectura:*\n" + lista

    return base

# ---------- Catálogo sectores / cabezales ----------

def build_label_from_row(row, tipo="sector"):
    sid = row.get("id")
    nombre = (row.get("nombre") or "").strip()
    codigo = (row.get("codigo") or "").strip()

    if codigo and nombre:
        return f"{codigo} – {nombre}"
    elif nombre:
        return nombre
    else:
        if tipo == "sector":
            return f"Sector {sid}"
        else:
            return f"Cabezal {sid}"


def build_options_keyboard(labels):
    rows = []
    row = []
    for label in labels:
        row.append(label)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(["🔴 Cancelar"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def load_sectores(context: ContextTypes.DEFAULT_TYPE):
    """Carga sectores de WP y guarda mapping en context.user_data['sectores_map'].
       Devuelve lista de labels para teclado.
    """
    try:
        params = {
            "finca_id": FINCA_ID,
            "_ts": int(time()),  # param "dummy" para saltar caché
        }
        r = requests.get(
            f"{API_BASE_URL}/sectores",
            params=params,
            timeout=10,
            headers={"User-Agent": "AgriWiseRiegoBot/1.0"},
        )
        logger.info("WP sectores status=%s url=%s", r.status_code, r.url)
        logger.info("WP sectores body=%s", r.text)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.exception("Error al cargar sectores: %s", e)
        return None  # error de conexión, JSON, etc.

    if isinstance(data, dict) and data.get("status") == "error":
        logger.error("WP sectores devolvió error lógico: %s", data)
        return None

    if not isinstance(data, list):
        logger.error("WP sectores devolvió algo que no es lista: %r", data)
        return None

    if not data:
        logger.info("WP sectores devolvió lista vacía para finca_id=%s", FINCA_ID)
        return []

    sectores_map = {}
    labels = []

    for row in data:
        label = build_label_from_row(row, tipo="sector")
        sectores_map[label] = row.get("id")
        labels.append(label)

    context.user_data["sectores_map"] = sectores_map
    logger.info("Sectores cargados: %s", labels)
    return labels


def load_cabezales(context: ContextTypes.DEFAULT_TYPE):
    """Carga cabezales de WP y guarda mapping en context.user_data['cabezales_map'].
       Devuelve lista de labels para teclado.
    """
    try:
        params = {
            "finca_id": FINCA_ID,
            "_ts": int(time()),  # param "dummy" para saltar caché
        }
        r = requests.get(
            f"{API_BASE_URL}/cabezales",
            params=params,
            timeout=10,
            headers={"User-Agent": "AgriWiseRiegoBot/1.0"},
        )
        logger.info("WP cabezales status=%s url=%s", r.status_code, r.url)
        logger.info("WP cabezales body=%s", r.text)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.exception("Error al cargar cabezales: %s", e)
        return None  # error de conexión, JSON, etc.

    if isinstance(data, dict) and data.get("status") == "error":
        logger.error("WP cabezales devolvió error lógico: %s", data)
        return None

    if not isinstance(data, list):
        logger.error("WP cabezales devolvió algo que no es lista: %r", data)
        return None

    if not data:
        logger.info("WP cabezales devolvió lista vacía para finca_id=%s", FINCA_ID)
        return []

    cabezales_map = {}
    labels = []

    for row in data:
        label = build_label_from_row(row, tipo="cabezal")
        cabezales_map[label] = row.get("id")
        labels.append(label)

    context.user_data["cabezales_map"] = cabezales_map
    logger.info("Cabezales cargados: %s", labels)
    return labels

# =========================
# TECLADOS
# =========================

def keyboard_menu_principal():
    return ReplyKeyboardMarkup(
        [
            ["Gestión del sistema de riego"],
            ["Mejora del riego", "Documentación"],
            ["Ayuda"],
        ],
        resize_keyboard=True
    )


def keyboard_gestion_menu():
    # Panel de control en una fila solo para que “se vea más grande”
    return ReplyKeyboardMarkup(
        [
            ["Panel de control"],
            ["Revisión", "Mantenimiento"],
            ["Incidencias"],
            ["🔴 Cancelar"],
        ],
        resize_keyboard=True
    )


def keyboard_mantenimiento_menu():
    return ReplyKeyboardMarkup(
        [
            ["🚨 Alertas abiertas"],
            ["🔴 Cancelar"],
        ],
        resize_keyboard=True
    )


def keyboard_cancelar():
    return ReplyKeyboardMarkup(
        [["🔴 Cancelar"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def keyboard_cancelar_omitir():
    return ReplyKeyboardMarkup(
        [["Omitir", "🔴 Cancelar"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def intentar_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip().lower()
    if text == "🔴 cancelar" or text == "cancelar":
        return await cancelar(update, context)
    return None

# =========================
# AYUDA
# =========================

AYUDA_TEXTO = (
    "⭐️ Desde el menú principal entra en \"*Gestión del sistema de riego*\".\n\n"
    "Ahí tienes:\n"
    "– *Panel de control*: un vistazo general de cómo está tu sistema de riego y el enlace al panel completo.\n\n"
    "– *Revisión*: esto es tu día a día, desde aquí puedes:\n"
    "   • *Registrar sector*: presiones y caudal del sector.\n"
    "   • *Registrar cabezal*: presiones de entrada y salida del cabezal.\n"
    "   • *Registrar bomba*: presión, caudal, arranque y estado general de la bomba.\n"
    "   • *Registrar CV goteros*: ensayo de 16 goteros y cálculo del CV para ver la uniformidad del riego.\n\n"
    "– *Mantenimiento*: para ver las *alertas abiertas* y registrar qué se ha hecho para resolverlas. "
    "Cada actuación queda registrada como mantenimiento correctivo y la alerta se marca como resuelta.\n\n"
    "– *Incidencias*: cualquier cosa que te haya llamado la atención. Pej.: hay gomas mordidas al final del sector 4, "
    "han saltado los empalmes del sector 12, en el cabezal hay pisadas de rata, etc.\n\n\n"
    "⭐️ Luego, en \"*Mejora del riego*\" puedes ver qué se ha hecho, en qué se está trabajando ahora y cuáles son los siguientes pasos.\n\n\n"
    "⭐️ Y en \"*Documentación*\" tienes manuales, procedimientos de campo y protocolos (cómo medir el CV de goteros, "
    "cómo hacer un tratamiento ácido, cómo mantener filtros, etc.).\n\n\n"
    "Además, en cualquier momento puedes usar *🔴 Cancelar* para volver al inicio.\n"
)

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        AYUDA_TEXTO,
        parse_mode="Markdown",
        reply_markup=keyboard_menu_principal(),
    )
    return MENU_PRINCIPAL

# =========================
# HANDLERS PRINCIPALES
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Siempre vuelve al menú principal."""
    context.user_data.clear()

    await update.message.reply_text(
        "Una finca puede tener toda la tecnología del mundo, pero grábate esto: *si el riego no va como debe, te van a fallar los kilos.*\n\n"
        "Aquí trabajamos lo que realmente manda.",
        parse_mode="Markdown",
        reply_markup=keyboard_menu_principal(),
    )

    return MENU_PRINCIPAL

async def menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip().lower()

    if text == "gestión del sistema de riego":
        await update.message.reply_text(
            "Una finca puede tener toda la tecnología del mundo, pero grábate esto: *si el riego no va como debe, te van a fallar los kilos.*\n\n"
            "Aquí trabajamos lo que realmente manda.",
            parse_mode="Markdown",
            reply_markup=keyboard_gestion_menu(),
        )
        return GESTION_MENU

    if text == "mejora del riego":
        await update.message.reply_text(
            "📈 *Mejora del riego*\n\n"
            "Qué se ha hecho, en qué se está trabajando y cuáles son los siguientes pasos.\n\n"
            f"{URL_AVANCE_PROYECTO}",
            parse_mode="Markdown",
            reply_markup=keyboard_menu_principal(),
        )
        return MENU_PRINCIPAL

    if text == "documentación":
        await update.message.reply_text(
            "📚 *Documentación*\n\n"
            "Manuales de trabajo, procedimientos de campo, protocolos y documentos. Todo organizado en una sola página.\n\n"
            f"{URL_DOCUMENTACION}",
            parse_mode="Markdown",
            reply_markup=keyboard_menu_principal(),
        )
        return MENU_PRINCIPAL

    if text == "ayuda":
        return await ayuda(update, context)

    await update.message.reply_text(
        "No te he entendido. Usa los botones, por favor.",
        reply_markup=keyboard_menu_principal(),
    )
    return MENU_PRINCIPAL

# =========================
# MENÚ GESTIÓN
# =========================

async def gestion_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip().lower()

    # Revisión -> elegir sector/cabezal de lista
    if text == "revisión":
        await update.message.reply_text(
            "*Esto es la clave de todo, así que tómate el tiempo que necesites para hacerlo bien.*\n\n"
            "Y recuerda: lo que no mires y apuntes hoy, no existe mañana.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["Registrar sector", "Registrar cabezal"],
                    ["Registrar bomba", "Registrar CV goteros", "🔴 Cancelar"],
                ],
                resize_keyboard=True
            ),
        )
        return GESTION_MENU

    if text == "registrar sector":
        labels = load_sectores(context)
        if labels is None:
            await update.message.reply_text(
                "Ha habido un problema al consultar los sectores en el sistema.\n"
                "Si se repite, coméntaselo al responsable.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        if not labels:
            await update.message.reply_text(
                "No hay sectores configurados para esta finca.\n"
                "Habla con el responsable para que los dé de alta.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        await update.message.reply_text(
            "Elige el *sector* donde estás midiendo:",
            parse_mode="Markdown",
            reply_markup=build_options_keyboard(labels),
        )
        return SECTOR_SELECT

    if text == "registrar cabezal":
        labels = load_cabezales(context)
        if labels is None:
            await update.message.reply_text(
                "Ha habido un problema al consultar los cabezales en el sistema.\n"
                "Si se repite, coméntaselo al responsable.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        if not labels:
            await update.message.reply_text(
                "No hay cabezales configurados para esta finca.\n"
                "Habla con el responsable para que los dé de alta.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        await update.message.reply_text(
            "Elige el *cabezal* donde estás midiendo:",
            parse_mode="Markdown",
            reply_markup=build_options_keyboard(labels),
        )
        return CABEZAL_SELECT

    if text == "registrar bomba":
        # 1. Pedir bombas a WP
        url = f"{API_BASE_URL}/bombas?finca_id={FINCA_ID}"
        try:
            r = requests.get(url, timeout=10).json()
        except Exception as e:
            logger.exception("Error al cargar bombas: %s", e)
            await update.message.reply_text(
                "Ha habido un problema al consultar las bombas en el sistema.\n"
                "Si se repite, coméntaselo al responsable.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        if r.get("status") != "ok" or not r.get("bombas"):
            await update.message.reply_text(
                "No hay bombas registradas.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        # Guardamos la lista en el contexto
        context.user_data["bombas"] = r["bombas"]

        # Creamos un teclado con los nombres de las bombas
        botones = [[b["nombre"]] for b in r["bombas"]]
        reply_markup = ReplyKeyboardMarkup(botones, resize_keyboard=True)

        await update.message.reply_text(
            "¿Qué bomba vas a revisar?",
            reply_markup=reply_markup,
        )
        return BOMBA_MENU

    # Registrar CV goteros (flujo de ensayo CV)
    if text == "registrar cv goteros":
        context.user_data.clear()

        labels = load_sectores(context)
        if labels is None:
            await update.message.reply_text(
                "Ha habido un problema al consultar los sectores en el sistema.\n"
                "Inténtalo de nuevo más tarde o avisa al responsable.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        if not labels:
            await update.message.reply_text(
                "No hay sectores configurados para esta finca.\n"
                "Habla con el responsable para que los dé de alta.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        await update.message.reply_text(
            "Elige el *sector* donde vas a hacer el ensayo de goteros (CV):",
            parse_mode="Markdown",
            reply_markup=build_options_keyboard(labels),
        )
        return MANT_ENSAYO_SECTOR_SELECT

    # Mantenimiento -> solo alertas abiertas
    if text == "mantenimiento":
        await update.message.reply_text(
            "*Un buen mantenimiento es lo que hace que las cosas no se descontrolen*.\n\n"
            "En *Por un puñado de dólares*, Clint Eastwood cuidaba más a su revolver que a su caballo. "
            "Pues eso, pero con el riego: si no hacemos un mantenimiento en condiciones... acabamos disparando "
            "problemas en vez de resolverlos.\n",
            parse_mode="Markdown",
            reply_markup=keyboard_mantenimiento_menu(),
        )
        return MANT_MENU

    # Incidencias (alerta manual general)
    if text == "incidencias":
        await update.message.reply_text(
            "Escribe la incidencia que quieras registrar.\n\n"
            "Cuando termines, envía el mensaje.\n"
            "Si no quieres continuar, pulsa 🔴 Cancelar.",
            reply_markup=keyboard_cancelar(),
        )
        return ALERTA_TEXTO

    # Panel de control
    if text == "panel de control":
        # Primer mensaje: feedback rápido
        await update.message.reply_text("Consultando el estado de la finca… ⏳")

        resumen_texto = ""
        try:
            data = call_wp_estado_finca(FINCA_ID)
            if data.get("status") == "ok":
                resumen_texto = format_resumen_finca(data)
            else:
                resumen_texto = (
                    "No he podido obtener el resumen de la finca ahora mismo.\n"
                    "Puedes abrir el panel completo desde el enlace."
                )
        except Exception as e:
            logger.exception("Error al llamar a /estado_finca: %s", e)
            resumen_texto = (
                "No he podido conectar con el panel para obtener el resumen.\n"
                "Abre el panel desde el enlace para ver el estado actualizado."
            )

        await update.message.reply_text(
            "📊 *Panel de control del sistema de riego*\n\n"
            f"{resumen_texto}\n\n"
            f"🔗 Panel completo:\n{URL_PANEL_CONTROL}",
            parse_mode="Markdown",
            reply_markup=keyboard_gestion_menu(),
        )
        return GESTION_MENU

    if text == "🔴 cancelar" or text == "cancelar":
        return await cancelar(update, context)

    await update.message.reply_text(
        "No te he entendido. Usa los botones del menú.",
        reply_markup=keyboard_gestion_menu(),
    )
    return GESTION_MENU

# =========================
# SUBMENÚ MANTENIMIENTO (solo alertas abiertas)
# =========================

async def mantenimiento_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip().lower()

    # Alertas abiertas
    if "alertas abiertas" in text or "alertas" in text:
        await update.message.reply_text("Buscando alertas abiertas… ⏳")

        try:
            resp = call_wp_get_alertas(FINCA_ID, estado="abierta", limite=20)
            if resp.get("status") != "ok":
                msg = resp.get("mensaje") or "Error al consultar alertas."
                await update.message.reply_text(
                    f"❌ No he podido obtener las alertas abiertas:\n{msg}",
                    reply_markup=keyboard_gestion_menu(),
                )
                return GESTION_MENU

            alertas = resp.get("alertas", [])
        except Exception as e:
            logger.exception("Error al consultar alertas abiertas: %s", e)
            await update.message.reply_text(
                f"❌ Error al conectar con el sistema de alertas: {e}",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        if not alertas:
            await update.message.reply_text(
                "✅ No hay alertas abiertas ahora mismo. Buen síntoma. 😄",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        labels = []
        alertas_map = {}
        lineas_texto = []

        for a in alertas:
            alerta_id    = a.get("id")
            lectura_tipo = (a.get("lectura_tipo") or "").lower()  # 'sector' o 'cabezal'
            elemento_id  = a.get("elemento_id")
            nivel        = (a.get("nivel") or "").upper()
            mensaje      = a.get("mensaje") or ""

            if lectura_tipo == "sector":
                tipo_txt = "Sector"
            elif lectura_tipo == "cabezal":
                tipo_txt = "Cabezal"
            elif lectura_tipo == "bomba":
                tipo_txt = "Bomba"
            else:
                tipo_txt = "Elemento"

            label = f"[#{alerta_id}] {tipo_txt} {elemento_id} · {nivel}"
            labels.append(label)
            alertas_map[label] = a

            linea = f"{label}\nMotivo: {mensaje}"
            lineas_texto.append(linea)

        context.user_data["alertas_map"] = alertas_map

        texto_alertas = (
            "Estas son las *alertas abiertas*:\n\n" +
            "\n\n".join(lineas_texto) +
            "\n\nElige una de la lista para registrar qué has hecho."
        )

        await update.message.reply_text(
            texto_alertas,
            parse_mode="Markdown",
            reply_markup=build_options_keyboard(labels),
        )
        return ALERTAS_SELECT

    await update.message.reply_text(
        "Elige una opción del menú (Alertas abiertas) o pulsa 🔴 Cancelar.",
        reply_markup=keyboard_mantenimiento_menu(),
    )
    return MANT_MENU

# =========================
# FLUJO REVISIÓN - SECTOR
# =========================

async def sector_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    label = (update.message.text or "").strip()
    sectores_map = context.user_data.get("sectores_map") or {}
    sector_id = sectores_map.get(label)

    if not sector_id:
        await update.message.reply_text(
            "No reconozco ese sector.\n\n"
            "Por favor, elige *uno de los sectores de la lista*.",
            parse_mode="Markdown",
            reply_markup=build_options_keyboard(list(sectores_map.keys())),
        )
        return SECTOR_SELECT

    context.user_data["sector_id"] = sector_id

    await update.message.reply_text(
        "1️⃣ Escribe la *presión en hidrante* (bar).\n"
        "Ejemplo: 3.5",
        parse_mode="Markdown",
        reply_markup=keyboard_cancelar(),
    )
    return SECTOR_P_HID


async def sector_p_hid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip()
    try:
        context.user_data["p_hidrante"] = float(text.replace(",", "."))
    except ValueError:
        await update.message.reply_text(
            "No he podido leer la presión.\n\n"
            "Escribe solo el número de la *presión en hidrante* en bar.\n"
            "Ejemplo: 3.5",
            parse_mode="Markdown",
            reply_markup=keyboard_cancelar(),
        )
        return SECTOR_P_HID

    await update.message.reply_text(
        "2️⃣ Escribe la *presión al final del sector* (bar).\n"
        "Ejemplo: 1.0",
        parse_mode="Markdown",
        reply_markup=keyboard_cancelar(),
    )
    return SECTOR_P_FIN


async def sector_p_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip()
    try:
        context.user_data["p_final"] = float(text.replace(",", "."))
    except ValueError:
        await update.message.reply_text(
            "No he podido leer la presión final.\n\n"
            "Escribe solo el número de la *presión al final del sector* en bar.\n"
            "Ejemplo: 1.0",
            parse_mode="Markdown",
            reply_markup=keyboard_cancelar(),
        )
        return SECTOR_P_FIN

    await update.message.reply_text(
        "3️⃣ Escribe el *caudal del sector* (m³/h).\n"
        "Ejemplo: 20",
        parse_mode="Markdown",
        reply_markup=keyboard_cancelar(),
    )
    return SECTOR_Q


async def sector_q(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip()
    try:
        context.user_data["q_sector"] = float(text.replace(",", "."))
    except ValueError:
        await update.message.reply_text(
            "No he podido leer el caudal.\n\n"
            "Escribe solo el número del *caudal del sector* en m³/h.\n"
            "Ejemplo: 20",
            parse_mode="Markdown",
            reply_markup=keyboard_cancelar(),
        )
        return SECTOR_Q

    user = update.effective_user
    user_id = user.id

    sector_id  = context.user_data["sector_id"]
    p_hidrante = context.user_data["p_hidrante"]
    p_final    = context.user_data["p_final"]
    q_sector   = context.user_data["q_sector"]

    await update.message.reply_text("Registrando lectura del sector… ⏳")

    try:
        resp = call_wp_lectura_sector(
            FINCA_ID,
            sector_id,
            user_id,
            p_hidrante,
            p_final,
            q_sector,
        )
        texto = format_alertas(resp)
    except Exception as e:
        logger.exception("Error al llamar a WP (sector): %s", e)
        texto = (
            "❌ Error al enviar la lectura al sistema.\n"
            f"Detalle técnico: {e}"
        )

    context.user_data.clear()

    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=keyboard_menu_principal(),
    )

    return MENU_PRINCIPAL

# =========================
# FLUJO REVISIÓN - CABEZAL (SIMPLIFICADO)
# =========================

async def cabezal_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    label = (update.message.text or "").strip()
    cabezales_map = context.user_data.get("cabezales_map") or {}
    cabezal_id = cabezales_map.get(label)

    if not cabezal_id:
        await update.message.reply_text(
            "No reconozco ese cabezal.\n\n"
            "Por favor, elige *uno de los cabezales de la lista*.",
            parse_mode="Markdown",
            reply_markup=build_options_keyboard(list(cabezales_map.keys())),
        )
        return CABEZAL_SELECT

    context.user_data["cabezal_id"] = cabezal_id

    await update.message.reply_text(
        "1️⃣ Escribe la *presión de entrada al cabezal* (bar).\n"
        "Ejemplo: 3.0",
        parse_mode="Markdown",
        reply_markup=keyboard_cancelar(),
    )
    return CABEZAL_P_ENT


async def cabezal_p_ent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip()
    try:
        context.user_data["p_entrada"] = float(text.replace(",", "."))
    except ValueError:
        await update.message.reply_text(
            "No he podido leer la presión de entrada.\n\n"
            "Escribe solo el número de la *presión de entrada* en bar.\n"
            "Ejemplo: 3.0",
            parse_mode="Markdown",
            reply_markup=keyboard_cancelar(),
        )
        return CABEZAL_P_ENT

    await update.message.reply_text(
        "2️⃣ Escribe la *presión de salida del cabezal* (bar).\n"
        "Ejemplo: 1.8",
        parse_mode="Markdown",
        reply_markup=keyboard_cancelar(),
    )
    return CABEZAL_P_SAL

# =========================
# FLUJO REVISIÓN - BOMBA
# =========================

async def bomba_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Selección de la bomba que se va a revisar.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    seleccion = (update.message.text or "").strip()
    bombas = context.user_data.get("bombas", [])

    # buscar bomba seleccionada
    bomba = next((b for b in bombas if b.get("nombre") == seleccion), None)

    if not bomba:
        if not bombas:
            await update.message.reply_text(
                "No encuentro la bomba seleccionada. Vuelve al menú de gestión.",
                reply_markup=keyboard_gestion_menu(),
            )
            return GESTION_MENU

        await update.message.reply_text(
            "No te entendí, elige una bomba de la lista.",
            reply_markup=ReplyKeyboardMarkup(
                [[b["nombre"]] for b in bombas],
                resize_keyboard=True,
            ),
        )
        return BOMBA_MENU

    context.user_data["bomba_id"] = bomba["id"]

    # Ahora pedimos turnos de esa bomba
    url = f"{API_BASE_URL}/turnos_bomba?bomba_id={bomba['id']}"
    try:
        r = requests.get(url, timeout=10).json()
    except Exception as e:
        logger.exception("Error al cargar turnos de bomba: %s", e)
        await update.message.reply_text(
            "Ha habido un problema al consultar los turnos de esta bomba.",
            reply_markup=keyboard_gestion_menu(),
        )
        context.user_data.clear()
        return GESTION_MENU

    if r.get("status") != "ok" or not r.get("turnos"):
        await update.message.reply_text(
            "No hay turnos definidos para esta bomba.",
            reply_markup=keyboard_gestion_menu(),
        )
        context.user_data.clear()
        return GESTION_MENU

    context.user_data["turnos"] = r["turnos"]

    botones = [[t["nombre_turno"]] for t in r["turnos"]]
    reply_markup = ReplyKeyboardMarkup(botones, resize_keyboard=True)

    await update.message.reply_text(
        "¿Qué turno está regando ahora?",
        reply_markup=reply_markup,
    )
    return BOMBA_TURNO_MENU


async def bomba_turno_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Selección del turno de riego de la bomba.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    seleccion = (update.message.text or "").strip()
    turnos = context.user_data.get("turnos", [])

    turno = next((t for t in turnos if t.get("nombre_turno") == seleccion), None)
    if not turno:
        if not turnos:
            await update.message.reply_text(
                "No encuentro turnos para esta bomba.",
                reply_markup=keyboard_gestion_menu(),
            )
            context.user_data.clear()
            return GESTION_MENU

        await update.message.reply_text(
            "Elige un turno válido.",
            reply_markup=ReplyKeyboardMarkup(
                [[t["nombre_turno"]] for t in turnos],
                resize_keyboard=True,
            ),
        )
        return BOMBA_TURNO_MENU

    context.user_data["turno_id"] = turno["id"]

    await update.message.reply_text(
        "¿Qué presión marca el manómetro? (bar)",
        reply_markup=keyboard_cancelar(),
    )
    return BOMBA_P_MENU


async def bomba_p_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Leer presión actual de la bomba.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip()
    try:
        p = float(text.replace(",", "."))
    except Exception:
        await update.message.reply_text(
            "Introduce un número válido para la presión (ejemplo: 3.5).",
            reply_markup=keyboard_cancelar(),
        )
        return BOMBA_P_MENU

    context.user_data["p_actual"] = p

    await update.message.reply_text(
        "¿Cuál es el caudal que has medido? (m³/h)",
        reply_markup=keyboard_cancelar(),
    )
    return BOMBA_Q_MENU


async def bomba_q_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Leer caudal actual de la bomba.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip()
    try:
        q = float(text.replace(",", "."))
    except Exception:
        await update.message.reply_text(
            "Introduce un número válido para el caudal (ejemplo: 25).",
            reply_markup=keyboard_cancelar(),
        )
        return BOMBA_Q_MENU

    context.user_data["q_actual"] = q

    botones = [["Sí"], ["No"]]
    await update.message.reply_text(
        "¿Ha arrancado bien?",
        reply_markup=ReplyKeyboardMarkup(botones, resize_keyboard=True),
    )
    return BOMBA_ARRANQUE_MENU


async def bomba_arranque_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Preguntar si el arranque ha sido correcto.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip().lower()
    context.user_data["arranque_ok"] = (text == "sí" or text == "si")

    botones = [["Sí"], ["No"]]
    await update.message.reply_text(
        "¿Hay vibraciones o ruidos raros?",
        reply_markup=ReplyKeyboardMarkup(botones, resize_keyboard=True),
    )
    return BOMBA_VIBRACIONES_MENU


async def bomba_vibraciones_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Preguntar por vibraciones/ruidos raros.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip().lower()
    context.user_data["vibraciones"] = (text == "sí" or text == "si")

    botones = [["Sí"], ["No"]]
    await update.message.reply_text(
        "¿Hay fugas en la zona de la bomba?",
        reply_markup=ReplyKeyboardMarkup(botones, resize_keyboard=True),
    )
    return BOMBA_FUGAS_MENU


async def bomba_fugas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Preguntar por fugas en la zona de la bomba.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip().lower()
    context.user_data["fugas"] = (text == "sí" or text == "si")

    botones = [["No"]]

    await update.message.reply_text(
        "¿Algo más que quieras comentar?",
        reply_markup=ReplyKeyboardMarkup(botones, resize_keyboard=True),
    )
    return BOMBA_OBS_MENU

async def bomba_obs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Guardar observaciones y enviar todo a WP (/lectura/bomba)
    y mostrar en el bot las alertas igual que en sectores/cabezales.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    observaciones = (update.message.text or "").strip()
    context.user_data["observaciones"] = observaciones

    datos = {
        "finca_id": FINCA_ID,
        "bomba_id": context.user_data.get("bomba_id"),
        "turno_id": context.user_data.get("turno_id"),
        "user_id": update.effective_user.id,
        "fecha": datetime.now().isoformat(),
        "p_actual": context.user_data.get("p_actual"),
        "q_actual": context.user_data.get("q_actual"),
        "arranque_ok": context.user_data.get("arranque_ok"),
        "vibraciones": context.user_data.get("vibraciones"),
        "fugas": context.user_data.get("fugas"),
        "observaciones": context.user_data.get("observaciones"),
    }

    # Mensaje de “estoy trabajando”, igual que en sectores/cabezales
    await update.message.reply_text("Registrando lectura de la bomba… ⏳")

    try:
        r = requests.post(
            f"{API_BASE_URL}/lectura/bomba",
            json=datos,
            timeout=10,
        )
        r.raise_for_status()

        # Intentamos leer el JSON y usar el mismo formato de alertas
        try:
            resp = r.json()
            texto = format_alertas(resp)
        except Exception:
            # Si por lo que sea no viene JSON como esperamos,
            # mostramos al menos el OK sencillo
            logger.exception("No se pudo parsear la respuesta de /lectura/bomba")
            texto = "✅ Lectura de bomba registrada correctamente."

    except Exception as e:
        logger.exception("Error al registrar lectura de bomba: %s", e)
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Ha habido un error al registrar la lectura de la bomba.\n"
            f"Detalle técnico: {e}",
            reply_markup=keyboard_menu_principal(),
        )
        return MENU_PRINCIPAL

    context.user_data.clear()

    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=keyboard_menu_principal(),
    )
    return MENU_PRINCIPAL

async def cabezal_p_sal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Nueva versión:
    - Aquí termina el flujo de cabezal.
    - No se pide caudal ni nº de sectores.
    - Se envía la lectura directamente a WP usando deltaP.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    text = (update.message.text or "").strip()
    try:
        p_salida = float(text.replace(",", "."))
        context.user_data["p_salida"] = p_salida
    except ValueError:
        await update.message.reply_text(
            "No he podido leer la presión de salida.\n\n"
            "Escribe solo el número de la *presión de salida* en bar.\n"
            "Ejemplo: 1.8",
            parse_mode="Markdown",
            reply_markup=keyboard_cancelar(),
        )
        return CABEZAL_P_SAL

    p_entrada = context.user_data.get("p_entrada")
    cabezal_id = context.user_data.get("cabezal_id")

    user = update.effective_user
    user_id = user.id

    # Aviso suave si la salida es mayor que la entrada, pero SIN pedir más datos
    if p_entrada is not None and p_salida > p_entrada:
        await update.message.reply_text(
            "⚠️ Ojo: la presión de salida es *mayor* que la de entrada.\n"
            "Revisa si los datos son correctos. De todos modos, registro la lectura.",
            parse_mode="Markdown",
        )

    await update.message.reply_text("Registrando lectura del cabezal… ⏳")

    try:
        resp = call_wp_lectura_cabezal(
            FINCA_ID,
            cabezal_id,
            user_id,
            p_entrada,
            p_salida,
        )
        texto = format_alertas(resp)
    except Exception as e:
        logger.exception("Error al llamar a WP (cabezal): %s", e)
        texto = (
            "❌ Error al enviar la lectura al sistema.\n"
            f"Detalle técnico: {e}"
        )

    context.user_data.clear()

    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=keyboard_menu_principal(),
    )

    return MENU_PRINCIPAL

# =========================
# FLUJO ENSAYO DE GOTEROS (CV)
# =========================

async def mantenimiento_ensayo_sector_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Seleccionar el sector donde se hace el ensayo de goteros (CV).
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    label = (update.message.text or "").strip()
    sectores_map = context.user_data.get("sectores_map") or {}
    sector_id = sectores_map.get(label)

    if not sector_id:
        await update.message.reply_text(
            "No reconozco ese sector.\n\n"
            "Por favor, elige *uno de los sectores de la lista*.",
            parse_mode="Markdown",
            reply_markup=build_options_keyboard(list(sectores_map.keys())),
        )
        return MANT_ENSAYO_SECTOR_SELECT

    context.user_data["ensayo_cv_sector_id"] = sector_id

    # Explicación sencilla del ensayo
    texto = (
        "Vamos a hacer el *ensayo de goteros (CV)* en este sector.\n\n"
        "👉 Mide **16 goteros** en total:\n"
        "   - 4 zonas distintas del sector × 4 goteros en cada zona.\n"
        "   - Cada medida es el volumen recogido en *5 minutos* en mililitros (mL/5min).\n\n"
        "Cuando termines, escribe **todos los valores en una sola línea**, separados por comas.\n"
        "Ejemplo:\n"
        "`120, 118, 125, 130, 119, ...`\n\n"
        "Necesitamos como mínimo *16 valores*."
    )

    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=keyboard_cancelar(),
    )

    return MANT_ENSAYO_VALORES


async def mantenimiento_ensayo_valores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Recibe los valores del ensayo, calcula CV y registra la lectura en WP.
    """
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    raw_text = (update.message.text or "").strip()
    if not raw_text:
        await update.message.reply_text(
            "No he recibido ningún número.\n\n"
            "Escribe los valores de los goteros en mL/5min separados por comas.\n"
            "Ejemplo: 120, 118, 125, 130, 119, ...",
            reply_markup=keyboard_cancelar(),
        )
        return MANT_ENSAYO_VALORES

    # Separar por comas y convertir a números
    partes = raw_text.split(",")
    valores = []
    for p in partes:
        s = p.strip()
        if not s:
            continue
        try:
            # Aceptamos tanto 120 como 120.5 (por si acaso)
            num = float(s.replace(" ", ""))
            valores.append(num)
        except ValueError:
            # Si alguna parte no es número, simplemente la ignoramos
            continue

    if len(valores) < 16:
        await update.message.reply_text(
            f"He podido leer {len(valores)} valores numéricos, pero necesito *al menos 16*.\n\n"
            "Vuelve a escribirlos en una sola línea, separados por comas.\n"
            "Ejemplo: 120, 118, 125, 130, 119, ...",
            parse_mode="Markdown",
            reply_markup=keyboard_cancelar(),
        )
        return MANT_ENSAYO_VALORES

    # ✅ Cálculo de la media y del CV (desviación estándar MUESTRAL)
    n = len(valores)
    media = sum(valores) / n if n > 0 else 0.0

    if n > 1:
        suma_cuad = sum((v - media) ** 2 for v in valores)
        var_muestral = suma_cuad / (n - 1)
        desvio = var_muestral ** 0.5
    else:
        desvio = 0.0

    if media != 0:
        cv = 100.0 * desvio / media
    else:
        cv = 0.0

    media_ml5 = media
    media_ml5_red = round(media_ml5, 1)
    cv_red = round(cv, 1)

    # Interpretación según rangos
    if cv < 5:
        interpretacion = "Excelente"
    elif cv < 7:
        interpretacion = "Muy bueno"
    elif cv < 10:
        interpretacion = "Aceptable"
    else:
        interpretacion = "Uniformidad baja (revisar)"

    sector_id = context.user_data.get("ensayo_cv_sector_id")
    if not sector_id:
        await update.message.reply_text(
            "Ha habido un problema interno: no tengo identificado el sector del ensayo.\n"
            "Vuelve a empezar el flujo de *Revisión → Registrar CV goteros*.",
            parse_mode="Markdown",
            reply_markup=keyboard_menu_principal(),
        )
        context.user_data.clear()
        return MENU_PRINCIPAL

    user = update.effective_user
    user_id = user.id

    await update.message.reply_text("Registrando ensayo de goteros… ⏳")

    try:
        # Enviamos una lectura de sector con solo el CV (sin presiones ni caudal)
        resp = call_wp_lectura_sector(
            FINCA_ID,
            sector_id,
            user_id,
            p_hidrante=None,
            p_final=None,
            q_sector=None,
            cv_goteros=cv,
        )
        status = resp.get("status")
        msg = resp.get("mensaje")

        if status == "ok":
            texto = (
                "✅ Ensayo de goteros (CV) registrado.\n\n"
                f"Caudal medio (mL/5min): *{media_ml5_red}*\n"
                f"CV: *{cv_red} %*\n"
                f"Interpretación: *{interpretacion}*"
            )
        else:
            texto = (
                "⚠️ He calculado el ensayo, pero el sistema no ha podido guardarlo correctamente.\n"
                f"Detalle: {msg or 'Error desconocido'}\n\n"
                f"Caudal medio (mL/5min): *{media_ml5_red}*\n"
                f"CV: *{cv_red} %*\n"
                f"Interpretación: *{interpretacion}*"
            )

    except Exception as e:
        logger.exception("Error al registrar ensayo CV: %s", e)
        texto = (
            "❌ He calculado el ensayo, pero ha habido un error al enviarlo al sistema.\n"
            f"Detalle técnico: {e}\n\n"
            f"Caudal medio (mL/5min): *{media_ml5_red}*\n"
            f"CV: *{cv_red} %*\n"
            f"Interpretación: *{interpretacion}*"
        )

    context.user_data.clear()

    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=keyboard_menu_principal(),
    )

    return MENU_PRINCIPAL

# =========================
# FLUJO RESOLUCIÓN DE ALERTAS ABIERTAS
# =========================

async def alertas_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    label = (update.message.text or "").strip()
    alertas_map = context.user_data.get("alertas_map") or {}
    alerta = alertas_map.get(label)

    if not alerta:
        if alertas_map:
            await update.message.reply_text(
                "Elige una alerta de la lista.",
                reply_markup=build_options_keyboard(list(alertas_map.keys())),
            )
            return ALERTAS_SELECT

        await update.message.reply_text(
            "No he encontrado esa alerta. Vuelve al menú de gestión.",
            reply_markup=keyboard_gestion_menu(),
        )
        return GESTION_MENU

    context.user_data["alerta_seleccionada"] = alerta

    alerta_id    = alerta.get("id")
    lectura_tipo = (alerta.get("lectura_tipo") or "").lower()
    elemento_id  = alerta.get("elemento_id")
    nivel        = (alerta.get("nivel") or "").upper()
    mensaje      = alerta.get("mensaje") or ""

    if lectura_tipo == "sector":
        tipo_txt = "Sector"
    elif lectura_tipo == "cabezal":
        tipo_txt = "Cabezal"
    elif lectura_tipo == "bomba":
        tipo_txt = "Bomba"
    else:
        tipo_txt = "Elemento"

    cabecera = f"[#{alerta_id}] {tipo_txt} {elemento_id} · {nivel}"

    await update.message.reply_text(
        f"Estás atendiendo la alerta {cabecera}.\n\n"
        f"*Motivo:*\n{mensaje}\n\n"
        "Describe brevemente qué has hecho para atender esta alerta.\n"
        "Por ejemplo: \"Lavado de filtros y purga de línea\".\n\n"
        "Si al final no has hecho nada, puedes escribir *Sin actuación* "
        "o pulsa *Omitir* para no dejar comentario.",
        parse_mode="Markdown",
        reply_markup=keyboard_cancelar_omitir(),
    )
    return ALERTAS_COMENTARIO


async def alertas_comentario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    raw = (update.message.text or "").strip()
    text = raw.lower()

    if text == "omitir":
        comentario = None
    else:
        comentario = raw or None

    alerta = context.user_data.get("alerta_seleccionada") or {}
    alerta_id    = alerta.get("id")
    lectura_tipo = (alerta.get("lectura_tipo") or "").lower()
    elemento_id  = alerta.get("elemento_id")

    sector_id = None
    cabezal_id = None
    if lectura_tipo == "sector" and elemento_id:
        sector_id = int(elemento_id)
    elif lectura_tipo == "cabezal" and elemento_id:
        cabezal_id = int(elemento_id)

    user = update.effective_user
    user_id = user.id

    await update.message.reply_text("Registrando la resolución de la alerta… ⏳")

    try:
        # Registrar mantenimiento correctivo enlazado a la alerta
        resp_mant = call_wp_mantenimiento(
            FINCA_ID,
            user_id,
            "RESOLUCION_ALERTA",
            comentario,
            tipo="correctivo",
            sector_id=sector_id,
            cabezal_id=cabezal_id,
            alerta_id=alerta_id,
        )

        status_mant = resp_mant.get("status")
        msg_mant    = resp_mant.get("mensaje")

        if status_mant == "ok":
            texto = (
                "✅ Mantenimiento correctivo registrado y alerta asociada marcada como *resuelta*.\n"
            )
        else:
            texto = (
                "⚠️ Se ha intentado registrar el mantenimiento correctivo pero la API devolvió un error:\n"
                f"{msg_mant or 'Error desconocido en mantenimiento.'}"
            )

    except Exception as e:
        logger.exception("Error al resolver alerta: %s", e)
        texto = f"❌ Error al comunicar con el sistema: {e}"

    context.user_data.clear()

    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=keyboard_menu_principal(),
    )
    return MENU_PRINCIPAL

# =========================
# FLUJO INCIDENCIAS (alerta manual general)
# =========================

async def alerta_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel = await intentar_cancelar(update, context)
    if cancel is not None:
        return cancel

    descripcion = (update.message.text or "").strip()
    if not descripcion:
        await update.message.reply_text(
            "El texto de la incidencia está vacío. Escribe algo o pulsa 🔴 Cancelar.",
            reply_markup=keyboard_cancelar(),
        )
        return ALERTA_TEXTO

    user = update.effective_user
    user_id = user.id

    await update.message.reply_text("Registrando incidencia… ⏳")

    try:
        resp = call_wp_incidencia(
            FINCA_ID,
            user_id,
            descripcion,
            tipo="alerta_manual",
        )
        status = resp.get("status")
        msg    = resp.get("mensaje")
        reg_id = resp.get("id_registro")
        if status == "ok":
            base = f"✅ {msg} (ID {reg_id})"
        else:
            base = f"❌ Algo ha fallado al registrar la incidencia: {msg or 'Error desconocido'}"
    except Exception as e:
        logger.exception("Error al llamar a WP (incidencia): %s", e)
        base = f"❌ Error al enviar la incidencia al sistema: {e}"

    context.user_data.clear()

    await update.message.reply_text(
        base,
        reply_markup=keyboard_menu_principal(),
    )
    return MENU_PRINCIPAL

# =========================
# CANCELAR
# =========================

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Operación cancelada. Vuelves al menú principal.",
        reply_markup=keyboard_menu_principal(),
    )
    return MENU_PRINCIPAL

# =========================
# MAIN
# =========================

def main():
    app = ApplicationBuilder().token(8509302212:AAGSFXLjWlEbUYHP237fe0OWiFMpVEosnv8).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
        ],
        states={
            MENU_PRINCIPAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_principal),
            ],
            GESTION_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, gestion_menu),
            ],
            SECTOR_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sector_select),
            ],
            SECTOR_P_HID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sector_p_hid),
            ],
            SECTOR_P_FIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sector_p_fin),
            ],
            SECTOR_Q: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sector_q),
            ],
            CABEZAL_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cabezal_select),
            ],
            CABEZAL_P_ENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cabezal_p_ent),
            ],
            CABEZAL_P_SAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cabezal_p_sal),
            ],
            MANT_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, mantenimiento_menu),
            ],
            MANT_ENSAYO_SECTOR_SELECT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    mantenimiento_ensayo_sector_select,
                ),
            ],
            MANT_ENSAYO_VALORES: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    mantenimiento_ensayo_valores,
                ),
            ],
            ALERTA_TEXTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, alerta_texto),
            ],
            ALERTAS_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, alertas_select),
            ],
            ALERTAS_COMENTARIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, alertas_comentario),
            ],
            BOMBA_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_menu),
            ],
            BOMBA_TURNO_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_turno_menu),
            ],
            BOMBA_P_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_p_menu),
            ],
            BOMBA_Q_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_q_menu),
            ],
            BOMBA_ARRANQUE_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_arranque_menu),
            ],
            BOMBA_VIBRACIONES_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_vibraciones_menu),
            ],
            BOMBA_FUGAS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_fugas_menu),
            ],
            BOMBA_OBS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bomba_obs_menu),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancelar),
            CommandHandler("start", start),
            CommandHandler("ayuda", ayuda),
        ],
    )

    app.add_handler(conv_handler)

    logger.info("Bot arrancando…")
    app.run_polling()


if __name__ == "__main__":
    main()



