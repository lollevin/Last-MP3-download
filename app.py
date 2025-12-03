import os
import tempfile
import io
import logging
from flask import Flask, render_template, request, send_file, jsonify, make_response
from yt_dlp import YoutubeDL, DownloadError

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# 定义 Render Secret File 的路径
COOKIE_FILE_PATH = '/etc/secrets/cookies.txt'

@app.route('/favicon.ico')
def favicon():
    return app.response_class(response=b'', status=200, mimetype='image/x-icon')

def get_ydl_opts(is_download=False):
    # 基础配置
    opts = {
        'quiet': True,
        'noprogress': True,
        # 关键修改：告诉 yt-dlp 使用我们上传的 Cookie 文件
        # 如果文件存在就使用，不存在（本地测试）就忽略
        'cookiefile': COOKIE_FILE_PATH if os.path.exists(COOKIE_FILE_PATH) else None,
        
        # 伪装配置：尽量模拟真实浏览器
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
                            raise FileNotFoundError("无法找到 MP3 文件，可能是 Cookie 过期或 IP 被封锁。")

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
            return render_template('index.html', error=f"下载失败: {str(e)}")

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
        if "429" in msg or "Sign in" in msg:
            msg = "服务器繁忙 (IP 限制)，请稍后再试或更新 Cookie。"
        return jsonify({"success": False, "message": msg}), 500

if __name__ == '__main__':
    app.run(debug=True)