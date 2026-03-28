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
    for c in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.exists(c): return c
    try:
        r = subprocess.run(["fc-list",":style=Bold","--format=%{file}\n"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().splitlines():
            f = line.strip()
            if f and os.path.exists(f): return f
    except: pass
    return None

FONT_PATH = find_font()
print(f"[startup] Font: {FONT_PATH}")

def clean(text):
    result = []
    for char in text:
        cp = ord(char)
        if (0x1F000 <= cp <= 0x1FFFF or 0x2600 <= cp <= 0x27BF or
            0xFE00 <= cp <= 0xFE0F or cp == 0x200D or cp == 0xFEFF):
            continue
        result.append(char)
    return re.sub(r'  +', ' ', ''.join(result)).strip()

def ts(sec):
    sec = max(0, float(sec))
    h=int(sec//3600); m=int((sec%3600)//60); s=int(sec%60); cs=int((sec%1)*100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

# ════════════════════════════════════════════════════
# İÇERİK TİPİ = EDİT MOTORU
# Her angle farklı bir video karakteri üretir
# ════════════════════════════════════════════════════

ANGLE_PROFILES = {
    "firsat": {
        "label": "Fırsat Kaçırma",
        # Renk: kırmızı+sarı — aciliyet
        "hook_color":   "&H000000FF",   # kırmızı (ASS BGR)
        "hi_primary":   "&H0055CCFF",   # sarı
        "hi_secondary": "&H000080FF",   # turuncu
        "outline":      "&H00000000",
        "shadow":       "&HCC000000",
        "font_scale":   115,
        "sub_size_ratio": 0.068,
        "hook_size_ratio": 0.088,
        # Zamanlama: agresif, hızlı
        "hook_dur":     2.5,           # hook kısa ve güçlü
        "sub_words":    3,             # az kelime, hızlı okunur
        "sub_gap":      0.1,           # kelimeler arası boşluk az
        # Zoom effect ffmpeg
        "zoom_filter":  "zoompan=z='if(lte(zoom,1.0),1.04,max(1.001,zoom-0.002))':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=720x1280:fps=30",
        "use_zoom":     False,         # RAM sorunu için kapalı
        # AI prompt karakteri
        "prompt_tone":  "ACİL ve SERT. Acele ettir. 'Son fırsat', 'kaçırma', 'şimdi' kelimelerini kullan. Hook maksimum 8 kelime.",
        "cta_style":    "urgent",      # 'Hemen DM at' gibi
    },
    "sir": {
        "label": "Sır / İçeriden Bilgi",
        "hook_color":   "&H00FF00FF",   # mor/purple
        "hi_primary":   "&H00FF00FF",
        "hi_secondary": "&H0055CCFF",
        "outline":      "&H00000000",
        "shadow":       "&H88000000",
        "font_scale":   100,
        "sub_size_ratio": 0.058,
        "hook_size_ratio": 0.078,
        "hook_dur":     3.5,
        "sub_words":    5,
        "sub_gap":      0.15,
        "use_zoom":     False,
        "prompt_tone":  "GİZEMLİ ve merak uyandırıcı. 'Kimse bilmiyor', 'gizli', 'içeriden' kelimelerini kullan. Yavaş ve emin bir ton.",
        "cta_style":    "curious",
    },
    "hata": {
        "label": "Yaygın Hata",
        "hook_color":   "&H000000FF",   # kırmızı
        "hi_primary":   "&H0055CCFF",   # sarı (YANLIŞ kelimesi)
        "hi_secondary": "&H0000FF00",   # yeşil (DOGRU kelimesi)
        "outline":      "&H00000000",
        "shadow":       "&HCC000000",
        "font_scale":   108,
        "sub_size_ratio": 0.062,
        "hook_size_ratio": 0.082,
        "hook_dur":     3.0,
        "sub_words":    4,
        "sub_gap":      0.12,
        "use_zoom":     False,
        "prompt_tone":  "UYARICI ve net. 'Hata', 'yanlış', 'dikkat' kelimelerini kullan. İzleyicide 'ben de mi yapıyorum?' hissi yarat.",
        "cta_style":    "help",
    },
    "kanit": {
        "label": "Sosyal Kanıt",
        "hook_color":   "&H0000FF00",   # yeşil — güven
        "hi_primary":   "&H0000FF00",
        "hi_secondary": "&H0055CCFF",
        "outline":      "&H00000000",
        "shadow":       "&H88000000",
        "font_scale":   105,
        "sub_size_ratio": 0.060,
        "hook_size_ratio": 0.080,
        "hook_dur":     3.0,
        "sub_words":    5,
        "sub_gap":      0.15,
        "use_zoom":     False,
        "prompt_tone":  "GÜVENİLİR ve samimi. Gerçek müşteri hikayesi, rakam, sonuç. 'Müşterim', 'kanıtlandı', 'gerçek sonuç' kullan.",
        "cta_style":    "trust",
    },
    "karsilastirma": {
        "label": "Karşılaştırma",
        "hook_color":   "&H00FFFFFF",
        "hi_primary":   "&H0000FF00",   # yeşil = iyi
        "hi_secondary": "&H000000FF",   # kırmızı = kötü
        "outline":      "&H00000000",
        "shadow":       "&HAA000000",
        "font_scale":   108,
        "sub_size_ratio": 0.060,
        "hook_size_ratio": 0.080,
        "hook_dur":     3.0,
        "sub_words":    4,
        "sub_gap":      0.12,
        "use_zoom":     False,
        "prompt_tone":  "KONTRAST ve net. 'VS', 'fark', 'hangisi daha iyi'. İki seçenek sun, birini öner.",
        "cta_style":    "choice",
    },
    "bilgi": {
        "label": "Bilgi / Eğitim",
        "hook_color":   "&H00FFFFFF",
        "hi_primary":   "&H005CCCFF",   # açık mavi
        "hi_secondary": "&H0055CCFF",
        "outline":      "&H00000000",
        "shadow":       "&H88000000",
        "font_scale":   100,
        "sub_size_ratio": 0.056,
        "hook_size_ratio": 0.076,
        "hook_dur":     3.5,
        "sub_words":    6,
        "sub_gap":      0.18,
        "use_zoom":     False,
        "prompt_tone":  "BİLGİLENDİRİCİ ve güvenilir. Rakam, adım, liste formatı kullan. Sade ve net.",
        "cta_style":    "learn",
    },
    "duygusal": {
        "label": "Duygusal Bağ",
        "hook_color":   "&H00FF8080",   # açık pembe
        "hi_primary":   "&H00FF8080",
        "hi_secondary": "&H0055CCFF",
        "outline":      "&H00000000",
        "shadow":       "&H88000000",
        "font_scale":   100,
        "sub_size_ratio": 0.056,
        "hook_size_ratio": 0.076,
        "hook_dur":     4.0,           # yavaş, etki bırakır
        "sub_words":    5,
        "sub_gap":      0.20,          # kelimeler arası nefes var
        "use_zoom":     False,
        "prompt_tone":  "DUYGUSAL ve samimi. Kişisel hikaye, empati, 'ben de yaşadım' hissi. Yavaş ve derin.",
        "cta_style":    "connect",
    },
}

CTA_STYLES = {
    "urgent":  "Hemen DM at — gecikme",
    "curious": "DM yaz — sana anlatayin",
    "help":    "DM at — dogru yolu goster",
    "trust":   "DM at — senin icin bakalim",
    "choice":  "DM at — en iyisini sec",
    "learn":   "Takip et — her gun paylasiyorum",
    "connect": "DM yaz — seninle konusalim",
}

def get_angle_profile(angle_str):
    a = (angle_str or "").lower()
    for key in ANGLE_PROFILES:
        if key in a: return ANGLE_PROFILES[key]
    # fuzzy match
    mapping = {
        "firsat":"firsat","kaçırma":"firsat","urgency":"firsat",
        "sır":"sir","gizli":"sir","secret":"sir",
        "hata":"hata","yanlis":"hata","error":"hata",
        "kanit":"kanit","sosyal":"kanit","proof":"kanit",
        "karsi":"karsilastirma","vs":"karsilastirma",
        "bilgi":"bilgi","egitim":"bilgi","info":"bilgi",
        "duygu":"duygusal","emotion":"duygusal",
    }
    for k, v in mapping.items():
        if k in a: return ANGLE_PROFILES[v]
    return ANGLE_PROFILES.get("bilgi")  # default: sakin

# ── ROUTES ──────────────────────────────────────────

@app.route("/")
def index(): return send_from_directory("static", "index.html")

@app.route("/api/health")
def health():
    try:
        r = subprocess.run(["ffmpeg","-version"], capture_output=True, timeout=5)
        ffok = r.returncode == 0
    except: ffok = False
    return jsonify({"ok":True,"ffmpeg":ffok,"font":FONT_PATH,
                    "angles": list(ANGLE_PROFILES.keys())})

@app.route("/api/generate", methods=["POST"])
def generate():
    import requests as req
    data = request.json or {}
    api_key = request.headers.get("X-Api-Key","")
    if not api_key: return jsonify({"error":"API key gerekli"}), 400

    sector   = data.get("sector","Genel")
    city     = data.get("city","Türkiye")
    goal     = data.get("goal","Müşteri")
    audience = data.get("audience","genel")
    detail   = data.get("detail","")

    # Her angle için ayrı prompt tonu
    angle_instructions = ""
    for key, p in ANGLE_PROFILES.items():
        angle_instructions += f"\n- {p['label']}: {p['prompt_tone']}"

    prompt = f"""Sen Türkiye pazarında uzman sosyal medya stratejisti ve Reels içerik uzmanısın.

Bilgiler:
- Sektör: {sector}
- Şehir: {city}
- Hedef: {goal}
- Hedef Kitle: {audience}
{f"- Detay: {detail}" if detail else ""}

7 farklı Reels içeriği üret. Her içerik farklı bir psikolojik tetikleyici kullanmalı.
İçerik tipleri ve tonları:{angle_instructions}

KURALLAR:
1. Hook ve CTA metinlerinde KESİNLİKLE EMOJI KULLANMA
2. Her içerik kendi tonuna SADIK olsun — fırsat acil, sır gizemli, duygusal samimi
3. highlight listesi: o angle'a uygun vurgu kelimeleri (max 3)
4. cta: o angle'ın CTA stiline uygun

SADECE JSON:
{{"meta":{{"sector":"{sector}","city":"{city}","goal":"{goal}"}},"contents":[{{"num":1,"angle":"firsat","hook":"max 10 kelime hook","video_flow":[{{"scene":1,"desc":"Hook","duration":"0-3sn"}},{{"scene":2,"desc":"Problem","duration":"3-8sn"}},{{"scene":3,"desc":"Deger","duration":"8-15sn"}},{{"scene":4,"desc":"Kanit","duration":"15-22sn"}},{{"scene":5,"desc":"CTA","duration":"22-27sn"}}],"script":"max 100 kelime","subtitles":[{{"text":"altyazi 1","highlight":["VURGU1","VURGU2"]}},{{"text":"altyazi 2","highlight":["VURGU3"]}}],"trigger":"mesaj","cta":"tek aksiyon","caption":"2-3 cumle","hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5"]}}]}}

angle degerleri: firsat, sir, hata, kanit, karsilastirma, bilgi, duygusal
7 icerik uret, her biri farkli angle. Sektore ozel, Turkce."""

    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":4000,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=90
        )
        d = r.json()
        if "error" in d: return jsonify({"error":d["error"]["message"]}), 400
        raw = re.sub(r"```json|```","","".join(x["text"] for x in d["content"] if x.get("type")=="text")).strip()
        result = json.loads(raw)
        # Her içeriğe CTA stilini ekle
        for c in result.get("contents",[]):
            ap = get_angle_profile(c.get("angle",""))
            if not c.get("cta") or c["cta"] == "tek aksiyon":
                c["cta"] = CTA_STYLES.get(ap.get("cta_style","help"),"DM yaz")
        return jsonify(result)
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/process", methods=["POST"])
def process_video():
    api_key = request.headers.get("X-Api-Key","")
    if "video" not in request.files: return jsonify({"error":"Video gerekli"}), 400

    vf          = request.files["video"]
    content_raw = request.form.get("content","{}")
    fmt         = request.form.get("format","9:16")
    t0          = float(request.form.get("trim_start",0) or 0)
    t1          = float(request.form.get("trim_end",0) or 0)
    use_wh      = request.form.get("use_whisper","true") == "true"

    try: content = json.loads(content_raw)
    except: content = {}

    jid = str(uuid.uuid4())[:8]
    ext = Path(vf.filename).suffix or ".mp4"
    inp = str(UPLOAD / f"{jid}_in{ext}")
    vf.save(inp)

    JOBS[jid] = {"status":"queued","progress":0,"msg":"Baslatiliyor..."}
    t = threading.Thread(target=run_job,
        args=(jid, inp, api_key, content, fmt, t0, t1, use_wh))
    t.daemon = True; t.start()
    return jsonify({"job_id":jid})

def upd(jid, p, msg, status="running"):
    JOBS[jid] = {"status":status,"progress":p,"msg":msg}
    print(f"[{jid}] {p}% {msg}")

def run_job(jid, inp, api_key, content, fmt, t0, t1, use_wh):
    try:
        import requests as req

        upd(jid, 5, "Video analiz ediliyor...")
        probe = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json","-show_streams","-show_format",inp],
            capture_output=True, text=True, timeout=30
        )
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        vs = next((s for s in info["streams"] if s["codec_type"]=="video"),{})
        vw=int(vs.get("width",1920)); vh=int(vs.get("height",1080))
        upd(jid, 10, f"Video: {vw}x{vh}, {duration:.1f}s")

        end_t = t1 if (t1 > t0 and t1 > 0) else duration
        total_dur = end_t - t0

        # Angle profilini al — bu video'nun karakterini belirler
        angle = content.get("angle","bilgi")
        profile = get_angle_profile(angle)
        upd(jid, 12, f"Angle: {profile['label']} | Stil: {profile['prompt_tone'][:40]}...")

        # Whisper
        whisper_words = []
        if use_wh and api_key:
            upd(jid, 15, "Whisper: ses analiz ediliyor...")
            try:
                aud = inp.replace("_in","_aud") + ".mp3"
                subprocess.run(
                    ["ffmpeg","-y","-i",inp,"-vn","-ar","16000","-ac","1","-b:a","64k",aud],
                    capture_output=True, check=True, timeout=120
                )
                upd(jid, 22, "Whisper: transkript aliniyor...")
                with open(aud,"rb") as f:
                    wr = req.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization":f"Bearer {api_key}"},
                        files={"file":("audio.mp3",f,"audio/mp3")},
                        data={"model":"whisper-1","language":"tr",
                              "response_format":"verbose_json",
                              "timestamp_granularities[]":"word"},
                        timeout=120
                    )
                try: os.remove(aud)
                except: pass
                if wr.status_code == 200:
                    wd = wr.json()
                    whisper_words = wd.get("words",[])
                    upd(jid, 32, f"Whisper: {len(whisper_words)} kelime OK")
                    # AI vurgu seçimi — angle'a göre farklı kelimeler seçer
                    if whisper_words:
                        whisper_words = ai_highlights(whisper_words, content, profile, api_key, req)
                else:
                    upd(jid, 32, f"Whisper hata {wr.status_code}")
            except Exception as e:
                upd(jid, 32, f"Whisper basarisiz: {e}")

        # ASS — angle profiline göre tamamen farklı görünüm
        upd(jid, 36, f"Altyazilar hazirlaniyor ({profile['label']})...")
        hook_text = clean(content.get("hook",""))
        cta_text  = clean(content.get("cta",""))
        subs      = content.get("subtitles",[])

        ass_path = build_ass(jid, inp, whisper_words, subs,
                             hook_text, cta_text, fmt, total_dur, t0, profile)

        # ffmpeg
        upd(jid, 45, "ffmpeg ile video isleniyor...")
        out_p = str(OUTPUT / f"{jid}_out.mp4")

        vf_parts = []
        if fmt == "9:16":
            vf_parts.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=720:1280")
        elif fmt == "1:1":
            vf_parts.append("crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,scale=720:720")
        elif fmt == "16:9":
            vf_parts.append("scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black")

        if ass_path and os.path.exists(ass_path):
            vf_parts.append(f"ass={ass_path}")

        cmd = ["ffmpeg","-y"]
        if t0 > 0: cmd += ["-ss", str(t0)]
        cmd += ["-i", inp]
        if t1 > 0 and t1 > t0: cmd += ["-t", str(t1-t0)]
        if vf_parts: cmd += ["-vf", ",".join(vf_parts)]
        cmd += ["-c:v","libx264","-preset","ultrafast","-crf","26",
                "-threads","1","-c:a","aac","-b:a","96k",
                "-movflags","+faststart", out_p]

        print(f"[{jid}] CMD: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(f"[{jid}] returncode: {result.returncode}")

        if result.returncode != 0:
            # Fallback
            upd(jid, 70, "ASS hatali — altyazisiz deneniyor...")
            cmd2 = ["ffmpeg","-y"]
            if t0 > 0: cmd2 += ["-ss", str(t0)]
            cmd2 += ["-i", inp]
            if t1 > 0 and t1 > t0: cmd2 += ["-t", str(t1-t0)]
            vf2 = [p for p in vf_parts if not p.startswith("ass=")]
            if vf2: cmd2 += ["-vf", ",".join(vf2)]
            cmd2 += ["-c:v","libx264","-preset","ultrafast","-crf","26",
                     "-threads","1","-c:a","aac","-b:a","96k",
                     "-movflags","+faststart", out_p]
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
            if r2.returncode != 0:
                raise Exception(f"ffmpeg basarisiz rc={r2.returncode}")
            upd(jid, 90, "Altyazisiz versiyon tamamlandi")
        else:
            upd(jid, 90, f"{profile['label']} stili uygulandı")

        size_mb = os.path.getsize(out_p)/1024/1024
        upd(jid, 100, f"Tamamlandi! {size_mb:.1f}MB", "done")

        for p in [inp, ass_path]:
            try:
                if p and os.path.exists(p): os.remove(p)
            except: pass

    except Exception as e:
        upd(jid, 0, f"Hata: {str(e)[:400]}", "error")
        print(f"[{jid}] EXCEPTION: {e}")

def ai_highlights(words, content, profile, api_key, req):
    """Angle'a göre farklı kelimeler vurgular.
    Fırsat: aciliyet kelimeleri | Sır: gizemli kelimeler | Hata: yanlış/doğru"""
    try:
        full_text = " ".join(w["word"] for w in words)
        angle_label = profile.get("label","")
        prompt_tone = profile.get("prompt_tone","")
        hook = clean(content.get("hook",""))

        prompt = f"""Video transkripti: "{full_text[:400]}"
Hook: "{hook}"
İçerik tipi: {angle_label}
Bu tip için ton: {prompt_tone}

Bu içerik tipine göre hangi kelimeler vurgulanmalı?
- Fırsat için: SON, KAÇIRMA, ŞİMDİ, HEMEN gibi aciliyet kelimeleri
- Sır için: GİZLİ, KIMSE, BİLMİYOR gibi merak kelimeleri  
- Hata için: YANLIŞ, HATA, DİKKAT kelimeleri
- Kanıt için: MÜŞTERI, SONUÇ, GERÇEK, RAKAM kelimeleri

SADECE JSON: {{"highlights": ["kelime1","kelime2","kelime3"]}}"""

        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":200,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=15
        )
        d = r.json()
        if "error" in d: raise Exception(d["error"]["message"])
        raw = re.sub(r"```json|```","","".join(x["text"] for x in d["content"] if x.get("type")=="text")).strip()
        hl = set(w.upper() for w in json.loads(raw).get("highlights",[]))
        for w in words:
            wc = re.sub(r"[^\wğüşöçıĞÜŞÖÇİ]","",w["word"]).upper()
            w["highlight"] = wc in hl
        return words
    except Exception as e:
        print(f"ai_highlights error: {e}")
        for w in words:
            w["highlight"] = w["word"].upper() == w["word"] and len(w["word"].strip()) > 2
        return words

def build_ass(jid, inp, whisper_words, subs, hook_text, cta_text,
              fmt, total_dur, t0, profile):
    try:
        if fmt == "9:16":   pw, ph = 720, 1280
        elif fmt == "1:1":  pw, ph = 720, 720
        else:               pw, ph = 1280, 720

        # Boyutlar — angle'a göre farklı
        fs_hook = int(pw * profile.get("hook_size_ratio", 0.082))
        fs_sub  = int(pw * profile.get("sub_size_ratio", 0.062))
        fs_cta  = int(pw * 0.052)
        fscale  = profile.get("font_scale", 105)

        # SAFE ZONE marjinleri (9:16 için):
        # Üst yasak: ~%18, Alt yasak: ~%27
        # Hook: %38-48 arası (güvenli orta)
        # Altyazı: %55-68 arası (güvenli alt-orta)
        # CTA: %72-80 (güvenli alt)
        hook_mv = int(ph * 0.42)   # Hook: safe zone ortası
        sub_mv  = int(ph * 0.30)   # Altyazı: \an2 ile alttan bu marjin
        cta_mv  = int(ph * 0.20)   # CTA: biraz daha aşağı

        hc  = profile.get("hook_color",  "&H00FFFFFF")
        hi1 = profile.get("hi_primary",  "&H0055CCFF")
        hi2 = profile.get("hi_secondary","&H0000FF00")
        oc  = profile.get("outline",     "&H00000000")
        sh  = profile.get("shadow",      "&HAA000000")

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,{fs_hook},{hc},&H00FFFFFF,{oc},{sh},-1,0,0,0,{fscale},{fscale},0.5,0,1,4,2,5,30,30,{hook_mv},1
Style: Sub,Arial,{fs_sub},&H00FFFFFF,&H00FFFFFF,{oc},{sh},-1,0,0,0,{fscale},{fscale},0,0,1,3,1,2,20,20,{sub_mv},1
Style: Hi1,Arial,{fs_sub},{hi1},&H00FFFFFF,{oc},{sh},-1,0,0,0,{int(fscale*1.08)},{int(fscale*1.08)},0,0,1,3,1,2,20,20,{sub_mv},1
Style: Hi2,Arial,{fs_sub},{hi2},&H00FFFFFF,{oc},{sh},-1,0,0,0,{int(fscale*1.12)},{int(fscale*1.12)},0,0,1,3,1,2,20,20,{sub_mv},1
Style: CTA,Arial,{fs_cta},&H00000000,&H00FFFFFF,{hi1},&H99000000,-1,0,0,0,{fscale},{fscale},1,0,1,0,0,2,20,20,{cta_mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        hook_dur = profile.get("hook_dur", 3.0)

        # ── HOOK ────────────────────────────────────
        if hook_text:
            h = clean(hook_text)
            words = h.split()
            # Uzun hook → 2 satır
            if len(words) > 4:
                mid = len(words) // 2
                fmt_hook = f"{{\\b1}}{' '.join(words[:mid])}\\N{{\\b1}}{' '.join(words[mid:])}"
            else:
                fmt_hook = f"{{\\b1}}{h}"
            # an5 = tam orta (yatay+dikey center)
            lines.append(f"Dialogue: 0,{ts(0)},{ts(hook_dur)},Hook,,0,0,0,,{{\\an5}}{fmt_hook}")

        # ── ALTYAZILAR ───────────────────────────────
        sub_words = profile.get("sub_words", 4)
        sub_gap   = profile.get("sub_gap", 0.12)

        if whisper_words:
            adj = []
            for w in whisper_words:
                s = w["start"] - t0
                e = w["end"] - t0
                if s >= hook_dur + 0.3 and s <= total_dur - 5.5:
                    adj.append({**w, "start":s, "end":e})

            for i in range(0, len(adj), sub_words):
                g = adj[i:i+sub_words]
                if not g: continue
                t_s = g[0]["start"]
                t_e = min(g[-1]["end"] + 0.2, total_dur - 5.5)
                if t_s >= t_e: continue

                parts = []
                for w in g:
                    word = clean(w["word"].strip())
                    if not word: continue
                    is_hl = w.get("highlight", False)
                    if not is_hl and word.upper() == word and len(word) > 2:
                        is_hl = True
                    if is_hl:
                        parts.append(f"{{\\rHi1}}{{\\b1}}{word}{{\\r}}")
                    else:
                        parts.append(word)
                if parts:
                    # an2 = alt-orta
                    lines.append(f"Dialogue: 0,{ts(t_s)},{ts(t_e)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")
        else:
            available = total_dur - hook_dur - 0.3 - 5.5
            if available > 0 and subs:
                seg = available / len(subs)
                for i, sub in enumerate(subs):
                    t_s = hook_dur + 0.3 + i * seg
                    t_e = min(t_s + seg - sub_gap, total_dur - 5.5)
                    if t_s >= t_e: continue

                    hl_set = set(x.upper().strip() for x in sub.get("highlight",[]))
                    words = clean(sub.get("text","")).split()
                    if not words: continue

                    # 2 satır max
                    if len(words) > 5:
                        mid = len(words) // 2
                        for li, wlist in enumerate([words[:mid], words[mid:]]):
                            lt_s = t_s + li * (seg/2)
                            lt_e = lt_s + seg/2 - sub_gap
                            parts = _style_words(wlist, hl_set)
                            lines.append(f"Dialogue: 0,{ts(lt_s)},{ts(lt_e)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")
                    else:
                        parts = _style_words(words, hl_set)
                        lines.append(f"Dialogue: 0,{ts(t_s)},{ts(t_e)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")

        # ── CTA ─────────────────────────────────────
        if cta_text:
            c = clean(cta_text)
            cta_start = max(hook_dur + 0.5, total_dur - 5.0)
            lines.append(f"Dialogue: 0,{ts(cta_start)},{ts(total_dur)},CTA,,0,0,0,,{{\\an2}}{{\\b1}}{c}")

        ass_path = inp.replace("_in","_sub").replace(Path(inp).suffix,".ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(lines))

        print(f"[{jid}] ASS: {len(lines)} satir ({profile['label']})")
        return ass_path

    except Exception as e:
        print(f"[{jid}] build_ass error: {e}")
        return None

def _style_words(words, hl_set):
    parts = []
    for w in words:
        wc = re.sub(r"[^\wğüşöçıĞÜŞÖÇİ]","",w.upper())
        if wc in hl_set or (w.upper() == w and len(w) > 2):
            parts.append(f"{{\\rHi1}}{{\\b1}}{w}{{\\r}}")
        else:
            parts.append(w)
    return parts

# ── STATUS / DOWNLOAD ────────────────────────────────

@app.route("/api/status/<jid>")
def status(jid):
    job = JOBS.get(jid)
    if not job: return jsonify({"error":"Bulunamadi"}), 404
    return jsonify(job)

@app.route("/api/download/<jid>")
def download(jid):
    p = OUTPUT / f"{jid}_out.mp4"
    if not p.exists(): return jsonify({"error":"Dosya yok"}), 404
    return send_file(str(p), mimetype="video/mp4",
                     as_attachment=True, download_name=f"conteniq-{jid}.mp4")

@app.route("/api/debug/<jid>")
def debug_job(jid):
    job = JOBS.get(jid,{})
    out_p = OUTPUT / f"{jid}_out.mp4"
    return jsonify({
        "job": job,
        "output_exists": out_p.exists(),
        "output_size_mb": round(out_p.stat().st_size/1024/1024,2) if out_p.exists() else 0,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
