from flask import Flask, jsonify, request, Response
from urllib.parse import unquote
from PIL import Image, ImageDraw, ImageFont
import os
import csv
from io import StringIO

app = Flask(__name__)

# ==================== 全域設定 ====================
FONT_CACHE = {}  # {size: {char: {'bytes': [...], 'char': char}}}
FONT_PATH = 'NotoSansTC-Regular.ttf'  # 支援中英數的字型

# 檢查字型檔案
if not os.path.exists(FONT_PATH):
    print(f"錯誤：找不到字型檔案 {FONT_PATH}")
    print("請下載 Noto Sans TC: https://fonts.google.com/noto/specimen/Noto+Sans+TC")
    print("下載 Regular 版本，改名為 NotoSansTC-Regular.ttf 放在此資料夾")
    exit(1)

print(f"字型載入成功：{FONT_PATH}")

# ==================== 點陣生成函數 ====================
def text_to_dot_matrix(text, font_path, font_size=16):
    """
    將單一字元轉為 N×N 點陣（1-bit）
    自動縮放 + 正確置中 + 防裁切
    """
    img_size = font_size

    # 嘗試載入字型
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception as e:
        print(f"字型載入失敗，使用預設字型: {e}")
        font = ImageFont.load_default()
        font_size = min(12, font_size)

    # 建立畫布
    img = Image.new('1', (img_size, img_size), 0)
    draw = ImageDraw.Draw(img)

    # 計算邊界框
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # 若超出畫布，縮小字型
    if text_width > img_size or text_height > img_size:
        scale = min(img_size / max(text_width, 1), img_size / max(text_height, 1)) * 0.9
        new_size = max(8, int(font_size * scale))
        try:
            font = ImageFont.truetype(font_path, new_size)
        except:
            font = ImageFont.load_default()
        # 重新計算
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

    # 正確置中（抵銷 bbox 的負偏移）
    x = (img_size - text_width) // 2 - bbox[0]
    y = (img_size - text_height) // 2 - bbox[1]

    # 繪製文字
    draw.text((x, y), text, font=font, fill=1)

    # 轉為 byte 陣列（每 8 像素 1 byte）
    bytes_list = []
    for y in range(img_size):
        for x_start in range(0, img_size, 8):
            byte = 0
            for bit in range(8):
                x = x_start + bit
                if x < img_size and img.getpixel((x, y)):
                    byte |= (1 << (7 - bit))
            bytes_list.append(byte)
    
    return bytes_list


def generate_font_dict(input_str, font_path, font_size=16):
    """為多個字元生成點陣字典"""
    result = {}
    unique_chars = ''.join(set(input_str))  # 去重
    for char in unique_chars:
        try:
            bytes_list = text_to_dot_matrix(char, font_path, font_size)
            result[char] = {
                'bytes': bytes_list,
                'char': char
            }
        except Exception as e:
            print(f"生成 '{char}' 失敗: {e}")
            # 產生空白點陣
            bytes_per_char = (font_size * font_size) // 8
            result[char] = {'bytes': [0] * bytes_per_char}
    return result


# ==================== API 端點 ====================

@app.route('/font.csv', methods=['GET'])
def get_font_csv():
    """CSV 點陣輸出：/font.csv?text=ㄅㄆㄇabc123笑臉&size=32"""
    raw_text = request.args.get('text', '')
    size = int(request.args.get('size', 16))
    text = unquote(raw_text)

    if not text:
        return jsonify({'error': '請提供 text 參數'}), 400

    if size not in [16, 24, 32]:
        size = 16

    # 處理所有字元（不去濾中文）
    chars_to_process = list(text)

    # 快取機制
    cache_key = str(size)
    if cache_key not in FONT_CACHE:
        FONT_CACHE[cache_key] = {}
    cache = FONT_CACHE[cache_key]

    # 找出缺少的字元
    missing_chars = [c for c in set(chars_to_process) if c not in cache]
    if missing_chars:
        print(f"生成 {len(missing_chars)} 個新字元點陣（{size}x{size}）: {''.join(missing_chars)}")
        new_fonts = generate_font_dict(''.join(missing_chars), FONT_PATH, font_size=size)
        cache.update(new_fonts)

    # 產生 CSV
    output = StringIO()
    writer = csv.writer(output)
    bytes_per_char = (size * size) // 8
    header = ['char'] + [f'byte{i}' for i in range(bytes_per_char)]
    writer.writerow(header)

    for char in chars_to_process:
        if char in cache and 'bytes' in cache[char]:
            raw_bytes = cache[char]['bytes']
            padded = raw_bytes + [0] * (bytes_per_char - len(raw_bytes))
            writer.writerow([char] + padded[:bytes_per_char])

    csv_content = output.getvalue()
    print(f"CSV 輸出：{len(chars_to_process)} 字，{size}x{size}，{len(csv_content)} bytes")

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=font_{size}.csv',
            'Cache-Control': 'no-cache'
        }
    )


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'name': '全字元點陣 API（中英數符號emoji）',
        'font': FONT_PATH,
        'endpoints': {
            '/font.csv?text=ㄅㄆㄇabc123笑臉&size=32': '下載 CSV 點陣',
        },
        'example': 'curl "http://localhost:5000/font.csv?text=你好World笑臉&size=32" -o font.csv'
    })


@app.route('/cache', methods=['GET'])
def get_cache():
    return jsonify({
        'cache_sizes': {k: len(v) for k, v in FONT_CACHE.items()},
        'total_chars': sum(len(v) for v in FONT_CACHE.values())
    })


@app.route('/clear', methods=['POST'])
def clear_cache():
    FONT_CACHE.clear()
    return jsonify({'message': '快取已清空'})


# ==================== 啟動 ====================
if __name__ == '__main__':
    print("=" * 60)
    print("全字元點陣 API 啟動中...")
    print(f"字型：{FONT_PATH}")
    print("API 端點：http://localhost:5000/font.csv?text=測試&size=32")
    print("首頁：http://localhost:5000/")
    print("使用 ngrok 暴露：ngrok http 5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)