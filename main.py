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
        if os.path.exists(c): return c
    try:
        r = subprocess.run(["fc-list",":style=Bold","--format=%{file}\n"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().splitlines():
            f = line.strip()
            if f and os.path.exists(f): return f
    except: pass
    return None

FONT_PATH = find_font()
print(f"[startup] Font: {FONT_PATH}")

def clean(text):
    """Emoji ve özel karakterleri temizle."""
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
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = int(sec % 60); cs = int((sec % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

# ── ROUTES ──────────────────────────────────────────

@app.route("/")
def index(): return send_from_directory("static", "index.html")

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
    if not api_key: return jsonify({"error":"API key gerekli"}), 400

    sector   = data.get("sector","Genel")
    city     = data.get("city","Türkiye")
    goal     = data.get("goal","Müşteri")
    audience = data.get("audience","genel")
    detail   = data.get("detail","")

    prompt = f"""Sen Türkiye pazarında uzman, yüksek dönüşüm odaklı bir sosyal medya stratejisti ve kısa video içerik üretim uzmanısın.

Kullanıcı bilgileri:
- Sektör: {sector}
- Şehir: {city}
- Hedef: {goal}
- Hedef Kitle: {audience}
{f"- Detay: {detail}" if detail else ""}

7 adet Reels içeriği üret. ONEMLI KURALLAR:
1. Hook ve CTA metinlerinde KESINLIKLE EMOJI KULLANMA
2. Tüm metinler sade Türkçe olmalı
3. Her içerik farklı bir açıdan: fırsat, sır, hata, kanıt, karşılaştırma, bilgi, duygusal

SADECE JSON döndür:
{{"meta":{{"sector":"{sector}","city":"{city}","goal":"{goal}"}},"contents":[{{"num":1,"angle":"tema","hook":"max 10 kelime hook emoji yok","video_flow":[{{"scene":1,"desc":"Hook sahnesi","duration":"0-3sn"}},{{"scene":2,"desc":"Problem","duration":"3-8sn"}},{{"scene":3,"desc":"Deger","duration":"8-15sn"}},{{"scene":4,"desc":"Kanit","duration":"15-22sn"}},{{"scene":5,"desc":"CTA","duration":"22-27sn"}}],"script":"max 100 kelime direkt kameraya","subtitles":[{{"text":"altyazi 1","highlight":["VURGU"]}},{{"text":"altyazi 2","highlight":["KELIME"]}}],"trigger":"aciliyet mesaji","cta":"tek net aksiyon emoji yok","caption":"2-3 satis cumlesi","hashtags":["#tag1","#tag2","#tag3","#tag4","#tag5"]}}]}}
7 icerik uret. Sektore cok ozel, dönüsüm odakli, Turkce."""

    try:
        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":4000,"messages":[{"role":"user","content":prompt}]},
            timeout=90
        )
        d = r.json()
        if "error" in d: return jsonify({"error":d["error"]["message"]}), 400
        raw = re.sub(r"```json|```","","".join(x["text"] for x in d["content"] if x.get("type")=="text")).strip()
        return jsonify(json.loads(raw))
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/process", methods=["POST"])
def process_video():
    api_key = request.headers.get("X-Api-Key","")
    if "video" not in request.files: return jsonify({"error":"Video gerekli"}), 400

    vf         = request.files["video"]
    # İçerik verileri
    content_json = request.form.get("content","{}") # Tam içerik objesi
    fmt        = request.form.get("format","9:16")
    sub_style  = request.form.get("sub_style","viral")
    t0         = float(request.form.get("trim_start",0) or 0)
    t1         = float(request.form.get("trim_end",0) or 0)
    use_wh     = request.form.get("use_whisper","true") == "true"
    # Geriye uyumluluk
    hook_text  = request.form.get("hook","")
    cta_text   = request.form.get("cta","")
    subs_json  = request.form.get("subtitles","[]")

    jid = str(uuid.uuid4())[:8]
    ext = Path(vf.filename).suffix or ".mp4"
    inp = str(UPLOAD / f"{jid}_in{ext}")
    vf.save(inp)

    # Content parse
    try:
        content = json.loads(content_json)
    except:
        content = {}

    if not hook_text and content.get("hook"):
        hook_text = content["hook"]
    if not cta_text and content.get("cta"):
        cta_text = content["cta"]
    if subs_json == "[]" and content.get("subtitles"):
        subs_json = json.dumps(content["subtitles"])

    JOBS[jid] = {"status":"queued","progress":0,"msg":"Baslatiliyor..."}
    t = threading.Thread(target=run_job, args=(
        jid, inp, api_key, content,
        hook_text, fmt, sub_style, cta_text,
        subs_json, t0, t1, use_wh
    ))
    t.daemon = True; t.start()
    return jsonify({"job_id":jid})

def upd(jid, p, msg, status="running"):
    JOBS[jid] = {"status":status,"progress":p,"msg":msg}
    print(f"[{jid}] {p}% {msg}")

def run_job(jid, inp, api_key, content, hook_text, fmt, sub_style, cta_text, subs_json, t0, t1, use_wh):
    try:
        import requests as req

        # ── 1. PROBE ────────────────────────────────
        upd(jid, 5, "Video analiz ediliyor...")
        probe = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json","-show_streams","-show_format",inp],
            capture_output=True, text=True, timeout=30
        )
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        vs = next((s for s in info["streams"] if s["codec_type"]=="video"),{})
        vw = int(vs.get("width",1920)); vh = int(vs.get("height",1080))
        upd(jid, 10, f"Video: {vw}x{vh}, {duration:.1f}s")

        end_t = t1 if (t1 > t0 and t1 > 0) else duration
        total_dur = end_t - t0

        # ── 2. AI VIDEO ANALİZİ ──────────────────────
        # Sektöre ve içeriğe göre edit planı oluştur
        upd(jid, 12, "AI video edit planı oluşturuyor...")
        edit_plan = create_edit_plan(content, total_dur, api_key, req)
        print(f"[{jid}] Edit plan: {json.dumps(edit_plan, ensure_ascii=False)[:200]}")

        # ── 3. WHISPER ──────────────────────────────
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
                    upd(jid, 32, f"Whisper: {len(whisper_words)} kelime alindi")
                else:
                    upd(jid, 32, f"Whisper hata {wr.status_code}")
            except Exception as e:
                upd(jid, 32, f"Whisper basarisiz: {e}")

        # ── 4. ASS DOSYASI OLUŞTURUp ─────────────────
        upd(jid, 35, "Altyazilar hazirlaniyor...")
        ass_path = build_ass(
            jid, inp, whisper_words, subs_json,
            edit_plan, hook_text, cta_text,
            sub_style, fmt, total_dur, t0
        )

        # ── 5. FFMPEG ───────────────────────────────
        upd(jid, 45, "Video isleniyor (ffmpeg)...")
        out_p = str(OUTPUT / f"{jid}_out.mp4")

        vf_parts = []
        # Crop/scale
        if fmt == "9:16":
            vf_parts.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=720:1280")
        elif fmt == "1:1":
            vf_parts.append("crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,scale=720:720")
        elif fmt == "16:9":
            vf_parts.append("scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black")

        # ASS altyazı
        if ass_path and os.path.exists(ass_path):
            vf_parts.append(f"ass={ass_path}")

        cmd = ["ffmpeg","-y"]
        if t0 > 0: cmd += ["-ss", str(t0)]
        cmd += ["-i", inp]
        if t1 > 0 and t1 > t0: cmd += ["-t", str(t1 - t0)]
        if vf_parts: cmd += ["-vf", ",".join(vf_parts)]
        cmd += ["-c:v","libx264","-preset","ultrafast","-crf","26",
                "-threads","1","-c:a","aac","-b:a","96k",
                "-movflags","+faststart", out_p]

        print(f"[{jid}] CMD: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(f"[{jid}] returncode: {result.returncode}")

        if result.returncode != 0:
            # ASS olmadan fallback
            upd(jid, 70, "Altyazisiz versiyon deneniyor...")
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
                raise Exception(f"ffmpeg basarisiz (returncode {r2.returncode})\n{r2.stderr[-300:]}")
            upd(jid, 90, "Altyazisiz versiyon tamamlandi")
        else:
            upd(jid, 90, "Video tamamlandi")

        size_mb = os.path.getsize(out_p) / 1024 / 1024
        upd(jid, 100, f"Tamamlandi! {size_mb:.1f}MB", "done")

        for p in [inp, ass_path]:
            try:
                if p and os.path.exists(p): os.remove(p)
            except: pass

    except Exception as e:
        upd(jid, 0, f"Hata: {str(e)[:400]}", "error")
        print(f"[{jid}] EXCEPTION: {e}")

# ── AI EDIT PLANI ────────────────────────────────────

def create_edit_plan(content, total_dur, api_key, req):
    """
    Claude'a içeriği ve video süresini vererek edit planı yaptır.
    Hook ne zaman, altyazılar ne zaman, CTA ne zaman — hepsini hesaplar.
    """
    if not api_key or not content:
        return default_edit_plan(total_dur)

    try:
        hook = clean(content.get("hook",""))
        cta  = clean(content.get("cta",""))
        subs = content.get("subtitles",[])
        script = content.get("script","")
        video_flow = content.get("video_flow",[])

        prompt = f"""Sen profesyonel bir video editörüsün. Aşağıdaki Reels videosu için tam edit planı yap.

Video süresi: {total_dur:.1f} saniye
Hook metni: {hook}
CTA metni: {cta}
Script: {script[:200] if script else "yok"}
Video akışı: {json.dumps(video_flow, ensure_ascii=False)}
Altyazı sayısı: {len(subs)}

Kurallar:
- Hook ilk 0-3 saniyede gösterilmeli, büyük ve dikkat çekici
- Altyazılar konuşmaya göre dağıtılmalı ({total_dur:.0f} saniyeye eşit yayılsın)
- CTA son 5 saniyede çıkmalı
- Her altyazı max 3-4 saniye ekranda durmalı

SADECE JSON döndür:
{{
  "hook_start": 0.0,
  "hook_end": 3.0,
  "cta_start": {max(3.0, total_dur - 5.0):.1f},
  "cta_end": {total_dur:.1f},
  "subtitle_slots": [
    {{"idx": 0, "start": 3.5, "end": 7.0}},
    {{"idx": 1, "start": 7.5, "end": 12.0}}
  ],
  "hook_size": "large",
  "hook_position": "center",
  "sub_position": "bottom",
  "style_notes": "kisa aciklama"
}}"""

        r = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":800,
                  "messages":[{"role":"user","content":prompt}]},
            timeout=30
        )
        d = r.json()
        if "error" in d: raise Exception(d["error"]["message"])
        raw = re.sub(r"```json|```","","".join(x["text"] for x in d["content"] if x.get("type")=="text")).strip()
        plan = json.loads(raw)
        print(f"AI edit plan OK: {plan.get('style_notes','')}")
        return plan
    except Exception as e:
        print(f"create_edit_plan error: {e}")
        return default_edit_plan(total_dur)

def default_edit_plan(total_dur):
    """AI yoksa varsayılan plan."""
    n_subs = 3
    sub_start = 3.5
    sub_seg = max(3.0, (total_dur - 8) / n_subs)
    slots = [{"idx":i,"start":sub_start + i*sub_seg,"end":sub_start + (i+1)*sub_seg - 0.3}
             for i in range(n_subs)]
    return {
        "hook_start": 0.0, "hook_end": 3.0,
        "cta_start": max(3.5, total_dur - 5.0), "cta_end": total_dur,
        "subtitle_slots": slots,
        "hook_size": "large", "hook_position": "center", "sub_position": "bottom"
    }

# ── ASS OLUŞTURMA ────────────────────────────────────

def get_ass_header(fmt, sub_style):
    if fmt == "9:16":   pw, ph = 720, 1280
    elif fmt == "1:1":  pw, ph = 720, 720
    else:               pw, ph = 1280, 720

    fs_hook = int(pw * 0.072)   # büyük hook
    fs_sub  = int(pw * 0.054)   # normal altyazı
    fs_cta  = int(pw * 0.048)   # CTA
    mv_top  = int(ph * 0.42)    # hook için dikey marj (ortaya yakın)
    mv_bot  = int(ph * 0.06)    # altyazı için alt marj

    style_colors = {
        "viral":   ("&H00FFFFFF","&H00000000","&HAA000000"),  # beyaz/siyah outline/koyu bg
        "tiktok":  ("&H00FFFFFF","&H000050FF","&HAA000000"),
        "yellow":  ("&H0055CCFF","&H00000000","&HAA000000"),
        "minimal": ("&H00FFFFFF","&H00000000","&H88000000"),
        "fire":    ("&H005C35FF","&H000000FF","&HAA000000"),
    }
    tc, oc, bc = style_colors.get(sub_style, style_colors["viral"])

    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,{fs_hook},{tc},&H00FFFFFF,{oc},{bc},-1,0,0,0,100,100,1,0,1,4,2,5,20,20,{mv_top},1
Style: Sub,Arial,{fs_sub},{tc},&H00FFFFFF,{oc},{bc},-1,0,0,0,100,100,1,0,1,3,1,2,20,20,{mv_bot},1
Style: CTA,Arial,{fs_cta},&H00000000,&H00FFFFFF,&H000050FF,&H990050FF,-1,0,0,0,100,100,1,0,1,0,0,2,20,20,{int(ph*0.06)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""", pw, ph

def build_ass(jid, inp, whisper_words, subs_json, edit_plan, hook_text, cta_text, sub_style, fmt, total_dur, t0):
    """Tüm overlay'leri içeren tek ASS dosyası oluştur."""
    try:
        header, pw, ph = get_ass_header(fmt, sub_style)
        lines = []

        # ── HOOK ────────────────────────────────────
        if hook_text:
            h = clean(hook_text)
            h_start = edit_plan.get("hook_start", 0.0)
            h_end   = edit_plan.get("hook_end", 3.0)
            # Uzun hook'u iki satıra böl
            words = h.split()
            if len(words) > 4:
                mid = len(words) // 2
                line1 = " ".join(words[:mid])
                line2 = " ".join(words[mid:])
                hook_text_fmt = f"{{\\b1}}{line1}\\N{{\\b1}}{line2}"
            else:
                hook_text_fmt = f"{{\\b1}}{h}"
            lines.append(f"Dialogue: 0,{ts(h_start)},{ts(h_end)},Hook,,0,0,0,,{{\\an5}}{hook_text_fmt}")

        # ── ALTYAZILAR ───────────────────────────────
        slots = edit_plan.get("subtitle_slots", [])

        if whisper_words and len(whisper_words) > 0:
            # Whisper var — gerçek kelime zamanlaması kullan
            # t0 offset'i düzelt
            adj_words = []
            for w in whisper_words:
                adj = {"word": w["word"], "start": w["start"] - t0, "end": w["end"] - t0}
                if adj["start"] >= 3.0:  # Hook bittikten sonra başla
                    adj_words.append(adj)

            # 4'lü gruplar halinde satır oluştur
            group_size = 4
            for i in range(0, len(adj_words), group_size):
                g = adj_words[i:i+group_size]
                if not g: continue
                t_s = g[0]["start"]
                t_e = g[-1]["end"] + 0.2
                if t_s >= total_dur - 5.5: break  # CTA alanına girme

                # Aktif kelimeyi vurgula — karaoke stili
                parts = []
                for w in g:
                    word = clean(w["word"].strip())
                    if not word: continue
                    # Büyük harfli kelimeler zaten vurgulu
                    if word == word.upper() and len(word) > 2:
                        parts.append(f"{{\\b1}}{{\\c&H0055CCFF&}}{word}{{\\b0}}{{\\c&HFFFFFF&}}")
                    else:
                        parts.append(word)
                if parts:
                    text = " ".join(parts)
                    lines.append(f"Dialogue: 0,{ts(t_s)},{ts(t_e)},Sub,,0,0,0,,{text}")

        else:
            # Whisper yok — AI altyazıları edit planına göre yerleştir
            try:
                subs = json.loads(subs_json) if subs_json else []
            except:
                subs = []

            for i, sub in enumerate(subs):
                # Edit planından slot al, yoksa hesapla
                if i < len(slots):
                    slot = slots[i]
                    t_s = slot["start"]
                    t_e = slot["end"]
                else:
                    seg = max(3.0, (total_dur - 9) / max(len(subs),1))
                    t_s = 3.5 + i * seg
                    t_e = t_s + seg - 0.3

                if t_s >= total_dur - 5.5: break  # CTA alanına girme
                t_e = min(t_e, total_dur - 5.5)

                hl = [x.upper().strip() for x in sub.get("highlight",[])]
                words = clean(sub.get("text","")).split()
                parts = []
                for w in words:
                    wc = re.sub(r"[^\wğüşöçıĞÜŞÖÇİ]","",w.upper())
                    if wc in hl or (w == w.upper() and len(w) > 2):
                        parts.append(f"{{\\b1}}{{\\c&H0055CCFF&}}{w}{{\\b0}}{{\\c&HFFFFFF&}}")
                    else:
                        parts.append(w)
                if parts:
                    lines.append(f"Dialogue: 0,{ts(t_s)},{ts(t_e)},Sub,,0,0,0,,{' '.join(parts)}")

        # ── CTA ─────────────────────────────────────
        if cta_text:
            c = clean(cta_text)
            cta_s = edit_plan.get("cta_start", max(3.5, total_dur - 5.0))
            cta_e = edit_plan.get("cta_end", total_dur)
            lines.append(f"Dialogue: 0,{ts(cta_s)},{ts(cta_e)},CTA,,0,0,0,,{{\\an2}}{{\\b1}}{c}")

        ass_path = inp.replace("_in","_sub").replace(Path(inp).suffix,".ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(lines))

        print(f"[{jid}] ASS: {len(lines)} satir yazildi")
        return ass_path

    except Exception as e:
        print(f"[{jid}] build_ass error: {e}")
        return None

# ── STATUS / DOWNLOAD ────────────────────────────────

@app.route("/api/status/<jid>")
def status(jid):
    job = JOBS.get(jid)
    if not job: return jsonify({"error":"Bulunamadi"}), 404
    return jsonify(job)

@app.route("/api/download/<jid>")
def download(jid):
    p = OUTPUT / f"{jid}_out.mp4"
    print(f"[download] {jid} exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")
    if not p.exists(): return jsonify({"error":"Dosya yok"}), 404
    return send_file(str(p), mimetype="video/mp4",
                     as_attachment=True, download_name=f"conteniq-{jid}.mp4")

@app.route("/api/debug/<jid>")
def debug_job(jid):
    job = JOBS.get(jid, {})
    out_p = OUTPUT / f"{jid}_out.mp4"
    return jsonify({
        "job": job,
        "output_exists": out_p.exists(),
        "output_size_mb": round(out_p.stat().st_size/1024/1024, 2) if out_p.exists() else 0,
        "output_files": [str(f) for f in OUTPUT.glob(f"{jid}*")],
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
