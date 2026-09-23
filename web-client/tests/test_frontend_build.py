import os

from webui import frontend_build


def _touch(path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_not_stale_without_a_build(tmp_path):
    frontend = tmp_path / "frontend"
    _touch(frontend / "src" / "main.tsx", 2000)

    assert frontend_build.is_stale(frontend, tmp_path / "dist" / "index.html") is False


def test_not_stale_without_a_source_checkout(tmp_path):
    dist_index = tmp_path / "dist" / "index.html"
    _touch(dist_index, 1000)

    assert frontend_build.is_stale(tmp_path / "frontend", dist_index) is False


def test_stale_when_a_source_file_is_newer_than_the_build(tmp_path):
    frontend = tmp_path / "frontend"
    dist_index = tmp_path / "dist" / "index.html"
    _touch(dist_index, 1000)
    _touch(frontend / "src" / "lib" / "storage.ts", 2000)

    assert frontend_build.is_stale(frontend, dist_index) is True


def test_not_stale_when_the_build_is_newer(tmp_path):
    frontend = tmp_path / "frontend"
    dist_index = tmp_path / "dist" / "index.html"
    _touch(frontend / "src" / "lib" / "storage.ts", 1000)
    _touch(frontend / "package.json", 1000)
    _touch(dist_index, 2000)

    assert frontend_build.is_stale(frontend, dist_index) is False


def test_package_lock_alone_does_not_count_as_a_source_change(tmp_path):
    frontend = tmp_path / "frontend"
    dist_index = tmp_path / "dist" / "index.html"
    _touch(frontend / "src" / "main.tsx", 1000)
    _touch(dist_index, 2000)
    _touch(frontend / "package-lock.json", 3000)

    assert frontend_build.is_stale(frontend, dist_index) is False
