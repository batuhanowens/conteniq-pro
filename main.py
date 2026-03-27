import os, uuid, json, subprocess, threading, re
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

UPLOAD = Path("uploads"); UPLOAD.mkdir(exist_ok=True)
OUTPUT = Path("outputs"); OUTPUT.mkdir(exist_ok=True)
JOBS = {}

# ── Font yolu — birden fazla yere bak ──────────────
def find_font():
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # Son çare: sistem fontlarını tara
    try:
        r = subprocess.run(["fc-list", ":style=Bold", "--format=%{file}\n"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().splitlines():
            f = line.strip()
            if f and os.path.exists(f):
                return f
    except:
        pass
    return None

FONT_PATH = find_font()
print(f"[startup] Font: {FONT_PATH}")

# ── STATIC ──────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── HEALTH ──────────────────────────────────────────
@app.route("/api/health")
def health():
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        ffmpeg_ok = r.returncode == 0
    except:
        ffmpeg_ok = False
    return jsonify({"ok": True, "ffmpeg": ffmpeg_ok, "font": FONT_PATH})

# ── GENERATE CONTENT ────────────────────────────────
@app.route("/api/generate", methods=["POST"])
def generate():
    import requests as req
    data = request.json or {}
    api_key = request.headers.get("X-Api-Key", "")
    if not api_key:
        return jsonify({"error": "API key gerekli"}), 400

    sector   = data.get("sector", "Genel")
    city     = data.get("city", "Türkiye")
    goal     = data.get("goal", "Müşteri")
    audience = data.get("audience", "genel")
    detail   = data.get("detail", "")
    has_vid  = data.get("hasVideo", False)

    prompt = f"""Sen Türkiye pazarında uzman, yüksek dönüşüm odaklı bir sosyal medya stratejisti ve kısa video (Reels/TikTok) içerik üretim uzmanısın.

Kullanıcı bilgileri:
- Sektör: {sector}
- Şehir: {city}
- Hedef: {goal}
- Hedef Kitle: {audience}
{f"- Detay: {detail}" if detail else ""}
- Video: {"Yüklendi" if has_vid else "Yok"}

7 adet Reels içeriği üret. SADECE JSON döndür (başka hiçbir şey yazma):
{{"meta":{{"sector":"{sector}","city":"{city}","goal":"{goal}"}},"contents":[{{"num":1,"angle":"tema","hook":"max 10 kelime hook asla merhaba yok","video_flow":[{{"scene":1,"desc":"Hook sahnesi","duration":"0-3sn"}},{{"scene":2,"desc":"Problem","duration":"3-8sn"}},{{"scene":3,"desc":"Değer","duration":"8-15sn"}},{{"scene":4,"desc":"Kanıt","duration":"15-22sn"}},{{"scene":5,"desc":"CTA","duration":"22-27sn"}}],"script":"max 100 kelime direkt kameraya","subtitles":[{{"text":"altyazı 1","highlight":["VURGU"]}},{{"text":"altyazı 2","highlight":["KELİME"]}}],"trigger":"aciliyet mesajı","cta":"tek net aksiyon","caption":"2-3 satış cümlesi","hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5"]}}]}}

7 içerik üret: fırsat, sır, hata, kanıt, karşılaştırma, bilgi, duygusal. Sektöre çok özel, Türkçe."""

    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":4000,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=90
        )
        d = r.json()
        if "error" in d:
            return jsonify({"error": d["error"]["message"]}), 400
        raw = "".join(x["text"] for x in d["content"] if x.get("type")=="text")
        raw = re.sub(r"```json|```", "", raw).strip()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── PROCESS VIDEO ────────────────────────────────────
@app.route("/api/process", methods=["POST"])
def process_video():
    api_key = request.headers.get("X-Api-Key", "")
    if "video" not in request.files:
        return jsonify({"error": "Video gerekli"}), 400

    video_file     = request.files["video"]
    hook_text      = request.form.get("hook", "")
    fmt            = request.form.get("format", "9:16")
    sub_style      = request.form.get("sub_style", "viral")
    cta_text       = request.form.get("cta", "")
    subtitles_json = request.form.get("subtitles", "[]")
    trim_start     = float(request.form.get("trim_start", 0) or 0)
    trim_end       = float(request.form.get("trim_end", 0) or 0)
    use_whisper    = request.form.get("use_whisper", "true") == "true"

    job_id = str(uuid.uuid4())[:8]
    ext = Path(video_file.filename).suffix or ".mp4"
    input_path = str(UPLOAD / f"{job_id}_in{ext}")
    video_file.save(input_path)

    JOBS[job_id] = {"status":"queued","progress":0,"msg":"Başlatılıyor…"}
    t = threading.Thread(target=run_job, args=(
        job_id, input_path, api_key,
        hook_text, fmt, sub_style, cta_text,
        subtitles_json, trim_start, trim_end, use_whisper
    ))
    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})

def upd(jid, p, msg, status="running"):
    JOBS[jid] = {"status":status,"progress":p,"msg":msg}
    print(f"[{jid}] {p}% {msg}")

def run_job(jid, inp, api_key, hook_text, fmt, sub_style, cta_text, subtitles_json, trim_start, trim_end, use_whisper):
    try:
        import requests as req

        # ── 1. PROBE ────────────────────────────────
        upd(jid, 5, "Video analiz ediliyor…")
        probe = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json","-show_streams","-show_format",inp],
            capture_output=True, text=True, timeout=30
        )
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        vs = next((s for s in info["streams"] if s["codec_type"]=="video"), {})
        vw = int(vs.get("width", 1920))
        vh = int(vs.get("height", 1080))
        upd(jid, 10, f"Video: {vw}×{vh}, {duration:.1f}s")

        end_t = trim_end if trim_end > trim_start > 0 or (trim_end > 0 and trim_start == 0) else duration
        if trim_end <= trim_start:
            end_t = duration

        # ── 2. WHISPER ──────────────────────────────
        ass_path = None
        if use_whisper and api_key:
            upd(jid, 15, "Whisper: ses çıkarılıyor…")
            try:
                audio_p = inp.replace("_in","_aud") + ".mp3"
                subprocess.run(
                    ["ffmpeg","-y","-i",inp,"-vn","-ar","16000","-ac","1","-b:a","64k",audio_p],
                    capture_output=True, check=True, timeout=120
                )
                upd(jid, 22, "Whisper: transkript alınıyor…")
                with open(audio_p,"rb") as f:
                    wr = req.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization":f"Bearer {api_key}"},
                        files={"file":("audio.mp3",f,"audio/mp3")},
                        data={"model":"whisper-1","language":"tr",
                              "response_format":"verbose_json",
                              "timestamp_granularities[]":"word"},
                        timeout=120
                    )
                try: os.remove(audio_p)
                except: pass
                if wr.status_code == 200:
                    wd = wr.json()
                    words = wd.get("words", [])
                    if words:
                        ass_path = inp.replace("_in","_sub").replace(Path(inp).suffix,".ass")
                        write_whisper_ass(words, ass_path, sub_style, fmt)
                        upd(jid, 35, f"Whisper: {len(words)} kelime alındı ✓")
                    else:
                        upd(jid, 35, "Whisper kelime bulamadı — AI altyazı kullanılıyor")
                        ass_path = write_ai_ass(subtitles_json, duration, inp, sub_style, fmt)
                else:
                    upd(jid, 35, f"Whisper hata {wr.status_code} — AI altyazı")
                    ass_path = write_ai_ass(subtitles_json, duration, inp, sub_style, fmt)
            except Exception as e:
                upd(jid, 35, f"Whisper başarısız ({e}) — AI altyazı")
                ass_path = write_ai_ass(subtitles_json, duration, inp, sub_style, fmt)
        else:
            upd(jid, 35, "AI altyazı hazırlanıyor…")
            ass_path = write_ai_ass(subtitles_json, duration, inp, sub_style, fmt)

        # ── 3. FFMPEG ───────────────────────────────
        upd(jid, 40, "ffmpeg ile video işleniyor…")
        out_p = str(OUTPUT / f"{jid}_out.mp4")

        # Video filter zinciri
        vf = build_vf(fmt, hook_text, cta_text, sub_style, ass_path, end_t, trim_start)

        # Komut
        cmd = ["ffmpeg", "-y"]
        if trim_start > 0:
            cmd += ["-ss", str(trim_start)]
        cmd += ["-i", inp]
        if trim_end > 0 and trim_end > trim_start:
            cmd += ["-t", str(trim_end - trim_start)]
        if vf:
            cmd += ["-vf", vf]
        cmd += [
            "-c:v","libx264","-preset","fast","-crf","20",
            "-c:a","aac","-b:a","128k","-movflags","+faststart",
            out_p
        ]

        print(f"[{jid}] CMD: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            err = result.stderr[-800:] if result.stderr else "bilinmeyen hata"
            raise Exception(err)

        size_mb = os.path.getsize(out_p) / 1024 / 1024
        upd(jid, 100, f"✅ Tamamlandı! {size_mb:.1f}MB", "done")

        # Temizlik
        for p in [inp, ass_path]:
            try:
                if p and os.path.exists(p): os.remove(p)
            except: pass

    except Exception as e:
        upd(jid, 0, f"Hata: {str(e)[:300]}", "error")
        print(f"[{jid}] ERROR: {e}")

def build_vf(fmt, hook_text, cta_text, sub_style, ass_path, end_t, trim_start):
    """ffmpeg -vf zinciri oluştur."""
    parts = []

    # 1. Format/crop
    if fmt == "9:16":
        parts.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920")
    elif fmt == "1:1":
        parts.append("crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,scale=1080:1080")
    elif fmt == "16:9":
        parts.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black")

    # 2. Hook (ilk 3 saniye) — font yoksa box only
    if hook_text and sub_style != "none":
        safe = hook_text.replace("\\","\\\\").replace("'","\\'").replace(":","\\:").replace(",","\\,")
        fs = 72 if fmt in ("9:16","1:1") else 74
        box = box_color(sub_style)
        if FONT_PATH:
            parts.append(
                f"drawtext=text='{safe}':fontfile='{FONT_PATH}':"
                f"fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=h*0.47:"
                f"enable='between(t,0,3)':box=1:{box}"
            )
        else:
            parts.append(
                f"drawtext=text='{safe}':"
                f"fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=h*0.47:"
                f"enable='between(t,0,3)':box=1:{box}"
            )

    # 3. CTA (son 5 saniye)
    if cta_text and sub_style != "none":
        safe = cta_text.replace("\\","\\\\").replace("'","\\'").replace(":","\\:").replace(",","\\,")
        dur = end_t - trim_start
        cta_t = max(0, dur - 5)
        fs = 52 if fmt in ("9:16","1:1") else 54
        if FONT_PATH:
            parts.append(
                f"drawtext=text='{safe}':fontfile='{FONT_PATH}':"
                f"fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=h*0.88:"
                f"enable='gte(t,{cta_t:.1f})':"
                f"box=1:boxcolor=0xff5c35@0.92:boxborderw=24"
            )
        else:
            parts.append(
                f"drawtext=text='{safe}':"
                f"fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=h*0.88:"
                f"enable='gte(t,{cta_t:.1f})':"
                f"box=1:boxcolor=0xff5c35@0.92:boxborderw=24"
            )

    # 4. ASS altyazı
    if ass_path and os.path.exists(ass_path):
        # ass filtresi virgül içerdiği için ayrı ele al
        parts.append(f"ass='{ass_path}'")

    return ",".join(parts)

def box_color(style):
    m = {
        "viral":   "boxcolor=black@0.88:boxborderw=22",
        "tiktok":  "boxcolor=0xff0050@0.92:boxborderw=22",
        "yellow":  "boxcolor=black@0.75:boxborderw=18",
        "minimal": "boxcolor=black@0.6:boxborderw=16",
        "fire":    "boxcolor=0xff5c35@0.88:boxborderw=22",
        "none":    "boxcolor=black@0:boxborderw=0",
    }
    return m.get(style, m["viral"])

def ts(sec):
    """Saniye → ASS timestamp."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def ass_header(fmt, sub_style):
    if fmt == "9:16":   pw, ph = 1080, 1920
    elif fmt == "1:1":  pw, ph = 1080, 1080
    else:               pw, ph = 1920, 1080
    fs = int(pw * 0.052)
    mv = int(ph * 0.15)
    colors = {
        "viral":   ("&H00FFFFFF","&H00000000"),
        "tiktok":  ("&H00FFFFFF","&H000050FF"),
        "yellow":  ("&H0055CCFF","&H00000000"),
        "minimal": ("&H00FFFFFF","&H00000000"),
        "fire":    ("&H005C35FF","&H000000FF"),
    }
    tc, oc = colors.get(sub_style, colors["viral"])
    fn = "Arial"
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fn},{fs},{tc},&H00FFFFFF,{oc},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""", pw, ph

def write_whisper_ass(words, path, style, fmt):
    """Whisper kelimelerinden ASS yaz — 4 kelimelik gruplar, aktif kelime vurgulanır."""
    header, pw, ph = ass_header(fmt, style)
    lines = []
    group = 5  # kaç kelime yan yana

    for i in range(0, len(words), group):
        g = words[i:i+group]
        t_s = ts(g[0]["start"])
        t_e = ts(g[-1]["end"] + 0.15)
        # Her kelime için karaoke tag
        parts = []
        for w in g:
            dur_cs = int((w["end"] - w["start"]) * 100)
            word = w["word"].strip()
            # Aktif kelimeyi büyük bold yap
            parts.append(f"{{\\kf{dur_cs}}}{{\\b1}}{word}{{\\b0}}")
        text = " ".join(parts)
        lines.append(f"Dialogue: 0,{t_s},{t_e},Default,,0,0,0,,{text}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))

def write_ai_ass(subtitles_json, duration, inp, style, fmt):
    """AI subtitle'lardan ASS yaz."""
    try:
        subs = json.loads(subtitles_json)
        if not subs:
            return None
        header, pw, ph = ass_header(fmt, style)
        seg = (duration * 0.65) / len(subs)
        start = duration * 0.08
        lines = []
        for i, sub in enumerate(subs):
            t_s = ts(start + i * seg)
            t_e = ts(start + (i+1) * seg - 0.1)
            hl = [h.upper() for h in sub.get("highlight", [])]
            words = sub.get("text","").split()
            parts = []
            for w in words:
                clean = re.sub(r"[^\wğüşöçıĞÜŞÖÇİ]","",w.upper())
                if clean in hl:
                    parts.append(f"{{\\b1}}{{\\c&H0055CCFF&}}{w}{{\\b0}}{{\\c&HFFFFFF&}}")
                else:
                    parts.append(w)
            lines.append(f"Dialogue: 0,{t_s},{t_e},Default,,0,0,0,,{' '.join(parts)}")
        path = inp.replace("_in","_ai").replace(Path(inp).suffix,".ass")
        with open(path,"w",encoding="utf-8") as f:
            f.write(header + "\n".join(lines))
        return path
    except Exception as e:
        print(f"write_ai_ass error: {e}")
        return None

# ── JOB STATUS ──────────────────────────────────────
@app.route("/api/status/<jid>")
def status(jid):
    job = JOBS.get(jid)
    if not job:
        return jsonify({"error":"Bulunamadı"}), 404
    return jsonify(job)

# ── DOWNLOAD ────────────────────────────────────────
@app.route("/api/download/<jid>")
def download(jid):
    p = OUTPUT / f"{jid}_out.mp4"
    if not p.exists():
        return jsonify({"error":"Dosya yok"}), 404
    return send_file(str(p), mimetype="video/mp4",
                     as_attachment=True, download_name=f"conteniq-{jid}.mp4")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
