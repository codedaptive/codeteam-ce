// The volume's free space for the FLEET and DISK captions (render._free): `?` amber when unread, salmon under
// DISK_RED_GB (render.DISK_RED_GB).
import { fmt } from "./fmt.js";
import { h } from "./h.js";

const DISK_RED_GB = 50;

export function freeSpace(snap) {
  const gb = fmt.num(fmt.mapping(snap.volume).free_gb);
  return h.span(`${gb === null ? "?" : gb.toFixed(0)}G free`, gb === null ? "amber" : gb < DISK_RED_GB ? "salmon" : "dim");
}
