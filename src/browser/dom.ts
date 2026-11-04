export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className = "",
  text = ""
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
export function button(
  text: string,
  action: () => void,
  className = ""
): HTMLButtonElement {
  const node = element("button", className, text);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
/** Block a control and say why on hover; an empty reason means it is available. */
export function setBlocked(control: HTMLButtonElement, reason: string): void {
  control.disabled = !!reason;
  control.title = reason;
}
export function field(label: string, input: HTMLElement): HTMLLabelElement {
  const node = element("label", "field");
  node.append(element("span", "", label), input);
  return node;
}
export function textInput(label: string, value = ""): HTMLInputElement {
  const node = element("input");
  node.type = "text";
  node.value = value;
  node.setAttribute("aria-label", label);
  return node;
}
export function audioControl(url: string, label: string): HTMLLabelElement {
  const audio = element("audio");
  audio.controls = true;
  audio.preload = "metadata";
  audio.src = url;
  // A wrapping label does not name an audio element, for assistive technology included.
  audio.setAttribute("aria-label", label);
  return field(label, audio);
}
export function drawer(title: string): {
  root: HTMLElement;
  content: HTMLElement;
  close: () => void;
  show: () => void;
} {
  const root = element("aside", "browser-drawer");
  root.hidden = true;
  root.setAttribute("aria-label", title);
  const heading = element("div", "drawer-heading");
  const close = (): void => {
    root.hidden = true;
    root.dispatchEvent(new Event("drawerclose"));
    document.querySelector<HTMLCanvasElement>("#canvas")?.focus();
  };
  heading.append(element("h2", "", title), button("Close", close));
  const content = element("div", "drawer-content");
  root.append(heading, content);
  document.body.append(root);
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape") close();
    event.stopPropagation();
  });
  return {
    root,
    content,
    close,
    show: () => {
      document
        .querySelectorAll<HTMLElement>(".browser-drawer")
        .forEach((node) => {
          if (node !== root && !node.hidden)
            node.dispatchEvent(new Event("drawerclose"));
          node.hidden = node !== root;
        });
      root.hidden = false;
    },
  };
}
