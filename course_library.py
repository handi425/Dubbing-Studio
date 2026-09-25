"""Persistent course indexes and recursively imported media folders."""
import json
import os
import re
import uuid
from pathlib import Path, PurePosixPath

from engine import VIDEO_EXTENSIONS

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | {'.srt', '.vtt'}


def natural(value):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', value)]


class Courses:
    def __init__(self, data, default_root, app_root, subtitle):
        self.home = Path(data) / 'playlists'
        self.default_root = Path(default_root).resolve()
        self.app_root = Path(app_root).resolve()
        self.subtitle = subtitle

    def directory(self, course_id):
        if not re.fullmatch(r'[a-f0-9]{32}', course_id):
            raise ValueError('Playlist tidak ditemukan.')
        return self.home / course_id

    def read(self, course_id):
        if course_id == 'default':
            return dict(id='default', name=self.default_root.name, root=str(self.default_root), kind='local', status='ready')
        path = self.directory(course_id) / 'playlist.json'
        if not path.is_file():
            raise ValueError('Playlist tidak ditemukan.')
        return json.loads(path.read_text(encoding='utf-8'))

    def save(self, course):
        directory = self.directory(course['id'])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'playlist.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    def scan(self, course):
        root = Path(course['root']).resolve()
        if not root.is_dir():
            raise ValueError('Folder kursus tidak tersedia. Sambungkan drive atau periksa lokasi folder.')
        videos, errors, visited = [], [], set()
        def onerror(error):
            errors.append(str(error))
        for directory, dirs, files in os.walk(root, onerror=onerror, followlinks=False):
            resolved_directory = Path(directory).resolve()
            if resolved_directory in visited:
                dirs[:] = []
                continue
            visited.add(resolved_directory)
            dirs[:] = [name for name in dirs if not name.startswith('.')
                       and not (Path(directory) / name).is_symlink()
                       and (Path(directory) / name).resolve().is_relative_to(root)
                       and (course['kind'] == 'upload' or not (Path(directory) / name).resolve().is_relative_to(self.app_root))]
            for name in files:
                path = Path(directory) / name
                if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.resolve().is_relative_to(root):
                    continue
                try:
                    if not path.is_file():
                        continue
                    subtitle = self.subtitle(path)
                    if subtitle and not subtitle.resolve().is_relative_to(root):
                        subtitle = None
                    videos.append(dict(path=path.relative_to(root).as_posix(), name=path.stem,
                                       folder=path.parent.relative_to(root).as_posix(),
                                       size_mb=round(path.stat().st_size / 1024 ** 2, 1), subtitle=bool(subtitle)))
                except OSError as error:
                    errors.append(str(error))
        if errors:
            raise ValueError('Sebagian folder/file kursus tidak dapat dibaca. Periksa izin akses lalu pindai ulang.')
        return sorted(videos, key=lambda video: natural(video['path']))

    def summary(self, course):
        return {key: course.get(key) for key in ('id', 'name', 'kind', 'status', 'source_folder')} | dict(
            count=len(course.get('videos', [])), available=Path(course['root']).is_dir())

    def list(self):
        default = self.read('default')
        # Existing library remains available as the first course.
        try:
            default['videos'] = self.scan(default)
        except ValueError:
            default['videos'] = []
        result = [self.summary(default)]
        for path in self.home.glob('*/playlist.json'):
            course = json.loads(path.read_text(encoding='utf-8'))
            result.append(self.summary(course))
        return result

    def detail(self, course_id, refresh=False):
        course = self.read(course_id)
        if course_id == 'default' or refresh:
            course['videos'] = self.scan(course)
            if course_id != 'default':
                self.save(course)
        return self.summary(course) | dict(videos=course.get('videos', []))

    def add_local(self, folder, name=''):
        root = Path(folder.strip().strip('"')).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError('Masukkan lokasi lengkap folder kursus yang tersedia di komputer ini.')
        root = root.resolve()
        if root.is_relative_to(self.app_root):
            raise ValueError('Pilih folder kursus di luar folder aplikasi DubbingStudio.')
        if root == self.default_root:
            return self.detail('default')
        for path in self.home.glob('*/playlist.json'):
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved['kind'] == 'local' and Path(saved['root']) == root:
                return self.detail(saved['id'], refresh=True)
        course = dict(id=uuid.uuid4().hex, name=name.strip() or root.name, root=str(root), kind='local', status='ready')
        course['videos'] = self.scan(course)
        if not course['videos']:
            raise ValueError('Tidak ada video yang didukung dalam folder dan subfolder kursus ini.')
        self.save(course)
        return self.detail(course['id'])

    def begin_upload(self, name, source_folder=''):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Nama playlist wajib diisi.')
        course_id = uuid.uuid4().hex
        root = self.directory(course_id) / 'media'
        root.mkdir(parents=True)
        course = dict(id=course_id, name=name.strip()[:200], root=str(root), kind='upload', status='importing', videos=[], source_folder=source_folder)
        self.save(course)
        return self.summary(course)

    def upload(self, course_id, relative, uploaded):
        course = self.read(course_id)
        if course['kind'] != 'upload' or course['status'] != 'importing':
            raise ValueError('Playlist ini tidak sedang menerima unggahan.')
        relative = PurePosixPath(relative.replace('\\', '/'))
        if relative.is_absolute() or not relative.parts or any(
                part in {'.', '..'} or any(c in part for c in ':<>"|?*') or part.endswith((' ', '.'))
                for part in relative.parts):
            raise ValueError('Lokasi file unggahan tidak valid.')
        if relative.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError('Hanya video dan subtitle SRT/VTT yang dapat diimpor.')
        root = Path(course['root']).resolve()
        target = (root / str(relative)).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Lokasi file unggahan tidak valid.')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.uploading')
        try:
            uploaded.save(temporary)
            if target.suffix.lower() in {'.srt', '.vtt'} and temporary.stat().st_size > 5 * 1024 ** 2:
                raise ValueError('Ukuran subtitle maksimal 5 MB.')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def finish(self, course_id):
        course = self.read(course_id)
        if course['kind'] != 'upload':
            raise ValueError('Playlist bukan unggahan folder.')
        course['videos'] = self.scan(course)
        if not course['videos']:
            raise ValueError('Belum ada video dalam playlist ini.')
        course['status'] = 'ready'
        self.save(course)
        return self.detail(course_id)

    def resolve(self, course_id, relative):
        course = self.read(course_id)
        if course['status'] != 'ready':
            raise ValueError('Tunggu hingga impor playlist selesai.')
        root = Path(course['root']).resolve()
        source = (root / relative).resolve()
        if (not source.is_relative_to(root) or not source.is_file()
                or source.suffix.lower() not in VIDEO_EXTENSIONS
                or (course['kind'] == 'local' and source.is_relative_to(self.app_root))):
            raise ValueError('Video tidak ditemukan dalam playlist. Coba pindai ulang folder.')
        subtitle = self.subtitle(source)
        if subtitle and not subtitle.resolve().is_relative_to(root):
            subtitle = None
        return source, subtitle
