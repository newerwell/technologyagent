export function formatMoney(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const absolute = Math.abs(Math.trunc(cents));
  return sign + "¥" + Math.floor(absolute / 100) + "." + String(absolute % 100).padStart(2, "0");
}

const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Shanghai",
});

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateTimeFormatter.format(date);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}
