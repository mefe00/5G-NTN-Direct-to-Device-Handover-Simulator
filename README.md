---
title: 5G-NTN Disaster Handover Simulator
emoji: 🛰️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# 🛰️ 5G-NTN Disaster Handover Simulator

**Afet durumları için 5G Non-Terrestrial Network (NTN) "Direct-to-Device" handover simülasyonu.**

Karasal mobil şebeke (gNodeB) bir afette çöktüğünde, kullanıcı cihazının gerçek LEO uydularına (Starlink) otonom olarak geçişini (handover) canlı olarak modelleyen, gerçek yörünge verisi ve link budget fiziği kullanan interaktif bir "Görev Kontrol Merkezi".

![status](https://img.shields.io/badge/status-stable-success) ![python](https://img.shields.io/badge/python-3.10+-blue) ![license](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Öne Çıkanlar

- **Gerçek uydu verisi** — Celestrak'tan canlı Starlink TLE (~10.000 uydu), SGP4 yörünge propagasyonu
- **Gerçek fizik** — FSPL, Doppler kayması, atmosferik kayıp, tam link budget zinciri, DVB-S2 benzeri ACM/MODCOD
- **Otonom dinamik handover** — uydu alçaldıkça veya daha iyi aday belirdikçe gerçek karar mantığıyla geçiş
- **Canlı görselleştirme** — 10 Hz telemetri grafikleri, skyplot radar, görünür uydu tablosu, karar log terminali
- **Otomatik konum** — tarayıcı Geolocation ile canlı konum + reverse-geocoding (şehir adı)
- **Kanıt araçları** — n2yo.com canlı doğrulama linki, link budget hesap dökümü, CSV/JSON dışa aktarım
- **Tek komutla çalışır** — Windows / Linux / macOS

---

## 🌐 Web'de Yayınlama (Render.com — Ücretsiz)

Projeyi herkesin tarayıcıdan erişebileceği bir web linki haline getirmek için:

1. Kodu GitHub'a yükleyin (zaten yüklüyse atlayın)
2. [render.com](https://render.com)'a GitHub hesabınızla giriş yapın (kredi kartı gerekmez)
3. **New → Blueprint** seçin, bu repo'yu seçin
4. Render `render.yaml` dosyasını otomatik algılar; **Apply** deyin
5. Birkaç dakikada build edip yayınlar, size bir `https://...onrender.com` linki verir

> **Ücretsiz plan notu:** Servis 15 dakika kullanılmazsa uyur; sonraki ilk açılış ~30-50 saniye sürer (uyanma). Sonra normal hızlanır. Kredi kartı istenmez, sürpriz ücret çıkmaz.

> **WebSocket fallback:** Arayüz, WebSocket bağlanamazsa otomatik olarak HTTP'ye geçer — yani hangi platformda olursa olsun veri akışı garanti çalışır.

---

## 🚀 Hızlı Başlangıç (Tek Komut)

### Ön Gereksinimler
- **Python 3.10+** — [python.org](https://www.python.org/downloads/) (Windows'ta kurulumda *"Add Python to PATH"* işaretleyin)
- **Node.js 18+ (LTS)** — [nodejs.org](https://nodejs.org/)

### Çalıştırma

**Windows:**
```
start-windows.bat        (çift tıklayın)
```
veya komut isteminde:
```
python run.py
```

**Linux / macOS:**
```bash
./start-unix.sh
```
veya:
```bash
python3 run.py
```

İşte bu kadar. Script otomatik olarak:
1. Python sanal ortamı kurar ve bağımlılıkları yükler
2. Arayüz bağımlılıklarını kurar ve üretim için build eder
3. Sunucuyu başlatır ve tarayıcınızı `http://localhost:8000` adresinde açar

> **İlk çalıştırma** bağımlılık kurulumu nedeniyle birkaç dakika sürer. Sonraki çalıştırmalar saniyeler içinde başlar.

---

## 🎮 Nasıl Kullanılır?

1. Açılışta sistem **karasal ağ** modundadır (yeşil "KARASAL AĞ AKTİF").
2. Tarayıcı konum izni isterse **izin verin** (uydu hesapları konumunuza göre yapılır; reddederseniz İstanbul varsayılır).
3. Büyük kırmızı **"AFETİ TETİKLE — AĞI KOPAR"** butonuna basın.
4. İzleyin: ağ çöker → uydular taranır → en uygun Starlink seçilir → NTN linki kurulur.
5. Sistem gökyüzünü taramaya devam eder; uydu alçaldıkça **otonom handover** yapar.
6. Sayfayı aşağı kaydırarak **handover zaman çizelgesi**, **n2yo doğrulama** ve **CSV/JSON dışa aktarım** araçlarına ulaşın.

Herhangi bir panele tıklayarak tam ekran detay görünümü açabilirsiniz.

---

## 👩‍💻 Geliştirici Modu (Hot Reload)

Kod üzerinde değişiklik yapacaksanız:
```bash
python run.py --dev
```
Bu mod backend'i (otomatik reload) ve Vite geliştirme sunucusunu (anlık arayüz güncellemesi) ayrı ayrı başlatır. Arayüz: `http://localhost:5173`

Mevcut build'i yeniden derlemeden başlatmak için:
```bash
python run.py --no-build
```

---

## 🏗️ Mimari

```
Celestrak (canlı TLE)
      │
      ▼
┌────────────────────────────────┐
│  BACKEND — Python / FastAPI      │
│  • Skyfield (SGP4 yörünge)        │
│  • Link budget fizik motoru       │
│  • Handover durum makinesi        │
│  • 1 Hz gökyüzü tarama görevi     │
│  • Frontend'i de servis eder      │
└────────────────────────────────┘
      │  WebSocket (10 Hz JSON)  +  REST API
      ▼
┌────────────────────────────────┐
│  FRONTEND — React / Vite          │
│  • Recharts canlı grafikler       │
│  • Skyplot radar (SVG)            │
│  • Log terminali, timeline        │
│  • Geolocation, dışa aktarım      │
└────────────────────────────────┘
```

**Üretim modunda** backend hem API'yi hem de derlenmiş arayüzü tek porttan (`8000`) sunar — ayrı sunucu gerekmez.

### Kullanılan Teknolojiler
| Katman | Teknoloji |
|--------|-----------|
| Backend | Python, FastAPI, Uvicorn, WebSocket |
| Yörünge/Fizik | Skyfield (SGP4), NumPy |
| Veri | Celestrak TLE, httpx |
| Frontend | React 18, Vite, Tailwind CSS, Recharts |

---

## 🔬 Ne Gerçek, Ne Modellenmiş?

Bu, dürüst bir **sistem-seviyesi davranış simülasyonudur**:

**Gerçek (hesaplanan):**
- Uydu pozisyonları (Celestrak TLE + SGP4 propagasyonu)
- Elevasyon, azimut, mesafe, Doppler kayması, yayılım gecikmesi
- FSPL, atmosferik kayıp, link budget → SNR
- Handover karar algoritması (elevasyon eşiği + histerezis)

**Modellenmiş (temsilî):**
- Protokol katmanı (RRC/PRACH adımları görsel olarak loglanır, gerçek radyo handshake değildir)
- Paket-seviyesi trafik (throughput/latency istatistiksel modeldir)
- "Sistem marjı" SNR'ı gerçekçi kullanıcı seviyesine kalibre eden bir parametredir

Protokol-seviyesi 3GPP NTN implementasyonu kapsam dışıdır.

---

## 📁 Proje Yapısı

```
ntn-disaster-sim/
├── run.py                 # Tek komut başlatıcı (cross-platform)
├── start-windows.bat      # Windows başlatıcı
├── start-unix.sh          # Linux/macOS başlatıcı
├── backend/
│   ├── main.py            # FastAPI + fizik + state machine
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.jsx        # Ana dashboard
    │   ├── main.jsx
    │   └── index.css
    ├── package.json
    └── vite.config.js
```

---

## 🐛 Sorun Giderme

**"Port 8000 zaten kullanımda"**
Başka bir uygulama 8000'i kullanıyor. Farklı port:
```bash
PORT=8080 python run.py        # Linux/macOS
set PORT=8080 && python run.py # Windows
```

**"Node.js bulunamadı"**
[nodejs.org](https://nodejs.org/)'dan LTS sürümünü kurun, terminali yeniden açın.

**Konum çalışmıyor**
Tarayıcılar Geolocation'ı yalnızca `localhost` veya `https` üzerinde verir. `localhost:8000` kullandığınız için sorun olmaz — sadece izin verin.

**TLE indirilemiyor / "Gömülü Yedek TLE"**
İnternet bağlantınızı kontrol edin. Bağlantı yoksa sistem yedek veriyle açılır (çökmez).

---

## 🤝 Katkı

Katkılar memnuniyetle karşılanır! `CONTRIBUTING.md` dosyasına bakın. Issue açabilir, pull request gönderebilirsiniz.

## 📜 Lisans

MIT — `LICENSE` dosyasına bakın. Eğitim, araştırma ve kişisel kullanım için serbesttir.

## 🙏 Teşekkür

- [Celestrak](https://celestrak.org/) — açık TLE verisi
- [Skyfield](https://rhodesmill.org/skyfield/) — yörünge hesabı
- 3GPP Release 17/18 NTN spesifikasyonları

---

*Akademik bir final projesi olarak başladı, açık kaynak bir öğrenme aracına dönüştü. NTN, uydu haberleşmesi ve handover konularını öğrenmek isteyenler için.*