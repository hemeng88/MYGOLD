import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "icu.ohmygold.app",
  appName: "MYGOLD",
  webDir: "dist",
  backgroundColor: "#090806",
  ios: {
    contentInset: "automatic",
    preferredContentMode: "mobile",
  },
};

export default config;
