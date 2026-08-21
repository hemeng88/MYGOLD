import { Capacitor } from "@capacitor/core";
import { Button, Group, Paper, Text, TextInput } from "@mantine/core";
import { useState } from "react";
import { apiBase, setApiBase } from "./api";

const PRESETS = ["https://ohmygold.icu", "http://49.232.222.121"];

export function NativeServerBar() {
  const [value, setValue] = useState(apiBase());
  const [open, setOpen] = useState(false);

  if (!Capacitor.isNativePlatform()) return null;

  return (
    <Paper className="glass" p="sm" mb="md">
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Text size="xs" c="dimmed">
            服务器
          </Text>
          <Text size="sm" fw={600} lineClamp={1}>
            {apiBase() || "未设置"}
          </Text>
        </div>
        <Button size="xs" variant="subtle" color="gold" onClick={() => setOpen((v) => !v)}>
          {open ? "收起" : "改地址"}
        </Button>
      </Group>
      {open ? (
        <>
          <TextInput
            mt="sm"
            size="xs"
            value={value}
            onChange={(event) => setValue(event.currentTarget.value)}
            placeholder="https://ohmygold.icu"
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
        </>
      ) : null}
    </Paper>
  );
}