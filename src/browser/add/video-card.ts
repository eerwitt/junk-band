import { element } from "../dom";

/** A video shown as one piece of the stage's cardboard. Put the picture inside `face`. */
export function videoCard(face: HTMLElement): HTMLElement {
  const card = element("div", "video-card");
  face.classList.add("card-face");
  card.append(
    element("span", "card-shadow"),
    element("span", "card-edge"),
    face
  );
  return card;
}

export const cardFibre = (): HTMLElement => element("span", "card-fibre");
