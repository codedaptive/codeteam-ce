// Patch a live DOM subtree to match new markup, keeping every element whose position and tag are unchanged. Kept
// elements keep their running CSS animations, and a changed inline width eases by CSS transition, where replacing
// innerHTML would restart one and jump the other.

function syncAttributes(from, to) {
  for (const { name } of [...from.attributes]) if (!to.hasAttribute(name)) from.removeAttribute(name);
  for (const { name, value } of [...to.attributes]) if (from.getAttribute(name) !== value) from.setAttribute(name, value);
}

function patch(live, next) {
  const liveKids = [...live.childNodes];
  const nextKids = [...next.childNodes];
  nextKids.forEach((want, i) => {
    const have = liveKids[i];
    if (!have) live.appendChild(want);
    else if (have.nodeType !== want.nodeType || have.nodeName !== want.nodeName) live.replaceChild(want, have);
    else if (have.nodeType === Node.ELEMENT_NODE) {
      syncAttributes(have, want);
      patch(have, want);
    } else if (have.nodeValue !== want.nodeValue) have.nodeValue = want.nodeValue;
  });
  for (const extra of liveKids.slice(nextKids.length)) live.removeChild(extra);
}

export function morph(target, markup) {
  const template = document.createElement("template");
  template.innerHTML = markup;
  patch(target, template.content);
}
