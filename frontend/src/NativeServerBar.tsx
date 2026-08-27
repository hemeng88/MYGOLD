import { Capacitor } from "@capacitor/core";
import { ActionIcon, Button, Group, Popover, Switch, Text, TextInput } from "@mantine/core";
import { IconServer } from "@tabler/icons-react";
import { useState } from "react";
import { apiBase, setApiBase } from "./api";
import { cancelDailyNotifies, notifyEnabled, notifyNow, scheduleDailyNotifies, setNotifyEnabled } from "./nativeNotify";

const PRESETS = ["http://49.232.222.121", "https://ohmygold.icu"];

export function NativeServerBar() {
  const [value, setValue] = useState(apiBase());
  const [opened, setOpened] = useState(false);
  const [notifyOn, setNotifyOn] = useState(notifyEnabled());

  if (!Capacitor.isNativePlatform()) return null;

  return (
    <Popover opened={opened} onChange={setOpened} width={280} position="bottom-end" shadow="md">
      <Popover.Target>
        <ActionIcon
          variant="default"
          size={40}
          radius="xl"
          aria-label="服务器地址"
          onClick={() => setOpened((v) => !v)}
        >
          <IconServer size={18} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown>
        <Text size="xs" c="dimmed">
          服务器
        </Text>
        <Text size="sm" fw={600} lineClamp={1} mb={8}>
          {apiBase() || "未设置"}
        </Text>
        <TextInput
          size="sm"
          value={value}
          onChange={(event) => setValue(event.currentTarget.value)}
          placeholder="http://49.232.222.121"
        />
        <Group mt={8} gap={8}>
          {PRESETS.map((item) => (
            <Button key={item} size="compact-xs" variant="light" color="gold" onClick={() => setValue(item)}>
              {item.includes("ohmygold") ? "域名" : "IP"}
            </Button>
          ))}
          <Button
            size="compact-xs"
            color="gold"
            onClick={() => {
              setApiBase(value);
              window.location.reload();
            }}
          >
            保存并刷新
          </Button>
        </Group>
        <Switch
          mt="md"
          color="gold"
          size="sm"
          label="盘中提醒"
          checked={notifyOn}
          onChange={async (event) => {
            const on = event.currentTarget.checked;
            setNotifyOn(on);
            setNotifyEnabled(on);
            if (on) await scheduleDailyNotifies();
            else await cancelDailyNotifies();
          }}
        />
        <Text size="xs" c="dimmed" mt={6}>
          每天 10:05、14:05、21:05 提醒看价。关掉 App 后金价一变就推，目前做不到。
        </Text>
        <Button
          mt={8}
          size="compact-xs"
          variant="light"
          color="gold"
          onClick={() => notifyNow("MYGOLD", "通知可以用了。锁屏或退到桌面也能看到。")}
        >
          试一条通知
        </Button>
      </Popover.Dropdown>
    </Popover>
  );
}
