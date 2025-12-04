import os
import tempfile
import io
import logging
import shutil
from flask import Flask, render_template, request, send_file, jsonify, make_response
from yt_dlp import YoutubeDL

app = Flask(__name__)
# 降低日志级别，只看关键信息
logging.basicConfig(level=logging.INFO)

ORIGINAL_COOKIE_PATH = '/etc/secrets/cookies.txt'
TEMP_COOKIE_PATH = '/tmp/cookies.txt'

@app.route('/favicon.ico')
def favicon():
    return app.response_class(response=b'', status=200, mimetype='image/x-icon')

@app.route('/logo.png')
def logo():
    return app.response_class(response=b'', status=200, mimetype='image/png')

def setup_cookies():
    # 确保 Cookie 文件存在且可读写
    if os.path.exists(ORIGINAL_COOKIE_PATH):
        try:
            if os.path.exists(TEMP_COOKIE_PATH):
                os.remove(TEMP_COOKIE_PATH)
            shutil.copy(ORIGINAL_COOKIE_PATH, TEMP_COOKIE_PATH)
            return TEMP_COOKIE_PATH
        except Exception:
            pass
    return None

def get_ydl_opts(is_download=False):
    cookie_file = setup_cookies()
    
    opts = {
        'quiet': True,
        'noprogress': True,
        'cookiefile': cookie_file,
        'socket_timeout': 30, # 增加超时时间
        'noplaylist': True,
        
        # 【关键修改】策略调整
        # 1. 'web': 只有 Web 客户端能完美支持我们上传的 cookies.txt
        # 2. 'tv_embedded': 如果 Web 失败，尝试 TV 嵌入式，它对 IP 限制非常宽松
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'tv_embedded'], 
                'skip': ['android', 'ios'], # 显式跳过不支持 Cookie 的移动端
            }
        },
        # 模拟真实 PC 浏览器
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    }

    if is_download:
        opts.update({
            'format': 'bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
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
        url = request.form.get('youtube_url')
        if not url: return render_template('index.html', error="请输入链接")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ydl_opts = get_ydl_opts(is_download=True)
                ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    
                    if not info:
                        raise Exception("YouTube 拒绝访问，请更新 Cookie")

                    title = info.get('title', 'audio')
                    
                    target = None
                    for f in os.listdir(temp_dir):
                        if f.endswith('.mp3'):
                            target = os.path.join(temp_dir, f)
                            break
                    
                    if not target: raise Exception("转换失败")

                    with open(target, 'rb') as f:
                        mem = io.BytesIO(f.read())
                    final_name = f"{title}.mp3"

            mem.seek(0)
            resp = make_response(send_file(mem, as_attachment=True, download_name=final_name, mimetype='audio/mpeg'))
            return resp

        except Exception as e:
            app.logger.error(f"DL Error: {e}")
            return render_template('index.html', error="下载失败，请稍后重试。")

    return render_template('index.html')

@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    url = data.get('youtube_url')
    if not url: return jsonify({"success": False}), 400

    try:
        ydl_opts = get_ydl_opts(is_download=False)
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info is None:
                return jsonify({"success": False, "message": "IP暂时受限"}), 500
            
            # 安全获取缩略图
            thumb = None
            if info.get('thumbnails'):
                 thumb = info['thumbnails'][-1].get('url')
            
            return jsonify({"success": True, "title": info.get('title'), "thumbnail_url": thumb})
            
    except Exception as e:
        app.logger.error(f"Info Error: {e}")
        return jsonify({"success": False, "message": "无法获取信息"}), 500

if __name__ == '__main__':
    app.run(debug=True)