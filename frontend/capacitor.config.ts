import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "icu.ohmygold.app",
  appName: "MYGOLD",
  webDir: "dist",
  backgroundColor: "#090806",
  ios: {
    contentInset: "never",
    preferredContentMode: "mobile",
    scrollEnabled: true,
  },
  plugins: {
    LocalNotifications: {
      iconColor: "#d4af37",
    },
  },
};

export default config;
