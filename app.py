import os
import tempfile
import io
import logging
import shutil # 1. 新增：用于复制文件
from flask import Flask, render_template, request, send_file, jsonify, make_response
from yt_dlp import YoutubeDL, DownloadError

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# Render Secret File 的原始路径 (只读)
ORIGINAL_COOKIE_PATH = '/etc/secrets/cookies.txt'
# 临时路径 (可读写)
TEMP_COOKIE_PATH = '/tmp/cookies.txt'

@app.route('/favicon.ico')
def favicon():
    return app.response_class(response=b'', status=200, mimetype='image/x-icon')

# =======================================================
# 帮助函数：准备 Cookie
# =======================================================
def setup_cookies():
    """
    将只读的 Cookie 文件复制到临时目录，以便 yt-dlp 可以写入更新
    """
    if os.path.exists(ORIGINAL_COOKIE_PATH):
        try:
            # 复制文件到 /tmp/cookies.txt
            shutil.copy(ORIGINAL_COOKIE_PATH, TEMP_COOKIE_PATH)
            return TEMP_COOKIE_PATH
        except Exception as e:
            app.logger.error(f"Cookie copy failed: {e}")
            return None
    return None

def get_ydl_opts(is_download=False):
    # 1. 准备 Cookie 副本
    cookie_file = setup_cookies()
    
    # 基础配置
    opts = {
        'quiet': True,
        'noprogress': True,
        # 2. 使用可读写的临时 Cookie 路径
        'cookiefile': cookie_file,
        
        # 伪装配置
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
            return render_template('index.html', error="请输入一个有效的 YouTube 链接。")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ydl_opts = get_ydl_opts(is_download=True)
                ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=True)
                    video_title = info.get('title', 'audio_file')
                    
                    downloaded_file_path = os.path.join(temp_dir, f"{video_title}.mp3")
                    
                    if not os.path.exists(downloaded_file_path):
                        all_files = os.listdir(temp_dir)
                        mp3_files = [f for f in all_files if f.endswith('.mp3')]
                        if mp3_files:
                             downloaded_file_path = os.path.join(temp_dir, mp3_files[0])
                             video_title = os.path.splitext(mp3_files[0])[0]
                        else:
                            raise FileNotFoundError("无法找到 MP3 文件 (Cookie 可能失效或 IP 被封)。")

                    with open(downloaded_file_path, 'rb') as f:
                        mem_file = io.BytesIO(f.read())
                    final_filename = f"{video_title}.mp3"

            mem_file.seek(0)
            response = make_response(send_file(mem_file, as_attachment=True, download_name=final_filename, mimetype='audio/mpeg'))
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Expires"] = "0"
            return response

        except Exception as e:
            app.logger.error(f"Download Error: {str(e)}")
            return render_template('index.html', error=f"下载错误: {str(e)}")

    return render_template('index.html')

@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    youtube_url = data.get('youtube_url')
    if not youtube_url: return jsonify({"success": False, "message": "未提供链接"}), 400

    try:
        ydl_opts = get_ydl_opts(is_download=False)
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            if not info: return jsonify({"success": False, "message": "无法获取信息"}), 500
            
            thumbnail_url = info['thumbnails'][-1]['url'] if info.get('thumbnails') else None
            return jsonify({"success": True, "title": info.get('title', '视频标题'), "thumbnail_url": thumbnail_url})
            
    except Exception as e:
        app.logger.error(f"Fetch Info Error: {str(e)}")
        # 友好的错误提示
        msg = str(e)
        if "Read-only" in msg:
            msg = "系统文件权限错误"
        elif "429" in msg or "Sign in" in msg:
            msg = "IP被限制，请稍后再试"
        return jsonify({"success": False, "message": msg}), 500

if __name__ == '__main__':
    app.run(debug=True)