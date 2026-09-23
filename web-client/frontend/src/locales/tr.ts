// Turkish strings for the web dashboard. Default locale -- these are the
// literal strings the frontend shipped with before language support
// existed. `en.ts` is typed against this file's key set (`Record<keyof
// typeof tr, string>`), so a missing/extra key there is a build error.
export const tr = {
  // -- common (reused across several panels/sections) -------------------------------
  "common.save": "Kaydet",
  "common.saving": "Kaydediliyor...",
  "common.save_failed": "Kaydedilemedi",
  "common.action_failed": "İşlem başarısız oldu",
  "common.configured": "yapılandırıldı",

  // -- settings/AppearanceSection.tsx -------------------------------------------------
  "appearance.theme_title": "Tema",
  "appearance.theme_description":
    "Arayüzün açık, koyu ya da işletim sistemi ayarını takip eden bir görünümde çalışmasını seç.",
  "appearance.theme_system": "Sistem",
  "appearance.theme_light": "Açık",
  "appearance.theme_dark": "Koyu",
  "appearance.language_title": "Dil",
  "appearance.language_description":
    "Panelin hangi dilde görüneceğini seç. Bu seçim yalnızca bu tarayıcıyı etkiler.",
  "appearance.language_tr": "Türkçe",
  "appearance.language_en": "English",
  "appearance.install_title": "Uygulama",
  "appearance.install_description": "Rona'yı ana ekranına ekle, tarayıcı yerine ayrı bir uygulama olarak aç.",
  "appearance.install_button": "Uygulama olarak yükle",
  "appearance.install_insecure_hint": "Uygulama olarak yüklemek için paneli HTTPS üzerinden aç.",

  // -- lib/toolLabels.ts ---------------------------------------------------------------
  "tool.get_time": "Saat kontrol ediliyor",
  "tool.web_search": "Webde aranıyor",
  "tool.web_scraper": "Sayfa okunuyor",
  "tool.get_weather": "Hava durumu alınıyor",
  "tool.translate_text": "Çevriliyor",
  "tool.get_events": "Takvim kontrol ediliyor",
  "tool.add_event": "Takvime ekleniyor",
  "tool.edit_event": "Takvim güncelleniyor",
  "tool.delete_event": "Takvimden siliniyor",
  "tool.get_contacts": "Kişiler taranıyor",
  "tool.add_contact": "Kişi ekleniyor",
  "tool.edit_contact": "Kişi güncelleniyor",
  "tool.delete_contact": "Kişi siliniyor",
  "tool.send_email": "E-posta gönderiliyor",
  "tool.get_recent_emails": "E-postalar taranıyor",
  "tool.add_note": "Not kaydediliyor",
  "tool.get_notes": "Notlara bakılıyor",
  "tool.edit_note": "Not güncelleniyor",
  "tool.delete_note": "Not siliniyor",
  "tool.add_person": "Kişi ekleniyor",
  "tool.get_people": "Kişiler taranıyor",
  "tool.edit_person": "Kişi güncelleniyor",
  "tool.delete_person": "Kişi siliniyor",
  "tool.search_person": "Kişi aranıyor",
  "tool.add_memory": "Hafızaya yazılıyor",
  "tool.get_memories": "Hafızada araştırılıyor",
  "tool.edit_memory": "Hafıza güncelleniyor",
  "tool.delete_memory": "Hafızadan siliniyor",
  "tool.search_memories": "Hafızada araştırılıyor",
  "tool.start_subagent": "Arka plan ajanı başlatılıyor",
  "tool.list_subagents": "Arka plan ajanları kontrol ediliyor",
  "tool.get_subagent_report": "Ajan raporu alınıyor",
  "tool.dismiss_subagent_report": "Ajan raporu kapatılıyor",
  "tool.create_task": "Görev planlanıyor",
  "tool.list_tasks": "Zamanlanmış görevler kontrol ediliyor",
  "tool.get_task": "Görev kontrol ediliyor",
  "tool.update_task": "Görev güncelleniyor",
  "tool.delete_task": "Görev siliniyor",
  "tool.get_task_run": "Görev sonucu kontrol ediliyor",
  "tool.dismiss_task_run": "Görev bildirimi kapatılıyor",
  "tool.bb_get_courses": "Dersler kontrol ediliyor",
  "tool.bb_get_announcements": "Duyurular kontrol ediliyor",
  "tool.bb_get_calendar": "Blackboard takvimi kontrol ediliyor",
  "tool.bb_get_assignments": "Ödevler kontrol ediliyor",
  "tool.bb_get_course_content": "Ders içeriği taranıyor",
  "tool.bb_get_item": "İçerik açılıyor",
  "tool.bb_get_assignment_detail": "Ödev kontrol ediliyor",
  "tool.bb_get_grades": "Notlar kontrol ediliyor",
  "tool.fallback_running": "{name} çalıştırılıyor",
  "tool.evaluating_results": "Sonuçlar değerlendiriliyor",
  "tool.thinking": "Düşünülüyor",
  "tool.preparing_confirmation": "Onay için hazırlanıyor",

  // -- settings/ChatsSection.tsx ---------------------------------------------------------
  "chats.ttl_off": "Kapalı",
  "chats.ttl_1h": "1 saat",
  "chats.ttl_2h": "2 saat",
  "chats.ttl_6h": "6 saat",
  "chats.ttl_1d": "1 gün",
  "chats.ttl_7d": "7 gün",
  "chats.ttl_30d": "30 gün",
  "chats.ttl_custom": "Özel…",
  "chats.seconds_placeholder": "saniye",
  "chats.seconds_hint": "saniye (0 = kapalı)",
  "chats.invalid_ttl": "Geçersiz süre değeri",
  "chats.export_failed": "Dışa aktarılamadı",
  "chats.delete_partial_failure":
    "Tarayıcıdaki sohbetler silindi. Sunucudaki geçmiş silinemedi (backend'e ulaşılamadı) — backend açıkken tekrar dene.",
  "chats.delete_all_success": "Tüm sohbetler tarayıcından ve sunucudan silindi.",
  "chats.retention_title": "Geçmiş saklama süresi",
  "chats.retention_description":
    "Bir süre sonra boşta kalan sohbetler sunucudan kalıcı olarak silinir. Sabitlenen sohbetler bu süreden muaftır. Varsayılan: kapalı (hiç silinmez).",
  "chats.context_limit_title": "Model bağlam sınırı",
  "chats.context_limit_description":
    "Bu sınır sohbetin kalıcı geçmişini budar ve saklama süresinden bağımsız çalışır. 0 yaparsan budama yapılmaz — token maliyeti ve zaman aşımı riski artar.",
  "chats.messages_hint": "mesaj (0 = sınırsız)",
  "chats.save": "Kaydet",
  "chats.unsaved_changes": "Kaydedilmemiş değişiklik var",
  "chats.data_title": "Veri",
  "chats.export_button": "Tüm sohbetleri dışa aktar (JSON)",
  "chats.delete_all_button": "Tüm sohbetleri sil",
  "chats.delete_confirm_instruction":
    'Bu işlem tarayıcıdaki ve sunucudaki tüm sohbetleri kalıcı olarak siler (sabitlenmiş olanlar dahil) ve geri alınamaz. Onaylamak için "{word}" yaz.',
  "chats.deleting": "Siliniyor...",
  "chats.confirm_and_delete": "Onayla ve sil",
  "chats.delete_confirm_word": "SİL",
  "chats.export_filename_prefix": "rona-sohbetler",

  // -- dashboard/StatusPanel.tsx ---------------------------------------------------------
  "status.start": "Başlat",
  "status.restart": "Yeniden başlat",
  "status.stop": "Durdur",
  "status.running_badge": "Çalışıyor",
  "status.stopped_badge": "Kapalı",
  "status.managed_by_systemd": "systemd üzerinden yönetiliyor",
  "status.uptime": "Çalışma süresi",
  "status.model": "Model",
  "status.pro_model": "Pro model",
  "status.not_configured": "yok",
  "status.scheduler": "Zamanlayıcı",
  "status.scheduler_running": "çalışıyor",
  "status.scheduler_stopped": "durdu",
  "status.active_conversations": "Sohbet sayısı",
  "status.running_agents": "Çalışan ajan",
  "status.running_tasks": "Çalışan görev",
  "status.database": "Veritabanı",
  "status.chat_history": "Sohbet geçmişi",
  "status.log_file": "Log dosyası",
  "status.hours_minutes": "{hours} sa {minutes} dk",
  "status.minutes": "{minutes} dk",

  // -- dashboard/ConnectionsPanel.tsx -----------------------------------------------------
  "connections.probe_failed": "Test başarısız oldu",
  "connections.title": "Bağlantılar",
  "connections.probing": "Test ediliyor...",
  "connections.probe_now": "Şimdi test et",
  "connections.flash_model": "Flash model",
  "connections.pro_model": "Pro model",
  "connections.gemini_embedding": "Gemini embedding (hafıza)",
  "connections.checkpoint_db": "Sohbet geçmişi (checkpoint)",
  "connections.packages_title": "Araç paketleri",
  "connections.no_packages": "Kurulu isteğe bağlı araç paketi yok. Eklemek için:",
  "connections.missing": "eksik: {fields}",
  "connections.missing_short": "eksik",
  "connections.live": "canlı",
  "connections.error_short": "hata",
  "common.continue": "Devam et",
  "connections.package_id_placeholder": "paket_id",
  "connections.configure": "Yapılandır",
  "connections.close": "Kapat",
  "connections.config_load_failed": "Yapılandırma okunamadı",
  "connections.secret_set": "(ayarlandı, değiştirmek için yaz)",
  "connections.secret_unset": "(ayarlanmadı)",
  "connections.list_placeholder": "virgülle ayırın",
  "connections.actions_title": "İşlemler",
  "connections.action_running": "Çalışıyor...",
  "connections.action_continue": "Devam et",

  // -- common (more) ------------------------------------------------------------------
  "common.delete": "Sil",

  // -- settings/sections.ts, SettingsRail.tsx, SettingsModal.tsx -----------------------
  "settings.section_appearance": "Görünüm",
  "settings.section_chats": "Sohbetler",
  "settings.section_status": "Durum",
  "settings.section_connections": "Bağlantılar",
  "settings.section_advanced": "Gelişmiş",
  "settings.section_tools": "Araçlar",
  "settings.section_tasks": "Görevler",
  "settings.section_subagents": "Ajanlar",
  "settings.section_logs": "Loglar",
  "settings.section_data": "Veri",
  "settings.modal_title": "Ayarlar",
  "settings.close": "Kapat",

  // -- dashboard/ConfigPanel.tsx ---------------------------------------------------------
  "config.group_general": "Genel",
  "config.group_model": "Model",
  "config.group_chat": "Sohbet",
  "config.group_subagents": "Arka plan ajanları",
  "config.group_tasks": "Zamanlanmış görevler",
  "config.group_web": "Web arayüzü",

  // -- layout/Sidebar.tsx -----------------------------------------------------------------
  "sidebar.conversation_removed_from_folder": "Sohbet klasörden çıkarıldı.",
  "sidebar.new_chat": "Yeni sohbet",
  "sidebar.pinned_heading": "Sabitlenenler",
  "sidebar.folders_heading": "Klasörler",
  "sidebar.chats_heading": "Sohbetler",
  "sidebar.new_folder": "Yeni klasör",
  "sidebar.folder_name_placeholder": "Klasör adı",
  "sidebar.no_chats_yet": "Henüz sohbet yok.",
  "sidebar.delete_chat_title": "Sohbeti sil",
  "sidebar.delete_chat_description": "Bu sohbet kalıcı olarak silinecek. Bu işlem geri alınamaz.",
  "sidebar.backend_checking": "Kontrol ediliyor",
  "sidebar.backend_up": "Backend açık",
  "sidebar.backend_down": "Backend kapalı",

  // -- layout/ConversationRow.tsx -----------------------------------------------------------
  "row.pinned": "Sohbet sabitlendi.",
  "row.unpinned": "Sabitleme kaldırıldı.",
  "row.pin_save_failed": "Sabitleme sunucuya kaydedilemedi, geri alındı.",
  "row.moved_to_folder": 'Sohbet "{folder}" klasörüne taşındı.',
  "row.untitled_chat": "Sohbet",
  "row.chat_menu": "Sohbet menüsü",
  "row.rename": "Yeniden adlandır",
  "row.unpin": "Sabitlemeyi kaldır",
  "row.pin": "Sabitle",
  "row.move_to_folder": "Klasöre taşı",
  "row.remove_from_folder": "Klasörden çıkar",
  "row.no_folders_yet": "Henüz klasör yok.",

  // -- common (more) ------------------------------------------------------------------
  "common.loading": "Yükleniyor...",

  // -- dashboard/TasksPanel.tsx -----------------------------------------------------------
  "tasks.confirm_delete": '"{name}" görevini silmek istediğine emin misin?',
  "tasks.no_tasks": "Zamanlanmış görev yok.",
  "tasks.next_run_label": "Sonraki çalışma: {value}",
  "tasks.history_button": "Geçmiş",
  "tasks.deactivate": "Durdur",
  "tasks.activate": "Etkinleştir",
  "tasks.no_runs_yet": "Henüz çalışma kaydı yok.",

  // -- dashboard/DataPanel.tsx -----------------------------------------------------------
  "data.tab_notes": "Notlar",
  "data.tab_people": "Kişiler",
  "data.tab_memories": "Hafıza",
  "data.notes_not_installed": "Not aracı kurulu değil. Eklemek için:",
  "data.no_notes": "Not yok.",
  "data.no_people": "Kişi yok.",
  "data.no_memories": "Hafıza kaydı yok.",

  // -- layout/FolderSection.tsx -----------------------------------------------------------
  "folder.menu_label": "Klasör menüsü",
  "folder.delete": "Klasörü sil",
  "folder.deleted_announcement": '"{name}" klasörü silindi, sohbetler klasörsüz listeye taşındı.',
  "folder.empty": "Boş klasör.",

  // -- settings/RestartBanner.tsx -----------------------------------------------------------
  "restart.required_message": "Değişikliklerin uygulanması için sunucunun yeniden başlatılması gerekiyor.",
  "restart.restarting": "Yeniden başlatılıyor...",
  "restart.restart_now": "Şimdi yeniden başlat",
  "restart.manual_required": "Otomatik yeniden başlatma kullanılamıyor — backend'i elle yeniden başlat (python run.py).",

  // -- hooks/useChat.ts -----------------------------------------------------------------
  "chat.approve_text": "evet, onaylıyorum",
  "chat.reject_text": "hayır, iptal et",

  // -- chat/Composer.tsx -----------------------------------------------------------------
  "composer.confirm_placeholder": "Onaylıyor musun? Yanıtını yaz...",
  "composer.approve": "Onayla",
  "composer.reject": "Reddet",
  "composer.send": "Gönder",

  // -- dashboard/LogsPanel.tsx -----------------------------------------------------------
  "logs.all_levels": "Tüm seviyeler",
  "logs.search_placeholder": "Ara...",
  "logs.no_logs": "Henüz log yok.",

  // -- dashboard/ToolsPanel.tsx -----------------------------------------------------------
  "tools.registered_count": "{count} araç kayıtlı",
  "tools.background_badge": "arka plan",
  "tools.requires_confirmation_badge": "onay gerekir",

  // -- chat/ProgressIndicator.tsx -----------------------------------------------------------
  "progress.duration_seconds": "{value} sn",
  "progress.steps_count": "{count} adım",

  // -- common (more) ------------------------------------------------------------------
  "common.cancel": "Vazgeç",

  // -- api/sse.ts -----------------------------------------------------------------
  "sse.request_failed": "İstek başarısız oldu.",
  "sse.unknown_error": "Bilinmeyen hata.",

  // -- layout/MobileTopBar.tsx -----------------------------------------------------------
  "mobile.open_chats": "Sohbetleri aç",

  // -- dashboard/SubagentsPanel.tsx -----------------------------------------------------
  "subagents.no_runs": "Arka plan ajan çalışması yok.",

  // -- chat/MessageList.tsx -----------------------------------------------------------
  "messages.empty_prompt": "Bugün ne var aklında?",

  // -- hooks/usePoll.ts -----------------------------------------------------------
  "poll.connection_error": "Bağlantı hatası",

  // -- App.tsx -----------------------------------------------------------
  "app.close_sidebar": "Kenar çubuğunu kapat",
} satisfies Record<string, string>;
