import type { ProgressEvent } from "../types";

const TOOL_LABELS: Record<string, string> = {
  get_time: "Saat kontrol ediliyor",
  web_search: "Webde aranıyor",
  web_scraper: "Sayfa okunuyor",
  get_weather: "Hava durumu alınıyor",
  translate_text: "Çevriliyor",
  get_events: "Takvim kontrol ediliyor",
  add_event: "Takvime ekleniyor",
  edit_event: "Takvim güncelleniyor",
  delete_event: "Takvimden siliniyor",
  get_contacts: "Kişiler taranıyor",
  add_contact: "Kişi ekleniyor",
  edit_contact: "Kişi güncelleniyor",
  delete_contact: "Kişi siliniyor",
  send_email: "E-posta gönderiliyor",
  get_recent_emails: "E-postalar taranıyor",
  add_note: "Not kaydediliyor",
  get_notes: "Notlara bakılıyor",
  edit_note: "Not güncelleniyor",
  delete_note: "Not siliniyor",
  add_person: "Kişi ekleniyor",
  get_people: "Kişiler taranıyor",
  edit_person: "Kişi güncelleniyor",
  delete_person: "Kişi siliniyor",
  search_person: "Kişi aranıyor",
  add_memory: "Hafızaya yazılıyor",
  get_memories: "Hafızada araştırılıyor",
  edit_memory: "Hafıza güncelleniyor",
  delete_memory: "Hafızadan siliniyor",
  search_memories: "Hafızada araştırılıyor",
  start_subagent: "Arka plan ajanı başlatılıyor",
  list_subagents: "Arka plan ajanları kontrol ediliyor",
  get_subagent_report: "Ajan raporu alınıyor",
  dismiss_subagent_report: "Ajan raporu kapatılıyor",
  create_task: "Görev planlanıyor",
  list_tasks: "Zamanlanmış görevler kontrol ediliyor",
  get_task: "Görev kontrol ediliyor",
  update_task: "Görev güncelleniyor",
  delete_task: "Görev siliniyor",
  get_task_run: "Görev sonucu kontrol ediliyor",
  dismiss_task_run: "Görev bildirimi kapatılıyor",
};

function truncate(value: string, max = 40): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function detail(name: string, args?: Record<string, unknown>): string | null {
  if (!args) return null;
  if (name === "web_search" && typeof args.query === "string") {
    return truncate(args.query);
  }
  if (name === "web_scraper" && typeof args.url === "string") {
    try {
      return new URL(args.url).hostname;
    } catch {
      return truncate(args.url);
    }
  }
  if (name === "search_person" && typeof args.query === "string") {
    return truncate(args.query);
  }
  if (name === "search_memories" && typeof args.query === "string") {
    return truncate(args.query);
  }
  return null;
}

export function toolLabel(name: string, args?: Record<string, unknown>): string {
  const base = TOOL_LABELS[name] ?? `${name} çalıştırılıyor`;
  const extra = detail(name, args);
  return extra ? `${base}: “${extra}”` : base;
}

export function agentPhaseLabel(event: ProgressEvent): string {
  if (event.hint === "followup") return "Sonuçlar değerlendiriliyor";
  return "Düşünülüyor";
}

export function confirmPhaseLabel(): string {
  return "Onay için hazırlanıyor";
}
