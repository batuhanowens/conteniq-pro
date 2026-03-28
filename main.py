import os, uuid, json, subprocess, threading, re
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)
UPLOAD = Path("uploads"); UPLOAD.mkdir(exist_ok=True)
OUTPUT = Path("outputs"); OUTPUT.mkdir(exist_ok=True)
JOBS = {}

def find_font():
    for c in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if os.path.exists(c): return c
    return None

FONT = find_font()
print(f"[startup] Font={FONT}")

def clean(t):
    out = []
    for c in (t or ""):
        cp = ord(c)
        if not (0x1F000 <= cp <= 0x1FFFF or 0x2600 <= cp <= 0x27BF or
                0xFE00 <= cp <= 0xFE0F or cp == 0x200D):
            out.append(c)
    return re.sub(r'  +', ' ', ''.join(out)).strip()

def ts_ass(s):
    s = max(0, float(s))
    h = int(s // 3600); m = int((s % 3600) // 60)
    sc = int(s % 60); cs = int((s % 1) * 100)
    return f"{h}:{m:02d}:{sc:02d}.{cs:02d}"

def ts_srt(s):
    s = max(0, float(s))
    h = int(s // 3600); m = int((s % 3600) // 60)
    sc = int(s % 60); ms = int((s % 1) * 1000)
    return f"{h:02d}:{m:02d}:{sc:02d},{ms:03d}"

# ════════════════════════════════════════
# ANGLE PROFİLLERİ — Her biri farklı edit DNA
# ════════════════════════════════════════
ANGLES = {
    "firsat": {
        "label": "Fırsat Kaçırma",
        "hook_c": "&H000000FF", "hi1": "&H0055CCFF", "hi2": "&H000080FF",
        "out": "&H00000000", "shd": "&HCC000000",
        "fscale": 115, "hook_sz": 0.092, "sub_sz": 0.068,
        "hook_dur": 2.5, "sub_n": 3,
        "silence_cut": True,
        "tone": "ACİL ve SERT. SON, KAÇIRMA, HEMEN, ŞİMDİ. Max 7 kelime hook.",
        "hi_words": ["SON", "KAÇIRMA", "HEMEN", "ŞİMDİ", "FIRSAT", "BUGÜN", "ACELE"],
        "edit_rules": [
            "İlk 3sn: Hook tam ekran ortasında, kırmızı, büyük",
            "3-8sn: Problemi göster, hızlı kes",
            "8-15sn: Çözümü sun, sarı vurgu kelimeleri",
            "15-22sn: Kanıt/rakam göster",
            "22-27sn: CTA — kırmızı kutu, alt ortada"
        ],
        "zoom_plan": ["2.sn zoom in %110", "8.sn zoom out normal", "15.sn zoom in %105"],
        "cut_notes": "Her 1.5sn'de cut. Sessizlikleri kes.",
    },
    "sir": {
        "label": "Sır",
        "hook_c": "&H00CC44CC", "hi1": "&H00CC44CC", "hi2": "&H0055CCFF",
        "out": "&H00000000", "shd": "&H88000000",
        "fscale": 100, "hook_sz": 0.080, "sub_sz": 0.060,
        "hook_dur": 3.5, "sub_n": 5,
        "silence_cut": False,
        "tone": "GİZEMLİ ve merak uyandırıcı. Kimse bilmiyor, ilk kez, gizli. Yavaş ve emin.",
        "hi_words": ["GİZLİ", "SIR", "KIMSE", "BİLMİYOR", "İLK", "KEZ", "ASLA"],
        "edit_rules": [
            "İlk 3.5sn: Hook mor renkte, yavaş fade in",
            "3-8sn: Merak yarat, yavaş kes",
            "8-15sn: Sırrı aç, mor vurgu",
            "15-22sn: Detay ver",
            "22-27sn: CTA — mor kutu"
        ],
        "zoom_plan": ["0.sn çok yavaş zoom in (30sn boyunca %102)", "10.sn hafif zoom"],
        "cut_notes": "Her 2.5sn'de cut. Sessizlikleri kesme.",
    },
    "hata": {
        "label": "Yaygın Hata",
        "hook_c": "&H000000FF", "hi1": "&H0055CCFF", "hi2": "&H0000FF00",
        "out": "&H00000000", "shd": "&HCC000000",
        "fscale": 108, "hook_sz": 0.086, "sub_sz": 0.064,
        "hook_dur": 3.0, "sub_n": 4,
        "silence_cut": True,
        "tone": "UYARICI. Hata, yanlış, dikkat. YANLIŞ kelimesi sarı, DOĞRU yeşil.",
        "hi_words": ["HATA", "YANLIŞ", "DİKKAT", "YAPMA", "ASLA", "DOĞRU", "ÇÖZÜM"],
        "edit_rules": [
            "İlk 3sn: Hook kırmızı, büyük uyarı",
            "3-8sn: Hata göster — sarı vurgu",
            "8-15sn: Doğrusu bu — yeşil vurgu",
            "15-22sn: Kanıt göster",
            "22-27sn: CTA"
        ],
        "zoom_plan": ["5.sn zoom in (hata anı)", "10.sn zoom out (çözüm)"],
        "cut_notes": "Her 2sn'de cut. Hata anında sert kes.",
    },
    "kanit": {
        "label": "Sosyal Kanıt",
        "hook_c": "&H0000CC55", "hi1": "&H0000FF00", "hi2": "&H0055CCFF",
        "out": "&H00000000", "shd": "&H88000000",
        "fscale": 105, "hook_sz": 0.082, "sub_sz": 0.062,
        "hook_dur": 3.0, "sub_n": 5,
        "silence_cut": False,
        "tone": "GÜVENİLİR. Rakam, müşteri sonucu, gerçek hikaye. Kanıtlandı, müşterim.",
        "hi_words": ["MÜŞTERİ", "SONUÇ", "KANIT", "BAŞARDI", "TL", "KAT", "GERÇEK"],
        "edit_rules": [
            "İlk 3sn: Hook yeşil — güven veren",
            "3-8sn: Müşteri/problem hikayesi",
            "8-15sn: Sonuç — yeşil rakamlar vurgulu",
            "15-22sn: Detay/nasıl oldu",
            "22-27sn: CTA — güven veren"
        ],
        "zoom_plan": ["8.sn zoom (sonuç anı)", "15.sn normal"],
        "cut_notes": "Her 2.5sn'de cut. Rakam söylenince vurgu.",
    },
    "karsilastirma": {
        "label": "Karşılaştırma",
        "hook_c": "&H00FFFFFF", "hi1": "&H0000FF00", "hi2": "&H000000FF",
        "out": "&H00000000", "shd": "&HAA000000",
        "fscale": 108, "hook_sz": 0.084, "sub_sz": 0.062,
        "hook_dur": 3.0, "sub_n": 4,
        "silence_cut": True,
        "tone": "KONTRAST. VS, fark, hangisi. Yeşil=iyi seçenek, Kırmızı=kötü seçenek.",
        "hi_words": ["VS", "FARK", "DAHA", "İYİ", "KÖTÜ", "KAZANAN", "KAYBEDEN"],
        "edit_rules": [
            "İlk 3sn: Hook beyaz — merak",
            "3-8sn: Seçenek 1 (kötü) — kırmızı",
            "8-15sn: Seçenek 2 (iyi) — yeşil",
            "15-22sn: Karşılaştırma — net fark",
            "22-27sn: CTA — kazananı sun"
        ],
        "zoom_plan": ["8.sn iyi seçenek anında zoom"],
        "cut_notes": "Her 2sn'de cut. Karşılaştırma anında sert geçiş.",
    },
    "bilgi": {
        "label": "Bilgi / Eğitim",
        "hook_c": "&H00FFFFFF", "hi1": "&H00DDAAFF", "hi2": "&H005CCCFF",
        "out": "&H00000000", "shd": "&H88000000",
        "fscale": 100, "hook_sz": 0.078, "sub_sz": 0.058,
        "hook_dur": 3.5, "sub_n": 6,
        "silence_cut": False,
        "tone": "BİLGİLENDİRİCİ. Adım, rakam, liste. Sade ve net öğretici.",
        "hi_words": ["ADIM", "BİLİYOR", "MUSUN", "GERÇEK", "ÖĞREN", "DİKKAT", "NOT"],
        "edit_rules": [
            "İlk 3.5sn: Hook beyaz sade",
            "3-8sn: 1. bilgi/adım",
            "8-15sn: 2. bilgi/adım — mavi vurgu",
            "15-22sn: 3. bilgi/adım",
            "22-27sn: CTA — takip et"
        ],
        "zoom_plan": ["Her yeni adımda hafif zoom in"],
        "cut_notes": "Her 3sn'de cut. Sade geçişler.",
    },
    "duygusal": {
        "label": "Duygusal Bağ",
        "hook_c": "&H00CC88FF", "hi1": "&H00CC88FF", "hi2": "&H0055CCFF",
        "out": "&H00000000", "shd": "&H88000000",
        "fscale": 100, "hook_sz": 0.078, "sub_sz": 0.058,
        "hook_dur": 4.0, "sub_n": 5,
        "silence_cut": False,
        "tone": "DUYGUSAL ve samimi. Kişisel hikaye, empati, yavaş ve derin.",
        "hi_words": ["HİSSETTİM", "ANLADIM", "KORKTUM", "BAŞARDIM", "İNANDIM", "UMUTTUM"],
        "edit_rules": [
            "İlk 4sn: Hook pembe, yavaş",
            "4-8sn: Kişisel hikaye başlangıcı",
            "8-15sn: Zorluk/his anı",
            "15-22sn: Çözüm/dönüşüm",
            "22-27sn: CTA — bağ kur"
        ],
        "zoom_plan": ["Çok yavaş sürekli zoom (tüm video %101-104)"],
        "cut_notes": "Her 3.5sn'de cut. Keskinlik değil akış.",
    },
}

def get_angle(s):
    s = (s or "").lower()
    for k in ANGLES:
        if k in s: return ANGLES[k]
    m = {"kaçırma": "firsat", "sır": "sir", "hata": "hata", "yanlış": "hata",
         "kanıt": "kanit", "sosyal": "kanit", "karşı": "karsilastirma",
         "bilgi": "bilgi", "duygu": "duygusal"}
    for k, v in m.items():
        if k in s: return ANGLES[v]
    return ANGLES["bilgi"]

# ── ROUTES ──────────────────────────────

@app.route("/")
def index(): return send_from_directory("static", "index.html")

@app.route("/api/health")
def health():
    try: ffok = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5).returncode == 0
    except: ffok = False
    return jsonify({"ok": True, "ffmpeg": ffok, "font": FONT})

# ══════════════════════════════════════════════════
# İÇERİK ÜRETİMİ — En gelişmiş hali
# ══════════════════════════════════════════════════

@app.route("/api/generate", methods=["POST"])
def generate():
    import requests as req
    data = request.json or {}
    key = request.headers.get("X-Api-Key", "")
    if not key: return jsonify({"error": "API key gerekli"}), 400

    sector   = data.get("sector", "Genel")
    city     = data.get("city", "Türkiye")
    goal     = data.get("goal", "Müşteri")
    audience = data.get("audience", "genel")
    detail   = data.get("detail", "")

    tones = "\n".join(f"  angle={k}: {v['tone']}" for k, v in ANGLES.items())

    prompt = f"""Sen Türkiye pazarında uzman bir sosyal medya stratejisti ve video içerik uzmanısın.
Görevin: Verilen sektör için, gerçekten izlenip DM getiren Reels içerikleri üretmek.

MÜŞTERİ BİLGİLERİ:
- Sektör: {sector}
- Şehir: {city}
- Hedef: {goal}
- Hedef Kitle: {audience}
{f"- Detay: {detail}" if detail else ""}

7 FARKLI REELS İÇERİĞİ ÜRET. Her biri farklı psikolojik tetikleyici:
{tones}

HER İÇERİK İÇİN GEREKEN:
1. hook: Max 8 kelime. İzleyiciyi ilk 2sn'de yakalamalı. EMOJİ YOK.
2. video_flow: Her sahne için ne yapılacağı net. Kamera talimatı gibi yaz.
3. script: Kameraya bakarak konuşulacak metin. Tona tam uygun. Max 80 kelime.
4. subtitles: En az 3 altyazı satırı. highlight: o satırın en güçlü 2 kelimesi.
5. edit_timing: Hangi saniyede ne yapılacak (zoom, cut, vurgu).
6. hook_visual: Hook'ta arka planda ne görünmeli.
7. cta: O angle'a uygun tek net aksiyon. EMOJİ YOK.

SADECE JSON — başka hiçbir şey yazma:
{{"meta":{{"sector":"{sector}","city":"{city}","goal":"{goal}","audience":"{audience}"}},"contents":[{{"num":1,"angle":"firsat","hook":"İzleyiciyi yakalan kısa hook","hook_visual":"kamera direkt yüze bakıyor, ciddi ifade","video_flow":[{{"scene":1,"sec":"0-3","action":"Hook — kameraya bak, ciddi ifade","text":"Hook metnini söyle"}},{{"scene":2,"sec":"3-8","action":"Problemi anlat — hızlı jestler","text":"Problem metni"}},{{"scene":3,"sec":"8-15","action":"Çözümü sun — güven veren duruş","text":"Çözüm metni"}},{{"scene":4,"sec":"15-22","action":"Kanıt göster — rakam söyle","text":"Kanıt metni"}},{{"scene":5,"sec":"22-27","action":"CTA — kameraya bak, gülümse","text":"CTA metni"}}],"script":"Kameraya bakarak söylenecek tam metin","subtitles":[{{"text":"Güçlü kısa cümle","highlight":["KELIME1","KELIME2"]}},{{"text":"İkinci cümle","highlight":["KELIME3"]}},{{"text":"Üçüncü cümle","highlight":["KELIME4"]}}],"edit_timing":[{{"sec":2,"action":"zoom_in","note":"Hook vurgusu"}},{{"sec":8,"action":"zoom_out","note":"Geçiş"}},{{"sec":15,"action":"zoom_in","note":"Kanıt anı"}}],"trigger":"İzleyicide yaratacağı his","cta":"Net tek aksiyon","caption":"Instagram/TikTok caption — 3 satır","hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5"]}}]}}

KURALLAR:
1. 7 içerik üret, her biri farklı angle
2. Sektöre ÇOKK özel — generik içerik üretme
3. Script tona tam uygun olsun (fırsat=acil, sır=gizemli, duygusal=samimi)
4. Her sahne talimatı çekim yapacak kişiye yol gösterir nitelikte olsun
5. Türkçe, emoji yok hook/cta'da"""

    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 6000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=120
        )
        d = r.json()
        if "error" in d: return jsonify({"error": d["error"]["message"]}), 400
        raw = re.sub(r"```json|```", "", "".join(x["text"] for x in d["content"] if x.get("type") == "text")).strip()
        result = json.loads(raw)
        # Angle profilinden eksikleri tamamla
        for c in result.get("contents", []):
            ap = get_angle(c.get("angle", ""))
            if not c.get("cta") or len(c.get("cta", "")) < 5:
                c["cta"] = "DM yaz simdi"
            # edit_rules ekle (frontend için)
            c["edit_rules"] = ap.get("edit_rules", [])
            c["zoom_plan"] = ap.get("zoom_plan", [])
            c["cut_notes"] = ap.get("cut_notes", "")
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════
# VIDEO İŞLEME — Altyazı + Hook + CTA + Silence Cut
# ══════════════════════════════════════════════════

@app.route("/api/process", methods=["POST"])
def process_video():
    key = request.headers.get("X-Api-Key", "")
    if "video" not in request.files: return jsonify({"error": "Video gerekli"}), 400

    vf          = request.files["video"]
    content_raw = request.form.get("content", "{}")
    fmt         = request.form.get("format", "9:16")
    t0          = float(request.form.get("trim_start", 0) or 0)
    t1          = float(request.form.get("trim_end", 0) or 0)
    use_wh      = request.form.get("use_whisper", "true") == "true"
    silence_cut = request.form.get("silence_cut", "false") == "true"

    try: content = json.loads(content_raw)
    except: content = {}

    jid = str(uuid.uuid4())[:8]
    ext = Path(vf.filename).suffix or ".mp4"
    inp = str(UPLOAD / f"{jid}_in{ext}")
    vf.save(inp)

    JOBS[jid] = {"status": "queued", "progress": 0, "msg": "Baslatiliyor..."}
    threading.Thread(target=run_job,
        args=(jid, inp, key, content, fmt, t0, t1, use_wh, silence_cut),
        daemon=True).start()
    return jsonify({"job_id": jid})

# ── SRT EXPORT ────────────────────────────────────

@app.route("/api/srt/<jid>")
def get_srt(jid):
    """Whisper altyazısını SRT formatında ver — CapCut/Premiere için."""
    p = OUTPUT / f"{jid}.srt"
    if not p.exists(): return jsonify({"error": "SRT yok"}), 404
    return send_file(str(p), mimetype="text/srt",
                     as_attachment=True, download_name=f"conteniq-{jid}.srt")

@app.route("/api/editplan/<jid>")
def get_edit_plan(jid):
    """Edit planını JSON olarak ver."""
    p = OUTPUT / f"{jid}_plan.json"
    if not p.exists(): return jsonify({"error": "Plan yok"}), 404
    return send_file(str(p), mimetype="application/json",
                     as_attachment=True, download_name=f"editplan-{jid}.json")

def upd(jid, p, msg, status="running"):
    JOBS[jid] = {"status": status, "progress": p, "msg": msg}
    print(f"[{jid}] {p}% {msg}")

def run_job(jid, inp, key, content, fmt, t0, t1, use_wh, do_silence_cut):
    try:
        import requests as req

        # PROBE
        upd(jid, 5, "Video analiz ediliyor...")
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", inp],
            capture_output=True, text=True, timeout=30)
        info = json.loads(probe.stdout)
        dur = float(info["format"]["duration"])
        has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
        end_t = t1 if (t1 > t0 and t1 > 0) else dur
        total = end_t - t0

        angle = content.get("angle", "bilgi")
        ap = get_angle(angle)
        upd(jid, 10, f"Angle: {ap['label']}, sure={total:.1f}s")

        # SILENCE CUT — sessizlikleri tespit et ve kes
        processed_inp = inp
        if do_silence_cut and ap.get("silence_cut", False) and has_audio:
            upd(jid, 13, "Sessizlikler kesiliyor...")
            cut_result = silence_cut_video(inp, jid, t0, end_t)
            if cut_result:
                processed_inp = cut_result
                total = float(subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", cut_result],
                    capture_output=True, text=True).stdout.strip() or total)
                upd(jid, 18, f"Sessizlikler kesildi — yeni sure: {total:.1f}s")
            t0 = 0; t1 = 0  # Zaten kesildi

        # WHISPER
        words = []
        if use_wh and key and has_audio:
            upd(jid, 20, "Whisper: ses analiz ediliyor...")
            try:
                aud = inp.replace("_in", "_aud") + ".mp3"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", processed_inp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", aud],
                    capture_output=True, check=True, timeout=120)
                with open(aud, "rb") as f:
                    wr = req.post("https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {key}"},
                        files={"file": ("a.mp3", f, "audio/mp3")},
                        data={"model": "whisper-1", "language": "tr",
                              "response_format": "verbose_json",
                              "timestamp_granularities[]": "word"},
                        timeout=120)
                try: os.remove(aud)
                except: pass
                if wr.status_code == 200:
                    words = wr.json().get("words", [])
                    upd(jid, 30, f"Whisper: {len(words)} kelime")
                    # SRT dosyası kaydet
                    srt_path = str(OUTPUT / f"{jid}.srt")
                    write_srt(words, srt_path, content.get("subtitles", []))
                    upd(jid, 32, "SRT kaydedildi")
            except Exception as e:
                upd(jid, 30, f"Whisper basarisiz: {e}")

        # Highlight flag
        hl_set = set(ap.get("hi_words", []))
        for w in words:
            wc = re.sub(r"[^\wğüşöçıĞÜŞÖÇİ]", "", w["word"]).upper()
            w["highlight"] = wc in hl_set or (w["word"].strip().upper() == w["word"].strip() and len(w["word"].strip()) > 2)

        # EDİT PLANI kaydet
        edit_plan_data = {
            "angle": ap["label"],
            "edit_rules": ap.get("edit_rules", []),
            "zoom_plan": ap.get("zoom_plan", []),
            "cut_notes": ap.get("cut_notes", ""),
            "content_timing": content.get("edit_timing", []),
            "video_flow": content.get("video_flow", []),
            "hook": content.get("hook", ""),
            "cta": content.get("cta", ""),
            "total_dur": total,
            "capcut_guide": _capcut_guide(ap, content, total),
        }
        with open(str(OUTPUT / f"{jid}_plan.json"), "w", encoding="utf-8") as f:
            json.dump(edit_plan_data, f, ensure_ascii=False, indent=2)

        # ASS
        upd(jid, 36, "Altyazilar olusturuluyor...")
        hook = clean(content.get("hook", ""))
        cta = clean(content.get("cta", ""))
        subs = content.get("subtitles", [])
        ass = build_ass(jid, processed_inp, words, subs, hook, cta, fmt, total, t0, ap)

        # FFMPEG
        upd(jid, 45, "ffmpeg: video isleniyor...")
        out = str(OUTPUT / f"{jid}_out.mp4")

        vf_str = _vf(fmt, ass)
        if _run_ff(jid, processed_inp, out, t0, t1, vf_str, "crop+altyazi"):
            upd(jid, 90, "Video tamamlandi")
        else:
            upd(jid, 75, "Sadece crop deneniyor...")
            if _run_ff(jid, processed_inp, out, t0, t1, _crop(fmt), "sadece crop"):
                upd(jid, 90, "Crop tamamlandi")
            else:
                _run_ff(jid, processed_inp, out, t0, t1, "", "copy", copy=True)

        # Temizlik
        if processed_inp != inp:
            try: os.remove(processed_inp)
            except: pass
        try: os.remove(inp)
        except: pass
        if ass:
            try: os.remove(ass)
            except: pass

        size = os.path.getsize(out) / 1024 / 1024 if os.path.exists(out) else 0
        has_srt = (OUTPUT / f"{jid}.srt").exists()
        upd(jid, 100, f"Tamamlandi! {size:.1f}MB | SRT={'var' if has_srt else 'yok'}", "done")

    except Exception as e:
        upd(jid, 0, f"Hata: {str(e)[:300]}", "error")
        print(f"[{jid}] EXCEPTION: {e}")

# ── SILENCE CUT ───────────────────────────────────

def silence_cut_video(inp, jid, t0, end_t):
    """Sessiz kısımları tespit et ve videoyu kes/birleştir."""
    try:
        # Silence tespiti
        result = subprocess.run(
            ["ffmpeg", "-i", inp, "-af", "silencedetect=noise=-35dB:d=0.5", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60)

        starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
        ends   = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", result.stderr)]

        if not starts: return None

        # Sessiz olmayan bölgeleri bul
        segments = []
        prev_end = t0
        for s, e in zip(starts, ends):
            s -= t0; e -= t0
            if s > prev_end + 0.3 and s > 3:  # hook'tan sonra kes
                segments.append((prev_end, s))
                prev_end = e
        # Son segment
        if prev_end < (end_t - t0) - 0.5:
            segments.append((prev_end, end_t - t0))

        if len(segments) < 2: return None

        # Her segment'i kes
        seg_files = []
        for i, (s, e) in enumerate(segments[:10]):  # Max 10 segment
            seg_f = str(UPLOAD / f"{jid}_seg{i}.mp4")
            r = subprocess.run([
                "ffmpeg", "-y", "-i", inp,
                "-ss", str(s + t0), "-t", str(e - s),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-threads", "1", "-c:a", "aac", "-b:a", "96k", seg_f
            ], capture_output=True, timeout=120)
            if r.returncode == 0 and os.path.exists(seg_f):
                seg_files.append(seg_f)

        if not seg_files: return None

        # Concat list
        list_f = str(UPLOAD / f"{jid}_list.txt")
        with open(list_f, "w") as f:
            for sf in seg_files:
                f.write(f"file '{sf}'\n")

        out_f = str(UPLOAD / f"{jid}_cut.mp4")
        r = subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_f,
            "-c", "copy", out_f
        ], capture_output=True, timeout=120)

        # Temizlik
        for sf in seg_files:
            try: os.remove(sf)
            except: pass
        try: os.remove(list_f)
        except: pass

        if r.returncode == 0 and os.path.exists(out_f):
            print(f"[{jid}] Silence cut: {len(segments)} segment birlestirildi")
            return out_f
        return None

    except Exception as e:
        print(f"silence_cut error: {e}")
        return None

# ── SRT YAZMA ─────────────────────────────────────

def write_srt(words, path, ai_subs):
    """Whisper kelimelerinden SRT formatı yaz — CapCut/Premiere uyumlu."""
    lines = []
    idx = 1
    group = 5  # Her satırda 5 kelime

    for i in range(0, len(words), group):
        g = words[i:i+group]
        if not g: continue
        t_s = g[0]["start"]
        t_e = g[-1]["end"] + 0.1
        text = " ".join(w["word"].strip() for w in g)
        lines.append(f"{idx}")
        lines.append(f"{ts_srt(t_s)} --> {ts_srt(t_e)}")
        lines.append(text)
        lines.append("")
        idx += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

# ── CAPCUT REHBERİ ────────────────────────────────

def _capcut_guide(ap, content, total_dur):
    """Kullanıcıya CapCut'ta ne yapacağını anlat."""
    video_flow = content.get("video_flow", [])
    edit_timing = content.get("edit_timing", [])
    guide = {
        "title": f"{ap['label']} — CapCut Edit Rehberi",
        "steps": [
            "1. Videoyu CapCut'a yükle",
            "2. SRT dosyasını 'Altyazı > Dosyadan İçe Aktar' ile yükle",
            f"3. Font: Bold/Kalın | Renk: Beyaz | Konum: Ekranın alt-ortası (safe zone)",
            f"4. Hook metni ({content.get('hook','')}) için: 0-{ap['hook_dur']}sn arası büyük text ekle",
        ],
        "zoom_timing": ap.get("zoom_plan", []),
        "cut_rule": ap.get("cut_notes", ""),
        "scene_by_scene": [
            f"Sahne {s.get('scene','?')} ({s.get('sec','?')}sn): {s.get('action','')} — '{s.get('text','')}'"
            for s in video_flow
        ],
        "highlight_words": ap.get("hi_words", []),
        "cta_timing": f"{max(3.0, total_dur-5):.0f}-{total_dur:.0f}sn: CTA göster — '{content.get('cta','')}'",
    }
    if edit_timing:
        guide["steps"].append("5. Zoom noktaları:")
        for et in edit_timing:
            guide["steps"].append(f"   • {et.get('sec','?')}. saniye: {et.get('action','')} — {et.get('note','')}")
    return guide

# ── FFMPEG YARDIMCILAR ─────────────────────────────

def _run_ff(jid, inp, out, t0, t1, vf, label, copy=False):
    cmd = ["ffmpeg", "-y"]
    if t0 > 0: cmd += ["-ss", str(t0)]
    cmd += ["-i", inp]
    if t1 > 0 and t1 > t0: cmd += ["-t", str(t1 - t0)]
    if vf: cmd += ["-vf", vf]
    if copy: cmd += ["-c", "copy"]
    else: cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                  "-threads", "1", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]
    cmd += [out]
    print(f"[{jid}] {label}...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 1000
    print(f"[{jid}] {label}: rc={r.returncode} ok={ok}")
    return ok

def _crop(fmt):
    if fmt == "9:16": return "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=720:1280"
    if fmt == "1:1":  return "crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,scale=720:720"
    if fmt == "16:9": return "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"
    return ""

def _vf(fmt, ass):
    parts = [p for p in [_crop(fmt), f"ass={ass}" if ass and os.path.exists(ass) else ""] if p]
    return ",".join(parts)

# ── ASS YAZAR ─────────────────────────────────────

def build_ass(jid, inp, words, subs, hook, cta, fmt, total, t0, ap):
    try:
        if fmt == "9:16":   pw, ph = 720, 1280
        elif fmt == "1:1":  pw, ph = 720, 720
        else:               pw, ph = 1280, 720

        fs_h = int(pw * ap["hook_sz"])
        fs_s = int(pw * ap["sub_sz"])
        fs_c = int(pw * 0.052)
        fs   = ap["fscale"]
        sub_mv = int(ph * 0.28)
        cta_mv = int(ph * 0.18)

        hc = ap["hook_c"]; h1 = ap["hi1"]; h2 = ap["hi2"]
        oc = ap["out"];    sh = ap["shd"]

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,{fs_h},{hc},&H00FFFFFF,{oc},{sh},-1,0,0,0,{fs},{fs},0.5,0,1,4,2,5,30,30,200,1
Style: Sub,Arial,{fs_s},&H00FFFFFF,&H00FFFFFF,{oc},{sh},-1,0,0,0,{fs},{fs},0,0,1,3,1,2,20,20,{sub_mv},1
Style: Hi1,Arial,{fs_s},{h1},&H00FFFFFF,{oc},{sh},-1,0,0,0,{int(fs*1.08)},{int(fs*1.08)},0,0,1,4,1,2,20,20,{sub_mv},1
Style: CTA,Arial,{fs_c},&H00FFFFFF,&H00FFFFFF,{h1},&H99001050,-1,0,0,0,{fs},{fs},1,0,1,0,0,2,20,20,{cta_mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        hd = ap["hook_dur"]
        sn = ap["sub_n"]

        if hook:
            ws = hook.split()
            fh = (f"{{\\b1}}{' '.join(ws[:len(ws)//2])}\\N{{\\b1}}{' '.join(ws[len(ws)//2:])}"
                  if len(ws) > 4 else f"{{\\b1}}{hook}")
            lines.append(f"Dialogue: 0,{ts_ass(0)},{ts_ass(hd)},Hook,,0,0,0,,{{\\an5}}{fh}")

        if words:
            adj = [{**w, "start": w["start"] - t0, "end": w["end"] - t0}
                   for w in words if hd + 0.2 <= w["start"] - t0 <= total - 5.5]
            for i in range(0, len(adj), sn):
                g = adj[i:i+sn]
                if not g: continue
                ts_ = g[0]["start"]; te_ = min(g[-1]["end"] + 0.2, total - 5.5)
                if ts_ >= te_: continue
                parts = []
                for w in g:
                    wd = clean(w["word"].strip())
                    if not wd: continue
                    is_hl = w.get("highlight", False) or (wd.upper() == wd and len(wd) > 2)
                    parts.append(f"{{\\rHi1}}{{\\b1}}{wd}{{\\r}}" if is_hl else wd)
                if parts:
                    lines.append(f"Dialogue: 0,{ts_ass(ts_)},{ts_ass(te_)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")
        elif subs:
            avail = total - hd - 0.2 - 5.5
            if avail > 0:
                seg = avail / len(subs)
                for i, sub in enumerate(subs):
                    ts_ = hd + 0.2 + i * seg
                    te_ = min(ts_ + seg - 0.15, total - 5.5)
                    if ts_ >= te_: continue
                    hl = set(x.upper().strip() for x in sub.get("highlight", []))
                    ws = clean(sub.get("text", "")).split()
                    if not ws: continue
                    if len(ws) > 5:
                        mid = len(ws) // 2
                        for li, wl in enumerate([ws[:mid], ws[mid:]]):
                            lt = ts_ + li * (seg / 2); le = lt + seg / 2 - 0.15
                            parts = _sw(wl, hl)
                            lines.append(f"Dialogue: 0,{ts_ass(lt)},{ts_ass(le)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")
                    else:
                        lines.append(f"Dialogue: 0,{ts_ass(ts_)},{ts_ass(te_)},Sub,,0,0,0,,{{\\an2}}{' '.join(_sw(ws, hl))}")

        if cta:
            cs = max(hd + 0.5, total - 5.0)
            lines.append(f"Dialogue: 0,{ts_ass(cs)},{ts_ass(total)},CTA,,0,0,0,,{{\\an2}}{{\\b1}}{cta}")

        path = inp.replace("_in", "_sub").replace(Path(inp).suffix, ".ass")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(lines))
        print(f"[{jid}] ASS: {len(lines)} satir ({ap['label']})")
        return path
    except Exception as e:
        print(f"[{jid}] build_ass error: {e}")
        return None

def _sw(words, hl_set):
    parts = []
    for w in words:
        wc = re.sub(r"[^\wğüşöçıĞÜŞÖÇİ]", "", w.upper())
        if wc in hl_set or (w.upper() == w and len(w) > 2):
            parts.append(f"{{\\rHi1}}{{\\b1}}{w}{{\\r}}")
        else:
            parts.append(w)
    return parts

# ── STATUS / DOWNLOAD ─────────────────────────────

@app.route("/api/status/<jid>")
def status(jid):
    job = JOBS.get(jid)
    if not job: return jsonify({"error": "Bulunamadi"}), 404
    return jsonify(job)

@app.route("/api/download/<jid>")
def download(jid):
    p = OUTPUT / f"{jid}_out.mp4"
    if not p.exists(): return jsonify({"error": "Dosya yok"}), 404
    return send_file(str(p), mimetype="video/mp4",
                     as_attachment=True, download_name=f"conteniq-{jid}.mp4")

@app.route("/api/debug/<jid>")
def debug_job(jid):
    job = JOBS.get(jid, {})
    out_p = OUTPUT / f"{jid}_out.mp4"
    has_srt = (OUTPUT / f"{jid}.srt").exists()
    has_plan = (OUTPUT / f"{jid}_plan.json").exists()
    return jsonify({
        "job": job,
        "output_exists": out_p.exists(),
        "output_size_mb": round(out_p.stat().st_size / 1024 / 1024, 2) if out_p.exists() else 0,
        "has_srt": has_srt,
        "has_edit_plan": has_plan,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
