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
}
