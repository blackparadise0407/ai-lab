import { Moon, Sun } from "lucide-react";

import { useTheme } from "../providers/ThemeProvider";
import { Button } from "../ui/button";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="border-white/15 bg-white/10 text-white hover:bg-white/20 hover:text-white dark:border-border dark:bg-card/80 dark:text-foreground dark:hover:bg-accent"
      onClick={toggleTheme}
      aria-label={`Switch to ${isDark ? "light" : "dark"} mode`}
      title={`Switch to ${isDark ? "light" : "dark"} mode`}
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
      <span className="hidden sm:inline">{isDark ? "Light" : "Dark"}</span>
    </Button>
  );
}
