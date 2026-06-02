"""
5G-NTN Direct-to-Device Handover Simulation Backend — v2 "Mission Control"
FastAPI + WebSocket + Skyfield

Yenilikler:
- Sürekli (1 Hz) gökyüzü taraması + dinamik Inter-Satellite Handover
- Elevasyon eşiği / daha iyi aday mantığı
- FSPL (Free Space Path Loss) ve Doppler (Hz) gerçek fizik hesabı
- Tüm görünür uydu listesi (skyplot/radar için)
- TLE epoch + kaynak bilgisi
- Zaman damgalı karar logları
"""
import asyncio
import json
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from skyfield.api import EarthSatellite, load, wgs84

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
ISTANBUL_LAT = 41.0082
ISTANBUL_LON = 28.9784
ISTANBUL_ELEV_M = 40.0

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"
CELESTRAK_NAME = "Celestrak (GROUP=starlink)"
TLE_CACHE_PATH = Path(__file__).parent / "starlink_cache.tle"
TLE_CACHE_MAX_AGE_SEC = 6 * 3600

# Durumlar
STATE_TERRESTRIAL = "TERRESTRIAL"
STATE_DISASTER = "DISASTER"
STATE_SCANNING = "SCANNING"
STATE_NTN_CONNECTED = "NTN_CONNECTED"
STATE_HANDOVER = "HANDOVER"  # uydular arası geçiş (kesinti)

# Fizik
NTN_DOWNLINK_FREQ_HZ = 11.7e9      # Starlink Ku-bandı downlink ~11.7 GHz
NTN_FREQ_GHZ = 11.7
SPEED_OF_LIGHT = 299_792_458.0
BOLTZMANN_DBW = -228.6             # 10log10(k), k = 1.38e-23 J/K

# --- Link Budget parametreleri (tipik Starlink Ku-bandı downlink) ---
SAT_EIRP_DBW = 38.0                # uydu spot-beam EIRP (dBW)
UE_GT_DB = 9.8                     # kullanıcı terminali (dish) G/T (dB/K)
CHANNEL_BW_HZ = 62.5e6            # kullanıcıya tahsis edilen kanal bant genişliği (Hz)
IMPL_LOSS_DB = 2.0                 # uygulama/işleme kaybı (dB)
POINTING_LOSS_DB = 0.5             # yönlendirme kaybı (dB)
SYSTEM_MARGIN_DB = 16.5            # paylaşımlı kapasite + beam roll-off + diğer marjlar (dB)
USER_SHARE = 0.108                 # D2D: kullanıcıya düşen beam kapasite dilimi (paylaşımlı erişim)

# --- Atmosferik / yağmur sönümlemesi (ITU-R P.618 basitleştirilmiş) ---
ZENITH_ATTEN_DB = 0.6              # zenitte (90°) toplam atmosferik kayıp (dB) — açık hava
RAIN_MARGIN_DB = 0.0              # ek yağmur marjı (demo: 0, istenirse artırılır)

# --- DVB-S2 benzeri ACM/MODCOD tablosu (eşik SNR dB, modülasyon, spektral verim bps/Hz) ---
# Kaynak: DVB-S2 standardı tipik gerekli Es/N0 değerleri (yaklaşık)
MODCOD_TABLE = [
    (16.0, "32APSK 9/10", 4.45),
    (14.0, "32APSK 3/4",  3.70),
    (12.0, "16APSK 3/4",  2.97),
    (10.0, "16APSK 2/3",  2.64),
    (8.0,  "8PSK 3/4",    2.23),
    (6.0,  "8PSK 2/3",    1.98),
    (4.5,  "QPSK 3/4",    1.49),
    (2.5,  "QPSK 1/2",    0.99),
    (1.0,  "QPSK 1/4",    0.49),
]
MODCOD_FLOOR = ("LINK LOST", 0.0)  # eşik altı: bağlantı yok

# Handover mantık eşikleri
MIN_ELEVATION_DEG = 20.0           # bu eşiğin altına düşen uydu bırakılır
HANDOVER_HYSTERESIS_DEG = 15.0     # yeni aday, mevcuttan bu kadar daha iyiyse geç
HANDOVER_INTERRUPT_SEC = 1.5       # geçiş sırasında veri kesintisi süresi
SCAN_INTERVAL_SEC = 1.0            # gökyüzü tarama periyodu (1 Hz)
MAX_SCAN_CANDIDATES = 2000         # performans için taranacak max uydu


# ---------------------------------------------------------------------------
# Global durum
# ---------------------------------------------------------------------------
class SimState:
    def __init__(self):
        self.ts = load.timescale()
        self.obs_lat = ISTANBUL_LAT
        self.obs_lon = ISTANBUL_LON
        self.obs_elev = ISTANBUL_ELEV_M
        self.obs_name = "İstanbul (varsayılan)"
        self.observer = wgs84.latlon(self.obs_lat, self.obs_lon, self.obs_elev)
        self.satellites: list[EarthSatellite] = []
        self.tle_source = CELESTRAK_NAME
        self.tle_epoch_iso = "—"
        self.tle_fetch_time_iso = "—"
        self.tle_age_days = None          # epoch'tan bu yana geçen gün
        self.tle_quality = "—"            # "GÜNCEL" / "KABUL EDİLEBİLİR" / "ESKİ"
        self.start_wall = time.time()
        self.reset()

    def compute_tle_age(self):
        """En güncel TLE epoch'undan bu yana geçen süreyi ve doğruluk sınıfını hesapla."""
        if not self.satellites:
            self.tle_age_days = None
            self.tle_quality = "—"
            return
        try:
            epoch = self.satellites[0].epoch.utc_datetime()
            now = datetime.now(timezone.utc)
            age = (now - epoch).total_seconds() / 86400.0
            self.tle_age_days = age
            # SGP4 propagasyon doğruluğu: ~birkaç günde sapar
            if age < 1.5:
                self.tle_quality = "GÜNCEL"
            elif age < 5.0:
                self.tle_quality = "KABUL EDİLEBİLİR"
            else:
                self.tle_quality = "ESKİ"
        except Exception:
            self.tle_age_days = None
            self.tle_quality = "—"

    def set_location(self, lat: float, lon: float, elev: float = 40.0, name: str = ""):
        # Sınır kontrolü: geçersiz koordinat skyfield'i bozabilir
        lat = max(-90.0, min(90.0, float(lat)))
        lon = max(-180.0, min(180.0, float(lon)))
        elev = max(-500.0, min(9000.0, float(elev)))  # makul irtifa aralığı (m)
        self.obs_lat = lat
        self.obs_lon = lon
        self.obs_elev = elev
        self.obs_name = name or f"{lat:.4f}, {lon:.4f}"
        self.observer = wgs84.latlon(self.obs_lat, self.obs_lon, self.obs_elev)
        # Görünür önbelleği geçersiz kıl ki yeni konuma göre yeniden taransın
        self.visible_cache = []

    def reset(self):
        self.state = STATE_TERRESTRIAL
        self.disaster_time: float | None = None
        self.selected_satellite: EarthSatellite | None = None
        self.handover_until: float = 0.0      # bu zamana kadar HANDOVER (kesinti)
        self.next_satellite: EarthSatellite | None = None
        self.logs: list[dict] = []
        self.visible_cache: list[dict] = []
        self.handover_count = 0
        self._warned_no_alt = False
        self.handover_timeline: list[dict] = []   # yapılandırılmış geçiş kayıtları
        self.telemetry_buffer: list[dict] = []     # CSV export için telemetri


sim = SimState()


def add_log(msg: str, level: str = "info"):
    sim.logs.append({"time": time.time(), "msg": msg, "level": level})
    # Bellek koruması
    if len(sim.logs) > 500:
        sim.logs = sim.logs[-400:]


# ---------------------------------------------------------------------------
# Reverse geocoding (koordinat -> şehir/ülke adı), Nominatim / OpenStreetMap
# ---------------------------------------------------------------------------
async def reverse_geocode(lat: float, lon: float) -> str:
    """Koordinatı insan-okunur yer adına çevir. Hata olursa koordinata düşer."""
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "accept-language": "tr"}
    headers = {"User-Agent": "ntn-sim/1.0 (akademik proje)"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            addr = data.get("address", {})
            # Şehir/ilçe + ülke birleştir
            city = (addr.get("city") or addr.get("town") or addr.get("province")
                    or addr.get("state") or addr.get("county") or "")
            country = addr.get("country", "")
            if city and country:
                return f"{city}, {country}"
            if data.get("display_name"):
                # display_name çok uzun olabilir, ilk 2 parça
                parts = data["display_name"].split(",")
                return ", ".join(p.strip() for p in parts[:2])
    except Exception as e:
        print(f"[GEO] reverse_geocode hatası: {e}")
    return f"{lat:.3f}°, {lon:.3f}°"


# ---------------------------------------------------------------------------
# TLE yükleme
# ---------------------------------------------------------------------------
async def fetch_tle_data() -> str:
    if TLE_CACHE_PATH.exists():
        age = time.time() - TLE_CACHE_PATH.stat().st_mtime
        if age < TLE_CACHE_MAX_AGE_SEC:
            print(f"[TLE] Cache kullanılıyor (yaş: {int(age)}s)")
            sim.tle_source = f"{CELESTRAK_NAME} [cache]"
            return TLE_CACHE_PATH.read_text(encoding="utf-8")

    print("[TLE] Celestrak'tan indiriliyor...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(CELESTRAK_URL, headers={"User-Agent": "ntn-sim/1.0"})
            r.raise_for_status()
            text = r.text
            if "STARLINK" not in text.upper():
                raise ValueError("Geçersiz TLE içeriği")
            TLE_CACHE_PATH.write_text(text, encoding="utf-8")
            sim.tle_source = CELESTRAK_NAME
            print(f"[TLE] {text.count(chr(10)) // 3} uydu indirildi")
            return text
    except Exception as e:
        print(f"[TLE] İndirme hatası: {e}")
        if TLE_CACHE_PATH.exists():
            sim.tle_source = f"{CELESTRAK_NAME} [eski cache]"
            return TLE_CACHE_PATH.read_text(encoding="utf-8")
        sim.tle_source = "Gömülü Yedek TLE (offline)"
        return _fallback_tle()


def _fallback_tle() -> str:
    return """STARLINK-1007
1 44713U 19074A   24001.50000000  .00001000  00000-0  70000-4 0  9999
2 44713  53.0534  95.4567 0001234  90.0000 270.0000 15.06400000200000
STARLINK-1008
1 44714U 19074B   24001.50000000  .00001000  00000-0  70000-4 0  9999
2 44714  53.0534 100.4567 0001234  90.0000 270.0000 15.06400000200000
STARLINK-1009
1 44715U 19074C   24001.50000000  .00001000  00000-0  70000-4 0  9999
2 44715  53.0534 105.4567 0001234  90.0000 270.0000 15.06400000200000
STARLINK-1010
1 44716U 19074D   24001.50000000  .00001000  00000-0  70000-4 0  9999
2 44716  53.0534 110.4567 0001234  90.0000 270.0000 15.06400000200000
"""


def parse_tle(text: str) -> list[EarthSatellite]:
    sats: list[EarthSatellite] = []
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    i = 0
    while i + 2 < len(lines):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            try:
                sats.append(EarthSatellite(l1, l2, name, sim.ts))
                i += 3
            except Exception:
                i += 1
        else:
            i += 1
    return sats


# ---------------------------------------------------------------------------
# Fizik yardımcıları
# ---------------------------------------------------------------------------
def compute_fspl_db(distance_km: float, freq_ghz: float = NTN_FREQ_GHZ) -> float:
    """Free Space Path Loss (dB). FSPL = 20log10(d_km) + 20log10(f_GHz) + 92.45"""
    if distance_km <= 0:
        return 0.0
    return 20 * math.log10(distance_km) + 20 * math.log10(freq_ghz) + 92.45


def compute_atmospheric_loss_db(elevation_deg: float) -> float:
    """
    Basitleştirilmiş ITU-R P.618 slant-path atmosferik sönümleme.
    Zenitteki (90°) kayıp, elevasyon düştükçe 1/sin(elev) ile artar (cosecant yasası).
    Çok düşük açıda doyum için elev tabanı uygulanır.
    """
    elev = max(elevation_deg, 3.0)  # 3° altında model güvenilmez
    cosec = 1.0 / math.sin(math.radians(elev))
    return (ZENITH_ATTEN_DB + RAIN_MARGIN_DB) * cosec


def compute_link_budget(distance_km: float, elevation_deg: float) -> dict:
    """
    Tam downlink link budget zinciri.
    C/N0 = EIRP - FSPL - atm - pointing - impl + G/T - k(dB)
    SNR  = C/N0 - 10log10(BW)
    """
    fspl = compute_fspl_db(distance_km)
    atm = compute_atmospheric_loss_db(elevation_deg)

    cn0_dbhz = (SAT_EIRP_DBW
                - fspl
                - atm
                - POINTING_LOSS_DB
                - IMPL_LOSS_DB
                - SYSTEM_MARGIN_DB
                + UE_GT_DB
                - BOLTZMANN_DBW)        # -(-228.6) => +228.6
    snr_db = cn0_dbhz - 10 * math.log10(CHANNEL_BW_HZ)

    return {
        "fspl_db": fspl,
        "atm_loss_db": atm,
        "cn0_dbhz": cn0_dbhz,
        "snr_db": snr_db,
    }


def select_modcod(snr_db: float) -> tuple[str, float]:
    """SNR'a göre DVB-S2 benzeri en yüksek desteklenen MODCOD'u seç."""
    for thr, mod, eff in MODCOD_TABLE:
        if snr_db >= thr:
            return mod, eff
    return MODCOD_FLOOR


def compute_shannon_throughput_mbps(snr_db: float, bw_hz: float = CHANNEL_BW_HZ) -> float:
    """Shannon-Hartley üst sınırı: C = BW * log2(1 + SNR_linear)."""
    if snr_db <= -20:
        return 0.0
    snr_lin = 10 ** (snr_db / 10.0)
    cap_bps = bw_hz * math.log2(1 + snr_lin)
    return cap_bps / 1e6


def compute_acm_throughput_mbps(snr_db: float, eff_bps_hz: float, bw_hz: float = CHANNEL_BW_HZ) -> float:
    """
    Gerçekçi (uygulanan) throughput: seçilen MODCOD spektral verimi x bant genişliği.
    Shannon teorik tavan; ACM bunun gerçekleştirilen kısmı.
    """
    return (eff_bps_hz * bw_hz) / 1e6


def compute_sat_metrics(sat: EarthSatellite, t_sky=None) -> dict:
    """Bir uydunun gözlemciye göre tam metrikleri."""
    if t_sky is None:
        t_sky = sim.ts.from_datetime(datetime.now(timezone.utc))
    diff = sat - sim.observer
    topo = diff.at(t_sky)
    alt, az, distance = topo.altaz()

    # Range-rate -> Doppler
    try:
        _, _, _, _, _, range_rate = topo.frame_latlon_and_rates(sim.observer)
        v_radial = range_rate.km_per_s * 1000.0  # m/s
    except Exception:
        # Yedek: geometrik range-rate
        pos = np.array(topo.position.km)
        vel = np.array(topo.velocity.km_per_s)
        v_radial = float(np.dot(pos, vel) / max(np.linalg.norm(pos), 1e-6)) * 1000.0

    doppler_hz = -(v_radial / SPEED_OF_LIGHT) * NTN_DOWNLINK_FREQ_HZ
    prop_delay_ms = (distance.km * 1000.0 / SPEED_OF_LIGHT) * 1000.0

    # --- Link budget + ACM + Shannon (gerçekçi fizik) ---
    lb = compute_link_budget(distance.km, alt.degrees)
    snr_clean = lb["snr_db"]
    modcod, eff = select_modcod(snr_clean)
    shannon_mbps = compute_shannon_throughput_mbps(snr_clean)
    acm_mbps = compute_acm_throughput_mbps(snr_clean, eff)

    return {
        "name": sat.name,
        "satnum": int(sat.model.satnum),
        "elevation": float(alt.degrees),
        "azimuth": float(az.degrees),
        "distance_km": float(distance.km),
        "doppler_hz": float(doppler_hz),
        "fspl_db": lb["fspl_db"],
        "atm_loss_db": lb["atm_loss_db"],
        "cn0_dbhz": lb["cn0_dbhz"],
        "snr_clean_db": float(snr_clean),
        "modcod": modcod,
        "spectral_eff": float(eff),
        "shannon_mbps": float(shannon_mbps),
        "acm_mbps": float(acm_mbps),
        "prop_delay_ms": float(prop_delay_ms),
        "range_rate_kms": float(v_radial / 1000.0),
    }


def scan_visible(min_elev: float = MIN_ELEVATION_DEG, limit_list: int = 12) -> list[dict]:
    """Ufkun üzerindeki tüm uyduları bul, elevasyona göre sırala."""
    now = sim.ts.from_datetime(datetime.now(timezone.utc))
    candidates = sim.satellites[:MAX_SCAN_CANDIDATES]
    visible = []
    for sat in candidates:
        try:
            diff = sat - sim.observer
            alt, az, distance = diff.at(now).altaz()
            if alt.degrees > min_elev:
                lb = compute_link_budget(distance.km, alt.degrees)
                modcod, _eff = select_modcod(lb["snr_db"])
                visible.append({
                    "sat": sat,
                    "name": sat.name,
                    "satnum": int(sat.model.satnum),
                    "elevation": float(alt.degrees),
                    "azimuth": float(az.degrees),
                    "distance_km": float(distance.km),
                    "fspl_db": lb["fspl_db"],
                    "snr_db": float(lb["snr_db"]),
                    "modcod": modcod,
                })
        except Exception:
            continue
    visible.sort(key=lambda x: x["elevation"], reverse=True)
    return visible[:limit_list]


# ---------------------------------------------------------------------------
# Metrik üretimi (her WS tick)
# ---------------------------------------------------------------------------
def generate_metrics(t: float) -> dict:
    rng = np.random.default_rng()
    payload = {
        "timestamp": round(t, 3),
        "state": sim.state,
        "throughput": 0.0,
        "latency": 0.0,
        "snr": 0.0,
        "satellite_info": None,
        "status_text": "",
        "handover_count": sim.handover_count,
        "observer": {"lat": sim.obs_lat, "lon": sim.obs_lon, "name": sim.obs_name},
    }

    if sim.state == STATE_TERRESTRIAL:
        payload["throughput"] = float(100 + rng.normal(0, 3))
        payload["latency"] = float(5 + abs(rng.normal(0, 0.5)))
        payload["snr"] = float(25 + rng.normal(0, 1.2))
        payload["status_text"] = "Karasal Ağ (gNodeB 3.5 GHz)"

    elif sim.state == STATE_DISASTER:
        payload["throughput"] = 0.0
        payload["latency"] = 0.0
        payload["snr"] = float(-10 + rng.normal(0, 1.0))
        payload["status_text"] = "AĞ ÇÖKTÜ - Sinyal Yok"

    elif sim.state == STATE_SCANNING:
        payload["throughput"] = 0.0
        payload["latency"] = 0.0
        payload["snr"] = float(-8 + rng.normal(0, 1.5))
        payload["status_text"] = "NTN Uyduları Taranıyor..."

    elif sim.state == STATE_HANDOVER:
        # Inter-satellite handover kesintisi
        payload["throughput"] = 0.0
        payload["latency"] = 0.0
        payload["snr"] = float(-5 + rng.normal(0, 2.0))
        nxt = sim.next_satellite.name if sim.next_satellite else "?"
        payload["status_text"] = f"Uydular Arası Geçiş → {nxt}"

    elif sim.state == STATE_NTN_CONNECTED and sim.selected_satellite is not None:
        try:
            m = compute_sat_metrics(sim.selected_satellite)
        except Exception as e:
            print(f"[SAT] metrik hatası: {e}")
            m = None

        if m is None:
            payload["throughput"] = 0.0
            payload["latency"] = 0.0
            payload["snr"] = -10.0
            payload["status_text"] = "Uydu metrik hatası"
            return payload

        # SNR: link budget'tan gelen temiz değer + Doppler kaynaklı küçük
        # dalgalanma (faz gürültüsü) + termal gürültü. Artık fiziksel.
        doppler_ripple = math.sin(t * 0.8) * 0.4
        snr = m["snr_clean_db"] + doppler_ripple + rng.normal(0, 0.4)

        # MODCOD'u anlık SNR'a göre yeniden seç (ACM canlı uyum sağlar)
        modcod, eff = select_modcod(snr)
        if eff <= 0.0:
            # SNR MODCOD tabanının altında: link fiilen kayıp
            throughput = 0.0
        else:
            # Beam kapasitesi x kullanıcı dilimi (D2D paylaşımlı erişim)
            beam_mbps = (eff * CHANNEL_BW_HZ) / 1e6
            throughput = beam_mbps * USER_SHARE + rng.normal(0, 0.3)

        # Latency: çift yön yayılım + işleme + jitter
        latency = 2 * m["prop_delay_ms"] + 15 + rng.normal(0, 1.5)

        payload["throughput"] = float(max(0, throughput))
        payload["latency"] = float(max(0, latency))
        payload["snr"] = float(snr)
        payload["status_text"] = f"NTN Uydu Linki Aktif: {m['name']} [{modcod}]"
        payload["satellite_info"] = {
            "name": m["name"],
            "satnum": m["satnum"],
            "elevation": round(m["elevation"], 2),
            "azimuth": round(m["azimuth"], 2),
            "distance_km": round(m["distance_km"], 1),
            "doppler_hz": round(m["doppler_hz"], 1),
            "fspl_db": round(m["fspl_db"], 2),
            "atm_loss_db": round(m["atm_loss_db"], 2),
            "cn0_dbhz": round(m["cn0_dbhz"], 1),
            "range_rate_kms": round(m["range_rate_kms"], 3),
            "modcod": modcod,
            "spectral_eff": round(eff, 2),
            "shannon_mbps": round(m["shannon_mbps"], 1),
            "beam_mbps": round((eff * CHANNEL_BW_HZ) / 1e6, 1),
            "user_mbps": round(max(0, throughput), 2),
            "snr_now_db": round(snr, 2),
        }

    return payload


# ---------------------------------------------------------------------------
# Arka plan görevi: ilk handover + sürekli tarama & dinamik geçiş
# ---------------------------------------------------------------------------
async def initial_handover():
    """Afet -> tarama -> ilk uydu seçimi."""
    await asyncio.sleep(0.8)
    sim.state = STATE_SCANNING
    add_log("Karasal bağlantı kaybı doğrulandı. NTN tarama başlatılıyor...", "warn")

    visible = await asyncio.to_thread(scan_visible, MIN_ELEVATION_DEG, 12)
    add_log(f"Tarama tamamlandı: {len(visible)} uydu ufkun üzerinde (>{MIN_ELEVATION_DEG:.0f}°).", "info")

    if not visible:
        visible = await asyncio.to_thread(scan_visible, 5.0, 12)
        add_log(f"Eşik 5°'ye düşürüldü: {len(visible)} aday.", "info")

    if not visible:
        add_log("Uyarı: görünür uydu yok, simülasyon moduna geçiliyor.", "warn")
        if sim.satellites:
            sim.selected_satellite = sim.satellites[0]
            sim.state = STATE_NTN_CONNECTED
            add_log(f"Yedek seçim: {sim.satellites[0].name}", "success")
        return

    for s in visible[:5]:
        add_log(f"Aday: {s['name']} | Elev {s['elevation']:.1f}° | {s['distance_km']:.0f} km | FSPL {s['fspl_db']:.1f} dB", "info")

    best = visible[0]
    sim.selected_satellite = best["sat"]
    sim.handover_timeline.append({
        "index": 0,
        "time": time.time(),
        "t_rel": round(time.time() - sim.start_wall, 1),
        "from_sat": "KARASAL (gNodeB)",
        "from_elev": None,
        "to_sat": best["name"],
        "to_elev": round(best["elevation"], 1),
        "to_dist_km": round(best["distance_km"], 0),
        "reason": "İlk NTN edinimi (afet)",
    })
    add_log(f"SEÇİLDİ: {best['name']} (Elev {best['elevation']:.2f}°, en yüksek)", "success")
    await asyncio.sleep(0.3)
    add_log("PRACH ön-iletim + Doppler ön-kompenzasyonu uygulandı.", "info")
    await asyncio.sleep(0.3)
    add_log("RRC bağlantısı kuruldu. NTN linki aktif.", "success")
    sim.state = STATE_NTN_CONNECTED


async def reacquire_satellite():
    """
    Bağlantı kaybından sonra (uydu ufuk altına indi) yeni uydu edin.
    initial_handover'ın hafif versiyonu — durum zaten SCANNING.
    """
    visible = await asyncio.to_thread(scan_visible, MIN_ELEVATION_DEG, 12)
    if not visible:
        visible = await asyncio.to_thread(scan_visible, 5.0, 12)
    if not visible:
        add_log("Görünür uydu bulunamadı, tarama sürüyor...", "warn")
        # NTN_CONNECTED'a dönme; sky_monitor bir sonraki turda tekrar deneyebilir
        # ama selected None olduğu için tick erken döner. Kısa bekleyip tekrar dene.
        await asyncio.sleep(1.0)
        if sim.state == STATE_SCANNING:
            asyncio.create_task(reacquire_satellite())
        return
    best = visible[0]
    sim.selected_satellite = best["sat"]
    sim.handover_count += 1
    sim.handover_timeline.append({
        "index": sim.handover_count,
        "time": time.time(),
        "t_rel": round(time.time() - sim.start_wall, 1),
        "from_sat": "BAĞLANTI KAYBI",
        "from_elev": None,
        "to_sat": best["name"],
        "to_elev": round(best["elevation"], 1),
        "to_dist_km": round(best["distance_km"], 0),
        "reason": "Yeniden edinim (link kaybı)",
    })
    add_log(f"Yeni uydu edinildi: {best['name']} (Elev {best['elevation']:.1f}°). NTN linki yeniden aktif.", "success")
    sim.state = STATE_NTN_CONNECTED


async def sky_monitor_supervisor():
    """
    sky_monitor'u izler; beklenmedik bir exception ile çökerse kısa bekleyip
    yeniden başlatır. Böylece dinamik handover demonun ortasında sessizce durmaz.
    """
    restarts = 0
    while True:
        try:
            await sky_monitor()
            # sky_monitor normalde sonsuz döngü; buraya düşerse temiz çıkış
            break
        except asyncio.CancelledError:
            raise  # uygulama kapanıyor, yeniden başlatma
        except Exception as e:
            restarts += 1
            print(f"[MONITOR] çöktü ({e}); yeniden başlatılıyor (#{restarts})")
            add_log(f"İzleme görevi yeniden başlatıldı (hata kurtarma #{restarts}).", "warn")
            await asyncio.sleep(2.0)


async def sky_monitor():
    """1 Hz sürekli tarama: görünür liste güncelle + dinamik handover kararı."""
    while True:
        await asyncio.sleep(SCAN_INTERVAL_SEC)
        try:
            await _sky_monitor_tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Tek bir tick hatası tüm görevi öldürmesin; logla ve devam et
            print(f"[MONITOR] tick hatası: {e}")


async def _sky_monitor_tick():
    """Tek bir izleme adımı (eskiden sky_monitor döngü gövdesi)."""
    if True:
        if sim.state not in (STATE_NTN_CONNECTED, STATE_HANDOVER):
            return

        # Handover kesintisi bitti mi?
        if sim.state == STATE_HANDOVER:
            if time.time() >= sim.handover_until and sim.next_satellite is not None:
                sim.selected_satellite = sim.next_satellite
                sim.next_satellite = None
                sim.state = STATE_NTN_CONNECTED
                try:
                    m = compute_sat_metrics(sim.selected_satellite)
                    add_log(f"Handover TAMAMLANDI → {m['name']} aktif (Elev {m['elevation']:.1f}°).", "success")
                except Exception:
                    add_log("Handover tamamlandı.", "success")
            return

        # NTN bağlı: görünür listeyi güncelle
        visible = await asyncio.to_thread(scan_visible, MIN_ELEVATION_DEG, 12)
        sim.visible_cache = [
            {k: v for k, v in s.items() if k != "sat"} for s in visible
        ]

        if sim.selected_satellite is None:
            return

        # Mevcut uydunun durumu
        try:
            cur = compute_sat_metrics(sim.selected_satellite)
        except Exception:
            return

        cur_elev = cur["elevation"]
        cur_satnum = cur["satnum"]

        # En iyi aday (kendisi hariç)
        best_other = None
        for s in visible:
            if s["satnum"] != cur_satnum:
                best_other = s
                break

        trigger = None
        target = None

        # 1) Mevcut uydu eşiğin altına düştü
        if cur_elev < MIN_ELEVATION_DEG:
            if best_other:
                add_log(f"{cur['name']} elevasyonu düşüyor ({cur_elev:.1f}° < {MIN_ELEVATION_DEG:.0f}°). Yeni hedef aranıyor...", "warn")
                trigger = "elevation_drop"
                target = best_other
            elif cur_elev < 5.0:
                # Uydu fiilen ufuk çizgisinde/altında ve alternatif yok:
                # linke tutunmak fiziksel değil. Bağlantıyı bırak, yeniden tara.
                add_log(f"{cur['name']} ufuk çizgisinin altına indi ({cur_elev:.1f}°) ve görünür alternatif yok. Bağlantı kaybedildi, yeniden taranıyor...", "error")
                sim.selected_satellite = None
                sim._warned_no_alt = False
                sim.state = STATE_SCANNING
                # Yeniden edinim görevini başlat
                asyncio.create_task(reacquire_satellite())
                return
            elif not sim._warned_no_alt:
                add_log("Uyarı: alternatif uydu yok, mevcut link zayıf ama korunuyor.", "warn")
                sim._warned_no_alt = True

        # 2) Çok daha iyi bir aday belirdi (histerezis)
        elif best_other and (best_other["elevation"] - cur_elev) > HANDOVER_HYSTERESIS_DEG:
            add_log(f"Daha iyi aday: {best_other['name']} ({best_other['elevation']:.1f}°) vs mevcut {cur['name']} ({cur_elev:.1f}°).", "info")
            trigger = "better_candidate"
            target = best_other

        if trigger and target:
            from_name = cur["name"]
            from_elev = cur_elev
            sim.next_satellite = target["sat"]
            sim.handover_until = time.time() + HANDOVER_INTERRUPT_SEC
            sim.state = STATE_HANDOVER
            sim.handover_count += 1
            sim._warned_no_alt = False
            reason = "Elevasyon düşüşü" if trigger == "elevation_drop" else "Daha iyi aday"
            # Yapılandırılmış timeline kaydı (sunum + CSV için)
            sim.handover_timeline.append({
                "index": sim.handover_count,
                "time": time.time(),
                "t_rel": round(time.time() - sim.start_wall, 1),
                "from_sat": from_name,
                "from_elev": round(from_elev, 1),
                "to_sat": target["name"],
                "to_elev": round(target["elevation"], 1),
                "to_dist_km": round(target["distance_km"], 0),
                "reason": reason,
            })
            add_log(
                f"Handover #{sim.handover_count} başlatıldı → Hedef: {target['name']} "
                f"(Elev {target['elevation']:.1f}°, {target['distance_km']:.0f} km). Kesinti ~{HANDOVER_INTERRUPT_SEC:.1f}s.",
                "error",
            )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[INIT] Starlink TLE yükleniyor...")
    tle_text = await fetch_tle_data()
    sim.satellites = parse_tle(tle_text)
    sim.tle_fetch_time_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if sim.satellites:
        try:
            sim.tle_epoch_iso = sim.satellites[0].epoch.utc_iso()
        except Exception:
            sim.tle_epoch_iso = "—"
    sim.compute_tle_age()
    age_str = f"{sim.tle_age_days:.1f} gün" if sim.tle_age_days is not None else "—"
    print(f"[INIT] {len(sim.satellites)} uydu yüklendi. Epoch: {sim.tle_epoch_iso} "
          f"(yaş: {age_str}, {sim.tle_quality})")
    # Sürekli tarama görevini başlat (kendini onaran sarmalayıcı ile)
    monitor_task = asyncio.create_task(sky_monitor_supervisor())
    yield
    monitor_task.cancel()
    print("[SHUTDOWN]")


app = FastAPI(title="5G-NTN Mission Control", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------
@app.get("/api/info")
async def api_info():
    return {
        "name": "5G-NTN Mission Control",
        "state": sim.state,
        "satellites_loaded": len(sim.satellites),
        "tle_source": sim.tle_source,
        "tle_epoch": sim.tle_epoch_iso,
    }


@app.post("/api/set_location")
async def set_location(payload: dict):
    """Frontend'in tarayıcı Geolocation API'sinden gönderdiği konumu uygula."""
    try:
        lat = float(payload.get("lat"))
        lon = float(payload.get("lon"))
        elev = float(payload.get("elev", 40.0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Geçersiz lat/lon"}

    # Sınır dışı koordinat reddi (clamp yerine açık hata, kullanıcı bilsin)
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return {"ok": False, "error": f"Koordinat aralık dışı: lat={lat}, lon={lon}"}

    old = (round(sim.obs_lat, 4), round(sim.obs_lon, 4))
    moved = old != (round(lat, 4), round(lon, 4))

    # Konumu hemen uygula (geçici ad = koordinat); geocoding arka planda
    sim.set_location(lat, lon, elev, f"{lat:.3f}°, {lon:.3f}°")

    if moved:
        add_log(f"Gözlemci konumu güncellendi: {lat:.4f}°, {lon:.4f}° — yer adı çözümleniyor...", "info")
        # Reverse geocoding arka planda (yanıtı bekletmeden)
        asyncio.create_task(_resolve_location_name(lat, lon, elev))

    return {
        "ok": True,
        "observer": {"lat": sim.obs_lat, "lon": sim.obs_lon, "name": sim.obs_name},
    }


async def _resolve_location_name(lat: float, lon: float, elev: float):
    """Arka planda yer adını çöz ve gözlemci adını güncelle."""
    name = await reverse_geocode(lat, lon)
    # Sadece hâlâ aynı konumdaysak güncelle (kullanıcı bu arada taşınmış olabilir)
    if abs(sim.obs_lat - lat) < 1e-4 and abs(sim.obs_lon - lon) < 1e-4:
        sim.obs_name = name
        add_log(f"Konum çözümlendi: {name}", "success")


@app.get("/api/tle_info")
async def tle_info():
    sim.compute_tle_age()
    return {
        "source": sim.tle_source,
        "epoch": sim.tle_epoch_iso,
        "fetched_at": sim.tle_fetch_time_iso,
        "age_days": round(sim.tle_age_days, 2) if sim.tle_age_days is not None else None,
        "quality": sim.tle_quality,
        "satellite_count": len(sim.satellites),
        "observer": {"lat": sim.obs_lat, "lon": sim.obs_lon, "name": sim.obs_name},
        "downlink_freq_ghz": NTN_FREQ_GHZ,
        "link_budget": {
            "eirp_dbw": SAT_EIRP_DBW,
            "ue_gt_db": UE_GT_DB,
            "bw_mhz": CHANNEL_BW_HZ / 1e6,
            "system_margin_db": SYSTEM_MARGIN_DB,
            "impl_loss_db": IMPL_LOSS_DB,
            "pointing_loss_db": POINTING_LOSS_DB,
        },
    }


@app.post("/api/trigger_disaster")
async def trigger_disaster():
    if sim.state == STATE_TERRESTRIAL:
        sim.state = STATE_DISASTER
        sim.disaster_time = time.time()
        sim.logs = []
        sim.handover_count = 0
        sim.handover_timeline = []
        sim.telemetry_buffer = []
        add_log("⚠ AFET TETİKLENDİ — Karasal gNodeB sinyali kayboldu.", "error")
        asyncio.create_task(initial_handover())
        return {"ok": True, "state": sim.state}
    return {"ok": False, "state": sim.state}


@app.post("/api/reset")
async def reset_sim():
    sim.reset()
    add_log("Sistem sıfırlandı. Karasal moda dönüldü.", "info")
    return {"ok": True, "state": sim.state}


@app.get("/api/state")
async def get_state():
    return {"state": sim.state, "satellites_loaded": len(sim.satellites)}


@app.get("/api/snapshot")
async def snapshot(since: int = 0):
    """
    WebSocket fallback: HTTP polling için anlık tam durum.
    `since` parametresi = istemcinin elindeki son log indeksi; sadece yeni loglar döner.
    Frontend WebSocket bağlanamazsa bu endpoint'i ~3 Hz çağırır.
    """
    t = time.time() - sim.start_wall
    payload = generate_metrics(t)
    payload["type"] = "tick"
    # Yeni loglar (since'den sonrakiler)
    total_logs = len(sim.logs)
    if since < total_logs:
        payload["new_logs"] = sim.logs[since:]
    payload["log_index"] = total_logs
    # Görünür uydular + timeline (polling'de her seferinde gönder)
    payload["visible_satellites"] = sim.visible_cache
    payload["handover_timeline"] = sim.handover_timeline
    # Meta (TLE bilgisi) de ekle ki ilk poll'de header dolsun
    sim.compute_tle_age()
    payload["meta"] = {
        "tle_source": sim.tle_source,
        "tle_epoch": sim.tle_epoch_iso,
        "tle_fetched_at": sim.tle_fetch_time_iso,
        "tle_age_days": round(sim.tle_age_days, 2) if sim.tle_age_days is not None else None,
        "tle_quality": sim.tle_quality,
        "satellite_count": len(sim.satellites),
    }
    return payload


@app.get("/api/handover_timeline")
async def handover_timeline():
    """Tüm handover olaylarının yapılandırılmış zaman çizelgesi (sunum kanıtı)."""
    return {"count": len(sim.handover_timeline), "events": sim.handover_timeline}


@app.get("/api/link_budget_breakdown")
async def link_budget_breakdown():
    """
    Seçili uydu için link budget'ın adım adım dökümü (hesap şeffaflığı).
    Jüriye 'SNR nereden geliyor' sorusunun tam cevabı.
    """
    if sim.selected_satellite is None:
        return {"ok": False, "error": "Bağlı uydu yok (önce afeti tetikleyin)"}
    try:
        m = compute_sat_metrics(sim.selected_satellite)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    d = m["distance_km"]
    f = NTN_FREQ_GHZ
    # FSPL bileşenleri
    fspl_dist = 20 * math.log10(d)
    fspl_freq = 20 * math.log10(f)
    steps = [
        {"label": "Uydu EIRP", "op": "+", "value": SAT_EIRP_DBW, "unit": "dBW"},
        {"label": f"FSPL = 20log₁₀({d:.0f}km) + 20log₁₀({f}GHz) + 92.45",
         "op": "−", "value": round(m["fspl_db"], 2), "unit": "dB",
         "detail": f"{fspl_dist:.1f} + {fspl_freq:.1f} + 92.45"},
        {"label": "Atmosferik kayıp (ITU-R P.618, csc)", "op": "−", "value": round(m["atm_loss_db"], 2), "unit": "dB"},
        {"label": "Yönlendirme kaybı", "op": "−", "value": POINTING_LOSS_DB, "unit": "dB"},
        {"label": "Uygulama kaybı", "op": "−", "value": IMPL_LOSS_DB, "unit": "dB"},
        {"label": "Sistem marjı (paylaşım+roll-off)", "op": "−", "value": SYSTEM_MARGIN_DB, "unit": "dB"},
        {"label": "Terminal G/T", "op": "+", "value": UE_GT_DB, "unit": "dB/K"},
        {"label": "Boltzmann sabiti −10log₁₀(k)", "op": "+", "value": 228.6, "unit": "dB"},
    ]
    return {
        "ok": True,
        "satellite": m["name"],
        "distance_km": round(d, 1),
        "freq_ghz": f,
        "steps": steps,
        "cn0_dbhz": round(m["cn0_dbhz"], 2),
        "bw_hz": CHANNEL_BW_HZ,
        "bw_term_db": round(10 * math.log10(CHANNEL_BW_HZ), 2),
        "snr_db": round(m["snr_clean_db"], 2),
        "modcod": m["modcod"],
        "spectral_eff": m["spectral_eff"],
        "shannon_mbps": round(m["shannon_mbps"], 1),
    }


@app.get("/api/export/telemetry.csv")
async def export_telemetry_csv():
    """Telemetri verisini CSV olarak indir (akademik rapor için)."""
    import io, csv
    from fastapi.responses import StreamingResponse

    buf = io.StringIO()
    if sim.telemetry_buffer:
        fieldnames = list(sim.telemetry_buffer[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sim.telemetry_buffer)
    else:
        buf.write("veri yok — once afeti tetikleyin\n")
    buf.seek(0)
    fname = f"ntn_telemetry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.get("/api/export/session.json")
async def export_session_json():
    """Tüm oturum verisini (telemetri + timeline + meta) JSON olarak indir."""
    from fastapi.responses import JSONResponse
    sim.compute_tle_age()
    payload = {
        "meta": {
            "tle_source": sim.tle_source,
            "tle_epoch": sim.tle_epoch_iso,
            "tle_age_days": sim.tle_age_days,
            "tle_quality": sim.tle_quality,
            "satellite_count": len(sim.satellites),
            "observer": {"lat": sim.obs_lat, "lon": sim.obs_lon, "name": sim.obs_name},
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "link_budget_params": {
                "eirp_dbw": SAT_EIRP_DBW, "ue_gt_db": UE_GT_DB,
                "bw_mhz": CHANNEL_BW_HZ / 1e6, "system_margin_db": SYSTEM_MARGIN_DB,
            },
        },
        "handover_timeline": sim.handover_timeline,
        "telemetry": sim.telemetry_buffer,
    }
    fname = f"ntn_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ---------------------------------------------------------------------------
# WebSocket — 10 Hz
# ---------------------------------------------------------------------------
@app.websocket("/ws/simulation")
async def ws_simulation(websocket: WebSocket):
    await websocket.accept()
    print("[WS] bağlandı")
    last_log_idx = 0
    last_visible_send = 0.0
    try:
        # Bağlanır bağlanmaz TLE meta + mevcut logları gönder
        sim.compute_tle_age()  # her yeni bağlantıda yaşı tazele
        await websocket.send_text(json.dumps({
            "type": "meta",
            "tle_source": sim.tle_source,
            "tle_epoch": sim.tle_epoch_iso,
            "tle_fetched_at": sim.tle_fetch_time_iso,
            "tle_age_days": round(sim.tle_age_days, 2) if sim.tle_age_days is not None else None,
            "tle_quality": sim.tle_quality,
            "satellite_count": len(sim.satellites),
            "observer": {"lat": sim.obs_lat, "lon": sim.obs_lon, "name": sim.obs_name},
        }))
        last_sample = 0.0
        while True:
            t = time.time() - sim.start_wall
            payload = generate_metrics(t)
            payload["type"] = "tick"

            new_logs = sim.logs[last_log_idx:]
            if new_logs:
                payload["new_logs"] = new_logs
                last_log_idx = len(sim.logs)

            # Görünür uydu listesini ~2 Hz gönder (bant genişliği)
            if time.time() - last_visible_send > 0.5:
                payload["visible_satellites"] = sim.visible_cache
                payload["handover_timeline"] = sim.handover_timeline
                last_visible_send = time.time()

            # Telemetriyi ~2 Hz buffer'a örnekle (CSV export için)
            if time.time() - last_sample > 0.5:
                si = payload.get("satellite_info")
                sim.telemetry_buffer.append({
                    "t_s": round(t, 2),
                    "state": payload["state"],
                    "throughput_mbps": round(payload["throughput"], 3),
                    "latency_ms": round(payload["latency"], 3),
                    "snr_db": round(payload["snr"], 3),
                    "satellite": si["name"] if si else "",
                    "elevation_deg": si["elevation"] if si else "",
                    "distance_km": si["distance_km"] if si else "",
                    "fspl_db": si["fspl_db"] if si else "",
                    "doppler_hz": si["doppler_hz"] if si else "",
                    "modcod": si["modcod"] if si else "",
                })
                # Bellek koruması: ~10 dk @ 2Hz = 1200 örnek
                if len(sim.telemetry_buffer) > 1500:
                    sim.telemetry_buffer = sim.telemetry_buffer[-1200:]
                last_sample = time.time()

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        print("[WS] ayrıldı")
    except Exception as e:
        print(f"[WS] hata: {e}")



from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    # SPA: bilinmeyen yollar index.html'e düşsün (client-side routing)
    @app.get("/")
    async def serve_index():
        return FileResponse(_FRONTEND_DIST / "index.html")

    # assets ve diğer statik dosyalar
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
    print(f"[STATIC] Frontend servis ediliyor: {_FRONTEND_DIST}")
else:
    @app.get("/")
    async def no_frontend():
        return {
            "message": "Frontend build edilmemiş. Geliştirme modunda 'npm run dev' kullanın "
                       "ya da üretim için 'frontend' klasöründe 'npm run build' çalıştırın.",
            "api_info": "/api/info",
        }


if __name__ == "__main__":
    import uvicorn
    # PORT ortam değişkeni varsa onu kullan (bulut deploy uyumu), yoksa 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)