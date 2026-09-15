import { useState } from "react";
import { Box, Button, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { api } from "./api";

export function LoginScreen({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!username.trim() || !password) {
      setError("账号和密码都要填");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.login(username.trim(), password);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box className="app-shell app-shell-mobile" style={{ display: "flex", alignItems: "center", minHeight: "80vh" }}>
      <Paper className="glass" p="lg" style={{ width: "100%", maxWidth: 360, margin: "0 auto" }}>
        <Title order={2} className="brand" mb={4}>
          MYGOLD
        </Title>
        <Text size="xs" c="dimmed" mb="lg">
          基金实时估值
        </Text>
        <Stack gap="sm">
          <TextInput
            label="账号"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") submit();
            }}
          />
          <PasswordInput
            label="密码"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") submit();
            }}
          />
          {error ? (
            <Text size="xs" c="red" role="alert">
              {error}
            </Text>
          ) : null}
          <Button color="gold" fullWidth loading={busy} onClick={submit}>
            登录
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}
