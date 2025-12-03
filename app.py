import os
import tempfile
import io
import logging
from flask import Flask, render_template, request, send_file, jsonify, make_response
from yt_dlp import YoutubeDL, DownloadError

app = Flask(__name__)

# 设置日志
logging.basicConfig(level=logging.DEBUG)

# =======================================================
# 1. 解决 favicon.ico 404 问题
# =======================================================
@app.route('/favicon.ico')
def favicon():
    return app.response_class(response=b'', status=200, mimetype='image/x-icon')

# =======================================================
# 2. 核心伪装配置 (欺骗 YouTube 我们是手机)
# =======================================================
def get_ydl_opts(is_download=False):
    opts = {
        'quiet': True,
        'noprogress': True,
        # 关键修改：伪装成 Android 客户端，绕过 Bot 检测
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'], 
                'player_skip': ['web', 'tv'],     
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36'
        }
    }

    if is_download:
        # 下载模式的额外配置
        opts.update({
            'format': 'bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s', # 临时路径稍后处理
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320', 
            }],
        })
    else:
        # 获取信息模式的额外配置
        opts.update({
            'skip_download': True,
            'ignoreerrors': True,
        })
    
    return opts

# =======================================================
# 主路由：下载音频
# =======================================================
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        youtube_url = request.form.get('youtube_url')
        
        if not youtube_url:
            return render_template('index.html', error="请输入一个有效的 YouTube 链接。")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # 获取下载配置
                ydl_opts = get_ydl_opts(is_download=True)
                # 更新输出路径到临时目录
                ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=True)
                    video_title = info.get('title', 'audio_file')
                    
                    downloaded_file_path = os.path.join(temp_dir, f"{video_title}.mp3")
                    
                    # 容错查找
                    if not os.path.exists(downloaded_file_path):
                        all_files = os.listdir(temp_dir)
                        mp3_files = [f for f in all_files if f.endswith('.mp3')]
                        if mp3_files:
                             downloaded_file_path = os.path.join(temp_dir, mp3_files[0])
                             video_title = os.path.splitext(mp3_files[0])[0]
                        else:
                            raise FileNotFoundError("无法找到转换后的 MP3 文件。")

                    # 读取到内存
                    with open(downloaded_file_path, 'rb') as f:
                        mem_file = io.BytesIO(f.read())
                    
                    final_filename = f"{video_title}.mp3"

            mem_file.seek(0)

            # 发送文件并禁止缓存
            response = make_response(send_file(
                mem_file,
                as_attachment=True,
                download_name=final_filename,
                mimetype='audio/mpeg'
            ))
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Expires"] = "0"

            return response

        except Exception as e:
            app.logger.error(f"Download Error: {str(e)}")
            return render_template('index.html', error=f"服务器受限: {str(e)}")

    return render_template('index.html')

# =======================================================
# 异步路由：获取信息
# =======================================================
@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    data = request.get_json()
    youtube_url = data.get('youtube_url')

    if not youtube_url:
        return jsonify({"success": False, "message": "未提供链接"}), 400

    try:
        # 获取信息配置
        ydl_opts = get_ydl_opts(is_download=False)

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            
            if not info:
                return jsonify({"success": False, "message": "无法获取视频信息"}), 500

            thumbnail_url = None
            if info.get('thumbnails'):
                thumbnail_url = info['thumbnails'][-1]['url']
            
            return jsonify({
                "success": True,
                "title": info.get('title', '视频标题'),
                "thumbnail_url": thumbnail_url
            })
    except Exception as e:
        app.logger.error(f"Fetch Info Error: {str(e)}")
        # 返回简化的错误信息给前端
        error_msg = str(e)
        if "Sign in" in error_msg:
            error_msg = "服务器 IP 被 YouTube 限制，正在尝试绕过..."
        return jsonify({"success": False, "message": error_msg}), 500

if __name__ == '__main__':
    app.run(debug=True)