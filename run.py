#!/usr/bin/env python3
"""
5G-NTN Disaster Handover Simulator — Tek Komut Başlatıcı
=========================================================
Bu script tüm kurulumu ve başlatmayı otomatik yapar:
  1. Python ve Node.js kontrolü
  2. Python sanal ortamı + bağımlılıklar
  3. Frontend bağımlılıkları + üretim build'i
  4. Sunucuyu başlatır ve tarayıcıyı açar

Kullanım:
    python run.py            # kur + build + başlat (üretim modu, tek port)
    python run.py --dev      # geliştirici modu (iki ayrı sunucu, hot-reload)
    python run.py --no-build # mevcut build'i kullan, yeniden build etme

Windows / Linux / macOS uyumludur.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / "venv"
IS_WINDOWS = platform.system() == "Windows"
PORT = int(os.environ.get("PORT", 8000))

# Renkli çıktı (Windows terminalde de çalışır)
class C:
    G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[94m"; X = "\033[0m"
    @staticmethod
    def ok(m):   print(f"{C.G}✓{C.X} {m}")
    @staticmethod
    def info(m): print(f"{C.B}→{C.X} {m}")
    @staticmethod
    def warn(m): print(f"{C.Y}!{C.X} {m}")
    @staticmethod
    def err(m):  print(f"{C.R}✗{C.X} {m}")
    @staticmethod
    def head(m): print(f"\n{C.B}{'='*60}\n  {m}\n{'='*60}{C.X}")


def run(cmd, cwd=None, check=True, shell=False):
    """Komut çalıştır, çıktıyı göster."""
    printable = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
    C.info(printable)
    result = subprocess.run(cmd, cwd=cwd, check=False, shell=shell)
    if check and result.returncode != 0:
        C.err(f"Komut başarısız (kod {result.returncode}): {printable}")
        sys.exit(1)
    return result


def venv_python():
    return str(VENV / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python"))


def venv_pip():
    return [venv_python(), "-m", "pip"]


def check_prerequisites(dev_mode):
    """Python ve (gerekiyorsa) Node.js var mı?"""
    C.head("1/4 · Gereksinim Kontrolü")

    # Python sürümü
    if sys.version_info < (3, 10):
        C.err(f"Python 3.10+ gerekli (mevcut: {sys.version.split()[0]})")
        sys.exit(1)
    C.ok(f"Python {sys.version.split()[0]}")

    # Node.js (build veya dev için gerekli)
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        C.err("Node.js / npm bulunamadı. https://nodejs.org adresinden kurun (LTS sürümü).")
        C.warn("Node.js olmadan arayüz build edilemez.")
        sys.exit(1)
    try:
        nv = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        C.ok(f"Node.js {nv}")
    except Exception:
        C.ok("Node.js bulundu")


def setup_backend():
    """Sanal ortam + Python bağımlılıkları."""
    C.head("2/4 · Backend Kurulumu")
    if not VENV.exists():
        C.info("Python sanal ortamı oluşturuluyor...")
        run([sys.executable, "-m", "venv", str(VENV)])
        C.ok("Sanal ortam oluşturuldu")
    else:
        C.ok("Sanal ortam zaten var")

    C.info("Python bağımlılıkları kuruluyor (birkaç dakika sürebilir)...")
    run(venv_pip() + ["install", "--upgrade", "pip", "--quiet"])
    run(venv_pip() + ["install", "-r", str(BACKEND / "requirements.txt"), "--quiet"])
    C.ok("Python bağımlılıkları hazır")


def setup_frontend(do_build):
    """npm install + (üretim için) build."""
    C.head("3/4 · Arayüz Kurulumu")
    npm = "npm.cmd" if IS_WINDOWS else "npm"

    if not (FRONTEND / "node_modules").exists():
        C.info("Arayüz bağımlılıkları kuruluyor (birkaç dakika sürebilir)...")
        run([npm, "install"], cwd=str(FRONTEND))
        C.ok("Arayüz bağımlılıkları hazır")
    else:
        C.ok("Arayüz bağımlılıkları zaten var")

    if do_build:
        C.info("Arayüz üretim için build ediliyor...")
        run([npm, "run", "build"], cwd=str(FRONTEND))
        C.ok("Arayüz build edildi (frontend/dist)")


def start_production():
    """Tek port: backend hem API hem arayüzü servis eder."""
    C.head("4/4 · Sunucu Başlatılıyor (Üretim Modu)")
    url = f"http://localhost:{PORT}"
    C.ok(f"Simülatör hazır → {C.G}{url}{C.X}")
    C.info("Durdurmak için Ctrl+C")
    print()

    # Tarayıcıyı 2 sn sonra aç (sunucu ayağa kalksın)
    def open_browser():
        time.sleep(2.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    env = dict(os.environ, PORT=str(PORT))
    try:
        subprocess.run(
            [venv_python(), "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(PORT)],
            cwd=str(BACKEND), env=env,
        )
    except KeyboardInterrupt:
        print()
        C.ok("Sunucu durduruldu. Hoşça kal!")


def start_dev():
    """Geliştirici modu: backend (reload) + vite dev (hot reload) ayrı süreçler."""
    C.head("4/4 · Geliştirici Modu (Hot Reload)")
    npm = "npm.cmd" if IS_WINDOWS else "npm"
    env = dict(os.environ, PORT=str(PORT))

    C.info(f"Backend → http://localhost:{PORT}")
    backend_proc = subprocess.Popen(
        [venv_python(), "-m", "uvicorn", "main:app", "--host", "0.0.0.0",
         "--port", str(PORT), "--reload"],
        cwd=str(BACKEND), env=env,
    )
    time.sleep(2)
    C.info("Arayüz (Vite) → http://localhost:5173")
    C.ok("Geliştirici sunucuları çalışıyor. Tarayıcıda http://localhost:5173 açın.")
    C.info("Durdurmak için Ctrl+C")
    print()

    def open_browser():
        time.sleep(3)
        try:
            webbrowser.open("http://localhost:5173")
        except Exception:
            pass
    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        subprocess.run([npm, "run", "dev"], cwd=str(FRONTEND), env=env)
    except KeyboardInterrupt:
        pass
    finally:
        backend_proc.terminate()
        print()
        C.ok("Sunucular durduruldu. Hoşça kal!")


def main():
    parser = argparse.ArgumentParser(description="5G-NTN Disaster Handover Simulator başlatıcı")
    parser.add_argument("--dev", action="store_true", help="Geliştirici modu (hot reload, iki sunucu)")
    parser.add_argument("--no-build", action="store_true", help="Arayüzü yeniden build etme")
    args = parser.parse_args()

    print(f"""{C.B}
  ╔════════════════════════════════════════════════════════╗
  ║   5G-NTN DISASTER HANDOVER SIMULATOR                     ║
  ║   Afet Durumları İçin Direct-to-Device Handover         ║
  ╚════════════════════════════════════════════════════════╝{C.X}""")

    check_prerequisites(args.dev)
    setup_backend()
    # Dev modunda build gerekmez (vite serve eder); üretimde build gerekir
    setup_frontend(do_build=not args.dev and not args.no_build)

    if args.dev:
        start_dev()
    else:
        start_production()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        sys.exit(0)
