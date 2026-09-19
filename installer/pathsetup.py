"""Put `rona` on PATH once the cli component is installed.

Windows: a tiny .cmd shim under %LOCALAPPDATA%\\Rona\\bin, plus that folder
added to the user's own PATH via HKCU\\Environment -- no admin rights
needed, and untouched if it's already there.

macOS/Linux: a shell shim under ~/.local/bin. If that folder isn't
already on PATH, this shows the exact rc-file line it would add and
asks before writing it (skipped with --yes/--json, which just do it).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from installer import ui


def setup(cli_venv_dir: Path, *, auto_yes: bool) -> None:
    """``cli_venv_dir``: the cli component's own venv, i.e. root/cli/.venv."""
    if sys.platform == "win32":
        _setup_windows(cli_venv_dir)
    else:
        _setup_posix(cli_venv_dir, auto_yes=auto_yes)


# ---- Windows ----------------------------------------------------------


def _windows_bin_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Rona" / "bin"


def _write_windows_shim(scripts_dir: Path) -> Path:
    bin_dir = _windows_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim_path = bin_dir / "rona.cmd"
    target = scripts_dir / "rona.exe"
    shim_path.write_text(f'@echo off\r\n"{target}" %*\r\n', encoding="utf-8")
    return bin_dir


def _read_user_path_windows() -> str:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
        try:
            value, _ = winreg.QueryValueEx(key, "Path")
            return value
        except FileNotFoundError:
            return ""


def _write_user_path_windows(value: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)


def _broadcast_environment_change() -> None:
    # Best-effort only -- some already-running apps pick up the PATH
    # change without a restart; a new terminal always sees it regardless.
    try:
        import ctypes

        result = ctypes.c_long()
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x1A, 0, "Environment", 0x0002, 5000, ctypes.byref(result)
        )
    except OSError:
        pass


def _is_on_user_path_windows(bin_dir: Path) -> bool:
    current = _read_user_path_windows()
    target = os.path.normcase(str(bin_dir).rstrip("\\"))
    return any(os.path.normcase(p.rstrip("\\")) == target for p in current.split(";") if p)


def _add_to_user_path_windows(bin_dir: Path) -> None:
    current = _read_user_path_windows()
    target = str(bin_dir)
    new_value = f"{current};{target}" if current else target
    _write_user_path_windows(new_value)
    _broadcast_environment_change()


def _setup_windows(cli_venv_dir: Path) -> None:
    scripts_dir = cli_venv_dir / "Scripts"
    if not (scripts_dir / "rona.exe").is_file():
        ui.warn("rona.exe bulunamadı, PATH kurulumu atlandı.")
        return

    bin_dir = _write_windows_shim(scripts_dir)
    if _is_on_user_path_windows(bin_dir):
        ui.ok(f"rona zaten PATH'te ({bin_dir}).")
        return

    _add_to_user_path_windows(bin_dir)
    ui.ok(f"rona PATH'e eklendi ({bin_dir}). Değişikliğin geçmesi için yeni bir terminal aç.")


# ---- macOS / Linux ------------------------------------------------------


def _posix_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def _write_posix_shim(cli_venv_dir: Path) -> Path | None:
    target = cli_venv_dir / "bin" / "rona"
    if not target.is_file():
        return None
    bin_dir = _posix_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim_path = bin_dir / "rona"
    shim_path.write_text(f'#!/usr/bin/env bash\nexec "{target}" "$@"\n', encoding="utf-8")
    shim_path.chmod(0o755)
    return bin_dir


def _is_on_path(bin_dir: Path) -> bool:
    target = os.path.normpath(str(bin_dir))
    return any(
        os.path.normpath(entry) == target for entry in os.environ.get("PATH", "").split(os.pathsep) if entry
    )


def _rc_file_for_shell() -> Path:
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    if "zsh" in shell:
        return home / ".zshrc"
    if "bash" in shell:
        bashrc = home / ".bashrc"
        return bashrc if bashrc.exists() else home / ".profile"
    return home / ".profile"


def _setup_posix(cli_venv_dir: Path, *, auto_yes: bool) -> None:
    bin_dir = _write_posix_shim(cli_venv_dir)
    if bin_dir is None:
        ui.warn("rona betiği bulunamadı, PATH kurulumu atlandı.")
        return

    if _is_on_path(bin_dir):
        ui.ok(f"rona zaten PATH'te ({bin_dir}).")
        return

    rc_file = _rc_file_for_shell()
    line = 'export PATH="$HOME/.local/bin:$PATH"'
    ui.warn(f"{bin_dir} PATH'te değil.")
    ui.info(f"Şu satır {rc_file} dosyasına eklenecek:")
    ui.info(f"  {line}")

    if not auto_yes and not ui.confirm("Eklensin mi?", default=True):
        ui.info(f"Elle eklemek istersen: {line}")
        return

    with rc_file.open("a", encoding="utf-8") as handle:
        handle.write(f"\n# Added by the Rona installer\n{line}\n")
    ui.ok(f"{rc_file} güncellendi. Geçmesi için yeni bir terminal aç ya da `source {rc_file}` çalıştır.")
