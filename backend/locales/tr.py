"""Turkish strings for the backend. `en.py` must define exactly the same
key set (enforced by tests/test_i18n.py).
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # -- prompts/persona.md's language directive (see app/prompts.py) -----------
    "prompt.primary_language_rule": (
        "Your default language is Turkish. However, if the user explicitly "
        "writes in another language, you must seamlessly adapt and respond "
        "in that language."
    ),
    # -- the worked example inside prompts/trigger.md and trigger/executor.py's
    # REPORTER_SYSTEM_PROMPT -- a plausible greeting in the active language,
    # so the few-shot example doesn't anchor the model to a fixed language.
    "prompt.example_greeting": "Nasılsın?",
    # -- app/main.py --------------------------------------------------------------
    "main.recursion_limit_reply": (
        "Bu istek beklenenden çok daha fazla araç adımı gerektirdi ve "
        "tur sınırına ulaştım. İsteği biraz daraltabilir misin, ya da "
        "nereden devam etmemi istediğini söyle."
    ),
    "main.auth_invalid_token": "Geçersiz ya da eksik bearer token",
    "main.model_call_failed": "Model çağrısı başarısız oldu: {exc}",
    "main.log_reconcile_failed": "konuşma kaydı senkronizasyonu başarısız oldu",
    "main.log_history_record_failed": "bir tur için sohbet geçmişi kaydedilemedi",
    # -- app/dashboard.py -----------------------------------------------------------
    "dashboard.not_editable": "Düzenlenemez: {names}",
    "dashboard.task_not_found": "Görev bulunamadı",
    "dashboard.run_not_found": "Kayıt bulunamadı",
    "dashboard.invalid_kind": "geçersiz tür: {kind}",
    "dashboard.run_not_reported": "Kayıt henüz kullanıcıya bildirilmedi",
    "dashboard.graph_not_ready": "Graf hazır değil",
    "dashboard.conversation_busy": "Konuşma meşgul",
    "dashboard.history_not_found": "Konuşma bulunamadı",
    "dashboard.folder_not_found": "Klasör bulunamadı",
    "dashboard.history_unavailable": "Sohbet geçmişi kullanılamıyor",
    "dashboard.memory_not_found": "#{id} numaralı anı bulunamadı.",
    "dashboard.archived_memory_not_found": "#{id} numaralı arşivlenmiş anı bulunamadı.",
    "dashboard.person_not_found": "#{id} numaralı kişi bulunamadı.",
    "dashboard.note_not_found": "#{id} numaralı not bulunamadı.",
    "dashboard.notes_not_installed": "Notlar paketi kurulu değil.",
    "dashboard.invalid_layer": "Geçersiz katman: {layer}. deep, seasonal veya short kullanın.",
    "dashboard.consolidation_busy": "Bir hafıza konsolidasyonu zaten sürüyor.",
    # -- app/prompts_api.py (prompt store HTTP hataları) ---------------------------------
    "prompts.not_found": "Prompt bulunamadı",
    "prompts.conflict": "Prompt başka bir yerden güncellendi; sürümünüz eski",
    "prompts.missing_placeholder": "Zorunlu placeholder eksik: {names}",
    "prompts.empty": "Bu prompt boş olamaz",
    "prompts.too_large": "Prompt en fazla {limit} bayt olabilir",
    "prompts.contract_warning": "Sözleşme işareti eksik olabilir: {markers}",
    # -- trigger/executor.py: outcome text stored on a task run -------------------------
    "trigger.outcome_timeout": "Çalışma {minutes} dakika sonra zaman aşımına uğradı.",
    "trigger.outcome_condition_not_met": "Koşul sağlanmadı.",
    "trigger.outcome_reported_failure": "Görev başarısız olduğunu bildirdi.",
    "trigger.outcome_abnormal_end": "Eylem çalıştırıldı ama çalışma anormal şekilde sona erdi: {loop_error}",
    "trigger.outcome_empty_message": "Yürütücü boş ya da geçersiz bir son mesaj döndürdü.",
    "trigger.outcome_not_active": "Çalışma başladığında görev aktif değildi.",
    "trigger.outcome_deactivated": "Görev yürütme sırasında pasife alındı.",
    # -- trigger/executor.py: log lines --------------------------------------------------
    "trigger.log_round": "[trigger] %s deneme %d tur %d llm %.1fsn",
    "trigger.log_report_ok": "[trigger] %s rapor tamam (özet %d karakter)",
    "trigger.log_report_fallback": "[trigger] %s rapor yedeği, ham raportör içeriği: %r",
    "trigger.log_reporter_failed": "[trigger] %s raportör başarısız: %s",
    "trigger.log_completed": "[trigger] %s tamamlandı (deneme %d)",
    "trigger.log_attempt_failed": "[trigger] %s deneme %d başarısız: %s",
    "trigger.log_failed_after_attempts": "[trigger] %s %d denemeden sonra başarısız oldu",
    "trigger.log_persist_failure_failed": "[trigger] %s başarısızlık kaydedilemedi: %s",
    "trigger.log_failed": "[trigger] %s başarısız: %s",
    "trigger.log_fire_skipped_inactive": "[trigger] %s tetikleme atlandı (görev aktif değil)",
    "trigger.log_fire_skipped_running": "[trigger] %s tetikleme atlandı (önceki çalışma sürüyor)",
    "trigger.log_fired": "[trigger] %s tetiklendi: %s",
    "trigger.log_fire_failed": "[trigger] %s için tetikleme başarısız: %s",
    # -- trigger/scheduler.py: log lines ---------------------------------------------------
    "trigger.log_missed": "[trigger] %s kaçırıldı: %s",
    "trigger.log_missed_event_failed": "[trigger] %s için kaçırılan-olay işlemi başarısız: %s",
    "trigger.log_db_not_found": "[trigger] veritabanı bulunamadı, görev kaydedilmedi",
    "trigger.log_register_failed": "[trigger] %s (%s) kaydedilemedi: %s",
    "trigger.log_scheduled_count": "[trigger] %d aktif görev zamanlandı",
    # -- subagents/runner.py: outcome text stored on a subagent run -----------------------
    "subagent.outcome_empty_message": "Alt ajan modeli boş bir son mesaj döndürdü.",
    "subagent.outcome_cancelled": "Görev tamamlanmadan iptal edildi.",
    "subagent.outcome_timeout": "Görev {seconds} saniye sonra zaman aşımına uğradı.",
    # -- subagents/runner.py: log lines -----------------------------------------------------
    "subagent.log_round": "[subagent] %s tur %d llm %.1fsn",
    "subagent.log_completed": "[subagent] %s tamamlandı (%s)",
    "subagent.log_timed_out": "[subagent] %s zaman aşımına uğradı (%s)",
    "subagent.log_failed": "[subagent] %s başarısız (%s): %s",
    "subagent.log_started": "[subagent] %s başladı (%s)",
    # -- toolbox/*.py: log lines --------------------------------------------------------------
    "toolbox.log_skip_tool": "toolbox: '%s' paketindeki araç atlanıyor: %s",
    "toolbox.log_skip_package": "toolbox: %s içindeki paket atlanıyor: %s",
    # -- graph/threads.py: log lines -----------------------------------------------------------
    "graph.log_purge_failed": "%s için konuşma temizliği başarısız oldu",
    # -- memory/ (Konsolidasyon): şema onarımı ve konsolidasyon log satırları ------------
    "memory.log_schema_upgraded": "[memory] memories tablosu güncellendi, eklenen kolonlar: %s",
    "memory.log_schema_failed": "[memory] şema kontrolü başarısız: %s",
    "memory.log_access_failed": "[memory] anı erişimi kaydedilemedi: %s",
    "memory.log_promoted": "[memory] #%d terfi etti %s -> %s (%d erişim): %s",
    "memory.log_archived": "[memory] #%d arşivlendi (%s, neden: %s): %s",
    "memory.log_deleted": "[memory] #%d silindi (short, %d erişim): %s",
    "memory.log_run_done": (
        "[memory] konsolidasyon (%s) tamamlandı: %d seasonal'a, %d deep'e terfi etti, "
        "%d arşivlendi, %d silindi"
    ),
    "memory.log_run_failed": "[memory] konsolidasyon (%s) başarısız: %s",
    "memory.log_scheduler_started": "[memory] konsolidasyon zamanlayıcısı başladı (her %d saatte bir)",
    "memory.log_scheduler_disabled": (
        "[memory] otomatik konsolidasyon kapalı (MEMORY_CONSOLIDATION_INTERVAL_HOURS=0)"
    ),
    "memory.log_scheduler_error": "[memory] konsolidasyon zamanlayıcısı hatası: %s",
    "memory.log_person_memories_archived": (
        "[memory] kişi #%d silindi, bağlı %d anı arşivlendi"
    ),
}
