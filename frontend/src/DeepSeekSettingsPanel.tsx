import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Modal, PasswordInput, Stack, Text, TextInput } from "@mantine/core";
import { api } from "./api";
import type { DeepSeekSettings } from "./types";

export function DeepSeekSettingsPanel({ onChanged }: { onChanged: () => Promise<void> }) {
  const [opened, setOpened] = useState(false);
  const [config, setConfig] = useState<DeepSeekSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("deepseek-flash");
  const [busy, setBusy] = useState<"load" | "save" | "test" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    setBusy("load");
    setError(null);
    try {
      const next = await api.deepSeekSettings();
      setConfig(next);
      setModel(next.model);
    } catch (err) {
      setError(err instanceof Error ? err.message : "配置读取失败");
    } finally {
      setBusy(null);
    }
  };
  const open = () => {
    setApiKey("");
    setConfig(null);
    setMessage(null);
    setOpened(true);
    void load();
  };
  const close = () => {
    setApiKey("");
    setOpened(false);
  };
  const act = async (kind: "save" | "test" | "delete") => {
    setBusy(kind);
    setError(null);
    setMessage(null);
    try {
      if (kind === "test") {
        const result = await api.testDeepSeekSettings();
        if (result.ok) setMessage(result.message);
        else setError(result.message);
      } else {
        const next = kind === "save" ? await api.saveDeepSeekSettings(apiKey.trim(), model.trim()) : await api.deleteDeepSeekSettings();
        setConfig(next);
        setApiKey("");
        setModel(next.model);
        setMessage(kind === "save" ? "已保存，立即生效。可以测试连接或返回分析。" : "已删除个人密钥并停用此账号的 DeepSeek 分析。");
        await onChanged();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败，请稍后重试");
    } finally {
      setBusy(null);
    }
  };
  return (
    <>
      <Button size="compact-xs" variant="subtle" color="gold" onClick={open}>配置 DeepSeek</Button>
      <Modal opened={opened} onClose={close} title="DeepSeek API 配置" centered>
        <Stack gap="sm">
          <Text size="sm" c="dimmed">配置仅用于当前账号，保存后立即生效。Key 加密保存在服务端，页面不回显已保存的原文；请通过 HTTPS 站点填写。</Text>
          {busy === "load" ? <Loader size="sm" color="gold" /> : null}
          {error ? <Alert color="red">{error}</Alert> : null}
          {message ? <Alert color="teal">{message}</Alert> : null}
          {!config && busy !== "load" ? <Button variant="light" onClick={() => void load()}>重新读取</Button> : null}
          {config ? (
            <>
              <Badge color={config.configured ? "teal" : "gray"} variant="light">
                {config.configured ? (config.source === "server" ? "已启用 · 服务器配置" : "已保存 · 个人配置") : "未启用"}
              </Badge>
              {config.error ? <Text size="xs" c="red">{config.error}</Text> : null}
              <PasswordInput
                label="API Key"
                description={config.configured ? "留空保留当前 Key；填写新 Key 会替换。" : "粘贴你的 DeepSeek API Key。"}
                placeholder={config.configured ? "已保存，原文不回显" : "请输入 API Key"}
                autoComplete="new-password"
                value={apiKey}
                onChange={(event) => setApiKey(event.currentTarget.value)}
                disabled={busy !== null}
              />
              <TextInput label="模型名称" value={model} onChange={(event) => setModel(event.currentTarget.value)} disabled={busy !== null} autoComplete="off" />
              <Text size="xs" c="dimmed">保存后，本页的有效候选会使用该配置自动分析，产生 DeepSeek API 费用。测试连接只检查已保存 Key 的鉴权和模型列表，不调用股票分析。</Text>
              {config.updated_at ? <Text size="xs" c="dimmed">上次更新：{config.updated_at.replace("T", " ").slice(0, 19)}</Text> : null}
              <Group grow>
                <Button color="gold" loading={busy === "save"} disabled={busy !== null || !model.trim()} onClick={() => void act("save")}>保存配置</Button>
                <Button variant="light" loading={busy === "test"} disabled={busy !== null || !config.configured || !!apiKey || model.trim() !== config.model} onClick={() => void act("test")}>测试连接</Button>
              </Group>
              <Button variant="subtle" color="red" loading={busy === "delete"} disabled={busy !== null || (!config.configured && config.source !== "account")} onClick={() => void act("delete")}>删除并停用</Button>
            </>
          ) : null}
        </Stack>
      </Modal>
    </>
  );
}
