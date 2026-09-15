import { useCallback, useEffect, useState } from "react";
import { ActionIcon, Box, Center, Group, Loader, Stack, Text, Title, Tooltip } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { Capacitor } from "@capacitor/core";
import { IconLogout } from "@tabler/icons-react";
import { api } from "./api";
import { UNAUTHORIZED_EVENT, getToken } from "./auth";
import { FundRankPanel } from "./FundRankPanel";
import { FundsPanel } from "./FundsPanel";
import { InstallHint } from "./InstallHint";
import { LoginScreen } from "./LoginScreen";

// 只剩基金一个页面，不再需要底部 tab 栏
export default function App() {
  const isNarrow = useMediaQuery("(max-width: 52em)") ?? true;
  const isMobile = Capacitor.isNativePlatform() || isNarrow;
  // checking: 本地有令牌，正在问后端还有效没
  const [state, setState] = useState<"checking" | "in" | "out">(getToken() ? "checking" : "out");

  const check = useCallback(async () => {
    if (!getToken()) {
      setState("out");
      return;
    }
    try {
      await api.me();
      setState("in");
    } catch {
      // 令牌无效时 api 层已经清掉了，这里只管切页面
      setState("out");
    }
  }, []);

  useEffect(() => {
    void check();
    const onUnauthorized = () => setState("out");
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [check]);

  if (state === "checking") {
    return (
      <Center style={{ minHeight: "60vh" }}>
        <Loader color="gold" />
      </Center>
    );
  }

  if (state === "out") {
    return <LoginScreen onDone={() => setState("in")} />;
  }

  return (
    <Box className={isMobile ? "app-shell app-shell-mobile" : "app-shell"}>
      <Group className="app-header" justify="space-between" align="center" mb={isMobile ? 12 : 24} wrap="nowrap">
        <div style={{ minWidth: 0 }}>
          {isMobile ? null : (
            <Text className="eyebrow" mb={4}>
              Fund Estimate
            </Text>
          )}
          <Title order={1} className="brand">
            MYGOLD
          </Title>
          <Text c="dimmed" size={isMobile ? "xs" : "sm"} mt={4}>
            基金实时估值 · 公示仓位穿透持仓股
          </Text>
        </div>
        <Tooltip label="退出登录">
          <ActionIcon
            variant="default"
            size={40}
            radius="xl"
            aria-label="退出登录"
            onClick={() => {
              api.logout();
              setState("out");
            }}
          >
            <IconLogout size={18} />
          </ActionIcon>
        </Tooltip>
      </Group>

      <div className="app-main">
        <Stack gap="sm">
          <InstallHint />
          <FundsPanel />
          <FundRankPanel />
        </Stack>
      </div>
    </Box>
  );
}
