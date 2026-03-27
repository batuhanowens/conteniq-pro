import os, uuid, json, subprocess, tempfile, threading
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

UPLOAD = Path("uploads"); UPLOAD.mkdir(exist_ok=True)
OUTPUT = Path("outputs"); OUTPUT.mkdir(exist_ok=True)
JOBS = {}

# ── STATIC ──────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── HEALTH ──────────────────────────────────────────
@app.route("/api/health")
def health():
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        ffmpeg_ok = r.returncode == 0
    except:
        ffmpeg_ok = False
    return jsonify({"ok": True, "ffmpeg": ffmpeg_ok})

# ── GENERATE CONTENT ────────────────────────────────
@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.json
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
Amacın: Kullanıcının sektörüne ve hedeflerine uygun, izlenme ve müşteri dönüşümü getiren kısa video içerikleri üretmek.

Kullanıcıdan gelen bilgiler:
- Sektör: {sector}
- Şehir: {city}
- Hedef: {goal}
- Hedef Kitle: {audience}
{f"- Detay: {detail}" if detail else ""}
- Video: {"Yüklendi" if has_vid else "Yok — çekim planı üret"}

Görevin: Toplam 7 adet yüksek performanslı Reels içeriği üret.
Her içerik farklı açıdan: fırsat, sır, hata, sosyal kanıt, karşılaştırma, bilgi, duygusal.

SADECE JSON döndür:
{{"meta":{{"sector":"{sector}","city":"{city}","goal":"{goal}"}},"contents":[{{"num":1,"angle":"tema","hook":"max 10 kelime asla merhaba yok","video_flow":[{{"scene":1,"desc":"Hook sahnesi","duration":"0-3sn"}},{{"scene":2,"desc":"Problem","duration":"3-8sn"}},{{"scene":3,"desc":"Değer","duration":"8-15sn"}},{{"scene":4,"desc":"Kanıt","duration":"15-22sn"}},{{"scene":5,"desc":"CTA","duration":"22-27sn"}}],"script":"max 100 kelime direkt kameraya","subtitles":[{{"text":"altyazı 1","highlight":["VURGU"]}},{{"text":"altyazı 2","highlight":["KELİME"]}}],"trigger":"aciliyet mesajı","cta":"tek net aksiyon","caption":"2-3 satış cümlesi","hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5"]}}]}}
7 içerik üret, hepsi farklı, sektöre çok özel, Türkçe, dönüşüm odaklı."""

    try:
        client = OpenAI(api_key=api_key)
        res = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        ) if False else None  # Anthropic SDK farklı

        # Anthropic HTTP API kullan
        import requests as req
        r = req.post("https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":4000,"messages":[{"role":"user","content":prompt}]},
            timeout=60
        )
        d = r.json()
        if "error" in d:
            return jsonify({"error": d["error"]["message"]}), 400
        raw = "".join(x["text"] for x in d["content"] if x["type"]=="text")
        import re
        raw = re.sub(r"```json|```","",raw).strip()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── PROCESS VIDEO ────────────────────────────────────
@app.route("/api/process", methods=["POST"])
def process_video():
    api_key = request.headers.get("X-Api-Key", "")
    if not api_key:
        return jsonify({"error": "API key gerekli"}), 400

    if "video" not in request.files:
        return jsonify({"error": "Video gerekli"}), 400

    video_file = request.files["video"]
    hook_text  = request.form.get("hook", "")
    fmt        = request.form.get("format", "9:16")
    sub_style  = request.form.get("sub_style", "viral")
    cta_text   = request.form.get("cta", "")
    subtitles_json = request.form.get("subtitles", "[]")
    trim_start = float(request.form.get("trim_start", 0))
    trim_end   = float(request.form.get("trim_end", 0))
    use_whisper = request.form.get("use_whisper", "true") == "true"

    job_id = str(uuid.uuid4())[:8]
    ext = Path(video_file.filename).suffix or ".mp4"
    input_path = UPLOAD / f"{job_id}_in{ext}"
    video_file.save(str(input_path))

    JOBS[job_id] = {"status": "queued", "progress": 0, "msg": "Sıraya alındı"}

    t = threading.Thread(target=run_job, args=(
        job_id, str(input_path), api_key,
        hook_text, fmt, sub_style, cta_text,
        subtitles_json, trim_start, trim_end, use_whisper
    ))
    t.daemon = True
    t.start()

    return jsonify({"job_id": job_id})

def upd(job_id, progress, msg, status="running"):
    JOBS[job_id] = {"status": status, "progress": progress, "msg": msg}
    print(f"[{job_id}] {progress}% {msg}")

def run_job(job_id, input_path, api_key, hook_text, fmt, sub_style, cta_text, subtitles_json, trim_start, trim_end, use_whisper):
    try:
        import requests as req

        upd(job_id, 5, "Video bilgisi alınıyor…")

        # Probe video
        probe = subprocess.run([
            "ffprobe","-v","quiet","-print_format","json",
            "-show_streams","-show_format", input_path
        ], capture_output=True, text=True)
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        vstream = next((s for s in info["streams"] if s["codec_type"]=="video"), {})
        vw = int(vstream.get("width", 1920))
        vh = int(vstream.get("height", 1080))
        upd(job_id, 10, f"Video: {vw}×{vh}, {duration:.1f}s")

        # Trim args
        trim_args = []
        if trim_start > 0:
            trim_args += ["-ss", str(trim_start)]
        end = trim_end if trim_end > trim_start and trim_end > 0 else duration
        if trim_end > trim_start and trim_end > 0:
            trim_args += ["-to", str(trim_end)]

        # ── WHISPER ──────────────────────────────────
        srt_path = None
        if use_whisper and api_key:
            upd(job_id, 15, "Ses Whisper'a gönderiliyor…")
            try:
                audio_path = input_path.replace("_in", "_audio") + ".mp3"
                subprocess.run([
                    "ffmpeg","-y","-i",input_path,
                    "-vn","-ar","16000","-ac","1","-b:a","64k",
                    audio_path
                ], capture_output=True, check=True)

                with open(audio_path,"rb") as f:
                    wr = req.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        files={"file": ("audio.mp3", f, "audio/mp3")},
                        data={"model":"whisper-1","language":"tr",
                              "response_format":"verbose_json",
                              "timestamp_granularities[]":"word"},
                        timeout=120
                    )

                os.remove(audio_path)

                if wr.status_code == 200:
                    wd = wr.json()
                    words = wd.get("words", [])
                    if words:
                        srt_path = input_path.replace("_in","_sub").replace(Path(input_path).suffix,".ass")
                        write_ass(words, srt_path, sub_style, vw, vh, fmt)
                        upd(job_id, 35, f"Altyazı: {len(words)} kelime")
                    else:
                        upd(job_id, 35, "Whisper kelime bulamadı — AI altyazı kullanılıyor")
                        srt_path = write_ai_subs(subtitles_json, duration, input_path, sub_style, vw, vh, fmt)
                else:
                    upd(job_id, 35, f"Whisper hata ({wr.status_code}) — AI altyazı")
                    srt_path = write_ai_subs(subtitles_json, duration, input_path, sub_style, vw, vh, fmt)
            except Exception as e:
                upd(job_id, 35, f"Whisper başarısız: {e}")
                srt_path = write_ai_subs(subtitles_json, duration, input_path, sub_style, vw, vh, fmt)
        else:
            srt_path = write_ai_subs(subtitles_json, duration, input_path, sub_style, vw, vh, fmt)

        upd(job_id, 40, "Video işleniyor (ffmpeg)…")

        output_path = str(OUTPUT / f"{job_id}_out.mp4")

        # ── BUILD FFMPEG COMMAND ──────────────────────
        vf_parts = []

        # 1. Crop/scale for format
        if fmt == "9:16":
            vf_parts.append(
                f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
                f"scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(1080-iw)/2:(1920-ih)/2:black"
            )
        elif fmt == "1:1":
            vf_parts.append(
                f"crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,"
                f"scale=1080:1080"
            )
        elif fmt == "16:9":
            vf_parts.append(
                f"scale=1920:1080:force_original_aspect_ratio=decrease,"
                f"pad=1920:1080:(1920-iw)/2:(1080-ih)/2:black"
            )

        # 2. Hook text overlay (ilk 3 saniye)
        if hook_text:
            safe_hook = hook_text.replace("'", "\\'").replace(":", "\\:").replace(",","\\,")
            # Canvas boyutuna göre font size
            if fmt == "9:16":
                cw, ch, font_size = 1080, 1920, 72
            elif fmt == "1:1":
                cw, ch, font_size = 1080, 1080, 68
            else:
                cw, ch, font_size = 1920, 1080, 72
            y_hook = int(ch * 0.48)
            box_style = get_box_style(sub_style)
            vf_parts.append(
                f"drawtext=text='{safe_hook}':"
                f"fontsize={font_size}:fontcolor=white:"
                f"x=(w-text_w)/2:y={y_hook}:"
                f"enable='between(t,0,3)':"
                f"box=1:{box_style}:"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )

        # 3. CTA overlay (son 5 saniye)
        if cta_text:
            safe_cta = cta_text.replace("'", "\\'").replace(":", "\\:").replace(",","\\,")
            if fmt == "9:16":
                cw2, ch2, font_size_cta = 1080, 1920, 52
            elif fmt == "1:1":
                cw2, ch2, font_size_cta = 1080, 1080, 50
            else:
                cw2, ch2, font_size_cta = 1920, 1080, 52
            y_cta = int(ch2 * 0.88)
            trim_dur = end - trim_start
            cta_start = max(0, trim_dur - 5)
            vf_parts.append(
                f"drawtext=text='{safe_cta}':"
                f"fontsize={font_size_cta}:fontcolor=white:"
                f"x=(w-text_w)/2:y={y_cta}:"
                f"enable='gte(t,{cta_start:.1f})':"
                f"box=1:boxcolor=0xff5c35@0.9:boxborderw=20:"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )

        # 4. ASS subtitle overlay
        ass_filter = ""
        if srt_path and os.path.exists(srt_path):
            ass_filter = f"ass={srt_path}"

        vf_final = ",".join(vf_parts)
        if ass_filter:
            vf_final = vf_final + ("," if vf_final else "") + ass_filter

        # Build command
        cmd = ["ffmpeg", "-y"]
        cmd += trim_args
        cmd += ["-i", input_path]
        if vf_final:
            cmd += ["-vf", vf_final]
        cmd += [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

        upd(job_id, 50, "ffmpeg çalışıyor…")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            raise Exception(f"ffmpeg hata: {result.stderr[-500:]}")

        size_mb = os.path.getsize(output_path) / 1024 / 1024
        upd(job_id, 100, f"Tamamlandı! {size_mb:.1f}MB", "done")

        # Cleanup
        try:
            os.remove(input_path)
            if srt_path and os.path.exists(srt_path):
                os.remove(srt_path)
        except:
            pass

    except Exception as e:
        upd(job_id, 0, f"Hata: {str(e)}", "error")
        print(f"Job error [{job_id}]: {e}")

def get_box_style(style):
    styles = {
        "viral":   "boxcolor=black@0.9:boxborderw=22",
        "tiktok":  "boxcolor=0xff0050@0.92:boxborderw=22",
        "yellow":  "boxcolor=black@0.75:boxborderw=18",
        "minimal": "boxcolor=black@0.6:boxborderw=16",
        "fire":    "boxcolor=0xff5c35@0.85:boxborderw=22",
        "none":    "boxcolor=black@0:boxborderw=0",
    }
    return styles.get(style, styles["viral"])

def write_ass(words, path, style, vw, vh, fmt):
    """Whisper kelimelerinden profesyonel ASS altyazı dosyası yaz."""
    # Format boyutları
    if fmt == "9:16":   pw, ph = 1080, 1920
    elif fmt == "1:1":  pw, ph = 1080, 1080
    else:               pw, ph = 1920, 1080

    font_size  = int(pw * 0.055)
    margin_v   = int(ph * 0.18)

    color_map = {
        "viral":   ("&H00FFFFFF", "&H00000000"),  # white text, black outline
        "tiktok":  ("&H00FFFFFF", "&H000050FF"),  # white, red outline
        "yellow":  ("&H0055CCFF", "&H00000000"),  # yellow, black outline
        "minimal": ("&H00FFFFFF", "&H00000000"),
        "fire":    ("&H005C35FF", "&H000000FF"),  # orange
    }
    tc, oc = color_map.get(style, color_map["viral"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
Collisions: Normal

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},{tc},&H00FFFFFF,{oc},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    # Group words into lines of ~5 words
    group_size = 5
    for i in range(0, len(words), group_size):
        group = words[i:i+group_size]
        t_start = ts(group[0]["start"])
        t_end   = ts(group[-1]["end"] + 0.1)
        # Bold the "active" word in group — ASS karaoke tag ile
        text_parts = []
        for j, w in enumerate(group):
            word = w["word"].strip()
            if j == 0:
                text_parts.append(f"{{\\k{int((w['end']-w['start'])*100)}}}{{\\b1}}{word}{{\\b0}}")
            else:
                text_parts.append(f"{{\\k{int((w['end']-w['start'])*100)}}}{word}")
        text = " ".join(text_parts)
        lines.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{text}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))

def write_ai_subs(subtitles_json, duration, input_path, style, vw, vh, fmt):
    """AI'ın ürettiği subtitle'lardan ASS dosyası yaz."""
    try:
        subs = json.loads(subtitles_json)
        if not subs:
            return None

        if fmt == "9:16":   pw, ph = 1080, 1920
        elif fmt == "1:1":  pw, ph = 1080, 1080
        else:               pw, ph = 1920, 1080

        font_size = int(pw * 0.052)
        margin_v  = int(ph * 0.18)
        color_map = {
            "viral":   ("&H00FFFFFF", "&H00000000"),
            "tiktok":  ("&H00FFFFFF", "&H000050FF"),
            "yellow":  ("&H0055CCFF", "&H00000000"),
            "minimal": ("&H00FFFFFF", "&H00000000"),
            "fire":    ("&H005C35FF", "&H000000FF"),
        }
        tc, oc = color_map.get(style, color_map["viral"])

        path = input_path.replace("_in","_ai_sub").replace(Path(input_path).suffix,".ass")
        seg_dur = (duration * 0.7) / len(subs)
        seg_start = duration * 0.1

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},{tc},&H00FFFFFF,{oc},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        for i, sub in enumerate(subs):
            t_s = seg_start + i * seg_dur
            t_e = t_s + seg_dur - 0.2
            highlights = [h.upper() for h in sub.get("highlight", [])]
            words = sub.get("text", "").split()
            text_parts = []
            for w in words:
                clean = w.upper().replace(".", "").replace(",", "").replace("!", "").replace("?", "")
                if clean in highlights:
                    text_parts.append(f"{{\\b1}}{{\\c&H0055CCFF&}}{w}{{\\b0}}{{\\c&H00FFFFFF&}}")
                else:
                    text_parts.append(w)
            lines.append(f"Dialogue: 0,{ts(t_s)},{ts(t_e)},Default,,0,0,0,,{' '.join(text_parts)}")

        with open(path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(lines))
        return path
    except Exception as e:
        print(f"AI sub error: {e}")
        return None

def ts(seconds):
    """Seconds → ASS timestamp H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

# ── JOB STATUS ──────────────────────────────────────
@app.route("/api/status/<job_id>")
def status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job bulunamadı"}), 404
    return jsonify(job)

# ── DOWNLOAD ────────────────────────────────────────
@app.route("/api/download/<job_id>")
def download(job_id):
    path = OUTPUT / f"{job_id}_out.mp4"
    if not path.exists():
        return jsonify({"error": "Dosya bulunamadı"}), 404
    return send_file(str(path), mimetype="video/mp4",
                     as_attachment=True, download_name=f"conteniq-{job_id}.mp4")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
