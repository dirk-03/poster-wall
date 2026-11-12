# 海报墙制作器

豆瓣编号搜电影海报 · 本地上传 · 自动裁剪 · 网格/自由排版一键拼贴

## 本地运行

```bash
pip install -r requirements.txt
python app.py
# 打开 http://localhost:8000
```

## 部署到 Render（推荐）

1. 把整个目录推送到 GitHub 仓库
2. 登录 [render.com](https://render.com)，用 GitHub 账号注册
3. 点 **New → Web Service**，选择该仓库
4. Render 会自动识别 `render.yaml`：
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`
5. 点 Deploy，约 2 分钟后得到 `https://xxx.onrender.com` 地址

## 配置豆瓣 Cookie（强烈建议，防反爬）

服务器 IP 直接请求豆瓣容易被拦截。配置自己账号的 Cookie 后成功率大幅提升：

1. 浏览器登录 [豆瓣](https://www.douban.com)，打开任意电影页（如 movie.douban.com/subject/1292052）
2. 按 F12 打开开发者工具 → **Network（网络）** 面板 → 刷新页面
3. 点第一个 `subject/1292052` 请求 → 找到 **Request Headers** 里的 `Cookie:` 一行，复制冒号后的全部内容
4. Render 后台 → 你的服务 → **Environment** → **Add Environment Variable**：
   - Key: `DOUBAN_COOKIE`
   - Value: 刚才复制的内容
5. 保存后服务自动重启，生效

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/movie/{豆瓣编号}` | 通过豆瓣编号获取海报 |
| POST | `/api/url` | 手动海报链接下载 |
| POST | `/api/upload` | 本地上传 |
| POST | `/api/collage` | 网格拼贴（crop/ratio 自动裁剪） |
| POST | `/api/collage_free` | 自由排版（自定义坐标） |

> 注意：免费档磁盘为临时存储，服务重启后已生成的拼贴图会清空（重新获取/上传即可）。
