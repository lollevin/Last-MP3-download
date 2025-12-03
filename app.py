import os
import tempfile
import io
import logging
import shutil
from flask import Flask, render_template, request, send_file, jsonify, make_response
from yt_dlp import YoutubeDL

app = Flask(__name__)
# 提高日志级别，减少 Render 日志中的噪音
logging.basicConfig(level=logging.INFO)

# Render Secret File 路径
ORIGINAL_COOKIE_PATH = '/etc/secrets/cookies.txt'
TEMP_COOKIE_PATH = '/tmp/cookies.txt'

# =======================================================
# 1. 彻底解决 404 干扰 (Logo 和 Favicon)
# =======================================================
@app.route('/favicon.ico')
def favicon():
    return app.response_class(response=b'', status=200, mimetype='image/x-icon')

@app.route('/logo.png')
def logo():
    # 返回空图片防止 404 刷屏
    return app.response_class(response=b'', status=200, mimetype='image/png')

# =======================================================
# Cookie 处理
# =======================================================
def setup_cookies():
    if os.path.exists(ORIGINAL_COOKIE_PATH):
        try:
            if os.path.exists(TEMP_COOKIE_PATH):
                os.remove(TEMP_COOKIE_PATH)
            shutil.copy(ORIGINAL_COOKIE_PATH, TEMP_COOKIE_PATH)
            return TEMP_COOKIE_PATH
        except Exception as e:
            app.logger.error(f"Cookie setup failed: {e}")
    return None

def get_ydl_opts(is_download=False):
    cookie_file = setup_cookies()
    
    opts = {
        'quiet': True,
        'noprogress': True,
        'cookiefile': cookie_file,
        # 关键修改：移除强制 Android 伪装
        # 让 yt-dlp 使用默认客户端，配合电脑 Cookie 效果更好
        # 且 Node.js 安装后，它能自动处理签名，不需要强制伪装
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    }

    if is_download:
        opts.update({
            'format': 'bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320', 
            }],
        })
    else:
        opts.update({
            'skip_download': True,
            'ignoreerrors': True,
        })
    
    return opts

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        youtube_url = request.form.get('youtube_url')
        if not youtube_url:
            return render_template('index.html', error="请输入有效链接")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ydl_opts = get_ydl_opts(is_download=True)
                ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=True)
                    video_title = info.get('title', 'audio')
                    
                    # 智能查找文件
                    target_file = None
                    for file in os.listdir(temp_dir):
                        if file.endswith('.mp3'):
                            target_file = os.path.join(temp_dir, file)
                            # 如果文件名还是原来的ID，尝试用标题重命名(可选)，这里直接用
                            break
                    
                    if not target_file:
                        raise Exception("转换失败，未找到MP3文件")

                    with open(target_file, 'rb') as f:
                        mem_file = io.BytesIO(f.read())
                    
                    final_name = f"{video_title}.mp3"

            mem_file.seek(0)
            response = make_response(send_file(mem_file, as_attachment=True, download_name=final_name, mimetype='audio/mpeg'))
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response

        except Exception as e:
            app.logger.error(f"DL Error: {e}")
            error_msg = str(e)
            if "429" in error_msg:
                error_msg = "服务器繁忙 (Google 限制了 IP)，请稍后重试。"
            elif "Sign in" in error_msg:
                error_msg = "需要更新 Cookie (认证失败)。"
            return render_template('index.html', error=error_msg)

    return render_template('index.html')

@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    url = data.get('youtube_url')
    if not url: return jsonify({"success": False, "message": "No URL"}), 400

    try:
        ydl_opts = get_ydl_opts(is_download=False)
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info: return jsonify({"success": False}), 500
            
            thumb = info['thumbnails'][-1]['url'] if info.get('thumbnails') else None
            return jsonify({"success": True, "title": info.get('title'), "thumbnail_url": thumb})
            
    except Exception as e:
        app.logger.error(f"Info Error: {e}")
        return jsonify({"success": False, "message": "无法获取信息 (可能IP受限)"}), 500

if __name__ == '__main__':
    app.run(debug=True)