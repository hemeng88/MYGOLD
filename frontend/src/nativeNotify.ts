import { Capacitor } from "@capacitor/core";
import { LocalNotifications } from "@capacitor/local-notifications";

const PREF_KEY = "mygold-notify-on";
const DAILY_IDS = [1001, 1002, 1003];

function isNative() {
  return Capacitor.isNativePlatform();
}

export function notifyEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(PREF_KEY) !== "0";
}

export function setNotifyEnabled(on: boolean) {
  window.localStorage.setItem(PREF_KEY, on ? "1" : "0");
}

export async function requestNotifyPermission(): Promise<boolean> {
  if (!isNative()) return false;
  const current = await LocalNotifications.checkPermissions();
  const status = current.display === "granted" ? current : await LocalNotifications.requestPermissions();
  return status.display === "granted";
}

export async function cancelDailyNotifies() {
  if (!isNative()) return;
  await LocalNotifications.cancel({ notifications: DAILY_IDS.map((id) => ({ id })) });
}

export async function scheduleDailyNotifies(priceText?: string) {
  if (!isNative() || !notifyEnabled()) return;
  const ok = await requestNotifyPermission();
  if (!ok) return;
  const extra = priceText ? ` 浙商 ${priceText} 元/克。` : "";
  await LocalNotifications.cancel({ notifications: DAILY_IDS.map((id) => ({ id })) });
  await LocalNotifications.schedule({
    notifications: [
      {
        id: 1001,
        title: "MYGOLD 日盘",
        body: `上午看一眼金价。${extra}`.trim(),
        schedule: { on: { hour: 10, minute: 5 }, allowWhileIdle: true },
      },
      {
        id: 1002,
        title: "MYGOLD 午后",
        body: `下午再对一下积存金。${extra}`.trim(),
        schedule: { on: { hour: 14, minute: 5 }, allowWhileIdle: true },
      },
      {
        id: 1003,
        title: "MYGOLD 夜盘",
        body: `晚上伦敦金和国内价可以对照。${extra}`.trim(),
        schedule: { on: { hour: 21, minute: 5 }, allowWhileIdle: true },
      },
    ],
  });
}

export async function notifyNow(title: string, body: string) {
  if (!isNative() || !notifyEnabled()) return;
  const ok = await requestNotifyPermission();
  if (!ok) return;
  await LocalNotifications.schedule({
    notifications: [
      {
        id: Math.floor(Date.now() % 100000) + 10,
        title,
        body,
        schedule: { at: new Date(Date.now() + 1200) },
      },
    ],
  });
}

export async function initNativeNotify(priceText?: string) {
  if (!isNative() || !notifyEnabled()) return;
  await scheduleDailyNotifies(priceText);
}
