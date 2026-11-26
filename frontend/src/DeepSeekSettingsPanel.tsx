import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Modal, PasswordInput, Select, Stack, Text, TextInput } from "@mantine/core";
import { api } from "./api";
import type { DeepSeekSettings } from "./types";

export function DeepSeekSettingsPanel({ onChanged }: { onChanged: () => Promise<void> }) {
  const [opened, setOpened] = useState(false);
  const [config, setConfig] = useState<DeepSeekSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("deepseek-flash");
  const [provider, setProvider] = useState("deepseek");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [jsonMode, setJsonMode] = useState("json_object");
  const [tokenField, setTokenField] = useState("max_tokens");
  const [busy, setBusy] = useState<"load" | "save" | "test" | "generation" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const sync = (next: DeepSeekSettings) => {
    setConfig(next);
    setModel(next.model);
    setProvider(next.provider);
    setBaseUrl(next.base_url);
    setJsonMode(next.json_mode);
    setTokenField(next.token_field);
  };
  const endpointChanged = !!config && (provider !== config.provider || baseUrl.replace(/\/$/, "") !== config.base_url.replace(/\/$/, ""));
  const unsaved = !!apiKey || endpointChanged || model.trim() !== config?.model || jsonMode !== config?.json_mode || tokenField !== config?.token_field;
  const selectProvider = (value: string | null) => {
    if (!value || value === provider) return;
    const preset = config?.providers.find((item) => item.id === value);
    if (!preset) return;
    setProvider(value);
    setBaseUrl(preset.base_url);
    setModel(preset.default_model);
    setTokenField(preset.token_field);
    setJsonMode("json_object");
    setApiKey("");
    setMessage(null);
    setError(null);
  };

  const load = async () => {
    setBusy("load");
    setError(null);
    try {
      const next = await api.deepSeekSettings();
      sync(next);
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
  const act = async (kind: "save" | "test" | "generation" | "delete") => {
    setBusy(kind);
    setError(null);
    setMessage(null);
    try {
      if (kind === "test" || kind === "generation") {
        const result = kind === "test" ? await api.testDeepSeekSettings() : await api.testModelGeneration();
        if (result.ok) setMessage(result.message);
        else setError(result.message);
      } else {
        const next = kind === "save" ? await api.saveDeepSeekSettings(apiKey.trim(), model.trim(), provider, baseUrl.trim(), jsonMode, tokenField) : await api.deleteDeepSeekSettings();
        sync(next);
        setApiKey("");
        setMessage(kind === "save" ? "已保存，立即生效。可以测试连接或验证分析格式。" : "已删除个人密钥并停用此账号的 AI 分析。");
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
      <Button size="compact-xs" variant="subtle" color="gold" onClick={open}>配置 AI 模型</Button>
      <Modal opened={opened} onClose={close} title="AI 模型配置" centered>
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
              <Select label="模型服务商" data={config.providers.map((item) => ({ value: item.id, label: item.label }))}
                value={provider} onChange={selectProvider} allowDeselect={false} disabled={busy !== null} />
              <TextInput label="API Base URL" description="填写基础地址，不含 /chat/completions。百炼可填控制台提供的地域或业务空间地址。"
                value={baseUrl} onChange={(event) => { setBaseUrl(event.currentTarget.value); setApiKey(""); }} disabled={busy !== null} autoComplete="off" />
              {endpointChanged ? <Text size="xs" c="yellow">服务商或地址已变更，请重新填入新地址对应的 Key；原 Key 不会自动沿用。</Text> : null}
              <PasswordInput
                label="API Key"
                description={config.configured && !endpointChanged ? "服务商及地址不变时，留空保留当前 Key。" : "粘贴所选服务商的 API Key。"}
                placeholder={config.configured ? "已保存，原文不回显" : "请输入 API Key"}
                autoComplete="new-password"
                value={apiKey}
                onChange={(event) => setApiKey(event.currentTarget.value)}
                disabled={busy !== null}
              />
              <TextInput label="模型名称" value={model} onChange={(event) => setModel(event.currentTarget.value)} disabled={busy !== null} autoComplete="off" />
              <Select label="JSON 输出方式" data={[{value:"json_object",label:"接口 JSON 模式"},{value:"prompt",label:"仅提示词要求 JSON（兼容模式）"}]} value={jsonMode} onChange={(value) => value && setJsonMode(value)} allowDeselect={false} disabled={busy !== null} />
              <Select label="Token 上限参数" data={["max_tokens", "max_completion_tokens"]} value={tokenField} onChange={(value) => value && setTokenField(value)} allowDeselect={false} disabled={busy !== null} />
              <Text size="xs" c="dimmed">仅支持 Chat Completions 兼容协议。保存后有效候选会自动使用所选服务商分析，产生对应 API 费用。测试连接仅检查鉴权和模型列表；“验证分析格式”会另调用一次模型，产生少量费用。修改后请先保存。</Text>
              {config.updated_at ? <Text size="xs" c="dimmed">上次更新：{config.updated_at.replace("T", " ").slice(0, 19)}</Text> : null}
              <Group grow>
                <Button color="gold" loading={busy === "save"} disabled={busy !== null || !model.trim() || !baseUrl.trim() || (endpointChanged && !apiKey.trim())} onClick={() => void act("save")}>保存配置</Button>
                <Button variant="light" loading={busy === "test"} disabled={busy !== null || !config.configured || unsaved} onClick={() => void act("test")}>测试连接</Button>
              </Group>
              <Button variant="light" color="gold" loading={busy === "generation"} disabled={busy !== null || !config.configured || unsaved} onClick={() => void act("generation")}>验证分析格式（少量费用）</Button>
              <Button variant="subtle" color="red" loading={busy === "delete"} disabled={busy !== null || (!config.configured && config.source !== "account")} onClick={() => void act("delete")}>删除并停用</Button>
            </>
          ) : null}
        </Stack>
      </Modal>
    </>
  );
}
