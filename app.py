import os
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from mercadopublico_scraper import MercadoPublicoScraper

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Flask ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)

DOWNLOAD_DIR = "/tmp/descargas"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ── Health check ───────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servicio": "MercadoPublico Scraper"}), 200


# ── Endpoint principal ─────────────────────────────────────────────────────────
@app.route("/scrape", methods=["POST"])
def scrape():
    """
    Recibe fecha_inicio y fecha_fin, ejecuta el scraping
    y retorna el CSV descargado como archivo adjunto.

    Body JSON:
        {
            "fecha_inicio": "2025-02-01",
            "fecha_fin":    "2025-02-28"
        }
    """
    data = request.get_json(force=True, silent=True) or {}

    fecha_inicio_str = data.get("fecha_inicio", "")
    fecha_fin_str    = data.get("fecha_fin", "")

    # ── Validar fechas ─────────────────────────────────────────────────────────
    if not fecha_inicio_str or not fecha_fin_str:
        return jsonify({
            "error": "Se requieren 'fecha_inicio' y 'fecha_fin' en formato YYYY-MM-DD"
        }), 400

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d")
        fecha_fin    = datetime.strptime(fecha_fin_str,    "%Y-%m-%d")
    except ValueError:
        return jsonify({
            "error": "Formato de fecha inválido. Usa YYYY-MM-DD (ej: 2025-02-01)"
        }), 400

    if fecha_fin < fecha_inicio:
        return jsonify({
            "error": "fecha_fin debe ser igual o posterior a fecha_inicio"
        }), 400

    logger.info(f"📥 /scrape — {fecha_inicio_str} → {fecha_fin_str}")

    # ── Ejecutar scraper ───────────────────────────────────────────────────────
    scraper = MercadoPublicoScraper(headless=True, download_dir=DOWNLOAD_DIR)
    try:
        scraper.iniciar()
        exito = scraper.scrape(fecha_inicio, fecha_fin)
    except Exception as e:
        logger.exception("Error inesperado en el scraper")
        return jsonify({"error": str(e)}), 500
    finally:
        scraper.cerrar()

    if not exito:
        return jsonify({
            "error": "El scraper no pudo completar la descarga. Revisa los logs."
        }), 500

    # ── Buscar el CSV descargado ───────────────────────────────────────────────
    archivos = sorted(
        [f for f in os.listdir(DOWNLOAD_DIR) if not f.endswith((".crdownload", ".tmp", ".part"))],
        key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
        reverse=True,
    )

    if not archivos:
        return jsonify({"error": "No se encontró el archivo descargado"}), 500

    ruta_csv = os.path.join(DOWNLOAD_DIR, archivos[0])
    nombre_descarga = f"licitaciones_{fecha_inicio_str}_{fecha_fin_str}.csv"

    logger.info(f"✅ Enviando archivo: {ruta_csv}")

    return send_file(
        ruta_csv,
        mimetype="text/csv",
        as_attachment=True,
        download_name=nombre_descarga,
    )


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🚀 Servidor en puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=False)