import { useCallback, useEffect, useState } from "react";
import { ActionIcon, Box, Center, Group, Loader, Stack, Tabs, Text, Title, Tooltip } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { Capacitor } from "@capacitor/core";
import { IconChartLine, IconLogout, IconTrophy, IconWallet } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { api } from "./api";
import { UNAUTHORIZED_EVENT, getToken } from "./auth";
import { ExposurePanel } from "./ExposurePanel";
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
  const [activeTab, setActiveTab] = useState<string | null>("funds");

  const check = useCallback(async () => {
    if (!getToken()) {
      setState("out");
      return;
    }
    try {
      await api.me();
      setState("in");
    } catch (err) {
      // 401 时 api 层已经清掉令牌了。但连不上服务器也会走到这里，
      // 那种情况令牌还在，不该把人踢去登录页，否则断网就等于被登出。
      setState(getToken() ? "in" : "out");
      if (getToken()) {
        notifications.show({
          color: "yellow",
          title: "连不上服务器",
          message: err instanceof Error ? err.message : "稍后重试",
        });
      }
    }
  }, []);

  useEffect(() => {
    void check();
    // 任何接口拿到 401 都会派发这个事件，收到就立刻切回登录页
    const onUnauthorized = () => setState("out");
    // 加到主屏幕的用法常常是挂后台好几天再切回来，这时令牌可能已经过期，
    // 重新可见时复查一次，别等到下一次轮询才发现
    const onVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
      document.removeEventListener("visibilitychange", onVisible);
    };
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
          <Tabs
            value={activeTab}
            onChange={setActiveTab}
            className="feature-tabs"
            keepMounted={false}
            variant="none"
          >
            <Tabs.List grow aria-label="选择功能">
              <Tabs.Tab value="funds" leftSection={<IconWallet size={16} />}>
                基金估值
              </Tabs.Tab>
              <Tabs.Tab value="exposure" leftSection={<IconChartLine size={16} />}>
                持仓穿透
              </Tabs.Tab>
              <Tabs.Tab value="rankings" leftSection={<IconTrophy size={16} />}>
                涨幅榜
              </Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="funds" pt="sm">
              <FundsPanel />
            </Tabs.Panel>
            <Tabs.Panel value="exposure" pt="sm">
              <ExposurePanel />
            </Tabs.Panel>
            <Tabs.Panel value="rankings" pt="sm">
              <FundRankPanel />
            </Tabs.Panel>
          </Tabs>
        </Stack>
      </div>
    </Box>
  );
}
