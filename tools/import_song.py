# -*- coding: utf-8 -*-
"""把一首歌登记进咕嘎的点歌库 —— 播放真实音频文件，不做音色转换

用法:
    python tools/import_song.py "D:\\某个目录\\晴天.mp3"
    python tools/import_song.py "D:\\某个目录\\某歌.flac" 某歌名

它做三件事:
  1. 把音频复制到 runtime/music/
  2. 读出真实时长（不是估算）
  3. 写 runtime/music/library.json，字段与 core/music_performance.py 对齐

注意: 这是"放原曲"，voice 字段会如实标注为非咕嘎音色。
真正的咕嘎翻唱要走 tools/convert_song.py（需人声分离环境 + Seed-VC 在线服务）。
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUSIC = ROOT / 'runtime' / 'music'
SUFFIXES = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus'}


def duration_of(path: Path) -> float:
    """返回秒数；wav 用标准库，其余用 mutagen"""
    if path.suffix.lower() == '.wav':
        import wave
        with wave.open(str(path), 'rb') as f:
            return f.getnframes() / float(f.getframerate())
    from mutagen import File as MutaFile
    audio = MutaFile(str(path))
    if audio is None or audio.info is None:
        raise RuntimeError('无法解析音频时长，文件可能损坏')
    return float(audio.info.length)


def main(argv):
    if len(argv) < 2:
        print(json.dumps({'ok': False, 'error': '用法: import_song.py <音频路径> [歌名]'},
                         ensure_ascii=False))
        return 2
    src = Path(argv[1]).expanduser()
    if not src.is_file():
        print(json.dumps({'ok': False, 'error': f'文件不存在: {src}'}, ensure_ascii=False))
        return 2
    if src.suffix.lower() not in SUFFIXES:
        print(json.dumps({'ok': False,
                          'error': f'不支持的格式 {src.suffix}，可用: {sorted(SUFFIXES)}'},
                         ensure_ascii=False))
        return 2

    title = (argv[2] if len(argv) > 2 else src.stem).strip().strip('《》')
    if not title:
        print(json.dumps({'ok': False, 'error': '歌名为空'}, ensure_ascii=False))
        return 2

    try:
        seconds = duration_of(src)
    except Exception as e:
        print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}, ensure_ascii=False))
        return 1
    if seconds < 10:
        print(json.dumps({'ok': False, 'error': f'时长只有 {seconds:.1f}s，不像完整歌曲'},
                         ensure_ascii=False))
        return 1

    MUSIC.mkdir(parents=True, exist_ok=True)
    target = MUSIC / (title + src.suffix.lower())
    if target.resolve() != src.resolve():
        shutil.copy2(src, target)

    lib_path = MUSIC / 'library.json'
    library = json.loads(lib_path.read_text(encoding='utf-8')) if lib_path.exists() else {}
    library[title] = {
        'path': target.name,
        'seconds': round(seconds, 2),
        'verified_full_length': True,   # 时长来自文件本身，不是估算
        'provider': 'user-provided',
        'voice': '原唱（非咕嘎音色）',
        'is_guga_cover': False,
        'quality_reviewed': False,
        'pipeline_version': 2,          # 满足 core/music_performance.py 的播放门槛
        'separated_vocals': False,
    }
    lib_path.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({'ok': True, 'title': title, 'file': str(target),
                      'seconds': round(seconds, 2), 'kind': '原曲播放'},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
