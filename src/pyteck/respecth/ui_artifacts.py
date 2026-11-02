"""Small browser previews and deferred, disk-backed export archives."""
from pathlib import Path
import hashlib
import zipfile
from PIL import Image


def preview_image(path, max_side=1400):
    path=Path(path)
    signature=f'{path.resolve()}:{path.stat().st_mtime_ns}:{path.stat().st_size}:{max_side}'
    directory=path.parent/'.previews'; directory.mkdir(exist_ok=True)
    preview=directory/(hashlib.sha256(signature.encode()).hexdigest()+'.png')
    if not preview.exists():
        with Image.open(path) as image:
            # Bound the decoded source as well as the browser image.
            if image.width*image.height>25_000_000:
                raise ValueError('图片超过 2500 万像素，请缩小图尺寸或子图数量；原导出文件保留。')
            image.thumbnail((max_side,max_side))
            image.convert('RGB').save(preview,optimize=True)
    return str(preview)


def deferred_archive(directory, files, name='download.zip', limit=64*1024**2):
    """Return a callable: no ZIP construction on display or automatic polling."""
    directory=Path(directory); files=tuple(Path(p) for p in files)
    def generate():
        # Streamlit ultimately stores a download in memory; keep a firm bound.
        if sum(p.stat().st_size for p in files if p.is_file())>limit:
            raise ValueError('下载内容超过 64 MiB，请从结果目录读取大文件或缩小导出范围。')
        path=directory/name
        temporary=path.with_suffix('.zip.tmp')
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for item in files:
                if item.is_file(): archive.write(item,item.relative_to(directory))
        temporary.replace(path)
        with path.open('rb') as stream:
            return stream.read()
    return generate
