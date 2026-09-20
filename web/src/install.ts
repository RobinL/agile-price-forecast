// Installation adds an icon and standalone window; it does not cache price data.
interface InstallPrompt extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}
export function setupInstall() {
  const button = document.querySelector<HTMLButtonElement>("#install-app")!;
  let pending: InstallPrompt | undefined;
  const standalone = window.matchMedia("(display-mode: standalone)");
  const hide = () => {
    pending = undefined;
    button.hidden = true;
  };
  window.addEventListener("beforeinstallprompt", (event) => {
    if (standalone.matches) return;
    event.preventDefault();
    pending = event as InstallPrompt;
    button.hidden = false;
  });
  window.addEventListener("appinstalled", hide);
  standalone.addEventListener("change", () => {
    if (standalone.matches) hide();
  });
  button.addEventListener("click", async () => {
    const prompt = pending;
    if (!prompt) return;
    hide();
    try {
      await prompt.prompt();
      await prompt.userChoice;
    } catch {
      /* Browser menu installation remains available. */
    }
  });
}
