# Katkı Rehberi

Bu projeye katkıda bulunmak istediğiniz için teşekkürler! 🛰️

## Nasıl Başlarım?

1. Bu depoyu **fork** edin
2. Geliştirme modunda çalıştırın:
   ```bash
   python run.py --dev
   ```
3. Değişikliklerinizi yapın
4. Test edin (aşağıya bakın)
5. Pull request gönderin

## Geliştirme Ortamı

- **Backend:** `backend/main.py` — FastAPI, fizik motoru, state machine
- **Frontend:** `frontend/src/App.jsx` — React dashboard

`--dev` modu hem backend'i (otomatik reload) hem Vite'ı (anlık arayüz güncelleme) başlatır.

## Test

Backend değişikliklerinden sonra hızlı kontrol:
```bash
cd backend
python -c "import ast; ast.parse(open('main.py').read()); print('Syntax OK')"
```

Frontend build kontrolü:
```bash
cd frontend
npm run build
```

## Katkı Fikirleri

- 🌧️ Daha gelişmiş yağmur/atmosferik sönümleme modeli (ITU-R P.618 tam implementasyon)
- 🤖 Prediktif (LSTM tabanlı) handover algoritması
- 📡 Çoklu konstellasyon desteği (OneWeb, Kuiper)
- 🌍 3B yer küresi görselleştirmesi
- 🌐 Çoklu dil desteği (i18n)
- 📊 Ek metrikler (BER, paket kaybı simülasyonu)

## Kod Stili

- Python: PEP 8, açıklayıcı değişken adları, Türkçe veya İngilizce yorum
- React: fonksiyonel bileşenler, hook'lar
- Anlamlı commit mesajları

## Sorular

Issue açmaktan çekinmeyin. Her türlü soru, hata bildirimi ve öneri değerlidir.
