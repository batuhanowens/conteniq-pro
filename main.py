import os, uuid, json, subprocess, threading, re, unicodedata
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
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]:
        if os.path.exists(c):
            return c
    try:
        r = subprocess.run(["fc-list",":style=Bold","--format=%{file}\n"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().splitlines():
            f = line.strip()
            if f and os.path.exists(f): return f
    except: pass
    return None

FONT_PATH = find_font()
print(f"[startup] Font: {FONT_PATH}")

def clean_text(text):
    """Emoji ve drawtext'te sorun çıkaran karakterleri temizle."""
    result = []
    for char in text:
        cp = ord(char)
        # Emoji blokları
        if (0x1F000 <= cp <= 0x1FFFF or 0x2600 <= cp <= 0x27BF or
            0xFE00 <= cp <= 0xFE0F or cp == 0x200D or cp == 0xFEFF):
            continue
        result.append(char)
    cleaned = ''.join(result).strip()
    cleaned = re.sub(r'  +', ' ', cleaned)
    return cleaned

def escape_drawtext(text):
    """ffmpeg drawtext için escape."""
    text = clean_text(text)
    text = text.replace('\\', '\\\\')
    text = text.replace("'", "\u2019")   # tek tırnak → curly
    text = text.replace(':', '\\:')
    text = text.replace(',', '\\,')
    text = text.replace('[', '\\[')
    text = text.replace(']', '\\]')
    text = text.replace('%', '\\%')
    return text

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/health")
def health():
    try:
        r = subprocess.run(["ffmpeg","-version"], capture_output=True, timeout=5)
        ffok = r.returncode == 0
    except: ffok = False
    return jsonify({"ok": True, "ffmpeg": ffok, "font": FONT_PATH})

@app.route("/api/generate", methods=["POST"])
def generate():
    import requests as req
    data = request.json or {}
    api_key = request.headers.get("X-Api-Key","")
    if not api_key:
        return jsonify({"error":"API key gerekli"}), 400

    sector   = data.get("sector","Genel")
    city     = data.get("city","Türkiye")
    goal     = data.get("goal","Müşteri")
    audience = data.get("audience","genel")
    detail   = data.get("detail","")
    has_vid  = data.get("hasVideo", False)

    prompt = f"""Sen Türkiye pazarında uzman, yüksek dönüşüm odaklı bir sosyal medya stratejisti ve kısa video (Reels/TikTok) içerik üretim uzmanısın.

Kullanıcı bilgileri:
- Sektör: {sector}
- Şehir: {city}
- Hedef: {goal}
- Hedef Kitle: {audience}
{f"- Detay: {detail}" if detail else ""}
- Video: {"Yüklendi" if has_vid else "Yok"}

7 adet Reels içeriği üret. ÖNEMLI: Hook ve CTA metinlerinde EMOJI KULLANMA — sadece Türkçe kelimeler.
SADECE JSON döndür:
{{"meta":{{"sector":"{sector}","city":"{city}","goal":"{goal}"}},"contents":[{{"num":1,"angle":"tema","hook":"max 10 kelime emoji yok","video_flow":[{{"scene":1,"desc":"Hook sahnesi","duration":"0-3sn"}},{{"scene":2,"desc":"Problem","duration":"3-8sn"}},{{"scene":3,"desc":"Deger","duration":"8-15sn"}},{{"scene":4,"desc":"Kanit","duration":"15-22sn"}},{{"scene":5,"desc":"CTA","duration":"22-27sn"}}],"script":"max 100 kelime direkt kameraya","subtitles":[{{"text":"altyazi 1","highlight":["VURGU"]}},{{"text":"altyazi 2","highlight":["KELIME"]}}],"trigger":"aciliyet mesaji","cta":"tek net aksiyon emoji yok","caption":"2-3 satis cumlesi","hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5"]}}]}}
7 icerik uret: firsat, sir, hata, kanit, karsilastirma, bilgi, duygusal. Sektore ozel, Turkce."""

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
            return jsonify({"error":d["error"]["message"]}), 400
        raw = "".join(x["text"] for x in d["content"] if x.get("type")=="text")
        raw = re.sub(r"```json|```","",raw).strip()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/process", methods=["POST"])
def process_video():
    api_key = request.headers.get("X-Api-Key","")
    if "video" not in request.files:
        return jsonify({"error":"Video gerekli"}), 400

    vf         = request.files["video"]
    hook_text  = request.form.get("hook","")
    fmt        = request.form.get("format","9:16")
    sub_style  = request.form.get("sub_style","viral")
    cta_text   = request.form.get("cta","")
    subs_json  = request.form.get("subtitles","[]")
    t0         = float(request.form.get("trim_start",0) or 0)
    t1         = float(request.form.get("trim_end",0) or 0)
    use_wh     = request.form.get("use_whisper","true") == "true"

    jid = str(uuid.uuid4())[:8]
    ext = Path(vf.filename).suffix or ".mp4"
    inp = str(UPLOAD / f"{jid}_in{ext}")
    vf.save(inp)

    JOBS[jid] = {"status":"queued","progress":0,"msg":"Baslatiliyor..."}
    t = threading.Thread(target=run_job, args=(jid,inp,api_key,hook_text,fmt,sub_style,cta_text,subs_json,t0,t1,use_wh))
    t.daemon = True
    t.start()
    return jsonify({"job_id":jid})

def upd(jid, p, msg, status="running"):
    JOBS[jid] = {"status":status,"progress":p,"msg":msg}
    print(f"[{jid}] {p}% {msg}")

def run_job(jid, inp, api_key, hook_text, fmt, sub_style, cta_text, subs_json, t0, t1, use_wh):
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
        vw = int(vs.get("width",1920))
        vh = int(vs.get("height",1080))
        upd(jid, 10, f"Video: {vw}x{vh}, {duration:.1f}s")

        end_t = t1 if (t1 > t0 and t1 > 0) else duration

        # ── WHISPER ──────────────────────────────────
        ass_path = None
        if use_wh and api_key:
            upd(jid, 15, "Whisper: ses cikariliyor...")
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
                    words = wd.get("words",[])
                    if words:
                        ass_path = inp.replace("_in","_sub").replace(Path(inp).suffix,".ass")
                        write_ass_whisper(words, ass_path, sub_style, fmt, hook_text, cta_text, end_t - t0)
                        upd(jid, 35, f"Whisper: {len(words)} kelime OK")
                    else:
                        upd(jid, 35, "Whisper kelime bulamadi - AI altyazi")
                        ass_path = write_ass_ai(subs_json, duration, inp, sub_style, fmt, hook_text, cta_text, end_t - t0)
                else:
                    upd(jid, 35, f"Whisper hata {wr.status_code}")
                    ass_path = write_ass_ai(subs_json, duration, inp, sub_style, fmt, hook_text, cta_text, end_t - t0)
            except Exception as e:
                upd(jid, 35, f"Whisper basarisiz: {e}")
                ass_path = write_ass_ai(subs_json, duration, inp, sub_style, fmt, hook_text, cta_text, end_t - t0)
        else:
            upd(jid, 35, "AI altyazi hazirlaniyor...")
            ass_path = write_ass_ai(subs_json, duration, inp, sub_style, fmt, hook_text, cta_text, end_t - t0)

        # ── FFMPEG ───────────────────────────────────
        upd(jid, 40, "ffmpeg ile video isleniyor...")
        out_p = str(OUTPUT / f"{jid}_out.mp4")

        # Sadece crop/scale — drawtext YOK, her şey ASS içinde
        vf_parts = []

        if fmt == "9:16":
            vf_parts.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920")
        elif fmt == "1:1":
            vf_parts.append("crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,scale=1080:1080")
        elif fmt == "16:9":
            vf_parts.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black")

        if ass_path and os.path.exists(ass_path):
            # ass filtresi virgül içerdiği için ayrı ekle
            vf_parts.append(f"ass={ass_path}")

        cmd = ["ffmpeg", "-y"]
        if t0 > 0:
            cmd += ["-ss", str(t0)]
        cmd += ["-i", inp]
        if t1 > 0 and t1 > t0:
            cmd += ["-t", str(t1 - t0)]
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        cmd += ["-c:v","libx264","-preset","fast","-crf","20",
                "-c:a","aac","-b:a","128k","-movflags","+faststart", out_p]

        print(f"[{jid}] CMD: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(f"[{jid}] returncode: {result.returncode}")
        if result.stderr:
            # Sadece hata satırlarını logla
            err_lines = [l for l in result.stderr.splitlines()
                        if any(x in l for x in ["Error","error","Invalid","failed","No such","ass","sub"])]
            if err_lines:
                print(f"[{jid}] STDERR errors:\n" + "\n".join(err_lines[-10:]))

        if result.returncode != 0:
            # ASS olmadan tekrar dene
            upd(jid, 70, "ASS hatali - altyazisiz tekrar deneniyor...")
            cmd2 = ["ffmpeg","-y"]
            if t0 > 0: cmd2 += ["-ss",str(t0)]
            cmd2 += ["-i",inp]
            if t1 > 0 and t1 > t0: cmd2 += ["-t",str(t1-t0)]
            vf2 = [p for p in vf_parts if not p.startswith("ass=")]
            if vf2: cmd2 += ["-vf",",".join(vf2)]
            cmd2 += ["-c:v","libx264","-preset","fast","-crf","20",
                     "-c:a","aac","-b:a","128k","-movflags","+faststart",out_p]
            print(f"[{jid}] CMD2: {' '.join(cmd2)}")
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
            print(f"[{jid}] CMD2 returncode: {r2.returncode}")
            if r2.returncode != 0:
                print(f"[{jid}] CMD2 STDERR:\n{r2.stderr[-500:]}")
                raise Exception(f"ffmpeg basarisiz (returncode {r2.returncode})")
            upd(jid, 90, "Altyazisiz versiyon tamamlandi")
        else:
            upd(jid, 90, "Video islendi")

        size_mb = os.path.getsize(out_p) / 1024 / 1024
        upd(jid, 100, f"Tamamlandi! {size_mb:.1f}MB", "done")

        for p in [inp, ass_path]:
            try:
                if p and os.path.exists(p): os.remove(p)
            except: pass

    except Exception as e:
        upd(jid, 0, f"Hata: {str(e)[:400]}", "error")
        print(f"[{jid}] EXCEPTION: {e}")

# ── ASS YAZMA ────────────────────────────────────────

def ts(sec):
    sec = max(0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def ass_styles(fmt, sub_style):
    if fmt == "9:16":   pw, ph = 1080, 1920
    elif fmt == "1:1":  pw, ph = 1080, 1080
    else:               pw, ph = 1920, 1080

    # Hook için büyük stil, altyazı için normal stil, CTA için renkli
    fs_hook = int(pw * 0.062)
    fs_sub  = int(pw * 0.048)
    fs_cta  = int(pw * 0.044)
    mv      = int(ph * 0.12)

    colors = {
        "viral":   ("&H00FFFFFF","&H00000000","&H80000000"),
        "tiktok":  ("&H00FFFFFF","&H000050FF","&H80000000"),
        "yellow":  ("&H0055CCFF","&H00000000","&H80000000"),
        "minimal": ("&H00FFFFFF","&H00000000","&HB4000000"),
        "fire":    ("&H005C35FF","&H000000FF","&H80000000"),
    }
    tc, oc, bc = colors.get(sub_style, colors["viral"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,{fs_hook},{tc},&H00FFFFFF,{oc},{bc},-1,0,0,0,100,100,0,0,1,4,2,5,30,30,{int(ph*0.45)},1
Style: Sub,Arial,{fs_sub},{tc},&H00FFFFFF,{oc},{bc},-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{mv},1
Style: CTA,Arial,{fs_cta},&H00FFFFFF,&H00FFFFFF,&H000050FF,&H900050FF,-1,0,0,0,100,100,0,0,1,0,0,2,20,20,{int(ph*0.08)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header, pw, ph

def write_ass_whisper(words, path, style, fmt, hook_text, cta_text, total_dur):
    """Whisper + hook + CTA hepsini tek ASS dosyasına yaz."""
    header, pw, ph = ass_styles(fmt, style)
    lines = []

    # Hook — ilk 3 saniye, ortada büyük
    if hook_text:
        h = clean_text(hook_text)
        lines.append(f"Dialogue: 0,{ts(0)},{ts(3)},Hook,,0,0,0,,{{\\an5}}{h}")

    # Whisper altyazıları — 4'lü gruplar
    group = 4
    for i in range(0, len(words), group):
        g = words[i:i+group]
        t_s = ts(g[0]["start"])
        t_e = ts(g[-1]["end"] + 0.2)
        # Aktif kelimeyi bold yap
        parts = []
        for w in g:
            word = clean_text(w["word"].strip())
            parts.append(f"{{\\b1}}{word}{{\\b0}}")
        text = " ".join(parts)
        lines.append(f"Dialogue: 0,{t_s},{t_e},Sub,,0,0,0,,{text}")

    # CTA — son 5 saniye
    if cta_text and total_dur > 5:
        c = clean_text(cta_text)
        cta_start = max(3.5, total_dur - 5)
        lines.append(f"Dialogue: 0,{ts(cta_start)},{ts(total_dur)},CTA,,0,0,0,,{{\\an2}}{c}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))

def write_ass_ai(subs_json, duration, inp, style, fmt, hook_text, cta_text, total_dur):
    """AI altyazıları + hook + CTA ASS dosyasına yaz."""
    try:
        subs = json.loads(subs_json)
        header, pw, ph = ass_styles(fmt, style)
        lines = []

        # Hook
        if hook_text:
            h = clean_text(hook_text)
            lines.append(f"Dialogue: 0,{ts(0)},{ts(3)},Hook,,0,0,0,,{{\\an5}}{h}")

        # AI altyazılar
        if subs:
            seg = (total_dur * 0.65) / len(subs)
            start = total_dur * 0.1
            for i, sub in enumerate(subs):
                t_s = ts(start + i * seg)
                t_e = ts(start + (i+1) * seg - 0.15)
                hl = [x.upper().strip() for x in sub.get("highlight",[])]
                words = clean_text(sub.get("text","")).split()
                parts = []
                for w in words:
                    wc = re.sub(r"[^\w]","",w.upper())
                    if wc in hl:
                        parts.append(f"{{\\b1}}{{\\c&H0055CCFF&}}{w}{{\\b0}}{{\\c&HFFFFFF&}}")
                    else:
                        parts.append(w)
                lines.append(f"Dialogue: 0,{t_s},{t_e},Sub,,0,0,0,,{' '.join(parts)}")

        # CTA
        if cta_text and total_dur > 5:
            c = clean_text(cta_text)
            cta_start = max(3.5, total_dur - 5)
            lines.append(f"Dialogue: 0,{ts(cta_start)},{ts(total_dur)},CTA,,0,0,0,,{{\\an2}}{c}")

        path = inp.replace("_in","_ai").replace(Path(inp).suffix,".ass")
        with open(path,"w",encoding="utf-8") as f:
            f.write(header + "\n".join(lines))
        return path
    except Exception as e:
        print(f"write_ass_ai error: {e}")
        return None

@app.route("/api/status/<jid>")
def status(jid):
    job = JOBS.get(jid)
    if not job: return jsonify({"error":"Bulunamadi"}), 404
    return jsonify(job)

@app.route("/api/download/<jid>")
def download(jid):
    p = OUTPUT / f"{jid}_out.mp4"
    print(f"[download] {jid} - exists={p.exists()} - size={p.stat().st_size if p.exists() else 0}")
    if not p.exists(): return jsonify({"error":"Dosya yok"}), 404
    return send_file(str(p), mimetype="video/mp4",
                     as_attachment=True, download_name=f"conteniq-{jid}.mp4")

@app.route("/api/debug/<jid>")
def debug_job(jid):
    """Job detaylarini goster."""
    job = JOBS.get(jid, {})
    out_p = OUTPUT / f"{jid}_out.mp4"
    inp_files = list(UPLOAD.glob(f"{jid}*"))
    out_files = list(OUTPUT.glob(f"{jid}*"))
    return jsonify({
        "job": job,
        "output_exists": out_p.exists(),
        "output_size_mb": round(out_p.stat().st_size/1024/1024, 2) if out_p.exists() else 0,
        "upload_files": [str(f) for f in inp_files],
        "output_files": [str(f) for f in out_files],
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
