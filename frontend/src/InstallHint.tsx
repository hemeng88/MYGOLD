import { Capacitor } from "@capacitor/core";
import { Button, Paper, Text } from "@mantine/core";
import { useEffect, useState } from "react";

const KEY = "mygold-hide-install-hint";

function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    ("standalone" in window.navigator && Boolean((window.navigator as Navigator & { standalone?: boolean }).standalone))
  );
}

export function InstallHint() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (Capacitor.isNativePlatform()) return;
    const mobile = window.matchMedia("(max-width: 52em)").matches;
    setShow(mobile && !isStandalone() && !localStorage.getItem(KEY));
  }, []);

  if (!show) return null;

  return (
    <Paper className="glass" p="sm" mb="md">
      <Text size="sm" fw={600}>
        加到 iPhone 主屏幕
      </Text>
      <Text size="xs" c="dimmed" mt={4}>
        用 Safari 打开这个网站，点底部分享，再选「添加到主屏幕」。之后像 App 一样点图标进来，数据还在这台服务器上。
      </Text>
      <Button
        size="xs"
        variant="subtle"
        color="gold"
        mt={8}
        onClick={() => {
          localStorage.setItem(KEY, "1");
          setShow(false);
        }}
      >
        知道了
      </Button>
    </Paper>
  );
}
