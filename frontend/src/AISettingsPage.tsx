import { useEffect, useState } from "react";
import { Alert, Badge, Button, Group, Loader, Modal, Paper, PasswordInput, Select, Stack, Text, TextInput } from "@mantine/core";
import { api } from "./api";
import type { AIProfile, AIProfileInput, AIProfileSettings, AIProviderPreset } from "./types";

function draftFor(preset: AIProviderPreset): AIProfileInput {
  return { name: "", api_key: "", provider: preset.id, model: preset.default_model,
    base_url: preset.base_url, json_mode: preset.json_mode, token_field: preset.token_field };
}

function ProfileEditor({ profile, providers, close, onSaved }: {
  profile: AIProfile | null;
  providers: AIProviderPreset[];
  close: () => void;
  onSaved: (next: AIProfile) => void;
}) {
  const [draft, setDraft] = useState<AIProfileInput>(() => profile ? { ...profile, api_key: "" } : draftFor(providers[0]));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const preset = providers.find((row) => row.id === draft.provider);
  const sameEndpoint = profile?.provider === draft.provider && profile?.base_url === draft.base_url.trim().replace(/\/$/, "");
  const canKeepKey = Boolean(profile?.configured && sameEndpoint);
  const key = draft.api_key?.trim() || "";
  const canSave = Boolean(draft.model.trim() && draft.base_url.trim() && (canKeepKey || key));

  function set<K extends keyof AIProfileInput>(field: K, value: AIProfileInput[K]) {
    setDraft((previous) => ({ ...previous, [field]: value }));
  }

  async function save() {
    if (!canSave || saving) return;
    setSaving(true);
    setError("");
    try {
      // 只提交表单字段，API Key 不参与列表或运行结果的状态。
      const { name, model, provider, base_url, json_mode, token_field } = draft;
      onSaved(await api.saveAIProfile({ name: profile?.id === "default" ? undefined : name?.trim(),
        api_key: key || null, model: model.trim(), provider, base_url: base_url.trim(), json_mode, token_field }, profile?.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  return <Modal opened onClose={close} title={profile ? "编辑 AI 配置" : "添加 AI 配置"} centered>
    <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <Stack gap="sm">
        {error ? <Alert color="red">{error}</Alert> : null}
        <Select label="服务商预设" data={providers.map((row) => ({ value: row.id, label: row.label }))}
          value={draft.provider} allowDeselect={false} disabled={saving} onChange={(value) => {
            const next = providers.find((row) => row.id === value);
            if (next && next.id !== draft.provider) setDraft((previous) => ({ ...draftFor(next), name: previous.name }));
          }} />
        <PasswordInput label="API Key" value={draft.api_key || ""} autoComplete="new-password" disabled={saving}
          placeholder={canKeepKey ? "留空保留已保存的 Key" : "填写该服务商和站点的 Key"}
          onChange={(event) => set("api_key", event.currentTarget.value)} />
        <details key={draft.provider} open={!preset?.base_url || !preset?.default_model || undefined}>
          <summary style={{ cursor: "pointer" }}><Text span size="sm">高级设置{draft.model ? ` · ${draft.model}` : ""}</Text></summary>
          <Stack gap="sm" mt="xs">
            {profile?.id !== "default" ? <TextInput label="备注名" description="可留空，系统按服务商命名。"
              value={draft.name || ""} maxLength={48} disabled={saving} onChange={(event) => set("name", event.currentTarget.value)} /> : null}
            <TextInput label="API Base URL" description="程序会拼接 /chat/completions。"
              value={draft.base_url} disabled={saving} onChange={(event) => setDraft((previous) => ({ ...previous, base_url: event.currentTarget.value, api_key: "" }))} />
            <TextInput label="模型名称" value={draft.model} disabled={saving} onChange={(event) => set("model", event.currentTarget.value)} />
            <Select label="JSON 输出方式" data={[{ value: "json_object", label: "接口 JSON 模式" }, { value: "prompt", label: "仅提示词要求 JSON（兼容模式）" }]}
              value={draft.json_mode} allowDeselect={false} disabled={saving} onChange={(value) => value && set("json_mode", value)} />
            <Select label="Token 上限参数" data={["max_tokens", "max_completion_tokens"]} value={draft.token_field}
              allowDeselect={false} disabled={saving} onChange={(value) => value && set("token_field", value)} />
          </Stack>
        </details>
        <Group justify="end">
          <Button variant="default" onClick={close} disabled={saving}>取消</Button>
          <Button type="submit" loading={saving} disabled={!canSave}>保存配置</Button>
        </Group>
      </Stack>
    </form>
  </Modal>;
}

export function AISettingsPage({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<AIProfileSettings | null>(null);
  const [editor, setEditor] = useState<AIProfile | null | undefined>(undefined);
  const [removing, setRemoving] = useState<AIProfile | null>(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState<string>();
  const [notices, setNotices] = useState<Record<string, { ok: boolean; message: string }>>({});

  async function load(signal?: AbortSignal) {
    setError("");
    try {
      setData(await api.aiProfiles(signal));
    } catch (err) {
      if (!signal?.aborted) setError(err instanceof Error ? err.message : "配置读取失败。");
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  function saved(profile: AIProfile) {
    setData((current) => current && ({ ...current, profiles: current.profiles.some((row) => row.id === profile.id)
      ? current.profiles.map((row) => row.id === profile.id ? profile : row) : [...current.profiles, profile] }));
    setNotices((previous) => ({ ...previous, [profile.id]: { ok: true, message: "配置已保存。" } }));
    setEditor(undefined);
  }

  async function act(profile: AIProfile, action: "test" | "test-generation" | "delete") {
    setActive(profile.id);
    try {
      if (action === "delete") {
        await api.deleteAIProfile(profile.id);
        setData((current) => current && ({ ...current, profiles: current.profiles.filter((row) => row.id !== profile.id) }));
      } else {
        const result = await api.testAIProfile(profile.id, action);
        setNotices((previous) => ({ ...previous, [profile.id]: result }));
      }
    } catch (err) {
      setNotices((previous) => ({ ...previous, [profile.id]: { ok: false, message: err instanceof Error ? err.message : "操作失败。" } }));
    } finally {
      setActive(undefined);
      setRemoving(null);
    }
  }

  return <Paper className="glass" p="md"><Stack gap="sm">
    <Group justify="space-between">
      <Text fw={700}>AI 配置</Text>
      <Group gap="xs">
        <Button variant="subtle" size="xs" onClick={onBack}>返回</Button>
        <Button size="xs" onClick={() => setEditor(null)} disabled={!data?.providers.length}>添加配置</Button>
      </Group>
    </Group>
    <Text size="xs" c="dimmed">在股票页选择要调用的模型。API Key 按账号加密保存，请通过 HTTPS 填写。</Text>
    {error ? <Alert color="red">{error}<Button variant="subtle" size="compact-xs" onClick={() => void load()}>重试</Button></Alert> : null}
    {!error && !data ? <Loader size="sm" /> : null}
    {data?.profiles.length === 0 ? <Text size="sm" c="dimmed">还没有 AI 配置。选一个服务商预设，填 API Key 即可添加。</Text> : null}
    {data?.profiles.map((profile) => <Paper key={profile.id} className="stat-tile" p="sm">
      <Stack gap="xs">
        <Group justify="space-between">
          <div>
            <Text fw={600} size="sm">{profile.name}</Text>
            <Text size="xs" c="dimmed">{profile.model} · {profile.base_url}</Text>
          </div>
          <Badge variant="light" color={profile.configured ? "teal" : "yellow"}>{profile.configured ? "已配置" : "需要更新 Key"}</Badge>
        </Group>
        {notices[profile.id] || profile.error ? <Text size="xs" c={notices[profile.id]?.ok ? "teal" : "red"}>{notices[profile.id]?.message || profile.error}</Text> : null}
        <Group gap="xs">
          <Button variant="light" size="compact-xs" disabled={!!active} onClick={() => setEditor(profile)}>编辑</Button>
          <Button variant="subtle" size="compact-xs" disabled={!!active || !profile.configured} onClick={() => void act(profile, "test")}>测试连接</Button>
          <Button variant="subtle" size="compact-xs" disabled={!!active || !profile.configured} onClick={() => void act(profile, "test-generation")}>验证格式（使用额度）</Button>
          <Button variant="subtle" size="compact-xs" color="red" disabled={!!active} onClick={() => setRemoving(profile)}>删除</Button>
        </Group>
      </Stack>
    </Paper>)}
    {data && editor !== undefined && <ProfileEditor profile={editor} providers={data.providers} close={() => setEditor(undefined)} onSaved={saved} />}
    <Modal opened={!!removing} onClose={() => { if (!active) setRemoving(null); }} title="删除 AI 配置" centered>
      <Stack gap="sm">
        <Text size="sm">删除「{removing?.name}」会移除这套配置和保存的 API Key。</Text>
        <Group justify="end">
          <Button variant="default" size="xs" disabled={!!active} onClick={() => setRemoving(null)}>取消</Button>
          <Button size="xs" color="red" loading={!!active} onClick={() => removing && void act(removing, "delete")}>确认删除</Button>
        </Group>
      </Stack>
    </Modal>
  </Stack></Paper>;
}
