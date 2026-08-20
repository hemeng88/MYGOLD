import { createTheme } from "@mantine/core";

export const theme = createTheme({
  primaryColor: "gold",
  defaultRadius: "lg",
  fontFamily: '"Noto Sans SC", "PingFang SC", sans-serif',
  headings: {
    fontFamily: '"Fraunces", "Noto Serif SC", serif',
    fontWeight: "560",
  },
  colors: {
    gold: [
      "#fff8e1",
      "#f5e7b8",
      "#ead58a",
      "#e0c25c",
      "#d4af37",
      "#c09a22",
      "#967818",
      "#6d5610",
      "#44350a",
      "#1c1504",
    ],
    dark: [
      "#f4ead6",
      "#c9b896",
      "#8c8170",
      "#5c5448",
      "#3a342c",
      "#2a241c",
      "#1c1812",
      "#14110c",
      "#0e0c09",
      "#080705",
    ],
  },
  components: {
    Paper: {
      defaultProps: { radius: "xl", withBorder: true },
    },
    Button: {
      defaultProps: { radius: "xl" },
    },
    NumberInput: {
      defaultProps: { size: "md" },
    },
    TextInput: {
      defaultProps: { size: "md" },
    },
    Select: {
      defaultProps: { size: "md" },
    },
  },
});
