# -*- coding: utf-8 -*-
"""海报墙制作网站：豆瓣编号抓海报 / 本地上传 / 一键拼贴"""
import io
import os
import re
import time
import uuid
import base64
import requests
from PIL import Image
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
POSTER_DIR = os.path.join(BASE, "posters")
os.makedirs(POSTER_DIR, exist_ok=True)

app = FastAPI(title="海报墙制作器")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# 沙箱/内网环境可能缺 CA 证书，校验失败时自动降级
import urllib3
urllib3.disable_warnings()

# 可选：配置自己的豆瓣 Cookie 可大幅降低反爬拦截率
# Render 后台 → Environment → 添加 DOUBAN_COOKIE
DOUBAN_COOKIE = os.environ.get("DOUBAN_COOKIE", "")

def douban_headers(extra=None):
    h = {"User-Agent": UA, "Referer": "https://movie.douban.com/"}
    if DOUBAN_COOKIE:
        h["Cookie"] = DOUBAN_COOKIE
    if extra:
        h.update(extra)
    return h

def get(url, **kw):
    kw.setdefault("timeout", 10)
    try:
        return requests.get(url, verify=True, **kw)
    except requests.exceptions.SSLError:
        return requests.get(url, verify=False, **kw)

@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))

# ---------- 1. 通过豆瓣电影编号获取海报 ----------
@app.get("/api/movie/{douban_id}")
def fetch_by_id(douban_id: str):
    if not re.fullmatch(r"\d{6,10}", douban_id):
        raise HTTPException(400, "豆瓣编号应为 6-10 位数字，例如 1292052")
    url = f"https://movie.douban.com/subject/{douban_id}/"
    api = f"https://m.douban.com/rexxar/api/v2/movie/{douban_id}"
    try:
        title, poster_url = None, None
        # 第一优先：豆瓣移动端 JSON 接口（反爬较弱，含高清海报），带重试
        for attempt in range(2):
            try:
                r = get(api, headers=douban_headers(), timeout=10)
                if r.status_code == 200:
                    d = r.json()
                    title = d.get("title")
                    pic = d.get("pic") or {}
                    poster_url = pic.get("large") or pic.get("normal")
                    if poster_url:
                        break
            except Exception:
                pass
            if attempt == 0:
                time.sleep(1.5)  # 限流时稍作退避再试
        # 兜底：解析 PC 页 og:image
        if not poster_url:
            try:
                r = get(url, headers=douban_headers(), timeout=10)
                if r.status_code == 200:
                    m = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
                    t = re.search(r'<meta property="og:title" content="([^"]+)"', r.text)
                    poster_url = m.group(1) if m else None
                    title = title or (t.group(1) if t else None)
            except Exception:
                pass
        if not poster_url:
            tip = "豆瓣拒绝了请求（反爬限制）"
            if not DOUBAN_COOKIE:
                tip += "；在 Render 环境变量中配置 DOUBAN_COOKIE 可显著提升成功率，详见 README"
            raise HTTPException(502, tip + "；也可改用「手动粘贴海报链接」")
        img = get(poster_url, headers={"User-Agent": UA, "Referer": "https://movie.douban.com/"}, timeout=10).content
        fname = _save(img)
        return {"ok": True, "file": fname,
                "title": (title or douban_id).strip(),
                "poster_url": poster_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"抓取失败：{e}")

# ---------- 2. 手动粘贴海报图片链接 ----------
@app.post("/api/url")
def fetch_by_url(poster_url: str = Form(...)):
    try:
        img = get(poster_url, headers={"User-Agent": UA}, timeout=10).content
        fname = _save(img)
        return {"ok": True, "file": fname}
    except Exception as e:
        raise HTTPException(502, f"下载失败：{e}")

# ---------- 3. 本地上传 ----------
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "图片不能超过 20MB")
    fname = _save(data)
    return {"ok": True, "file": fname}

OUT_FORMAT = "png"  # 拼贴成品输出格式：png 无损 / jpg 高质量

def _save_out(canvas: Image.Image) -> str:
    """保存拼贴成品，PNG 无损 / JPG 高质量"""
    out = f"collage_{int(time.time())}_{uuid.uuid4().hex[:6]}.{OUT_FORMAT}"
    kw = {} if OUT_FORMAT == "png" else {"quality": 95}
    canvas.save(os.path.join(POSTER_DIR, out), **kw)
    return out

# ---------- 4. 一键拼贴（自动裁剪为统一比例） ----------
def _center_crop(im: Image.Image, rw: int, rh: int) -> Image.Image:
    """居中裁剪到 rw:rh 比例"""
    w, h = im.size
    target = rw / rh
    if w / h > target:  # 太宽，裁左右
        nw = int(h * target)
        x = (w - nw) // 2
        return im.crop((x, 0, x + nw, h))
    nh = int(w / target)  # 太高，裁上下
    y = (h - nh) // 2
    return im.crop((0, y, w, y + nh))

@app.post("/api/collage")
def collage(files: str = Form(...), cols: int = Form(4),
            gap: int = Form(8), bg: str = Form("#111111"),
            width: int = Form(300), crop: int = Form(1),
            ratio: str = Form("2:3")):
    names = [f for f in files.split(",") if f]
    if not names:
        raise HTTPException(400, "请先添加海报")
    try:
        rw, rh = (int(x) for x in ratio.split(":"))
    except Exception:
        rw, rh = 2, 3
    imgs = []
    for n in names:
        path = os.path.join(POSTER_DIR, os.path.basename(n))
        if os.path.exists(path):
            im = Image.open(path).convert("RGB")
            if crop:
                im = _center_crop(im, rw, rh)
            h = int(width * im.height / im.width)
            imgs.append(im.resize((width, h)))
    if not imgs:
        raise HTTPException(400, "没有找到有效的海报文件")
    rows = (len(imgs) + cols - 1) // cols
    # 海报顶满画布边缘，间隙只出现在海报之间
    cw = cols * width + (cols - 1) * gap
    ch = rows * imgs[0].height + (rows - 1) * gap
    canvas = Image.new("RGB", (cw, ch), bg)
    for i, im in enumerate(imgs):
        x = (i % cols) * (width + gap)
        y = (i // cols) * (im.height + gap)
        canvas.paste(im, (x, y))
    out = _save_out(canvas)
    return {"ok": True, "file": out, "count": len(imgs),
            "size": f"{canvas.width}x{canvas.height}"}

# ---------- 5. 自由排版拼贴（自定义位置） ----------
@app.post("/api/collage_free")
def collage_free(items: str = Form(...), canvas_w: int = Form(1600),
                 canvas_h: int = Form(900), bg: str = Form("#111111"),
                 trim: int = Form(1), padding: int = Form(10)):
    """items: JSON [{file,x,y,w,h}]，x/y/w/h 为画布比例 0~1，每张自动裁剪填满自己的框
       trim=1 时自动裁掉画布空白区域，仅保留海报占用范围 + padding 边距"""
    import json as _json
    try:
        arr = _json.loads(items)
    except Exception:
        raise HTTPException(400, "排版数据格式错误")
    arr = [a for a in arr if os.path.exists(os.path.join(POSTER_DIR, os.path.basename(a.get("file", ""))))]
    if not arr:
        raise HTTPException(400, "画布上还没有海报")
    boxes = []
    for a in arr:
        im = Image.open(os.path.join(POSTER_DIR, os.path.basename(a["file"]))).convert("RGB")
        bw = max(1, int(canvas_w * float(a["w"])))
        bh = max(1, int(canvas_h * float(a["h"])))
        px = int(canvas_w * float(a["x"]))
        py = int(canvas_h * float(a["y"]))
        boxes.append((_center_crop(im, bw, bh).resize((bw, bh)), px, py))
    if trim:
        x1 = min(b[1] for b in boxes); y1 = min(b[2] for b in boxes)
        x2 = max(b[1] + b[0].width for b in boxes); y2 = max(b[2] + b[0].height for b in boxes)
        cw, ch = (x2 - x1) + padding * 2, (y2 - y1) + padding * 2
        canvas = Image.new("RGB", (cw, ch), bg)
        for im, px, py in boxes:
            canvas.paste(im, (px - x1 + padding, py - y1 + padding))
    else:
        canvas = Image.new("RGB", (canvas_w, canvas_h), bg)
        for im, px, py in boxes:
            canvas.paste(im, (px, py))
    out = _save_out(canvas)
    return {"ok": True, "file": out, "count": len(arr),
            "size": f"{canvas.width}x{canvas.height}"}

@app.get("/poster/{name}")
def get_poster(name: str):
    path = os.path.join(POSTER_DIR, os.path.basename(name))
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path)

def _save(data: bytes) -> str:
    """原图直存，不重新压缩，避免画质损耗"""
    try:
        im = Image.open(io.BytesIO(data))
        im.verify()
    except Exception:
        raise HTTPException(400, "不是有效的图片文件")
    ext = (Image.open(io.BytesIO(data)).format or "JPEG").lower()
    ext = {"jpeg": "jpg"}.get(ext, ext)
    fname = f"{uuid.uuid4().hex[:10]}.{ext}"
    with open(os.path.join(POSTER_DIR, fname), "wb") as f:
        f.write(data)
    return fname

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
