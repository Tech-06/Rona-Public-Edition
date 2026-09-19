"""Turkish strings for the installer. Default language -- these are the
literal strings the installer shipped with before language support
existed. `en.py` must define exactly the same key set (enforced by
tests/test_i18n.py).
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # -- shared --------------------------------------------------------------
    "common.empty": "(boş)",
    "common.cancelled": "Vazgeçildi.",
    # -- ui.py -----------------------------------------------------------------
    "ui.confirm_default_yes_suffix": "[E/h]",
    "ui.confirm_default_no_suffix": "[e/H]",
    "ui.confirm_yes_words": "e,evet,y,yes",
    "ui.select_components_prompt": "Kurulacak bileşenleri seç (numara yaz + Enter: seç/kaldır, boş satır: onayla)",
    # -- main.py ---------------------------------------------------------------
    "main.python_too_old": "Python {min_major}.{min_minor}+ gerekli, bulunan: {found_major}.{found_minor}.",
    "main.git_not_found": "git bulunamadı (bu kurulum için gerekli değil, sadece bilgi amaçlı).",
    "main.no_components_selected": "Hiçbir bileşen seçilmedi, çıkılıyor.",
    "main.node_required": "Node.js olmadan web paneli kurulamaz (--components ile çıkarabilirsin).",
    "main.auth_token_set": "AUTH_TOKEN ayarlandı (backend ve web .env dosyaları eşleşiyor).",
    "main.step_precheck": "Ön kontroller",
    "main.step_summary": "Özet",
    "main.status_done": "tamam",
    "main.status_failed": "başarısız",
    "main.result_line": "{name}: {status}",
    "main.next_steps_heading": "Sıradaki adımlar:",
    "main.next_step_model": "  rona edit model flash   # zorunlu: Flash model bilgilerini gir",
    "main.repair_none_found": "Onarılacak kurulu bir bileşen bulunamadı.",
    "main.unknown_components": "Bilinmeyen bileşen(ler): {names}",
    "main.status_reinstall": "kurulu — yeniden kurulacak",
    "main.label_cli": "CLI      rona yönetim aracı",
    "main.label_backend": "Backend  Rona çekirdeği (:8000)",
    "main.label_web": "Web      Web paneli (:8016)",
    # -- prereq.py -----------------------------------------------------------------
    "prereq.no_package_manager": "{name} bulunamadı ve otomatik kurulum için bir paket yöneticisi tespit edilemedi.",
    "prereq.install_manually": "{name} kurulumunu elle yap, ardından scripti tekrar çalıştır.",
    "prereq.not_found": "{name} bulunamadı.",
    "prereq.will_run": "Şu komut çalıştırılacak: {command}",
    "prereq.confirm_install": "{name} kurulsun mu?",
    "prereq.install_failed_exc": "{name} kurulumu başarısız oldu: {exc}",
    "prereq.install_failed_code": "{name} kurulumu başarısız oldu (çıkış kodu {code}).",
    "prereq.installed_ok": "{name} kuruldu.",
    "prereq.installed_not_on_path": (
        "{name} kuruldu ama bu oturumda PATH'te henüz görünmüyor. "
        "Yeni bir terminal açıp scripti tekrar çalıştır."
    ),
    # -- steps/*.py: text shared verbatim by all three components -------------------
    "steps.common.removing_venv": "Var olan sanal ortam kaldırılıyor...",
    "steps.common.creating_venv": "Sanal ortam oluşturuluyor...",
    "steps.common.venv_create_failed": "Sanal ortam oluşturulamadı.",
    "steps.common.deps_failed": "Bağımlılık kurulumu başarısız oldu.",
    # -- steps/cli.py -----------------------------------------------------------------
    "steps.cli.title": "CLI (rona)",
    "steps.cli.installing": "rona-cli kuruluyor (pip install -e .)...",
    "steps.cli.install_failed": "rona-cli kurulumu başarısız oldu.",
    "steps.cli.done": "rona CLI kuruldu.",
    # -- steps/backend.py -----------------------------------------------------------------
    "steps.backend.title": "Backend",
    "steps.backend.installing_deps": "Bağımlılıklar kuruluyor (bu biraz sürebilir)...",
    "steps.backend.preparing_db": "Veritabanı hazırlanıyor...",
    "steps.backend.db_failed": "Veritabanı hazırlığı başarısız oldu.",
    "steps.backend.done": "Backend kuruldu.",
    # -- steps/web.py -----------------------------------------------------------------
    "steps.web.title": "Web paneli",
    "steps.web.installing_deps": "Bağımlılıklar kuruluyor...",
    "steps.web.npm_not_found": "npm bulunamadı; web paneli derlenemedi.",
    "steps.web.installing_frontend_deps": "Frontend bağımlılıkları kuruluyor ({cmd})...",
    "steps.web.npm_install_failed": "npm install/ci başarısız oldu.",
    "steps.web.building_frontend": "Frontend derleniyor (npm run build)...",
    "steps.web.npm_build_failed": "npm run build başarısız oldu.",
    "steps.web.done": "Web paneli kuruldu.",
    # -- pathsetup.py -----------------------------------------------------------------
    "pathsetup.windows_exe_missing": "rona.exe bulunamadı, PATH kurulumu atlandı.",
    "pathsetup.already_on_path": "rona zaten PATH'te ({bin_dir}).",
    "pathsetup.windows_added": "rona PATH'e eklendi ({bin_dir}). Değişikliğin geçmesi için yeni bir terminal aç.",
    "pathsetup.posix_script_missing": "rona betiği bulunamadı, PATH kurulumu atlandı.",
    "pathsetup.posix_not_on_path": "{bin_dir} PATH'te değil.",
    "pathsetup.posix_will_add_line": "Şu satır {rc_file} dosyasına eklenecek:",
    "pathsetup.posix_confirm_add": "Eklensin mi?",
    "pathsetup.posix_manual_hint": "Elle eklemek istersen: {line}",
    "pathsetup.posix_rc_updated": (
        "{rc_file} güncellendi. Geçmesi için yeni bir terminal aç ya da `source {rc_file}` çalıştır."
    ),
    "pathsetup.windows_removed": "rona PATH'ten kaldırıldı ({bin_dir}).",
    "pathsetup.windows_not_on_path": "rona zaten PATH'te değildi ({bin_dir}).",
    "pathsetup.posix_shim_removed": "rona betiği kaldırıldı ({shim_path}).",
    "pathsetup.posix_shim_not_found": "rona betiği zaten yoktu ({shim_path}).",
    "pathsetup.posix_confirm_remove_rc": "{rc_file} dosyasına eklenen satır kaldırılsın mı?",
    "pathsetup.posix_rc_left_untouched": "{rc_file} dosyasına dokunulmadı.",
    "pathsetup.posix_rc_cleaned": "{rc_file} dosyasından kaldırıldı.",
    # -- wizard.py -----------------------------------------------------------------
    "wizard.field_name": "Model adı",
    "wizard.field_url": "API taban URL'si",
    "wizard.field_key": "API anahtarı",
    "wizard.field_headers": "Ek HTTP başlıkları (JSON, boş = yok)",
    "wizard.embedding_field_key": "Google API anahtarı",
    "wizard.embedding_field_name": "Embedding model adı",
    "wizard.invalid_choice": "Geçersiz seçim.",
    "wizard.required_hint": "gerekli ama",
    "wizard.optional_hint": "opsiyonel;",
    "wizard.step_hint": "Bu adım {hint} istersen 's' yazarak atlayabilirsin.",
    "wizard.test_ok": "Test başarılı.",
    "wizard.test_failed": "Test başarısız: {detail}",
    "wizard.choice_retry": "Tekrar gir",
    "wizard.choice_save_anyway": "Yine de kaydet",
    "wizard.choice_skip": "Atla",
    "wizard.title": "Yapılandırma sihirbazı",
    "wizard.intro": (
        "Şimdi Flash/Pro/embedding model ayarlarını gireceğiz. "
        "Her adımda 's' yazarak o adımı atlayabilirsin."
    ),
    "wizard.section_flash": "Flash model",
    "wizard.pro_heading": "Pro model",
    "wizard.pro_same_as_flash": "Flash ile aynı ayarlar kullanılsın mı?",
    "wizard.pro_same_ok": "Pro, Flash ile aynı ayarlanacak.",
    "wizard.section_pro": "Pro model (opsiyonel)",
    "wizard.section_embedding": "Embedding (hafıza için, opsiyonel)",
    "wizard.summary_title": "Yapılandırma özeti",
    "wizard.summary_flash_skipped": "Flash atlandı -- doldurulmadan backend başlamaz: `rona edit model flash`",
    "wizard.summary_flash_ok": "Flash ayarlandı.",
    "wizard.summary_pro_skipped": "Pro atlandı (opsiyonel): `rona edit model pro`",
    "wizard.summary_pro_ok": "Pro ayarlandı.",
    "wizard.summary_embedding_skipped": "Embedding atlandı (opsiyonel, hafıza aracı için gerekli): `rona edit model embedding`",
    "wizard.summary_embedding_ok": "Embedding ayarlandı.",
    # -- steps/tools.py -----------------------------------------------------------
    "tools_step.title": "İsteğe bağlı araç paketleri",
    "tools_step.git_missing": (
        "git bulunamadı, araç paketi kurulumu atlandı "
        "(sonra `rona tools install <id>` ile kurabilirsin)."
    ),
    "tools_step.catalog_unreachable": "Araç paketi kataloğuna ulaşılamadı, bu adım atlandı.",
    "tools_step.none_selected": "Hiçbir paket seçilmedi.",
    "tools_step.installing": "{id} kuruluyor...",
    "tools_step.installed_summary": "Kurulan paketler: {ids}",
    "tools_step.failed_summary": "Kurulamayan paketler: {ids}",
    # -- uninstall.py (new) -----------------------------------------------------------
    "uninstall.item_environments": "Ortamlar (sanal ortamlar, node_modules, derlenen panel)",
    "uninstall.item_path": "PATH entegrasyonu (rona komutu)",
    "uninstall.item_state": "Kurulum durumu (~/.rona/config.json)",
    "uninstall.item_user_data": "Kullanıcı verisi (.env dosyaları, veritabanı, log)",
    "uninstall.item_tool_packages": "Kurulu araç paketleri",
    "uninstall.item_runtime": "Çalışma artıkları (pid, lock, log dosyaları)",
    "uninstall.title": "Rona kaldırma",
    "uninstall.nothing_found": "Kaldırılacak bir şey bulunamadı.",
    "uninstall.process_running": "{label} çalışıyor görünüyor (pid {pid}).",
    "uninstall.confirm_stop": "{label} durdurulsun mu?",
    "uninstall.process_stopped": "{label} durduruldu.",
    "uninstall.items_required": "Etkileşimsiz modda --items ile neyin kaldırılacağını belirt.",
    "uninstall.unknown_items": "Bilinmeyen öğe(ler): {names}",
    "uninstall.none_selected": "Hiçbir şey seçilmedi, çıkılıyor.",
    "uninstall.user_data_warning": (
        "Kullanıcı verisi API anahtarlarını, anıları, kişileri ve görevleri içerir "
        "ve geri alınamaz şekilde silinecek."
    ),
    "uninstall.confirm_user_data": "Kullanıcı verisi gerçekten silinsin mi?",
    "uninstall.user_data_kept": "Kullanıcı verisi korundu.",
    "uninstall.done": "Kaldırıldı: {items}",
    "uninstall.repo_kept_hint": "Bu klasör (repo) silinmedi; kalanı kaldırmak için elle sil.",
}
