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

from installer import i18n, ui


def setup(cli_venv_dir: Path, *, auto_yes: bool) -> None:
    """``cli_venv_dir``: the cli component's own venv, i.e. root/cli/.venv."""
    if sys.platform == "win32":
        _setup_windows(cli_venv_dir)
    else:
        _setup_posix(cli_venv_dir, auto_yes=auto_yes)


def remove(*, auto_yes: bool) -> None:
    """The reverse of setup() -- surgical, not a wholesale rewrite: only
    ever removes exactly what setup() itself would have added (the shim
    file, the one PATH entry, the one rc-file block), never touches
    anything else already in the user's PATH or shell config.
    """
    if sys.platform == "win32":
        _remove_windows()
    else:
        _remove_posix(auto_yes=auto_yes)


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
        ui.warn(i18n.t("pathsetup.windows_exe_missing"))
        return

    bin_dir = _write_windows_shim(scripts_dir)
    if _is_on_user_path_windows(bin_dir):
        ui.ok(i18n.t("pathsetup.already_on_path", bin_dir=bin_dir))
        return

    _add_to_user_path_windows(bin_dir)
    ui.ok(i18n.t("pathsetup.windows_added", bin_dir=bin_dir))


def _remove_from_user_path_windows(bin_dir: Path) -> None:
    current = _read_user_path_windows()
    target = os.path.normcase(str(bin_dir).rstrip("\\"))
    kept = [p for p in current.split(";") if p and os.path.normcase(p.rstrip("\\")) != target]
    _write_user_path_windows(";".join(kept))
    _broadcast_environment_change()


def _remove_windows() -> None:
    bin_dir = _windows_bin_dir()
    shim_path = bin_dir / "rona.cmd"
    if shim_path.is_file():
        shim_path.unlink()
    try:
        if bin_dir.is_dir() and not any(bin_dir.iterdir()):
            bin_dir.rmdir()
    except OSError:
        pass

    if _is_on_user_path_windows(bin_dir):
        _remove_from_user_path_windows(bin_dir)
        ui.ok(i18n.t("pathsetup.windows_removed", bin_dir=bin_dir))
    else:
        ui.info(i18n.t("pathsetup.windows_not_on_path", bin_dir=bin_dir))


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


_POSIX_PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH"'
_POSIX_RC_MARKER = "# Added by the Rona installer"
_POSIX_RC_BLOCK = f"\n{_POSIX_RC_MARKER}\n{_POSIX_PATH_LINE}\n"


def _setup_posix(cli_venv_dir: Path, *, auto_yes: bool) -> None:
    bin_dir = _write_posix_shim(cli_venv_dir)
    if bin_dir is None:
        ui.warn(i18n.t("pathsetup.posix_script_missing"))
        return

    if _is_on_path(bin_dir):
        ui.ok(i18n.t("pathsetup.already_on_path", bin_dir=bin_dir))
        return

    rc_file = _rc_file_for_shell()
    ui.warn(i18n.t("pathsetup.posix_not_on_path", bin_dir=bin_dir))
    ui.info(i18n.t("pathsetup.posix_will_add_line", rc_file=rc_file))
    ui.info(f"  {_POSIX_PATH_LINE}")

    if not auto_yes and not ui.confirm(i18n.t("pathsetup.posix_confirm_add"), default=True):
        ui.info(i18n.t("pathsetup.posix_manual_hint", line=_POSIX_PATH_LINE))
        return

    with rc_file.open("a", encoding="utf-8") as handle:
        handle.write(_POSIX_RC_BLOCK)
    ui.ok(i18n.t("pathsetup.posix_rc_updated", rc_file=rc_file))


def _remove_posix(*, auto_yes: bool) -> None:
    bin_dir = _posix_bin_dir()
    shim_path = bin_dir / "rona"
    if shim_path.is_file():
        shim_path.unlink()
        ui.ok(i18n.t("pathsetup.posix_shim_removed", shim_path=shim_path))
    else:
        ui.info(i18n.t("pathsetup.posix_shim_not_found", shim_path=shim_path))

    rc_file = _rc_file_for_shell()
    if not rc_file.is_file():
        return
    content = rc_file.read_text(encoding="utf-8")
    if _POSIX_RC_BLOCK not in content:
        return

    if not auto_yes and not ui.confirm(
        i18n.t("pathsetup.posix_confirm_remove_rc", rc_file=rc_file), default=True
    ):
        ui.info(i18n.t("pathsetup.posix_rc_left_untouched", rc_file=rc_file))
        return

    rc_file.write_text(content.replace(_POSIX_RC_BLOCK, ""), encoding="utf-8")
    ui.ok(i18n.t("pathsetup.posix_rc_cleaned", rc_file=rc_file))
