import sys
import logging
from datetime import datetime
from time import sleep
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# ─────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# La página Home redirige al buscador real en este subdominio
URL_BUSCADOR = "https://www.mercadopublico.cl/Home/BusquedaLicitacion"


class MercadoPublicoScraper:
    """
    Scraper Mercado Público Chile — descarga CSV de licitaciones por rango de fechas.

    Uso:
        python mercadopublico_scraper.py 2025-02-01 2025-02-28
        python mercadopublico_scraper.py 2025-02-01 2025-02-28 --headless
        python mercadopublico_scraper.py  (modo interactivo)
    """

    def __init__(self, headless: bool = False, download_dir: str = None):
        self.headless = headless
        self.download_dir = str(Path(download_dir or Path.cwd()).resolve())
        self.driver = None
        logger.info(f"📁 Descargas en: {self.download_dir}")

    # ──────────────────────────────────────────
    #  Navegador
    # ──────────────────────────────────────────
    def iniciar(self):
        logger.info("🚀 Iniciando Chrome...")
        options = Options()

        if self.headless:
            logger.info("   👻 Modo headless")
            options.add_argument("--headless=new")
        else:
            logger.info("   👁️  Modo visible")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=es-CL")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        prefs = {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "profile.default_content_setting_values.notifications": 2,
        }
        options.add_experimental_option("prefs", prefs)

        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            logger.info("✅ Chrome listo\n")
        except Exception as e:
            logger.error(f"❌ Error iniciando Chrome: {e}")
            raise

    def cerrar(self):
        if self.driver:
            logger.info("🔒 Cerrando navegador...")
            self.driver.quit()
            logger.info("✅ Cerrado")

    # ──────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────
    def _wait(self, timeout: int = 30):
        return WebDriverWait(self.driver, timeout)

    def _js_click(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        sleep(0.3)
        self.driver.execute_script("arguments[0].click();", element)

    def _js_set_date(self, element, value: str):
        """Forza valor en datepicker y dispara todos los eventos necesarios."""
        self.driver.execute_script("arguments[0].removeAttribute('readonly');", element)
        self.driver.execute_script("arguments[0].value = '';", element)
        self.driver.execute_script("arguments[0].value = arguments[1];", element, value)
        for event in ["input", "change", "blur", "keyup"]:
            self.driver.execute_script(
                f"arguments[0].dispatchEvent(new Event('{event}', {{bubbles:true}}));", element
            )
        sleep(0.3)

    def _cerrar_popup(self):
        """Intenta cerrar modales/popups de bienvenida."""
        selectores = [
            "//button[@class='close']",
            "//button[contains(@data-dismiss,'modal')]",
            "//*[contains(@class,'modal') and contains(@style,'display: block')]//button[contains(@class,'close')]",
        ]
        for xpath in selectores:
            try:
                elem = self.driver.find_element(By.XPATH, xpath)
                if elem.is_displayed():
                    self._js_click(elem)
                    sleep(0.5)
                    logger.info("   ✓ Popup cerrado")
                    return
            except NoSuchElementException:
                continue

    def _debug_pagina(self):
        """Loggea info de debug cuando algo falla."""
        logger.error(f"   URL actual : {self.driver.current_url}")
        logger.error(f"   Título     : {self.driver.title}")
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        if iframes:
            for i, f in enumerate(iframes):
                logger.info(f"   iframe[{i}] src={f.get_attribute('src')}")

    # ──────────────────────────────────────────
    #  Flujo principal
    # ──────────────────────────────────────────
    def scrape(self, fecha_inicio: datetime, fecha_fin: datetime) -> bool:
        fi_str = fecha_inicio.strftime("%d/%m/%Y")
        ff_str = fecha_fin.strftime("%d/%m/%Y")
        logger.info(f"📅 Rango: {fi_str} → {ff_str}")

        # ── 1. Cargar buscador ───────────────────────────────────────────
        logger.info(f"🌐 Cargando {URL_BUSCADOR} ...")
        self.driver.get(URL_BUSCADOR)
        sleep(5)          # esperar JS inicial
        self._cerrar_popup()

        # Si redirige, seguir la redirección
        url_actual = self.driver.current_url
        logger.info(f"   URL tras carga: {url_actual}")

        # ── 2. Entrar al iframe que contiene el buscador ────────────────
        logger.info("🔖 Buscando iframe del buscador...")
        iframe_encontrado = False
        try:
            iframes = self._wait(30).until(
                lambda d: d.find_elements(By.TAG_NAME, "iframe")
            )
            logger.info(f"   Iframes disponibles: {len(iframes)}")

            for i, frame in enumerate(iframes):
                try:
                    self.driver.switch_to.frame(frame)
                    # Verificar si este iframe tiene el selector de estado
                    self.driver.find_element(By.ID, "selectestado")
                    logger.info(f"   ✓ iframe[{i}] contiene el buscador")
                    iframe_encontrado = True
                    break
                except NoSuchElementException:
                    self.driver.switch_to.default_content()
                    continue

            if not iframe_encontrado:
                logger.error("❌ Ningún iframe contiene #selectestado")
                logger.error(self.driver.page_source[:3000])
                return False

        except TimeoutException:
            logger.error("❌ No se encontraron iframes en la página")
            logger.error(self.driver.page_source[:3000])
            return False

        # ── 3. Estado → Todos los estados ───────────────────────────────
        logger.info("🔘 Seleccionando estado: Todos los estados...")
        try:
            select_elem = self._wait(15).until(
                EC.presence_of_element_located((By.ID, "selectestado"))
            )
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "selectestado"))
            )
            Select(select_elem).select_by_value("-1")
            logger.info("   ✓ Estado = Todos los estados")
            sleep(1)
        except TimeoutException:
            logger.error("❌ No se encontró #selectestado dentro del iframe")
            logger.error(self.driver.page_source[:3000])
            return False

        # ── 4. Fecha DESDE ───────────────────────────────────────────────
        logger.info(f"📝 Fecha desde: {fi_str}")
        try:
            campo_desde = self._wait(15).until(
                EC.presence_of_element_located((By.ID, "fechadesde"))
            )
            self._js_set_date(campo_desde, fi_str)
            logger.info(f"   ✓ {fi_str}")
        except TimeoutException:
            logger.error("❌ No se encontró #fechadesde")
            return False

        # ── 5. Fecha HASTA ───────────────────────────────────────────────
        logger.info(f"📝 Fecha hasta: {ff_str}")
        try:
            campo_hasta = self._wait(15).until(
                EC.presence_of_element_located((By.ID, "fechahasta"))
            )
            self._js_set_date(campo_hasta, ff_str)
            logger.info(f"   ✓ {ff_str}")
        except TimeoutException:
            logger.error("❌ No se encontró #fechahasta")
            return False

        # ── 6. Botón Buscar ──────────────────────────────────────────────
        logger.info("🔍 Buscando...")
        btn_encontrado = False
        candidatos_buscar = [
            (By.ID,    "btnBuscarLicitacion"),
            (By.XPATH, "//button[contains(.,'Buscar')]"),
            (By.XPATH, "//a[contains(.,'Buscar')]"),
            (By.XPATH, "//*[contains(@onclick,'Busqueda.buscar')]"),
            (By.XPATH, "//*[contains(@onclick,'buscar')]"),
        ]
        for by, selector in candidatos_buscar:
            try:
                btn = self.driver.find_element(by, selector)
                if btn.is_displayed():
                    self._js_click(btn)
                    logger.info(f"   ✓ Clic en Buscar ({selector})")
                    btn_encontrado = True
                    break
            except NoSuchElementException:
                continue

        if not btn_encontrado:
            logger.info("   ℹ️  Botón Buscar no encontrado — la página puede buscar al cambiar fechas")

        # ── 7. Esperar botón de descarga ─────────────────────────────────
        logger.info("⏳ Esperando resultados (hasta 60 s)...")
        try:
            self._wait(60).until(
                EC.presence_of_element_located((By.ID, "descargarCSV"))
            )
            logger.info("   ✓ Botón de descarga disponible")
            sleep(2)
        except TimeoutException:
            logger.error("❌ El botón #descargarCSV no apareció en 60 s")
            self._debug_pagina()
            return False

        # ── 8. Clic en Descargar CSV ─────────────────────────────────────
        logger.info("⬇️  Descargando CSV...")
        try:
            btn_csv = self._wait(10).until(
                EC.element_to_be_clickable((By.ID, "descargarCSV"))
            )
            self._js_click(btn_csv)
            logger.info("   ✓ Descarga iniciada")
        except TimeoutException:
            logger.error("❌ No se pudo hacer clic en #descargarCSV")
            return False

        # ── 9. Esperar archivo en disco ──────────────────────────────────
        logger.info(f"⏳ Esperando archivo en disco...")
        descargado = self._esperar_descarga(timeout=90)

        if descargado:
            logger.info(f"✅ Archivo: {descargado}")
            return True
        else:
            logger.warning("⚠️  No se detectó el archivo en el tiempo límite")
            return False

    def _esperar_descarga(self, timeout: int = 90) -> str:
        carpeta = Path(self.download_dir)
        archivos_antes = set(carpeta.iterdir())

        for _ in range(timeout):
            sleep(1)
            archivos_ahora = set(carpeta.iterdir())
            nuevos = archivos_ahora - archivos_antes
            completos = [f for f in nuevos if f.suffix not in (".crdownload", ".tmp", ".part")]
            if completos:
                return str(sorted(completos, key=lambda f: f.stat().st_mtime)[-1])

        return ""


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────
def main():
    print("\n" + "=" * 65)
    print("🇨🇱  MERCADO PÚBLICO CHILE — Scraper de Licitaciones")
    print("=" * 65)

    modo_headless = False
    if "--headless" in sys.argv:
        modo_headless = True
        sys.argv.remove("--headless")
        print("   👻 Modo headless activado")

    if len(sys.argv) >= 3:
        try:
            fecha_inicio = datetime.strptime(sys.argv[1], "%Y-%m-%d")
            fecha_fin    = datetime.strptime(sys.argv[2], "%Y-%m-%d")
        except ValueError:
            print("\n❌ Formato incorrecto")
            print("   Uso: python mercadopublico_scraper.py YYYY-MM-DD YYYY-MM-DD [--headless]")
            return
    else:
        print("\n📅 Ingresa las fechas (formato: DD/MM/YYYY)\n")
        while True:
            try:
                fecha_inicio = datetime.strptime(input("Fecha inicio: ").strip(), "%d/%m/%Y")
                break
            except ValueError:
                print("❌ Usa DD/MM/YYYY  ej: 01/02/2025")
        while True:
            try:
                fecha_fin = datetime.strptime(input("Fecha fin:    ").strip(), "%d/%m/%Y")
                break
            except ValueError:
                print("❌ Usa DD/MM/YYYY  ej: 28/02/2025")

    if fecha_fin < fecha_inicio:
        print("\n❌ La fecha fin debe ser posterior a la fecha inicio")
        return

    print("\n" + "-" * 65)
    print(f"📅 Inicio : {fecha_inicio.strftime('%d/%m/%Y')}")
    print(f"📅 Fin    : {fecha_fin.strftime('%d/%m/%Y')}")
    print(f"📆 Días   : {(fecha_fin - fecha_inicio).days + 1}")
    print("-" * 65)

    if len(sys.argv) < 3:
        if input("\n¿Continuar? (s/n): ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("❌ Cancelado")
            return

    print("\n" + "=" * 65)
    print("🚀 INICIANDO EXTRACCIÓN...")
    print("=" * 65 + "\n")

    scraper = MercadoPublicoScraper(headless=modo_headless)
    try:
        scraper.iniciar()
        exito = scraper.scrape(fecha_inicio, fecha_fin)
        sleep(3)

        print("\n" + "=" * 65)
        if exito:
            print("✅ ¡DESCARGA COMPLETADA!")
            print(f"   Carpeta: {scraper.download_dir}")
        else:
            print("⚠️  El proceso terminó con advertencias — revisa los logs")
        print("=" * 65 + "\n")

    except KeyboardInterrupt:
        print("\n⚠️  Interrumpido")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        scraper.cerrar()


if __name__ == "__main__":
    main()