// BUILDS' job rows (render._running_row, _queued_row): running jobs longest first, then queued jobs in queue order.
import { fmt } from "./fmt.js";
import { h } from "./h.js";

// Name caps as render.TEAM_CAP, SESSION_CAP and JOB_TAIL_CAP, so a job reads the same as on the terminal.
const TEAM_CAP = 8;
const SESSION_CAP = 10;
const TAIL_CAP = 10;

const jobName = (job) => `${fmt.cap(job.team || "?", TEAM_CAP)} · ${fmt.cap(job.session || "?", SESSION_CAP)}`;
const where = (job) => h.cut(fmt.tail(job.worktree, TAIL_CAP), "dim", "wt");

function running(job) {
  const cost = fmt.num(job.cost);
  const title = `${jobName(job)} ${fmt.timer(job.running_s)} ${job.kind || "?"} ${job.worktree || ""}`;
  return h.row(h.span("●", "green") + " " + h.span(jobName(job), "")
    + (job.pid_alive === false ? "  " + h.span("pid gone", "salmon") : "")
    + "  " + h.span(fmt.timer(job.running_s), "dim") + "  " + h.span(job.kind || "?", "dim")
    + "  " + h.span(`cost ${cost === null ? "?" : cost.toFixed(1)}`, "dim") + "  " + where(job), "job", title);
}

function queued(job) {
  const title = `#${fmt.g(job.position)} ${jobName(job)} wait ${fmt.dur(job.waiting_s)} ${job.worktree || ""}`;
  return h.row(h.span(`#${fmt.g(job.position)} ${jobName(job)}`, "dim")
    + (job.hold ? "  " + h.span(`held ${job.hold}`, "amber") : "")
    + "  " + h.span(`wait ${fmt.dur(job.waiting_s)}`, "dim")
    + "  " + h.span(`start ${fmt.clock(job.estimated_start)}`, "dim") + "  " + where(job), "job", title);
}

export function buildJobs(runningJobs, queuedJobs) {
  const longest = [...runningJobs].sort((a, b) => (fmt.num(b.running_s) || 0) - (fmt.num(a.running_s) || 0));
  return longest.map(running).join("") + queuedJobs.map(queued).join("");
}
