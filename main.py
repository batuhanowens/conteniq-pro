import os, uuid, json, subprocess, threading, re, math
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
# EDİT MOTOR PROFİLLERİ
# Her angle = farklı edit davranışı
# ════════════════════════════════════════════════════

ANGLE_PROFILES = {
    "firsat": {
        "label": "Fırsat Kaçırma",
        "hook_color": "&H000000FF", "hi1": "&H0055CCFF", "hi2": "&H000080FF",
        "outline": "&H00000000", "shadow": "&HCC000000",
        "font_scale": 115, "sub_size": 0.068, "hook_size": 0.090,
        "hook_dur": 2.5,
        # Edit davranışı
        "cut_interval": 1.5,      # her 1.5 sn cut
        "silence_cut": True,       # sessizlikleri kes
        "zoom_factor": 1.06,       # %6 zoom
        "zoom_interval": 3.0,      # her 3sn bir zoom
        "sub_words": 3,            # hızlı okunur
        "rhythm": "fast",          # baş hızlı, son hızlı
        "prompt_tone": "ACİL. 'SON', 'KAÇIRMA', 'HEMEN' kelimelerini kullan. Max 8 kelime hook.",
        "cta": "Hemen DM at — gecikme",
    },
    "sir": {
        "label": "Sır",
        "hook_color": "&H00FF00FF", "hi1": "&H00FF00FF", "hi2": "&H0055CCFF",
        "outline": "&H00000000", "shadow": "&H88000000",
        "font_scale": 100, "sub_size": 0.058, "hook_size": 0.078,
        "hook_dur": 3.5,
        "cut_interval": 2.5, "silence_cut": False,
        "zoom_factor": 1.03, "zoom_interval": 5.0,
        "sub_words": 5, "rhythm": "slow_start",
        "prompt_tone": "GİZEMLİ. 'Kimse bilmiyor', 'gizli', 'ilk kez paylaşıyorum' kullan.",
        "cta": "DM yaz — anlatayin",
    },
    "hata": {
        "label": "Yaygın Hata",
        "hook_color": "&H000000FF", "hi1": "&H0055CCFF", "hi2": "&H0000FF00",
        "outline": "&H00000000", "shadow": "&HCC000000",
        "font_scale": 108, "sub_size": 0.062, "hook_size": 0.084,
        "hook_dur": 3.0,
        "cut_interval": 2.0, "silence_cut": True,
        "zoom_factor": 1.05, "zoom_interval": 3.5,
        "sub_words": 4, "rhythm": "medium",
        "prompt_tone": "UYARICI. 'Hata', 'yanlış', 'dikkat et' kullan. YANLIŞ=sarı, DOĞRU=yeşil.",
        "cta": "DM at — dogru yolu goster",
    },
    "kanit": {
        "label": "Sosyal Kanıt",
        "hook_color": "&H0000FF00", "hi1": "&H0000FF00", "hi2": "&H0055CCFF",
        "outline": "&H00000000", "shadow": "&H88000000",
        "font_scale": 105, "sub_size": 0.060, "hook_size": 0.080,
        "hook_dur": 3.0,
        "cut_interval": 2.5, "silence_cut": False,
        "zoom_factor": 1.03, "zoom_interval": 4.0,
        "sub_words": 5, "rhythm": "steady",
        "prompt_tone": "GÜVENİLİR. Rakam, müşteri, sonuç. 'Kanıtlandı', 'gerçek' kullan.",
        "cta": "DM at — senin icin bakalim",
    },
    "karsilastirma": {
        "label": "Karşılaştırma",
        "hook_color": "&H00FFFFFF", "hi1": "&H0000FF00", "hi2": "&H000000FF",
        "outline": "&H00000000", "shadow": "&HAA000000",
        "font_scale": 108, "sub_size": 0.060, "hook_size": 0.082,
        "hook_dur": 3.0,
        "cut_interval": 2.0, "silence_cut": True,
        "zoom_factor": 1.04, "zoom_interval": 3.5,
        "sub_words": 4, "rhythm": "medium",
        "prompt_tone": "KONTRAST. 'VS', 'karşılaştır', iki seçenek. Yeşil=iyi, Kırmızı=kötü.",
        "cta": "DM at — en iyisini sec",
    },
    "bilgi": {
        "label": "Bilgi",
        "hook_color": "&H00FFFFFF", "hi1": "&H005CCCFF", "hi2": "&H0055CCFF",
        "outline": "&H00000000", "shadow": "&H88000000",
        "font_scale": 100, "sub_size": 0.056, "hook_size": 0.076,
        "hook_dur": 3.5,
        "cut_interval": 3.0, "silence_cut": False,
        "zoom_factor": 1.02, "zoom_interval": 6.0,
        "sub_words": 6, "rhythm": "steady",
        "prompt_tone": "BİLGİLENDİRİCİ. Adım, rakam, liste. Sade ve net.",
        "cta": "Takip et — her gun paylasiyorum",
    },
    "duygusal": {
        "label": "Duygusal",
        "hook_color": "&H00FF8080", "hi1": "&H00FF8080", "hi2": "&H0055CCFF",
        "outline": "&H00000000", "shadow": "&H88000000",
        "font_scale": 100, "sub_size": 0.056, "hook_size": 0.076,
        "hook_dur": 4.0,
        "cut_interval": 3.5, "silence_cut": False,
        "zoom_factor": 1.02, "zoom_interval": 7.0,
        "sub_words": 5, "rhythm": "slow",
        "prompt_tone": "DUYGUSAL. Kişisel hikaye, empati. Yavaş ve derin ton.",
        "cta": "DM yaz — seninle konusalim",
    },
}

def get_profile(angle_str):
    a = (angle_str or "").lower()
    for key in ANGLE_PROFILES:
        if key in a: return ANGLE_PROFILES[key]
    mapping = {"kaçırma":"firsat","firsat":"firsat","sır":"sir","gizli":"sir",
               "hata":"hata","yanlış":"hata","kanıt":"kanit","sosyal":"kanit",
               "karşı":"karsilastirma","karsi":"karsilastirma","bilgi":"bilgi",
               "duygu":"duygusal","duygusal":"duygusal"}
    for k,v in mapping.items():
        if k in a: return ANGLE_PROFILES[v]
    return ANGLE_PROFILES["bilgi"]

# ── ROUTES ──────────────────────────────────────────

@app.route("/")
def index(): return send_from_directory("static", "index.html")

@app.route("/api/health")
def health():
    try:
        r = subprocess.run(["ffmpeg","-version"], capture_output=True, timeout=5)
        ffok = r.returncode == 0
    except: ffok = False
    return jsonify({"ok":True,"ffmpeg":ffok,"font":FONT_PATH})

@app.route("/api/generate", methods=["POST"])
def generate():
    import requests as req
    data = request.json or {}
    api_key = request.headers.get("X-Api-Key","")
    if not api_key: return jsonify({"error":"API key gerekli"}), 400

    sector=data.get("sector","Genel"); city=data.get("city","Türkiye")
    goal=data.get("goal","Müşteri"); audience=data.get("audience","genel")
    detail=data.get("detail","")

    angle_descs = "\n".join(f"- {v['label']} (angle={k}): {v['prompt_tone']}" 
                             for k,v in ANGLE_PROFILES.items())

    prompt = f"""Sen Türkiye pazarında uzman sosyal medya stratejisti ve video edit uzmanısın.

Bilgiler:
- Sektör: {sector}
- Şehir: {city}
- Hedef: {goal}
- Hedef Kitle: {audience}
{f"- Detay: {detail}" if detail else ""}

7 farklı Reels içeriği üret. Her içerik farklı bir psikolojik tetikleyici ve edit stili:
{angle_descs}

KURALLAR:
1. Hook/CTA'da KESİNLİKLE EMOJI YOK
2. Her içerik kendi tonuna sadık olsun
3. highlight: o angle için en güçlü 2-3 kelime
4. angle değeri tam olarak şunlardan biri: firsat, sir, hata, kanit, karsilastirma, bilgi, duygusal

SADECE JSON:
{{"meta":{{"sector":"{sector}","city":"{city}","goal":"{goal}"}},"contents":[{{"num":1,"angle":"firsat","hook":"max 10 kelime","video_flow":[{{"scene":1,"desc":"Hook","duration":"0-3sn"}},{{"scene":2,"desc":"Problem","duration":"3-8sn"}},{{"scene":3,"desc":"Deger","duration":"8-15sn"}},{{"scene":4,"desc":"Kanit","duration":"15-22sn"}},{{"scene":5,"desc":"CTA","duration":"22-27sn"}}],"script":"max 100 kelime","subtitles":[{{"text":"altyazi 1","highlight":["KELIME1","KELIME2"]}},{{"text":"altyazi 2","highlight":["KELIME3"]}}],"trigger":"mesaj","cta":"tek aksiyon","caption":"2-3 cumle","hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5"]}}]}}
7 icerik uret. Sektore ozel, Turkce."""

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
        # CTA yoksa angle'dan al
        for c in result.get("contents",[]):
            p = get_profile(c.get("angle",""))
            if not c.get("cta") or "aksiyon" in c.get("cta",""):
                c["cta"] = p["cta"]
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

# ════════════════════════════════════════════════════
# CORE: EDİT KARAR MOTORU
# ════════════════════════════════════════════════════

def run_job(jid, inp, api_key, content, fmt, t0, t1, use_wh):
    try:
        import requests as req

        # 1. PROBE
        upd(jid, 5, "Video analiz ediliyor...")
        probe = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json","-show_streams","-show_format",inp],
            capture_output=True, text=True, timeout=30
        )
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        vs = next((s for s in info["streams"] if s["codec_type"]=="video"),{})
        vw=int(vs.get("width",1920)); vh=int(vs.get("height",1080))
        has_audio = any(s["codec_type"]=="audio" for s in info["streams"])
        upd(jid, 10, f"Video: {vw}x{vh}, {duration:.1f}s, ses={'var' if has_audio else 'yok'}")

        end_t = t1 if (t1 > t0 and t1 > 0) else duration
        total_dur = end_t - t0

        # Angle profili — bu her şeyi belirler
        angle = content.get("angle","bilgi")
        profile = get_profile(angle)
        upd(jid, 12, f"Edit profili: {profile['label']} | ritim={profile['rhythm']}")

        # 2. SILENCE DETECTION — sessiz kısımları tespit et
        silence_cuts = []
        if profile["silence_cut"] and has_audio and total_dur > 10:
            upd(jid, 14, "Sessizlikler tespit ediliyor...")
            silence_cuts = detect_silence(inp, t0, end_t, jid)
            upd(jid, 18, f"{len(silence_cuts)} sessiz bölge bulundu")

        # 3. WHISPER
        whisper_words = []
        highlight_times = []  # [(start, end, word)] — zoom yapılacak anlar
        if use_wh and api_key and has_audio:
            upd(jid, 20, "Whisper: ses analiz ediliyor...")
            try:
                aud = inp.replace("_in","_aud") + ".mp3"
                subprocess.run(
                    ["ffmpeg","-y","-i",inp,"-vn","-ar","16000","-ac","1","-b:a","64k",aud],
                    capture_output=True, check=True, timeout=120
                )
                upd(jid, 27, "Whisper: transkript aliniyor...")
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
                    upd(jid, 34, f"Whisper: {len(whisper_words)} kelime OK")
                    # AI: angle'a göre vurgu ve zoom noktaları
                    if whisper_words:
                        whisper_words, highlight_times = ai_edit_decisions(
                            whisper_words, content, profile, api_key, req, jid)
                else:
                    upd(jid, 34, f"Whisper hata {wr.status_code}")
            except Exception as e:
                upd(jid, 34, f"Whisper basarisiz: {e}")

        # 4. ASS — angle profiline göre farklı görünüm
        upd(jid, 36, f"Altyazilar olusturuluyor ({profile['label']})...")
        hook_text = clean(content.get("hook",""))
        cta_text  = clean(content.get("cta","") or profile["cta"])
        subs      = content.get("subtitles",[])

        ass_path = build_ass(jid, inp, whisper_words, subs,
                             hook_text, cta_text, fmt, total_dur, t0, profile)

        # 5. FFMPEG — edit kararlarını uygula
        upd(jid, 45, "ffmpeg ile video isleniyor...")
        out_p = str(OUTPUT / f"{jid}_out.mp4")

        # Video filter zinciri — angle'a göre farklı
        vf_chain = build_vf_chain(fmt, profile, highlight_times, silence_cuts,
                                   total_dur, t0, ass_path)

        cmd = ["ffmpeg","-y"]
        if t0 > 0: cmd += ["-ss", str(t0)]
        cmd += ["-i", inp]
        if t1 > 0 and t1 > t0: cmd += ["-t", str(t1-t0)]
        if vf_chain: cmd += ["-vf", vf_chain]
        cmd += ["-c:v","libx264","-preset","ultrafast","-crf","26",
                "-threads","1","-c:a","aac","-b:a","96k",
                "-movflags","+faststart", out_p]

        print(f"[{jid}] CMD: {' '.join(cmd[:8])}... vf={vf_chain[:80] if vf_chain else 'none'}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(f"[{jid}] returncode: {result.returncode}")

        if result.returncode != 0:
            err_lines = [l for l in result.stderr.splitlines()
                        if any(x in l for x in ["Error","error","Invalid","failed","ass"])]
            print(f"[{jid}] STDERR: {chr(10).join(err_lines[-5:])}")
            # Fallback — sadece crop + altyazı, zoom yok
            upd(jid, 70, "Zoom filtresi hatali — basit versiyon deneniyor...")
            simple_vf = build_simple_vf(fmt, ass_path)
            cmd2 = ["ffmpeg","-y"]
            if t0 > 0: cmd2 += ["-ss", str(t0)]
            cmd2 += ["-i", inp]
            if t1 > 0 and t1 > t0: cmd2 += ["-t", str(t1-t0)]
            if simple_vf: cmd2 += ["-vf", simple_vf]
            cmd2 += ["-c:v","libx264","-preset","ultrafast","-crf","26",
                     "-threads","1","-c:a","aac","-b:a","96k",
                     "-movflags","+faststart", out_p]
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
            if r2.returncode != 0:
                # Son çare — sadece crop
                cmd3 = ["ffmpeg","-y"]
                if t0 > 0: cmd3 += ["-ss", str(t0)]
                cmd3 += ["-i", inp]
                if t1 > 0 and t1 > t0: cmd3 += ["-t", str(t1-t0)]
                crop = get_crop_filter(fmt)
                if crop: cmd3 += ["-vf", crop]
                cmd3 += ["-c:v","libx264","-preset","ultrafast","-crf","26",
                         "-threads","1","-c:a","aac","-b:a","96k",
                         "-movflags","+faststart", out_p]
                r3 = subprocess.run(cmd3, capture_output=True, text=True, timeout=600)
                if r3.returncode != 0:
                    raise Exception(f"Tüm denemeler basarisiz rc={r3.returncode}")
                upd(jid, 90, "Sadece format donusumu yapildi")
            else:
                upd(jid, 90, "Altyazili versiyon tamamlandi")
        else:
            upd(jid, 90, f"{profile['label']} edit tamamlandi")

        size_mb = os.path.getsize(out_p)/1024/1024
        upd(jid, 100, f"Tamamlandi! {size_mb:.1f}MB", "done")

        for p in [inp, ass_path]:
            try:
                if p and os.path.exists(p): os.remove(p)
            except: pass

    except Exception as e:
        upd(jid, 0, f"Hata: {str(e)[:400]}", "error")
        print(f"[{jid}] EXCEPTION: {e}")

# ════════════════════════════════════════════════════
# SİLENCE DETECTION
# ════════════════════════════════════════════════════

def detect_silence(inp, t0, end_t, jid):
    """ffmpeg silencedetect ile sessiz kısımları bul."""
    try:
        result = subprocess.run([
            "ffmpeg","-i",inp,
            "-af","silencedetect=noise=-35dB:d=0.4",
            "-f","null","-"
        ], capture_output=True, text=True, timeout=60)

        silence_periods = []
        starts = re.findall(r"silence_start: ([\d.]+)", result.stderr)
        ends   = re.findall(r"silence_end: ([\d.]+)", result.stderr)

        for s, e in zip(starts, ends):
            s_t = float(s) - t0
            e_t = float(e) - t0
            dur = e_t - s_t
            # Kısa sessizlikler (0.4-1.5sn) = kesme noktası
            if 0.3 <= dur <= 1.5 and s_t > 3 and e_t < (end_t - t0 - 3):
                silence_periods.append({"start": s_t, "end": e_t, "dur": dur})

        print(f"[{jid}] Silence: {len(silence_periods)} adet")
        return silence_periods
    except Exception as e:
        print(f"silence detect error: {e}")
        return []

# ════════════════════════════════════════════════════
# AI EDİT KARARLARI
# ════════════════════════════════════════════════════

def ai_edit_decisions(words, content, profile, api_key, req, jid):
    """
    Claude'dan edit planı al:
    - Hangi kelimeler vurgulanacak (angle'a göre)
    - Hangi anlarda zoom yapılacak
    """
    try:
        full_text = " ".join(w["word"] for w in words)
        hook = clean(content.get("hook",""))

        prompt = f"""Sen bir video edit uzmanısın. Bu videoyu analiz et ve edit kararları ver.

İçerik tipi: {profile['label']}
Ton: {profile['prompt_tone']}
Hook: "{hook}"
Transkript: "{full_text[:400]}"
Video süresi tahmini: {len(words)/2.5:.0f} saniye

GÖREV 1 — Vurgu kelimeleri:
Bu angle için en etkili 3-5 kelime seç.
- {profile['label']} için güçlü kelimeler neler?

GÖREV 2 — Zoom anları:
Transkriptte en güçlü/vurucu 2-3 an hangisi? (saniye cinsinden tahmin et)
Bu anlarda zoom yapılacak.

SADECE JSON:
{{
  "highlights": ["kelime1","kelime2","kelime3"],
  "zoom_moments": [
    {{"time": 4.5, "word": "kelime", "intensity": 1.06}},
    {{"time": 8.2, "word": "kelime", "intensity": 1.04}}
  ],
  "edit_notes": "kisa aciklama"
}}"""

        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":400,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=20
        )
        d = r.json()
        if "error" in d: raise Exception(d["error"]["message"])
        raw = re.sub(r"```json|```","","".join(x["text"] for x in d["content"] if x.get("type")=="text")).strip()
        ed = json.loads(raw)

        hl_set = set(w.upper() for w in ed.get("highlights",[]))
        zoom_moments = ed.get("zoom_moments",[])
        print(f"[{jid}] AI edit: hl={hl_set}, zoom={len(zoom_moments)}, notes={ed.get('edit_notes','')[:50]}")

        # Highlight flag'lerini ekle
        for w in words:
            wc = re.sub(r"[^\wğüşöçıĞÜŞÖÇİ]","",w["word"]).upper()
            w["highlight"] = wc in hl_set

        # Zoom zamanlarını word zamanlarıyla eşleştir
        highlight_times = []
        for zm in zoom_moments:
            t = zm.get("time", 0)
            intensity = min(zm.get("intensity", profile["zoom_factor"]), 1.08)
            highlight_times.append({"time": t, "intensity": intensity, "dur": 1.0})

        return words, highlight_times

    except Exception as e:
        print(f"ai_edit_decisions error: {e}")
        # Fallback: büyük harflileri vurgula, otomatik zoom noktaları
        for w in words:
            w["highlight"] = w["word"].upper() == w["word"] and len(w["word"].strip()) > 2
        # Her n saniyede bir zoom
        n = profile["zoom_interval"]
        hl_times = [{"time": i*n+3, "intensity": profile["zoom_factor"], "dur": 1.0}
                    for i in range(int(len(words)/2.5 / n))]
        return words, hl_times

# ════════════════════════════════════════════════════
# FFMPEG VF ZİNCİRİ
# ════════════════════════════════════════════════════

def get_crop_filter(fmt):
    if fmt == "9:16":
        return "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=720:1280"
    elif fmt == "1:1":
        return "crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,scale=720:720"
    elif fmt == "16:9":
        return "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"
    return ""

def build_vf_chain(fmt, profile, highlight_times, silence_cuts, total_dur, t0, ass_path):
    """
    ffmpeg vf zinciri:
    1. Crop/scale
    2. Zoom effect (highlight anlarında)
    3. ASS altyazı
    """
    parts = []

    # 1. Crop
    crop = get_crop_filter(fmt)
    if crop:
        parts.append(crop)

    # 2. Zoom — highlight anlarında dinamik zoom
    # zoompan filtresi ile — hafif zoom in/out
    # Sadece fırsat ve hata için (agresif stiller)
    if highlight_times and profile["rhythm"] in ("fast", "medium"):
        zoom_filter = build_zoom_filter(highlight_times, total_dur, profile)
        if zoom_filter:
            parts.append(zoom_filter)

    # 3. ASS
    if ass_path and os.path.exists(ass_path):
        parts.append(f"ass={ass_path}")

    return ",".join(parts)

def build_simple_vf(fmt, ass_path):
    """Fallback: sadece crop + ass."""
    parts = []
    crop = get_crop_filter(fmt)
    if crop: parts.append(crop)
    if ass_path and os.path.exists(ass_path):
        parts.append(f"ass={ass_path}")
    return ",".join(parts)

def build_zoom_filter(highlight_times, total_dur, profile):
    """
    ffmpeg zoompan ile highlight anlarında zoom.
    Her highlight noktasında kısa zoom in → geri.
    RAM tasarrufu için max 3 zoom noktası.
    """
    if not highlight_times: return ""

    # Max 3 zoom noktası — RAM kısıtı
    points = highlight_times[:3]
    fps = 30

    # zoompan expression: belirli framelerde zoom artır
    # z='if(between(t,START,END),ZOOM,1)' formatı
    zoom_exprs = []
    for p in points:
        t_start = p["time"]
        t_end   = t_start + p.get("dur", 0.8)
        z       = min(p.get("intensity", 1.05), 1.08)  # max %8 zoom
        # Smooth: t_start'tan z'ye git, t_end'de geri dön
        zoom_exprs.append(
            f"if(between(t,{t_start:.2f},{t_end:.2f}),{z:.3f},1)"
        )

    if not zoom_exprs: return ""

    # Birden fazla nokta varsa if-elif zinciri
    if len(zoom_exprs) == 1:
        z_expr = zoom_exprs[0]
    else:
        # En basit: ilkini kullan (birden fazla zoompan iç içe geçince hata çıkabilir)
        z_expr = zoom_exprs[0]

    # zoompan — dikkatli kullan, RAM yer
    try:
        # Önce width/height tahmin et
        w, h = (720, 1280)  # 9:16 default
        return (f"zoompan=z='{z_expr}':d=1:x='iw/2-(iw/zoom/2)'"
                f":y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}")
    except:
        return ""

# ════════════════════════════════════════════════════
# ASS OLUŞTURMA
# ════════════════════════════════════════════════════

def build_ass(jid, inp, whisper_words, subs, hook_text, cta_text,
              fmt, total_dur, t0, profile):
    try:
        if fmt == "9:16":   pw, ph = 720, 1280
        elif fmt == "1:1":  pw, ph = 720, 720
        else:               pw, ph = 1280, 720

        fs_hook = int(pw * profile.get("hook_size", 0.085))
        fs_sub  = int(pw * profile.get("sub_size",  0.062))
        fs_cta  = int(pw * 0.052)
        fscale  = profile.get("font_scale", 105)

        # SAFE ZONE:
        # 9:16 (720x1280): Üst yasak 145px (%11), Alt yasak 204px (%16)
        # Hook: an5 ile tam ortada (safe)
        # Altyazı: an2 (alt-orta) + MarginV = alttan %28 — safe zone içi
        # CTA: an2 + MarginV = alttan %20
        sub_mv  = int(ph * 0.28)   # alttan safe zone
        cta_mv  = int(ph * 0.18)   # CTA biraz daha aşağı ama hâlâ safe

        hc  = profile.get("hook_color", "&H00FFFFFF")
        hi1 = profile.get("hi1",        "&H0055CCFF")
        hi2 = profile.get("hi2",        "&H0000FF00")
        oc  = profile.get("outline",    "&H00000000")
        sh  = profile.get("shadow",     "&HAA000000")

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,{fs_hook},{hc},&H00FFFFFF,{oc},{sh},-1,0,0,0,{fscale},{fscale},0.5,0,1,4,2,5,30,30,200,1
Style: Sub,Arial,{fs_sub},&H00FFFFFF,&H00FFFFFF,{oc},{sh},-1,0,0,0,{fscale},{fscale},0,0,1,3,1,2,20,20,{sub_mv},1
Style: Hi1,Arial,{fs_sub},{hi1},&H00FFFFFF,{oc},{sh},-1,0,0,0,{int(fscale*1.08)},{int(fscale*1.08)},0,0,1,4,1,2,20,20,{sub_mv},1
Style: Hi2,Arial,{fs_sub},{hi2},&H00FFFFFF,{oc},{sh},-1,0,0,0,{int(fscale*1.12)},{int(fscale*1.12)},0,0,1,4,1,2,20,20,{sub_mv},1
Style: CTA,Arial,{fs_cta},&H00FFFFFF,&H00FFFFFF,{hi1},&H99001050,-1,0,0,0,{fscale},{fscale},1,0,1,0,0,2,20,20,{cta_mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        hook_dur = profile.get("hook_dur", 3.0)
        sub_words = profile.get("sub_words", 4)

        # HOOK — an5 tam orta, büyük, bold
        if hook_text:
            h = clean(hook_text)
            wds = h.split()
            if len(wds) > 4:
                mid = len(wds)//2
                fmt_h = f"{{\\b1}}{' '.join(wds[:mid])}\\N{{\\b1}}{' '.join(wds[mid:])}"
            else:
                fmt_h = f"{{\\b1}}{h}"
            lines.append(f"Dialogue: 0,{ts(0)},{ts(hook_dur)},Hook,,0,0,0,,{{\\an5}}{fmt_h}")

        # ALTYAZILAR
        if whisper_words:
            adj = []
            for w in whisper_words:
                s = w["start"] - t0
                e = w["end"] - t0
                if s >= hook_dur + 0.2 and s <= total_dur - 5.5:
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
                    is_hl = w.get("highlight", False) or (word.upper()==word and len(word)>2)
                    if is_hl:
                        parts.append(f"{{\\rHi1}}{{\\b1}}{word}{{\\r}}")
                    else:
                        parts.append(word)
                if parts:
                    lines.append(f"Dialogue: 0,{ts(t_s)},{ts(t_e)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")
        else:
            avail = total_dur - hook_dur - 0.2 - 5.5
            if avail > 0 and subs:
                seg = avail / len(subs)
                for i, sub in enumerate(subs):
                    t_s = hook_dur + 0.2 + i * seg
                    t_e = min(t_s + seg - 0.15, total_dur - 5.5)
                    if t_s >= t_e: continue

                    hl_set = set(x.upper().strip() for x in sub.get("highlight",[]))
                    wds = clean(sub.get("text","")).split()
                    if not wds: continue

                    if len(wds) > 5:
                        mid = len(wds)//2
                        for li, wlist in enumerate([wds[:mid], wds[mid:]]):
                            lt_s = t_s + li*(seg/2)
                            lt_e = lt_s + seg/2 - 0.15
                            parts = _style_words(wlist, hl_set)
                            lines.append(f"Dialogue: 0,{ts(lt_s)},{ts(lt_e)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")
                    else:
                        parts = _style_words(wds, hl_set)
                        lines.append(f"Dialogue: 0,{ts(t_s)},{ts(t_e)},Sub,,0,0,0,,{{\\an2}}{' '.join(parts)}")

        # CTA — an2 alt-orta, renkli box
        if cta_text:
            c = clean(cta_text)
            cta_s = max(hook_dur + 0.5, total_dur - 5.0)
            lines.append(f"Dialogue: 0,{ts(cta_s)},{ts(total_dur)},CTA,,0,0,0,,{{\\an2}}{{\\b1}}{c}")

        ass_path = inp.replace("_in","_sub").replace(Path(inp).suffix,".ass")
        with open(ass_path,"w",encoding="utf-8") as f:
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
        if wc in hl_set or (w.upper()==w and len(w)>2):
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
