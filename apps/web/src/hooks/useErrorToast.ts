import { useEffect } from "react";
import { toast } from "sonner";

export function useErrorToast(
  message: string | null | undefined,
  title = "Error",
) {
  useEffect(() => {
    if (!message) return;

    const id = `${title}:${message}`;
    toast.error(title, {
      description: message,
      id,
    });
  }, [message, title]);
}
