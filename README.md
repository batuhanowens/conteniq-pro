# ConteniQ Pro — Railway Kurulum (5 Dakika)

## Ne yapıyor?
- Python + ffmpeg sunucuda çalışır
- Whisper ile gerçek ses → kelime kelime altyazı
- ffmpeg ile profesyonel video kırpma (9:16/1:1/16:9)
- Hook ve CTA videoya yazılır
- MP4 indirilir

## Kurulum

### 1. GitHub'a yükle
- github.com → New repository → `conteniq-pro`
- Bu klasördeki TÜM dosya ve klasörleri yükle (static klasörü dahil)

### 2. Railway'e deploy et
- railway.app → "Start a New Project"
- "Deploy from GitHub repo" → `conteniq-pro` seç
- Otomatik build başlar (3-4 dakika)
- Deploy bitti → sağ üstte URL belirir: `https://conteniq-pro.up.railway.app`

### 3. Kullan
- Siteye git
- Anthropic API key gir
- Sektör seç → 7 İçerik Üret
- Video yükle → Sunucuda İşle & İndir

## Maliyet
- Railway: Ücretsiz (aylık $5 kredi, yeterli)
- Anthropic API: Kullandıkça öde (~$0.01/istek)

## Dosya Yapısı
```
conteniq-pro/
├── main.py          ← Python sunucu (Flask + ffmpeg)
├── requirements.txt ← Bağımlılıklar
├── Dockerfile       ← ffmpeg kurulumu
├── static/
│   └── index.html   ← Web arayüzü
```
