"""Turkish strings for the web dashboard's BFF. Must define exactly the
same key set as `en.py` (enforced by tests/test_i18n.py).
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # -- host.py ---------------------------------------------------------------
    "webui.backend_dir_not_found": "Backend klasörü bulunamadı: {backend_dir}",
    "webui.already_running": "Backend zaten çalışıyor olarak izleniyor",
    "webui.exited_immediately": "Backend hemen sonlandı (kod {code})",
    "webui.started_pid": "PID {pid} başlatıldı",
    "webui.not_tracked": "Bu web sunucusu tarafından izlenen bir backend süreci yok",
    "webui.stop_requested": "Durdurma istendi",
    "webui.restart_too_soon": "Yeniden başlatma çok erken istendi; birkaç saniye bekle",
    # -- proxy.py ---------------------------------------------------------------
    "webui.backend_unreachable": "Backend'e ulaşılamıyor",
    "webui.backend_timeout": "Backend isteği zaman aşımına uğradı",
    "webui.backend_status_code": "durum {code}",
    # -- server.py ---------------------------------------------------------------
    "webui.unsupported_content_type": "Desteklenmeyen içerik türü",
    "webui.cross_site_blocked": "Siteler arası istek engellendi",
    "webui.frontend_not_built": "Frontend derlenmemiş",
    "webui.frontend_stale": (
        "Arayüz derlemesi kaynak kodundan eski (git pull sonrası npm run build "
        "çalıştırılmamış olabilir); tarayıcılar hâlâ eski arayüzü alıyor. "
        "'rona web build' ya da web-client/frontend içinde "
        "'npm ci && npm run build' çalıştır."
    ),
    # -- package_jobs.py ---------------------------------------------------------
    "webui.invalid_package_id": "Geçersiz paket id'si: {package_id}",
    "webui.package_job_busy": "Başka bir paket kurulum/güncelleme/kaldırma işlemi zaten çalışıyor",
    "webui.backend_python_missing": "Backend python bulunamadı: {path}",
    "webui.manager_no_output": "Manager komutu hiçbir çıktı üretmedi",
    "webui.manager_timeout": "Manager komutu zaman aşımına uğradı",
    "webui.package_job_timed_out": "Paket işlemi zaman aşımına uğradı ve sonlandırıldı",
    # -- auth.py (dashboard login) ----------------------------------------------
    "webui.login_required": "Giriş gerekli",
    "webui.invalid_password": "Parola hatalı",
    "webui.password_not_set": "Panel parolası ayarlanmamış; önce 'rona web password' çalıştırın",
    "webui.too_many_attempts": "Çok fazla hatalı deneme; {seconds} saniye sonra tekrar deneyin",
    "webui.password_wrong_current": "Mevcut parola hatalı",
    "webui.password_too_short": "Yeni parola en az {min} karakter olmalı",
    "webui.password_write_failed": "Yeni parola kaydedilemedi",
    "webui.session_secret_ephemeral": (
        "WEB_SESSION_SECRET boş; geçici bir anahtar kullanılıyor, bu yüzden "
        "oturumlar yeniden başlatmada kapanır. Kalıcı olması için "
        "'rona web password' çalıştırın."
    ),
    "webui.public_without_password": (
        "Başlatılmıyor: WEB_HOST {host} (loopback değil) ama panel parolası "
        "ayarlanmamış. Önce 'rona web password' çalıştırın."
    ),
    "webui.panel_locked_warning": (
        "Panel parolası ayarlanmamış; 'rona web password' çalıştırılana kadar "
        "panel kilitli kalır."
    ),
}
