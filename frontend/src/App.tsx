import { Box, Group, Stack, Text, Title } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { Capacitor } from "@capacitor/core";
import { FundRankPanel } from "./FundRankPanel";
import { FundsPanel } from "./FundsPanel";
import { InstallHint } from "./InstallHint";

// 只剩基金一个页面，不再需要底部 tab 栏
export default function App() {
  const isNarrow = useMediaQuery("(max-width: 52em)") ?? true;
  const isMobile = Capacitor.isNativePlatform() || isNarrow;

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
