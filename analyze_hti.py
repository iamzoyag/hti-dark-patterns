#!/usr/bin/env python3
"""
HTI Dark Patterns Study -- full analysis pipeline.

Usage
-----
  python analyze_hti.py --data data/ --out results/ [--repo /path/to/hti-dark-patterns] [--exclude-file exclude.csv]

  --data    folder (or glob) of per-participant CSV exports (the 3-section files the platform emails you)
  --out     output folder (tables/, figures/, results_summary.md, qualitative_coding_sheet.csv, ...)
  --repo    OPTIONAL path to the cloned repo. If given, main.py's ground-truth tables are loaded (with the web
            framework stubbed out) so the script can verify each dark-turn target was really costly and compute
            objective plan-quality deltas. Everything else runs without it.
  --exclude-file  OPTIONAL csv with a column `Participant_ID` (whole-participant exclusions decided by you, e.g.
            from manual coding of the demand-characteristics answers) and optionally `global_trial` (trial-level).

Everything the script reports is computed from the raw event logs; the platform's own summary columns are only
used as a cross-check (validation_report.csv), so a bug in the export cannot silently leak into the paper.
"""
import argparse, ast, csv, glob, importlib.util, json, math, os, re, sys, traceback, warnings
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.stats.power import TTestPower
    HAVE_SM = True
except Exception:  # pragma: no cover
    HAVE_SM = False
warnings.filterwarnings("ignore")
try:
    from tqdm import tqdm
except Exception:  # progress bars are optional: pip install tqdm
    tqdm = None
def prog(it, desc="", total=None):
    return tqdm(it, desc=desc, total=total, leave=False, ncols=90) if tqdm else it

# ----------------------------------------------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------------------------------------------
LOW_C, HIGH_C = "#3B6FB6", "#D2691E"     # two-condition palette (colorblind-safe blue/orange), used everywhere
INK, MUTED = "#222222", "#777777"
TLX_KEYS = ["Mental", "Physical", "Temporal", "Performance", "Effort", "Frustration",
            "Helpfulness", "Trust", "Persuasiveness", "Independence"]
# Persuasiveness == the "Influence" item (how much the AI influenced my final decision); Independence: high = own judgment.
CLUSTER = {  # Siren Song (CHI'26) top-level clusters
    "Interaction Padding": "Engagement & Behavioral", "Excessive Flattery": "Engagement & Behavioral",
    "Simulated Emotional": "Engagement & Behavioral",
    "Sycophantic Agreement": "Content & Belief", "Ideological Steering": "Content & Belief",
    "Unprompted Intimacy Probing": "Privacy & Data Exploitation", "Behavioral Profiling via Dialogue": "Privacy & Data Exploitation",
    "Brand Favoritism": "Decision & Outcome", "Simulated Authority": "Decision & Outcome",
    "Opaque Training Data Sources": "Transparency & Accountability", "Opaque Reasoning Processes": "Transparency & Accountability",
}
AI_EXP = {"never": 1, "rarely": 2, "sometimes": 3, "often": 4, "daily": 5}
ALIASES = {"climbing": "climb", "cadences": "cadence|cappella", "tutoring": "tutor", "soccer": "soccer|intramural",
           "mixer": "mixer|international students", "studio": "studio|art collective", "debate": "debate",
           "robotics": "robot", "chess": "chess", "capstone": "capstone|dashboard"}
SEG_TIMED = {1: False, 2: False, 3: True, 4: True}  # experiment.js TIMED_SEGMENTS

LOG = []
def log(msg):
    print(msg); LOG.append(str(msg))

def cluster_of(tactic):
    if not isinstance(tactic, str): return None
    for k, v in CLUSTER.items():
        if tactic.startswith(k): return v
    return "Other"

# ----------------------------------------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------------------------------------
def _lit(s):
    if not isinstance(s, str): return s
    try: return ast.literal_eval(s)
    except Exception: return s

def read_file(path):
    """Return (summaries: list[dict], events: list[dict]) from one 3-section export."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    mode, hdr, summ, evs = None, None, [], []
    for r in rows:
        if not r or all(c == "" for c in r): continue
        if r[0] == "Participant_ID":
            hdr = r
            mode = "summary" if "Task_Order" in r else ("events" if "Segment" in r else "final")
            continue
        if hdr is None: continue
        d = dict(zip(hdr, r))
        if mode == "summary": summ.append(d)
        else:
            d.setdefault("Task", ""); d.setdefault("Segment", ""); d.setdefault("Global_Trial", "")
            evs.append(d)
    return summ, evs

def load_all(data):
    files = sorted(glob.glob(os.path.join(data, "*.csv"))) if os.path.isdir(data) else sorted(glob.glob(data))
    if not files: sys.exit(f"No CSV files found at {data}")
    S, E, seen = [], [], {}
    for fp in prog(files, "reading files"):
        try: s, e = read_file(fp)
        except Exception as ex: log(f"!! could not read {fp}: {ex}"); continue
        if not s or not any(d.get("Event_Type") for d in e):
            log(f"-- skipped {os.path.basename(fp)}: not a participant export (no summary row / no event log)"); continue
        for d in s:
            if d["Participant_ID"] in seen: log(f"!! duplicate participant {d['Participant_ID']} in {os.path.basename(fp)} -- keeping the file with more events")
            seen.setdefault(d["Participant_ID"], []).append((fp, len(e)))
        for d in e: d["_file"] = os.path.basename(fp)
        S += s; E += e
    # de-duplicate participants that appear in >1 file (keep the most complete)
    dup = {p: v for p, v in seen.items() if len(v) > 1}
    for p, v in dup.items():
        keep = max(v, key=lambda x: x[1])[0]
        E = [d for d in E if not (d["Participant_ID"] == p and d["_file"] != os.path.basename(keep))]
    seen_p = set(); S2 = []
    for d in S:
        if d["Participant_ID"] in seen_p: continue
        seen_p.add(d["Participant_ID"]); S2.append(d)
    ev = pd.DataFrame(E)
    ev["pid"] = ev["Participant_ID"]; ev["etype"] = ev["Event_Type"]
    ev["gt"] = pd.to_numeric(ev["Global_Trial"], errors="coerce")
    ev["seg"] = pd.to_numeric(ev["Segment"], errors="coerce")
    ev["ts"] = pd.to_datetime(ev["Timestamp"], utc=True, errors="coerce", format="ISO8601")
    n_bad = int(ev["ts"].isna().sum())
    if n_bad: log(f"!! {n_bad} of {len(ev)} timestamps could not be parsed -- time-based measures will be missing for those events")
    ev["d"] = ev["Data"].map(_lit)
    ev = ev.sort_values("pid", kind="stable").reset_index(drop=True)  # keep the log's own event order within each participant
    return S2, ev, files

# ----------------------------------------------------------------------------------------------------------
# optional repo ground truth
# ----------------------------------------------------------------------------------------------------------
def load_repo(repo):
    if not repo: return None
    try:
        mods = ["fastapi", "fastapi.responses", "fastapi.staticfiles", "fastapi.templating", "langchain_google_genai",
                "langchain_openai", "langchain_core", "langchain_core.runnables", "langchain_core.prompts",
                "langchain_core.messages", "dotenv", "uvicorn", "sheet_logger", "requests"]
        saved = {m: sys.modules.get(m) for m in mods}
        for m in mods: sys.modules[m] = MagicMock()
        cwd = os.getcwd(); sys.path.insert(0, repo); os.chdir(repo)
        spec = importlib.util.spec_from_file_location("hti_main", os.path.join(repo, "main.py"))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        os.chdir(cwd)
        for m, v in saved.items():
            if v is None: sys.modules.pop(m, None)
            else: sys.modules[m] = v
        log(f"repo ground truth loaded from {repo}")
        return mod
    except Exception as ex:
        log(f"!! could not load repo ground truth ({ex}); continuing without it"); return None

def quality_raw(mod, cat, seg_key, ps, load):
    return getattr(mod, f"plan_quality_{cat}")(seg_key, ps, load)

def locked_fact_ids(mod, cat, seg_key, load):
    if cat == "A": return [f["id"] for f in mod.describe_locked_facts_A(seg_key, load)]
    if cat == "B": return [f["id"] for f in mod.describe_locked_facts_B(seg_key)]
    return [f["id"] for f in mod.describe_locked_facts_C(seg_key, load)]

def toggle_target(mod, cat, seg_key, ps, target):
    """Return the plan_state with target's presence flipped (B/C). Used to test whether following the
    tactic's push (add/keep target) is costly."""
    ps = json.loads(json.dumps(ps))
    if cat == "C":
        sel = ps.setdefault("selections", [])
        if target in sel: sel.remove(target)
        else: sel.append(target)
    elif cat == "B":
        sel = ps.setdefault("selections", {"major": [], "minor": [], "elective": []})
        present = [b for b in sel if target in sel[b]]
        if present:
            for b in present: sel[b].remove(target)
        else:
            pools = mod.TASK_DATA_B[seg_key]["pools"]
            for b, ids in pools.items():
                if target in ids: sel.setdefault(b, []).append(target); break
    return ps

def contrib(cat, ps, item):
    ps = ps or {}
    if not cat or not item: return 0.0
    if cat == "A": return float((ps.get("hours") or {}).get(item, 0) or 0)
    if cat == "B":
        s = ps.get("selections") or {}
        return 1.0 if item in (s.get("major") or []) + (s.get("minor") or []) + (s.get("elective") or []) else 0.0
    return 1.0 if item in (ps.get("selections") or []) else 0.0

def fact_about(fid, target):
    kind, _, rest = str(fid).partition("_")
    return rest == target if kind in ("item", "hours", "prereq") else target in rest.split("_")

def target_regex(target):
    t = str(target)
    if t in ALIASES: return re.compile(ALIASES[t], re.I)
    m = re.match(r"^([a-z]+)(\d+)$", t)
    if m: return re.compile(rf"{m.group(1)}\s*-?\s*{m.group(2)}", re.I)
    return re.compile(re.escape(t), re.I)

# ----------------------------------------------------------------------------------------------------------
# build tables
# ----------------------------------------------------------------------------------------------------------
def num(x):
    try: return float(x)
    except Exception: return np.nan

def build_participants(S):
    rows = []
    for s in S:
        r = {"pid": s["Participant_ID"], "group": s.get("Group"), "task_order": s.get("Task_Order"),
             "age": num(s.get("Age")), "gender": s.get("Gender"), "education": s.get("Education"),
             "ai_experience_raw": s.get("AI_Experience"), "domain": s.get("Domain"),
             "critical_ability": num(s.get("Critical_Ability")), "ai_planning_familiarity": num(s.get("AI_Planning_Familiarity"))}
        exp = str(s.get("AI_Experience", "")).lower()
        r["ai_experience"] = next((v for k, v in AI_EXP.items() if exp.startswith(k)), np.nan)
        pe = [num(s.get(f"P_e{i}")) for i in range(1, 5)]
        for i, v in enumerate(pe, 1): r[f"P_e{i}"] = v
        r["emotionality"] = np.nanmean(pe) if not all(np.isnan(pe)) else np.nan
        for k in ["Claims_Accepted", "Claims_Rejected", "Transient_Acceptance", "Turns_Elapsed", "Corrections_Made",
                  "Recall_Accuracy_Pct", "Notifications_Shown_Total", "DivAttn_Accuracy_Pct", "DivAttn_False_Alarms",
                  "Plan_Quality_Avg", "Plan_Quality_Weeks_Scored"]:
            r["exp_" + k] = num(s.get(k))
        for k in ["Recall_Qualified", "DivAttn_Qualified", "Bonus_Qualified", "Plan_Quality_Qualified"]:
            r["exp_" + k] = str(s.get(k)).strip().lower() == "true"
        r["influence_moment_text"] = s.get("Recognition_Influence_Moment", "")
        r["comm_style_text"] = s.get("Recognition_Communication_Style", "")
        for i in range(1, 4):
            pass
        for a in "ABC":
            key = {"A": "A_Workload", "B": "B_DegreeRequirements", "C": "C_NonAcademicLife"}[a]
            r[f"load_seq_{a}"] = s.get(f"{key}_Trial_Load_Sequence")
            r[f"dropped_idx_{a}"] = num(s.get(f"{key}_Dropped_Category_Index"))
        rows.append(r)
    return pd.DataFrame(rows)

def build_trials(S, ev, repo):
    """One row per participant x global trial (12 per participant)."""
    tl_rows, msg_rows = [], []
    sumd = {s["Participant_ID"]: s for s in S}
    for pid, e in prog(list(ev.groupby("pid", sort=False)), "building trials (per participant)"):
        s = sumd.get(pid, {})
        order = str(s.get("Task_Order", "")).split("|")
        tri_all = e[e["etype"] == "trial_started"]
        n_starts = tri_all.groupby("gt").size().to_dict()
        tri = tri_all.drop_duplicates("gt", keep="last")  # a refreshed/restarted segment fires trial_started again: keep the last attempt only
        for ridx, ts_row in tri.iterrows():
            gt = int(ts_row["gt"]); task = ts_row["Task"]; cat = task[:1]; seg = int(ts_row["seg"])
            seg_key = f"segment_{seg}"
            et = e[(e["gt"] == gt) & (e.index >= ridx)]
            load = ts_row["d"].get("load_level")
            start_state = ts_row["d"].get("starting_plan_state")
            sub = et[et["etype"] == "trial_submitted"]
            subd = sub.iloc[-1]["d"] if len(sub) else {}
            t0 = ts_row["ts"]; t1 = sub.iloc[-1]["ts"] if len(sub) else pd.NaT
            row = dict(pid=pid, gt=gt, n_starts=n_starts.get(gt, 1), task=task, cat=cat, seg=seg, load=load, high=int(load == "HighLoad"),
                       timed=SEG_TIMED.get(seg, False), task_position=(order.index(task) + 1) if task in order else np.nan,
                       completed=len(sub) > 0, timed_out=bool(subd.get("timed_out")) if subd else np.nan,
                       passed=subd.get("passed") if subd else np.nan, submit_attempts=subd.get("submit_attempt") if subd else np.nan,
                       final_pct=num(subd.get("final_score")) if subd else np.nan,
                       duration_s=(t1 - t0).total_seconds() if pd.notna(t1) else np.nan)
            # ---- per-trial questionnaires (from summary row)
            for k in TLX_KEYS: row[f"tlx_{k.lower()}"] = num(s.get(f"Trial{gt}_TLX_{k}"))
            row["flags"] = s.get(f"Trial{gt}_Flags", "")
            row["feedback_text"] = s.get(f"Trial{gt}_Feedback", "")
            row["justification_text"] = s.get(f"Trial{gt}_Justification", "")
            row["reasoning_score"] = num(s.get(f"Trial{gt}_ReasoningScore"))
            # ---- dark turn
            ai = et[et["etype"].isin(["ai_response", "ai_proactive_message"])]
            dark = ai[ai["d"].map(lambda d: isinstance(d, dict) and d.get("isDark") is True).astype(bool)]
            row["n_dark_events"] = len(dark)
            user = et[et["etype"] == "user_message"]
            row["n_user_msgs"] = len(user)
            row["n_ai_replies"] = int((et["etype"] == "ai_response").sum())
            row["n_proactive"] = int((et["etype"] == "ai_proactive_message").sum())
            tgt = None; dts = None
            if len(dark):
                dr = dark.iloc[0]; dd = dr["d"]; dts = dr["ts"]; tgt = dd.get("target_item")
                row.update(tactic=dd.get("category"), cluster=cluster_of(dd.get("category")), target=tgt,
                           dark_via=dr["etype"], tactic_verified=dd.get("tactic_verified"),
                           dark_downgraded=dd.get("dark_turn_downgraded"), dark_fallback=dd.get("dark_turn_fallback_used"),
                           dark_target_reply=dd.get("dark_target_reply"), pattern_id=dd.get("pattern_id"),
                           dark_text_words=len(str(dd.get("text", "")).split()),
                           dark_clean_words=len(str(dd.get("decoy", "")).split()),
                           t_dark_s=(dts - t0).total_seconds(),
                           n_user_before_dark=int((user["ts"] < dts).sum()))
                before = contrib(cat, dd.get("plan_state_at_request"), tgt)
                # walk states after the dark turn
                peak = before; final = None
                for _, r2 in et[et["ts"] >= dts].iterrows():
                    d2 = r2["d"]
                    if isinstance(d2, dict) and r2["etype"] in ("ai_response", "ai_proactive_message", "plan_actions_applied") and d2.get("plan_state_snapshot") is not None:
                        peak = max(peak, contrib(cat, d2["plan_state_snapshot"], tgt)); final = d2["plan_state_snapshot"]
                if subd and subd.get("final_plan_state") is not None: final = subd["final_plan_state"]
                after = contrib(cat, final, tgt) if final is not None else np.nan
                peak = max(peak, after) if not np.isnan(after) else peak
                if np.isnan(after): outcome = None
                elif cat == "A":
                    outcome = "rejected" if after > before else ("transient" if peak > before else "accepted")
                else:
                    outcome = "accepted" if after > 0 else ("transient" if (before == 0 and peak > 0) else "rejected")
                row.update(target_before=before, target_after=after, target_peak=peak, outcome=outcome)
                row["accepted"] = np.nan if outcome is None else float(outcome == "accepted")
                row["accepted_or_transient"] = np.nan if outcome is None else float(outcome in ("accepted", "transient"))
                # ---- PRIMARY DV = plan state at the FIRST submit attempt after the dark turn (this is also the platform's own
                # definition: main.py closes the segment at the first trial_submitted, and the front-end logs trial_submitted on
                # every attempt, failed ones included). The FINAL plan is contaminated by the submit gate, which forces people to
                # fix a plan that fails the checklist (that is what made Category A look like 0% compliance). Final-plan version kept
                # as *_final columns for the sensitivity analysis.
                row.update(outcome_final=outcome, accepted_final=row["accepted"], accepted_or_transient_final=row["accepted_or_transient"])
                sub_dark = sub[sub.index > dr.name]
                o1 = None; after1 = np.nan
                if len(sub_dark):
                    fi = sub_dark.index[0]; fs = sub_dark.iloc[0]["d"].get("final_plan_state")
                    pk1 = before
                    for _, r3 in et[(et.index >= dr.name) & (et.index < fi)].iterrows():
                        d3 = r3["d"]
                        if isinstance(d3, dict) and r3["etype"] in ("ai_response", "ai_proactive_message", "plan_actions_applied") and d3.get("plan_state_snapshot") is not None:
                            pk1 = max(pk1, contrib(cat, d3["plan_state_snapshot"], tgt))
                    if fs is not None:
                        after1 = contrib(cat, fs, tgt); pk1 = max(pk1, after1)
                        if cat == "A": o1 = "rejected" if after1 > before else ("transient" if pk1 > before else "accepted")
                        else: o1 = "accepted" if after1 > 0 else ("transient" if (before == 0 and pk1 > 0) else "rejected")
                row.update(outcome=o1, target_after_first=after1, first_attempt_is_final=bool(len(sub_dark) and sub_dark.index[0] == sub.index[-1]),
                           accepted=np.nan if o1 is None else float(o1 == "accepted"),
                           accepted_or_transient=np.nan if o1 is None else float(o1 in ("accepted", "transient")))
                # ---- Category A: HOW and WHEN the under-allocated target got corrected. accepted/rejected is at ceiling for A (the submit gate
                # forces everyone to raise the hours), so the informative behaviours are speed, who specified the fix, and whether the AI's own
                # later replies had already disclosed the true number.
                if cat == "A":
                    fx = None
                    for ix, r4 in et[et.index > dr.name].iterrows():
                        d4 = r4["d"]
                        if r4["etype"] == "plan_actions_applied" and isinstance(d4, dict) and d4.get("plan_state_snapshot") is not None \
                           and contrib(cat, d4["plan_state_snapshot"], tgt) > before:
                            fx = (ix, r4); break
                    row["a_fixed"] = int(fx is not None)
                    if fx is not None:
                        fix_ix, fr = fx; fts = fr["ts"]; rxa = target_regex(tgt)
                        um = user[(user["ts"] > dts) & (user.index < fix_ix)]          # user messages after the dark turn, up to and incl. the one that produced the fix
                        row["a_secs_to_fix"] = (fts - dts).total_seconds(); row["a_msgs_to_fix"] = len(um)
                        row["a_asked_target_before_fix"] = int(any(rxa.search(str(m.get("text", ""))) for m in um["d"].iloc[:-1])) if len(um) > 1 else 0
                        lastm = user[user.index < fix_ix]
                        txt = str(lastm.iloc[-1]["d"].get("text", "")) if len(lastm) else ""
                        val = next((a_.get("value") for a_ in (fr["d"].get("actions") or []) if a_.get("item") == tgt), None)
                        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", txt)]
                        # 1 = the participant typed the number (or named the item with a number) that produced the fix; 0 = the AI/plan supplied it
                        row["a_fix_user_specified"] = int(bool(nums) and (val is None or any(abs(x - float(val)) < 1e-9 for x in nums)))
                        fa_ = et[et["etype"] == "fact_revealed"]
                        fa_ = fa_[fa_["d"].map(lambda d: isinstance(d, dict) and fact_about(d.get("id"), tgt)).astype(bool)]
                        row["a_truth_disclosed_before_fix"] = int(((fa_["ts"] > dts) & (fa_["ts"] <= fts)).any())
                # ---- verification behaviour around the dark turn
                facts = et[et["etype"] == "fact_revealed"]
                fa = facts[facts["d"].map(lambda d: fact_about(d.get("id"), tgt)).astype(bool)]
                row["n_facts_revealed"] = len(facts)
                row["target_fact_before_dark"] = int((fa["ts"] < dts).sum() > 0)
                fa_after = fa[fa["ts"] >= dts]
                row["target_fact_after_dark"] = int(len(fa_after) > 0)
                row["target_fact_latency_s"] = (fa_after["ts"].min() - dts).total_seconds() if len(fa_after) else np.nan
                rx = target_regex(tgt)
                after_msgs = user[user["ts"] > dts]
                before_msgs = user[user["ts"] < dts]
                row["asked_target_after_dark"] = int(any(rx.search(str(m.get("text", ""))) for m in after_msgs["d"]))
                row["asked_target_before_dark"] = int(any(rx.search(str(m.get("text", ""))) for m in before_msgs["d"]))
                # ---- ground truth via repo
                if repo is not None and isinstance(dd.get("plan_state_at_request"), dict):
                    try:
                        psr = dd["plan_state_at_request"]
                        row["q_at_dark"] = quality_raw(repo, cat, seg_key, psr, load)
                        if final is not None: row["q_final_raw"] = quality_raw(repo, cat, seg_key, final, load)
                        if cat == "A":
                            seg = repo.TASK_DATA_A[seg_key]; th = seg.get("true_hours", seg.get("true_minimum"))[load]
                            row["target_shortfall_at_dark"] = max(0.0, th.get(tgt, 0) - (psr.get("hours") or {}).get(tgt, 0))
                            row["target_costly"] = row["target_shortfall_at_dark"] > 0
                            row["target_costly_repo"] = repo.find_costly_target_A(seg_key, psr, load, preferred=tgt) == tgt
                        else:
                            alt = toggle_target(repo, cat, seg_key, psr, tgt)
                            q_alt = quality_raw(repo, cat, seg_key, alt, load)
                            in_plan = before > 0
                            # "following the push" = keeping (if present) / adding (if absent) the target
                            q_follow, q_resist = (row["q_at_dark"], q_alt) if in_plan else (q_alt, row["q_at_dark"])
                            row["q_cost_of_following"] = q_follow - q_resist
                            row["target_costly"] = q_follow < q_resist
                            fn = repo.find_costly_target_B if cat == "B" else repo.find_costly_target_C
                            row["target_costly_repo"] = fn(seg_key, psr, load, preferred=tgt) == tgt  # platform's own verification (incl. tie-break on hours/credits)
                        ids = locked_fact_ids(repo, cat, seg_key, load)
                        row["n_locked_facts"] = len(ids); row["prop_facts_revealed"] = len(set(subd.get("revealed_fact_ids", [])) & set(ids)) / max(1, len(ids)) if subd else np.nan
                    except Exception as ex:
                        row["repo_err"] = str(ex)[:80]
            # ---- corrections (replicates platform definition, per trial)
            run = start_state; corr = 0; n_rem = 0; n_assign = 0
            for _, r2 in et[et["etype"] == "plan_actions_applied"].iterrows():
                for a in r2["d"].get("actions", []):
                    op, item = a.get("op"), a.get("item")
                    if op == "remove": corr += 1; n_rem += 1
                    elif op == "assign":
                        n_assign += 1
                        prior = contrib(cat, run, item)
                        if cat == "A" and prior and a.get("value") != prior: corr += 1
                    elif op in ("increase", "decrease") and cat == "A":
                        if op == "decrease" or contrib(cat, run, item): corr += 1
                if r2["d"].get("plan_state_snapshot") is not None: run = r2["d"]["plan_state_snapshot"]
            row.update(corrections=corr, n_removes=n_rem, n_assigns=n_assign, n_plan_action_events=int((et["etype"] == "plan_actions_applied").sum()))
            # ---- load-manipulation telemetry
            row["n_notifications"] = int((et["etype"] == "notification_shown").sum())
            rc = et[et["etype"] == "recall_check_answered"]
            row["n_recall_probes"] = len(rc)
            row["recall_correct"] = int(rc["d"].map(lambda d: bool(d.get("correct"))).sum()) if len(rc) else 0
            row["recall_acc"] = row["recall_correct"] / len(rc) if len(rc) else np.nan
            hit = int((et["etype"] == "div_attn_hit").sum()); miss = int((et["etype"] == "div_attn_miss").sum()); fal = int((et["etype"] == "div_attn_false_alarm").sum())
            row.update(da_hits=hit, da_misses=miss, da_false_alarms=fal, da_acc=hit / (hit + miss) if (hit + miss) else np.nan)
            # ---- reading-time / hesitation proxies
            lat_dark = lat_neutral = np.nan
            evs = et[et["etype"].isin(["ai_response", "ai_proactive_message", "user_message"])].sort_values("ts")
            lat_d, lat_n = [], []
            arr = list(evs.itertuples())
            for i, x in enumerate(arr):
                if x.etype in ("ai_response", "ai_proactive_message"):
                    nxt = next((y for y in arr[i + 1:] if y.etype == "user_message"), None)
                    if nxt is not None:
                        (lat_d if (isinstance(x.d, dict) and x.d.get("isDark")) else lat_n).append((nxt.ts - x.ts).total_seconds())
            row["latency_after_dark_s"] = np.mean(lat_d) if lat_d else np.nan
            row["latency_after_neutral_s"] = np.mean(lat_n) if lat_n else np.nan
            # dwell telemetry (visible-ms of each AI message)
            dw = subd.get("message_dwell_telemetry", {}) if subd else {}
            if isinstance(dw, dict) and dw and row.get("pattern_id") in dw:
                dvals = {k: v.get("totalVisibleMs", np.nan) for k, v in dw.items() if isinstance(v, dict)}
                row["dwell_dark_ms"] = dvals.get(row["pattern_id"], np.nan)
                oth = [v for k, v in dvals.items() if k != row["pattern_id"]]
                row["dwell_other_mean_ms"] = np.mean(oth) if oth else np.nan
                row["dwell_dark_rel"] = row["dwell_dark_ms"] / row["dwell_other_mean_ms"] if oth and row["dwell_other_mean_ms"] else np.nan
            # user message typing telemetry
            words, wpm, pause, bs = [], [], [], []
            for _, m in user.iterrows():
                d = m["d"]; t = d.get("telemetry", {}) or {}
                words.append(len(str(d.get("text", "")).split())); wpm.append(num(t.get("wpm"))); pause.append(num(t.get("pause_ms"))); bs.append(num(t.get("backspaces")))
                msg_rows.append(dict(pid=pid, gt=gt, load=load, cat=cat, ts=m["ts"], words=words[-1], wpm=wpm[-1], pause_ms=pause[-1], backspaces=bs[-1],
                                     after_dark=int(dts is not None and m["ts"] > dts), text=d.get("text", "")))
            row.update(msg_words_mean=np.mean(words) if words else np.nan, msg_wpm_mean=np.nanmean(wpm) if wpm else np.nan,
                       msg_pause_mean_s=np.nanmean(pause) / 1000 if pause else np.nan, msg_backspaces_mean=np.nanmean(bs) if bs else np.nan)
            tl_rows.append(row)
    T = pd.DataFrame(tl_rows).sort_values(["pid", "gt"]).reset_index(drop=True)
    # derived
    T["rtlx"] = T[["tlx_mental", "tlx_physical", "tlx_temporal", "tlx_effort", "tlx_frustration"]].sum(axis=1, min_count=5).add(8 - T["tlx_performance"]) / 6
    T["load_cog"] = T[["tlx_mental", "tlx_temporal", "tlx_effort"]].mean(axis=1)
    T["timed_i"] = T["timed"].astype(int)
    T["pos_z"] = (T["gt"] - 6.5) / 3.45
    T["dir"] = np.where(T["cat"] == "A", "understate-need", "harmful-add/keep")
    T["dark_first_reply"] = (T["dark_target_reply"] == 1).astype(float)
    T["excl_trial"] = T["flags"].fillna("").str.contains("tactic_unverified|no_dark_turn|ai_error|submit_unverified")
    # within-person centred perceived load (for dose-response)
    T["final_pct_scored"] = np.where(T["passed"] == True, T["final_pct"], 0.0)
    T["rtlx_within"] = T["rtlx"] - T.groupby("pid")["rtlx"].transform("mean")
    T["rtlx_between"] = T.groupby("pid")["rtlx"].transform("mean")
    return T, pd.DataFrame(msg_rows)

def build_recognition(ev, T):
    rows = []
    for pid, e in ev[ev["etype"] == "recognition_test_submitted"].groupby("pid"):
        d = e.iloc[-1]["d"]
        for it in d.get("scored_results", []):
            rows.append(dict(pid=pid, q=it.get("question_id"), pattern_id=it.get("pattern_id"), category=it.get("category"),
                             text=it.get("text"), flagged=int(bool(it.get("flagged_as_dark"))), agreement=num(it.get("agreement")),
                             is_dark=int(bool(it.get("was_actually_dark"))), hit=int(bool(it.get("hit")))))
    R = pd.DataFrame(rows)
    if R.empty: return R
    R = R[R["pattern_id"] != "SEED"].copy()
    R["tactic"] = R["category"].str.replace("_Decoy", "", regex=False)
    keep = ["pid", "pattern_id", "gt", "load", "high", "cat", "task", "timed", "outcome", "accepted", "tactic", "cluster", "rtlx"]
    R = R.merge(T[keep].rename(columns={"tactic": "tactic_trial"}), on=["pid", "pattern_id"], how="left")
    return R

# ----------------------------------------------------------------------------------------------------------
# statistics helpers
# ----------------------------------------------------------------------------------------------------------
REPORT = []
def rep(line=""): REPORT.append(line)
def H(title): rep(); rep(f"## {title}"); rep()

def fmt_p(p):
    if p is None or (isinstance(p, float) and np.isnan(p)): return "p = n/a"
    return "p < .001" if p < .001 else f"p = {p:.3f}".replace("0.", ".")

def wilson(k, n, z=1.96):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)

def holm(pvals):
    p = np.array(pvals, float); o = np.argsort(p); m = len(p); adj = np.empty(m); run = 0
    for i, idx in enumerate(o):
        run = max(run, (m - i) * p[idx]); adj[idx] = min(1, run)
    return adj

def pmeans(df, dv, cond="load", levels=("LowLoad", "HighLoad")):
    w = df.groupby(["pid", cond])[dv].mean().unstack(cond)
    return w.reindex(columns=list(levels)).dropna()

def paired(df, dv, cond="load", levels=("LowLoad", "HighLoad"), nperm=10000, seed=1):
    """Participant-level paired comparison High - Low on the per-participant means. Returns dict."""
    w = pmeans(df, dv, cond, levels)
    n = len(w); out = dict(dv=dv, n=n)
    if n < 2:
        out.update(mean_low=w.iloc[:, 0].mean() if n else np.nan, mean_high=w.iloc[:, 1].mean() if n else np.nan); return out
    a, b = w.iloc[:, 0].values, w.iloc[:, 1].values; d = b - a
    out.update(mean_low=a.mean(), mean_high=b.mean(), sd_low=a.std(ddof=1), sd_high=b.std(ddof=1), diff=d.mean(),
               n_up=int((d > 0).sum()), n_down=int((d < 0).sum()), n_tie=int((d == 0).sum()))
    sd = d.std(ddof=1)
    out["dz"] = d.mean() / sd if sd > 0 else np.nan
    t = stats.ttest_rel(b, a); out.update(t=t.statistic, p_t=t.pvalue, df=n - 1)
    try: out["p_wilcoxon"] = stats.wilcoxon(b, a, zero_method="wilcox").pvalue if np.any(d != 0) else np.nan
    except Exception: out["p_wilcoxon"] = np.nan
    nz = int((d != 0).sum())
    out["p_sign"] = stats.binomtest(int((d > 0).sum()), nz, .5).pvalue if nz > 0 else np.nan
    rng = np.random.default_rng(seed)
    bs = [rng.choice(d, n, replace=True).mean() for _ in range(2000)]
    out["ci_lo"], out["ci_hi"] = np.percentile(bs, [2.5, 97.5])
    signs = rng.choice([-1, 1], size=(nperm, n)); out["p_signflip"] = (np.mean(np.abs((signs * d).mean(1)) >= abs(d.mean()) - 1e-12))
    return out

def perm_within(df, dv="accepted", nperm=10000, seed=2):
    """Randomisation test: shuffle the High/Low labels *within participant* (keeps each person's 6/6 split)."""
    d = df.dropna(subset=[dv]).copy(); pids = d["pid"].unique(); rng = np.random.default_rng(seed)
    grp = [(g[dv].values.astype(float), g["high"].values.astype(int)) for _, g in d.groupby("pid")]
    grp = [(y, h) for y, h in grp if 0 < h.sum() < len(h)]
    if not grp: return np.nan, np.nan
    def stat(perm):
        s = []
        for y, h in grp:
            hh = rng.permutation(h) if perm else h
            s.append(y[hh == 1].mean() - y[hh == 0].mean())
        return np.mean(s)
    obs = stat(False); null = np.array([stat(True) for _ in prog(range(nperm), "permutation test")])
    return obs, float(np.mean(np.abs(null) >= abs(obs) - 1e-12))

def gee_logit(formula, df, group="pid", _retry=True):
    if not HAVE_SM or df[group].nunique() < 5: return None
    try:
        m = smf.gee(formula, groups=group, data=df, family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
        ci = m.conf_int()
        t = pd.DataFrame({"OR": np.exp(m.params), "CI_lo": np.exp(ci[0]), "CI_hi": np.exp(ci[1]), "b": m.params, "se": m.bse, "z": m.tvalues, "p": m.pvalues})
        t.attrs["n_obs"] = int(m.nobs); t.attrs["n_groups"] = df[group].nunique()
        if _retry and (t["p"].isna().any() or (t["se"] > 50).any()) and "cat" in df.columns:
            # complete/quasi-complete separation (e.g. a task where nobody complied): drop task levels with a constant outcome and refit
            y = formula.split("~")[0].strip(); keep = df.groupby("cat")[y].transform("nunique") > 1
            if keep.sum() < len(df) and keep.sum() > 30:
                log(f"   separation in `{formula}`: refit without constant-outcome tasks ({sorted(df.loc[~keep, 'cat'].unique())})")
                t2 = gee_logit(formula, df[keep], group, _retry=False)
                if t2 is not None: t2.attrs["note"] = "refit without constant-outcome tasks"; return t2
        return t
    except Exception as ex:
        log(f"   GEE failed for `{formula}`: {str(ex)[:100]}"); return None

def gee_gauss(formula, df, group="pid"):
    if not HAVE_SM or df[group].nunique() < 5: return None
    try:
        m = smf.gee(formula, groups=group, data=df, family=sm.families.Gaussian(), cov_struct=sm.cov_struct.Exchangeable()).fit()
        ci = m.conf_int()
        t = pd.DataFrame({"b": m.params, "CI_lo": ci[0], "CI_hi": ci[1], "se": m.bse, "z": m.tvalues, "p": m.pvalues}); t.attrs["n_obs"] = int(m.nobs); return t
    except Exception as ex:
        log(f"   GEE(gauss) failed for `{formula}`: {str(ex)[:100]}"); return None

def lmm(formula, df, group="pid"):
    if not HAVE_SM or df[group].nunique() < 5: return None
    m = None
    for meth in ("lbfgs", "powell", "nm"):
        try: m = smf.mixedlm(formula, df, groups=df[group]).fit(reml=True, method=meth); break
        except Exception as ex: err = str(ex)[:80]
    if m is None: log(f"   LMM failed for `{formula}`: {err}"); return None
    ci = m.conf_int().iloc[:len(m.fe_params)]
    t = pd.DataFrame({"b": m.fe_params, "CI_lo": ci[0], "CI_hi": ci[1], "se": m.bse_fe, "z": m.tvalues[:len(m.fe_params)], "p": m.pvalues[:len(m.fe_params)]})
    t.attrs["icc_var"] = float(m.cov_re.iloc[0, 0]); t.attrs["resid"] = float(m.scale); return t

def save(df, name, out, index=True):
    p = os.path.join(out, "tables", name); df.to_csv(p, index=index); return p

def coef_line(t, term, label=None, logit=True):
    if t is None or term not in t.index: return f"{label or term}: n/a"
    r = t.loc[term]
    if logit: return f"{label or term}: OR = {r['OR']:.2f}, 95% CI [{r['CI_lo']:.2f}, {r['CI_hi']:.2f}], {fmt_p(r['p'])}"
    return f"{label or term}: b = {r['b']:.2f}, 95% CI [{r['CI_lo']:.2f}, {r['CI_hi']:.2f}], {fmt_p(r['p'])}"

def para(pr, name, unit=""):
    if pr.get("n", 0) < 2: return f"{name}: Low = {pr.get('mean_low', np.nan):.2f}, High = {pr.get('mean_high', np.nan):.2f} (N < 2, no inference)."
    return (f"{name}: Low M = {pr['mean_low']:.2f}, High M = {pr['mean_high']:.2f}{unit}; mean within-person diff = {pr['diff']:+.2f} "
            f"[{pr['ci_lo']:+.2f}, {pr['ci_hi']:+.2f}] (bootstrap 95% CI), paired t({pr['df']}) = {pr['t']:.2f}, {fmt_p(pr['p_t'])}, "
            f"Wilcoxon {fmt_p(pr['p_wilcoxon'])}, dz = {pr['dz']:.2f}; {pr['n_up']} of {pr['n']} participants higher under High load, {pr['n_down']} lower, {pr['n_tie']} tied.")

# ----------------------------------------------------------------------------------------------------------
# figures
# ----------------------------------------------------------------------------------------------------------
def style():
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED,
                         "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK, "axes.titlesize": 11,
                         "axes.titleweight": "bold", "figure.dpi": 150, "savefig.dpi": 300, "savefig.bbox": "tight",
                         "axes.grid": False, "legend.frameon": False})

def slope(ax, df, dv, title, ylabel=None):
    w = pmeans(df, dv)
    if w.empty: ax.set_title(title); return
    for _, r in w.iterrows(): ax.plot([0, 1], r.values, color="#bbbbbb", lw=.8, zorder=1)
    ax.scatter(np.zeros(len(w)), w.iloc[:, 0], color=LOW_C, s=22, zorder=3, edgecolor="white", linewidth=.6)
    ax.scatter(np.ones(len(w)), w.iloc[:, 1], color=HIGH_C, s=22, zorder=3, edgecolor="white", linewidth=.6)
    m = w.mean().values; se = w.sem().values * 1.96 if len(w) > 1 else [0, 0]
    ax.errorbar([-.18, 1.18], m, yerr=se, fmt="_", color=INK, capsize=4, lw=1.5, ms=12, zorder=4)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["Low load", "High load"]); ax.set_xlim(-.4, 1.4); ax.set_title(title)
    if ylabel: ax.set_ylabel(ylabel)

def savefig(fig, name, out):
    fig.savefig(os.path.join(out, "figures", name)); plt.close(fig)

# ----------------------------------------------------------------------------------------------------------
# analysis sections
# ----------------------------------------------------------------------------------------------------------
def paired_table(T, dvs, out, name, labels=None):
    rows = [paired(T, dv) for dv in dvs if dv in T.columns]
    df = pd.DataFrame(rows)
    if not df.empty and "p_wilcoxon" in df:
        ok = df["p_t"].notna()
        if ok.sum() > 1: df.loc[ok, "p_t_holm"] = holm(df.loc[ok, "p_t"].values)
    save(df, name, out, index=False); return df

def platform_replay(e, order):
    """Literal port of main.py::_compute_session_behavior_metrics (the platform's own Claims_* scoring), run on one participant's raw
    event log in file order. Returns (totals, {global_trial: outcome}). Lets us (a) check the exported Claims_* columns were produced by the
    deployed scoring code and (b) compare per trial with our own outcome coding."""
    tot = dict(accepted=0, rejected=0, transient=0); res = {}
    st = dict(seg=-1, cat=None, dark=None, peak=None, last=None)
    def close(final):
        d = st["dark"]
        if d and final is not None:
            after = contrib(st["cat"], final, d["target"]); before = d["before"]; pk = max(st["peak"] if st["peak"] is not None else before, after)
            if st["cat"] == "A": o = "rejected" if after > before else ("transient" if pk > before else "accepted")
            else: o = "accepted" if after > 0 else ("transient" if (before == 0 and pk > 0) else "rejected")
            tot[o] += 1; res[st["seg"] + 1] = o
        st["dark"] = None; st["peak"] = None
    for et, c in zip(e["etype"], e["d"]):
        c = c if isinstance(c, dict) else {}
        if et == "trial_started":
            close(st["last"]); st["seg"] += 1
            k = st["seg"] // 4
            st["cat"] = order[k].split("_")[0] if 0 <= k < len(order) and order[k] else None
            st["last"] = c.get("starting_plan_state")
        elif et in ("ai_response", "ai_proactive_message"):
            if c.get("isDark") and c.get("target_item") and st["dark"] is None and st["cat"]:
                b = contrib(st["cat"], c.get("plan_state_at_request"), c["target_item"]); st["dark"] = dict(target=c["target_item"], before=b); st["peak"] = b
            snap = c.get("plan_state_snapshot")
            if snap is not None:
                st["last"] = snap
                if st["dark"]: st["peak"] = max(st["peak"], contrib(st["cat"], snap, st["dark"]["target"]))
        elif et == "plan_actions_applied":
            snap = c.get("plan_state_snapshot")
            if snap is not None:
                st["last"] = snap
                if st["dark"]: st["peak"] = max(st["peak"], contrib(st["cat"], snap, st["dark"]["target"]))
        elif et == "trial_submitted":
            if c.get("final_plan_state") is not None: st["last"] = c["final_plan_state"]
            close(st["last"])
    close(st["last"])
    return tot, res

def detect_shifts(P, T, ev):
    """'Data shift' screen for participants with all 12 trials. A file is flagged as shifted when its platform-exported summary cannot have come
    from the deployed code: (1) the exported Claims_*/Transient_* do not match a replay of the deployed scoring rule on the file's own raw
    events, or (2) the client-side recall / divided-attention accuracy columns are blank although raw events for them exist (older client
    build). Reload/crash resumes and ai_error retries are counted and reported but are NOT by themselves grounds for dropping."""
    rows, RES = [], {}
    for _, p in P.iterrows():
        pid = p["pid"]; t = T[T["pid"] == pid]; e = ev[ev["pid"] == pid]
        try: tot, res = platform_replay(e, str(p["task_order"]).split("|")); failed = False
        except Exception: tot, res, failed = dict(accepted=np.nan, rejected=np.nan, transient=np.nan), {}, True  # events inconsistent with Task_Order
        RES[pid] = res
        complete = bool(t["completed"].sum() >= 12)
        def same(k, v):
            x = p["exp_" + k]; return True if (pd.isna(x) or failed) else abs(x - tot[v]) < 0.5
        claims_ok = all([same("Claims_Accepted", "accepted"), same("Claims_Rejected", "rejected"), same("Transient_Acceptance", "transient")])
        old = bool((pd.isna(p["exp_Recall_Accuracy_Pct"]) and (e["etype"] == "recall_check_answered").any())
                   or (pd.isna(p["exp_DivAttn_Accuracy_Pct"]) and e["etype"].isin(["div_attn_hit", "div_attn_miss"]).any()))
        why = []
        if complete and not claims_ok: why.append("exported Claims_* not reproducible by deployed scoring rule")
        if complete and old: why.append("recall/div-attn accuracy blank in export (older client build)")
        rows.append(dict(pid=pid, complete=complete, claims_replay_matches_export=claims_ok, replay_failed=failed,
                         exp_claims=f"{p['exp_Claims_Accepted']}/{p['exp_Claims_Rejected']}/{p['exp_Transient_Acceptance']}",
                         replay_claims=f"{tot['accepted']}/{tot['rejected']}/{tot['transient']}", older_build_signature=old,
                         n_trial_resumed=int((e["etype"] == "trial_resumed").sum()), n_ai_error=int((e["etype"] == "ai_error").sum()),
                         shifted=bool(why), reason="; ".join(why)))
    return pd.DataFrame(rows), RES

def s0_sample(P, T, R, ev, out, S, T_all=None):
    H("0. Sample, design integrity and data quality")
    n = P["pid"].nunique(); comp = T.groupby("pid")["completed"].sum()
    rep(f"- Participants in files: **N = {n}**; participants with all 12 trials submitted: {(comp == 12).sum()}; "
        f"with a recognition test: {R['pid'].nunique() if len(R) else 0}.")
    if P["age"].notna().any():
        rep(f"- Age: M = {P['age'].mean():.1f}, SD = {P['age'].std():.1f}, range {P['age'].min():.0f}-{P['age'].max():.0f}. "
            f"Gender: {P['gender'].value_counts().to_dict()}. Education: {P['education'].value_counts().to_dict()}. Domain: {P['domain'].value_counts().to_dict()}.")
        rep(f"- AI experience (1-5): M = {P['ai_experience'].mean():.2f}; critical-evaluation self-rating (1-5): M = {P['critical_ability'].mean():.2f}; "
            f"AI-planning familiarity (1-5): M = {P['ai_planning_familiarity'].mean():.2f}; emotionality (mean of 4 items): M = {P['emotionality'].mean():.2f}.")
    demo = P[["pid", "age", "gender", "education", "ai_experience_raw", "domain", "critical_ability", "ai_planning_familiarity", "emotionality"]]
    save(demo, "table1_participants.csv", out, index=False)
    # counterbalancing
    cell = T.groupby(["load", "task", "seg"]).size().unstack(["task", "seg"]).fillna(0).astype(int)
    save(cell, "design_cell_counts_load_x_task_segment.csv", out)
    rep(f"- Trials per load condition: {T['load'].value_counts().to_dict()}. Task-order counts: {P['task_order'].value_counts().to_dict()}.")
    seqs = pd.concat([P["load_seq_A"], P["load_seq_B"], P["load_seq_C"]]).value_counts()
    rep(f"- Load sequences used (per task block): {seqs.to_dict()}.")
    # dark-turn integrity
    d = T[T["n_dark_events"] > 0]
    rep(f"- Dark-turn delivery: {len(d)} of {len(T)} trials contain a dark turn; trials with exactly one: {(T['n_dark_events'] == 1).sum()}; "
        f"tactic verified by the platform's LLM check: {(d['tactic_verified'] == True).sum()} ({(d['tactic_verified'] == True).mean():.0%}); "
        f"downgraded: {int(d['dark_downgraded'].fillna(False).astype(bool).sum())}; fallback target used: {d['dark_fallback'].notna().sum()}; "
        f"delivered on proactive (not user-initiated) turn: {(d['dark_via'] == 'ai_proactive_message').sum()}.")
    rep(f"- Dark turn landed on the participant's 1st reply in {(d['dark_target_reply'] == 1).mean():.0%} of trials (deployed `main.py` targets 60/40 -- the old design notes say 70/30; report 60/40).")
    if "target_costly_repo" in T:
        rep(f"- **Manipulation validity (costly target):** platform's own check says the target was genuinely costly to follow at delivery in "
            f"{d['target_costly_repo'].mean():.0%} of dark turns; by a stricter plan-quality-only test {d['target_costly'].mean():.0%} "
            f"(the remainder are costly only through the hours/credit tie-break, i.e. a *small* cost). Report both, and use `q_cost_of_following` as severity.")
    ct = d.groupby(["cat", "tactic"]).size().rename("n_trials").reset_index()
    save(ct, "tactic_coverage.csv", out, index=False)
    rep(f"- Tactic coverage (n trials): " + "; ".join(f"{r.tactic} [{r.cat}]={r.n_trials}" for r in ct.itertuples()))
    flg = T["flags"].fillna("").str.split(";").explode().value_counts()
    flg = flg[flg.index != ""]
    rep(f"- Trial-level quality flags: {flg.to_dict() if len(flg) else 'none'}; timed-out trials: {int(T['timed_out'].fillna(False).sum())}/{len(T)} "
        f"({T.groupby('load')['timed_out'].mean().round(3).to_dict()}).")
    T_all0 = T if T_all is None else T_all
    rs = T_all0[T_all0["n_starts"] > 1]
    rep(f"- **Restarted segments** (trial_started fired more than once = page refresh/reload): {len(rs)} trials in {rs['pid'].nunique()} participants" + (": " + ", ".join(f"{p} (trials {sorted(g['gt'].tolist())})" for p, g in rs.groupby("pid")) if len(rs) else "") + ". Only the last attempt is analysed. The platform's own Claims_* / Corrections_* export counts a restart as an extra segment, which shifts its task assignment for the rest of the session -- if a participant listed here also appears in the cross-check mismatches below, the export is the one that is wrong.")
    # cross-check vs platform summary columns
    V = []
    T_all = T if T_all is None else T_all
    for _, p in P.iterrows():
        t = T_all[T_all["pid"] == p["pid"]]
        if t["completed"].sum() < 12: continue  # summary columns of unfinished sessions are checkpoints, not comparable
        ep = ev[ev["pid"] == p["pid"]]
        # the client's Turns_Elapsed counter is decremented whenever a send fails (ai_error) and the participant retries
        nu = int((ep["etype"] == "user_message").sum() - (ep["etype"] == "ai_error").sum())
        probes = t["n_recall_probes"].sum(); hits = t["da_hits"].sum(); miss = t["da_misses"].sum()
        pairs = [("Claims_Accepted", (t["outcome"] == "accepted").sum()), ("Claims_Rejected", (t["outcome"] == "rejected").sum()),
                 ("Transient_Acceptance", (t["outcome"] == "transient").sum()), ("Corrections_Made", t["corrections"].sum()),
                 ("Turns_Elapsed", nu), ("Notifications_Shown_Total", t["n_notifications"].sum()),
                 ("Recall_Accuracy_Pct", round(100 * t["recall_correct"].sum() / probes, 1) if probes else np.nan),
                 ("DivAttn_Accuracy_Pct", round(100 * hits / (hits + miss), 1) if hits + miss else np.nan),
                 ("Plan_Quality_Avg", round(t["final_pct_scored"].mean(), 1))]
        for k, mine in pairs:
            ex = p["exp_" + k]; V.append(dict(pid=p["pid"], metric=k, exported=ex, recomputed=mine, match=bool(np.isclose(ex, mine, atol=0.11, equal_nan=True))))
    V = pd.DataFrame(V); save(V, "validation_report.csv", out, index=False)
    bad = V[~V["match"]]
    rep(f"- **Export cross-check:** recomputed {len(V)} platform summary values from raw events; mismatches: {len(bad)}."
        + ("" if bad.empty else " -> " + "; ".join(f"{r.pid}:{r.metric} exported {r.exported} vs {r.recomputed}" for r in bad.itertuples())))
    if "outcome_platform" in T_all:
        c = T_all[T_all["completed"] & T_all["outcome_platform"].notna() & T_all["outcome"].notna()]
        dif = c[c["outcome_platform"] != c["outcome"]]
        only = T_all[T_all["completed"] & (T_all["outcome_platform"].notna() != T_all["outcome"].notna())]
        rep(f"- **Own outcome coding vs the platform's scoring rule (replayed):** {len(c)} trials scored by both, {len(dif)} disagree; {len(only)} trials scored by only one of them."
            + ("" if dif.empty and only.empty else " Disagreements (participant, trial, category: platform vs own; target hours/presence before -> at first submit): "
               + "; ".join(f"{r.pid} t{r.gt} {r.cat}: {r.outcome_platform} vs {r.outcome} ({r.target_before}->{r.target_after_first})" for r in dif.head(15).itertuples())
               + ("; only-one-scored: " + ", ".join(f"{r.pid} t{r.gt}" for r in only.head(10).itertuples()) if len(only) else "")))
        save(pd.concat([dif.assign(kind="disagree"), only.assign(kind="scored_by_one")])[["pid", "gt", "cat", "kind", "outcome_platform", "outcome", "target_before", "target_after_first", "n_user_msgs"]], "s0_outcome_disagreements.csv", out, index=False)

def s1_manip(P, T, out):
    H("1. Manipulation checks (was High load actually higher load?)")
    dvs = ["rtlx", "tlx_mental", "tlx_effort", "tlx_temporal", "tlx_frustration", "tlx_physical", "tlx_performance", "load_cog",
           "n_notifications", "recall_acc", "duration_s", "n_user_msgs"]
    tb = paired_table(T, dvs, out, "s1_manipulation_check_paired.csv")
    for dv, lab in [("rtlx", "Raw NASA-TLX composite (1-7)"), ("tlx_mental", "Mental demand"), ("tlx_effort", "Effort"), ("tlx_temporal", "Temporal demand"),
                    ("tlx_frustration", "Frustration"), ("tlx_performance", "Self-rated performance"), ("n_notifications", "Notifications per trial"),
                    ("recall_acc", "Notification recall-check accuracy"), ("duration_s", "Trial duration (s)"), ("n_user_msgs", "User messages per trial")]:
        r = tb[tb["dv"] == dv]
        if len(r): rep("- " + para(r.iloc[0].to_dict(), lab))
    hi = T[T["high"] == 1]
    if hi["da_hits"].sum() + hi["da_misses"].sum() > 0:
        hits, miss, fa = hi["da_hits"].sum(), hi["da_misses"].sum(), hi["da_false_alarms"].sum()
        pa = hi.groupby("pid").apply(lambda g: g["da_hits"].sum() / max(1, g["da_hits"].sum() + g["da_misses"].sum()))
        rep(f"- Divided-attention task (High load only): pooled hit rate = {hits / (hits + miss):.1%}; false alarms = {fa} total; per-participant hit rate M = {pa.mean():.1%} (SD {pa.std():.1%}). "
            f"Low hit-rates indicate the secondary task was demanding (or that the digit stream is too fast -- see participant feedback).")
    if HAVE_SM and len(T) > 20:
        for dv in ["rtlx", "tlx_mental"]:
            m = lmm(f"{dv} ~ high + timed_i + pos_z", T.dropna(subset=[dv]))
            if m is not None:
                save(m, f"s1_lmm_{dv}.csv", out); rep(f"- LMM {dv} ~ load + timed + trial position (random intercept for participant): " + coef_line(m, "high", "High load", logit=False) + "; " + coef_line(m, "timed_i", "timed segment", logit=False))
    # time-pressure confound: High load also had 20% less time on timed segments
    tt = T[T["timed"] == True]
    if len(tt): rep(f"- **Confound to disclose:** on timed segments (3 and 4) High load also cut the time limit by 20% (A/B 3:12 vs 4:00; C 2:24 vs 3:00). Timed-out: High {tt[tt.high==1]['timed_out'].mean():.0%} vs Low {tt[tt.high==0]['timed_out'].mean():.0%}. "
                    f"Run the load effect on untimed segments (1-2) only as a robustness check (see s2 sensitivity table).")

def rate_table(df, by, out, name):
    g = df.groupby(by)["accepted"].agg(["sum", "count"]).reset_index()
    g["rate"] = g["sum"] / g["count"]; ci = g.apply(lambda r: wilson(r["sum"], r["count"]), axis=1)
    g["ci_lo"] = [c[0] for c in ci]; g["ci_hi"] = [c[1] for c in ci]
    save(g, name, out, index=False); return g

def sens_row(name, d):
    d = d.dropna(subset=["accepted"])
    if d["pid"].nunique() < 2 or d["high"].nunique() < 2: return dict(subset=name, n_trials=len(d), n_pid=d["pid"].nunique())
    lo, hi = d[d.high == 0]["accepted"].mean(), d[d.high == 1]["accepted"].mean()
    pr = paired(d, "accepted"); g = gee_logit("accepted ~ high", d)
    r = dict(subset=name, n_trials=len(d), n_pid=d["pid"].nunique(), rate_low=lo, rate_high=hi, diff=hi - lo, paired_p_t=pr.get("p_t"), paired_p_signflip=pr.get("p_signflip"))
    if g is not None and "high" in g.index: r.update(OR=g.loc["high", "OR"], OR_lo=g.loc["high", "CI_lo"], OR_hi=g.loc["high", "CI_hi"], gee_p=g.loc["high", "p"])
    return r

def s2_primary(P, T, out):
    H("2. PRIMARY: does cognitive load change compliance with the costly manipulative recommendation?")
    D = T[(T["n_dark_events"] > 0) & (T["tactic_verified"] != False)].dropna(subset=["accepted"]).copy()
    D = D.merge(P[["pid", "critical_ability", "ai_experience", "ai_planning_familiarity", "emotionality"]], on="pid", how="left")
    D["exp_DivAttn_Qualified"] = D["pid"].map(P.set_index("pid")["exp_DivAttn_Qualified"])
    rep(f"Analysis set: {len(D)} trials from {D['pid'].nunique()} participants (one verified dark turn per trial; unverified dark turns excluded, as in the recognition test).")
    g = rate_table(D, "load", out, "s2_compliance_by_load.csv")
    for r in g.itertuples(): rep(f"- {r.load}: accepted the costly recommendation in {int(r.sum)}/{int(r.count)} trials = {r.rate:.1%} (Wilson 95% CI {r.ci_lo:.1%}-{r.ci_hi:.1%}).")
    o = D.groupby("outcome").size().to_dict(); rep(f"- Outcome counts: {o}. (Transient = target briefly followed then reverted; counted as *not accepted* in the primary DV and as uptake in the sensitivity DV.)")
    pr = paired(D, "accepted"); save(pd.DataFrame([pr]), "s2_primary_paired.csv", out, index=False)
    rep("- **Participant-level paired test (recommended headline):** " + para(pr, "P(accept)", ""))
    if "p_signflip" in pr: rep(f"  Sign-flip randomisation p = {pr['p_signflip']:.3f}; exact sign test {fmt_p(pr['p_sign'])}.")
    obs, pperm = perm_within(D); rep(f"- Within-participant label-permutation test (10,000 shuffles of High/Low labels inside each person): observed mean diff = {obs:+.3f}, {fmt_p(pperm)}.")
    # GEE models
    m1 = gee_logit("accepted ~ high", D); m2 = gee_logit("accepted ~ high + C(cat) + timed + pos_z", D)
    D["timed_i"] = D["timed"].astype(int)
    m2 = gee_logit("accepted ~ high + C(cat) + timed_i + pos_z", D)
    m3 = gee_logit("accepted ~ high * C(cat) + timed_i + pos_z", D)
    for nm, m in [("m1_high", m1), ("m2_adjusted", m2), ("m3_high_x_task", m3)]:
        if m is not None: save(m, f"s2_gee_{nm}.csv", out)
    if m1 is not None: rep("- GEE logit (exchangeable, clustered on participant), accepted ~ load: " + coef_line(m1, "high", "High vs Low"))
    if m2 is not None: rep("- Adjusted for task, timed segment, trial position: " + coef_line(m2, "high", "High vs Low"))
    if m3 is not None: rep("- Load x task interaction terms: " + "; ".join(coef_line(m3, t) for t in m3.index if t.startswith("high:")))
    # individual differences in susceptibility
    w = pmeans(D, "accepted")
    if len(w) >= 2:
        d = (w["HighLoad"] - w["LowLoad"]); cls = pd.cut(d, [-9, -1e-9, 1e-9, 9], labels=["more compliant under LOW", "no difference", "more compliant under HIGH"])
        rep(f"- **Heterogeneity:** {cls.value_counts().to_dict()}. Participants whose compliance rose under High load: {(d > 0).sum()} of {len(d)}; mean compliance rate overall = {D.groupby('pid')['accepted'].mean().mean():.1%}.")
        save(pd.DataFrame({"pid": w.index, "p_accept_low": w["LowLoad"], "p_accept_high": w["HighLoad"], "diff": d, "class": cls.values}), "s2_individual_load_effects.csv", out, index=False)
        # is between-person variation bigger than chance? compare observed SD of diffs with sign-flip-null of Bernoulli noise
        rng = np.random.default_rng(3); pool = D.groupby("pid")["accepted"].transform("mean"); sim = []
        for _ in prog(range(2000), "heterogeneity simulation"):
            y = rng.binomial(1, pool.values); tmp = D[["pid", "high"]].copy(); tmp["y"] = y
            ww = tmp.groupby(["pid", "high"])["y"].mean().unstack().dropna(); sim.append((ww[1] - ww[0]).std())
        rep(f"- SD of individual High-Low differences = {d.std():.3f}; expected under 'no true individual differences' (binomial noise around each person's own mean) = {np.mean(sim):.3f} [95% {np.percentile(sim,2.5):.3f}, {np.percentile(sim,97.5):.3f}] -> "
            + ("more heterogeneity than chance" if d.std() > np.percentile(sim, 97.5) else "not clearly more than chance (so 'some participants' is descriptive)") + ".")
    # dose-response with perceived load
    m4 = gee_logit("accepted ~ rtlx_within + rtlx_between + C(cat)", D.dropna(subset=["rtlx_within"]))
    if m4 is not None:
        save(m4, "s2_gee_perceived_load_dose_response.csv", out)
        rep("- Dose-response with *perceived* load (raw TLX split into within-person and between-person parts): " + coef_line(m4, "rtlx_within", "within-person +1 TLX point") + "; " + coef_line(m4, "rtlx_between", "between-person +1 TLX point"))
    # severity of the cost
    if "q_cost_of_following" in D and D["q_cost_of_following"].notna().sum() > 10:
        Dz = D.dropna(subset=["q_cost_of_following"]).copy(); Dz["severe"] = (Dz["q_cost_of_following"] <= -1).astype(int)
        m5 = gee_logit("accepted ~ high + severe", Dz)
        if m5 is not None: rep("- Adding cost severity (B/C turns with quality penalty >= 1): " + coef_line(m5, "high", "High") + "; " + coef_line(m5, "severe", "severe cost"))
    # moderators
    mods = ["critical_ability", "ai_experience", "ai_planning_familiarity", "emotionality"]
    rows = []
    for mname in mods:
        if D[mname].nunique() < 2: continue
        Dz = D.copy(); Dz["mz"] = (Dz[mname] - Dz[mname].mean()) / Dz[mname].std()
        m = gee_logit("accepted ~ high * mz + C(cat)", Dz)
        if m is not None and "high:mz" in m.index: rows.append(dict(moderator=mname, OR_interaction=m.loc["high:mz", "OR"], CI_lo=m.loc["high:mz", "CI_lo"], CI_hi=m.loc["high:mz", "CI_hi"], p=m.loc["high:mz", "p"],
                                                                     OR_main_moderator=m.loc["mz", "OR"], p_main=m.loc["mz", "p"]))
    if rows:
        mt = pd.DataFrame(rows); mt["p_holm"] = holm(mt["p"].values); save(mt, "s2_moderators.csv", out, index=False)
        rep("- Moderation of the load effect by individual differences (interaction OR per +1 SD; Holm-adjusted): " + "; ".join(f"{r.moderator}: OR = {r.OR_interaction:.2f}, p = {r.p:.3f} (Holm {r.p_holm:.3f})" for r in mt.itertuples()))
    # sensitivity
    subs = [("All verified dark-turn trials (primary)", D),
            ("Any uptake DV (accepted + transient)", D.assign(accepted=D["accepted_or_transient"])),
            ("Platform's own scoring rule (main.py replay)", D.assign(accepted=D["accepted_platform"]).dropna(subset=["accepted"])),
            ("Categories B + C only (Category A is a 0% ceiling cell)", D[D["cat"] != "A"]),
            ("Untimed segments only (1-2; removes time-limit confound)", D[D["seg"] <= 2]),
            ("Exclude timed-out trials", D[D["timed_out"] != True]),
            ("Exclude trials flagged by platform", D[~D["excl_trial"]]),
            ("Only dark turns delivered on user's 1st reply", D[D["dark_target_reply"] == 1]),
            ("Exclude participants failing div-attn qualification", D[D["exp_DivAttn_Qualified"] == True]),
            ("Only targets costly by platform check", D[D.get("target_costly_repo", True) == True] if "target_costly_repo" in D else D),
            ("Only Category A (understate need)", D[D["cat"] == "A"]), ("Only Category B", D[D["cat"] == "B"]), ("Only Category C", D[D["cat"] == "C"])]
    st = pd.DataFrame([sens_row(n, d) for n, d in subs]); save(st, "s2_sensitivity.csv", out, index=False)
    rep("- Sensitivity table saved (`s2_sensitivity.csv`); every row reports High-Low difference, participant-level paired p and GEE OR.")
    # figure
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.4), gridspec_kw={"width_ratios": [1, 1, 1.2]})
    slope(ax[0], D, "accepted", "Compliance with costly advice", "P(accept)")
    if len(w) >= 2:
        ax[1].hist(d, bins=np.linspace(-1.05, 1.05, 15), color="#888888"); ax[1].axvline(0, color=INK, lw=1); ax[1].set_xlabel("High - Low  P(accept), per participant"); ax[1].set_ylabel("participants"); ax[1].set_title("Individual load effects")
    gc = D.groupby(["cat", "load"])["accepted"].agg(["mean", "count", "sum"]).reset_index()
    for i, (lv, col) in enumerate([("LowLoad", LOW_C), ("HighLoad", HIGH_C)]):
        sub = gc[gc["load"] == lv]; ci = [wilson(r["sum"], r["count"]) for _, r in sub.iterrows()]
        x = np.arange(len(sub)) + (i - .5) * .35
        ax[2].bar(x, sub["mean"], .32, color=col, label=lv.replace("Load", " load"), yerr=[sub["mean"] - [c[0] for c in ci], [c[1] for c in ci] - sub["mean"]], error_kw=dict(lw=1, capsize=2, ecolor=INK))
    ax[2].set_xticks(range(len(gc["cat"].unique()))); ax[2].set_xticklabels([{"A": "A Workload", "B": "B Degree", "C": "C Non-acad."}[c] for c in sorted(gc["cat"].unique())]); ax[2].set_ylabel("P(accept)"); ax[2].set_title("By task"); ax[2].legend()
    savefig(fig, "fig2_compliance_by_load.png", out)
    return D

def s3a_categoryA(P, T, out):
    H("3A. Category A: how and when the under-allocated target was corrected (accepted/rejected is at ceiling for A)")
    if "a_fixed" not in T or T["a_fixed"].notna().sum() == 0: rep("- No Category A trials with a dark target."); return
    A = T[(T["cat"] == "A") & T["a_fixed"].notna()].copy(); A["timed_i"] = A["timed"].astype(int)
    rep(f"- {len(A)} Category A trials from {A['pid'].nunique()} participants. Target hours were raised after the dark turn in {A['a_fixed'].mean():.0%} of them "
        f"(High {A.loc[A['high'] == 1, 'a_fixed'].mean():.0%}, Low {A.loc[A['high'] == 0, 'a_fixed'].mean():.0%}); "
        f"the {int(A['a_fixed'].sum())} corrected trials are analysed below. Caution: not every A tactic makes a false claim (flattery, intimacy probing and authority can wrap "
        f"the *correct* number), so speed of correction is a measure of how quickly people act on the truth, not of how far they trusted a lie.")
    dvs = ["a_secs_to_fix", "a_msgs_to_fix", "a_fix_user_specified", "a_truth_disclosed_before_fix", "a_asked_target_before_fix"]
    tb = paired_table(A, dvs, out, "s3a_categoryA_paired.csv")
    labs = {"a_secs_to_fix": "Seconds from dark turn to first raise of the target", "a_msgs_to_fix": "User messages until the target was raised",
            "a_fix_user_specified": "Share of fixes where the participant typed the number", "a_truth_disclosed_before_fix": "Share where the AI had already disclosed the true value",
            "a_asked_target_before_fix": "Share where the participant asked about the target before fixing it"}
    for dv, lab in labs.items():
        r = tb[tb["dv"] == dv]
        if len(r): rep("- " + para(r.iloc[0].to_dict(), lab))
    F = A[A["a_fixed"] == 1].dropna(subset=["a_secs_to_fix"]).copy(); F["log_secs"] = np.log1p(F["a_secs_to_fix"])
    m = lmm("log_secs ~ high + timed_i", F)
    if m is not None: rep("- LMM log(1 + seconds to fix) ~ load + timed (random intercept for participant): " + coef_line(m, "high", "High load (b is on the log scale; exp(b) = time ratio)", logit=False))
    tt = F.groupby("tactic")["a_secs_to_fix"].agg(["count", "median"]).round(1)
    rep("- Median seconds to fix by tactic: " + "; ".join(f"{k} = {r['median']} s (n = {int(r['count'])})" for k, r in tt.iterrows()))
    save(F[["pid", "gt", "seg", "load", "tactic", "target", "a_secs_to_fix", "a_msgs_to_fix", "a_fix_user_specified", "a_truth_disclosed_before_fix", "a_asked_target_before_fix"]], "s3a_categoryA_trials.csv", out, index=False)

def s3_behaviour(P, T, D, out):
    H("3. Secondary behaviour: corrections, verification, effort and reading time")
    dvs = ["corrections", "n_removes", "n_facts_revealed", "prop_facts_revealed", "target_fact_before_dark", "target_fact_after_dark", "asked_target_before_dark", "asked_target_after_dark",
           "n_user_before_dark", "duration_s", "final_pct_scored", "submit_attempts", "latency_after_dark_s", "latency_after_neutral_s", "dwell_dark_rel", "msg_words_mean", "msg_wpm_mean",
           "msg_pause_mean_s", "msg_backspaces_mean", "q_final_raw"]
    tb = paired_table(D, dvs, out, "s3_behaviour_paired.csv")
    for r in tb.itertuples():
        if getattr(r, "n", 0) >= 2: rep(f"- {r.dv}: Low {r.mean_low:.2f} vs High {r.mean_high:.2f} (diff {r.diff:+.2f}, {fmt_p(r.p_t)}, Holm {fmt_p(getattr(r,'p_t_holm',np.nan))})")
    D = D.copy(); D["lat_diff"] = D["latency_after_dark_s"] - D["latency_after_neutral_s"]
    pr = paired(D, "lat_diff")
    if pr.get("n", 0) >= 2: rep("- Reading/hesitation proxy: extra latency before the next user message after the dark turn vs after neutral AI turns (dark - neutral seconds): " + para(pr, "diff-of-latency"))
    D["passed_i"] = D["passed"].astype(float)
    # verification -> resistance, and load -> verification (ELM central route)
    Dv = D.dropna(subset=["asked_target_after_dark", "accepted"]).copy()
    if HAVE_SM and len(Dv) > 30:
        a = gee_logit("asked_target_after_dark ~ high + C(cat)", Dv); b = gee_logit("accepted ~ asked_target_after_dark + high + C(cat)", Dv)
        c = gee_logit("target_fact_after_dark ~ high + C(cat)", Dv); b2 = gee_logit("accepted ~ target_fact_after_dark + high + C(cat)", Dv)
        rep("- **ELM central-route check.** Load -> asking about the flagged item after the dark turn: " + coef_line(a, "high") + ". Asking -> accepting (controlling load): " + coef_line(b, "asked_target_after_dark") +
            ". Load -> revealing a locked fact about the target: " + coef_line(c, "high") + ". Revealing -> accepting: " + coef_line(b2, "target_fact_after_dark") + ".")
        # cluster-bootstrap indirect effect load -> verification -> accept
        rng = np.random.default_rng(5); pids = Dv["pid"].unique(); ind = []
        for _ in prog(range(500), "mediation bootstrap"):
            samp = rng.choice(pids, len(pids), replace=True); bs = pd.concat([Dv[Dv["pid"] == p] for p in samp])
            try:
                ma = sm.Logit(bs["asked_target_after_dark"], sm.add_constant(bs[["high"]])).fit(disp=0)
                mb = sm.Logit(bs["accepted"], sm.add_constant(bs[["asked_target_after_dark", "high"]])).fit(disp=0)
                ind.append(ma.params["high"] * mb.params["asked_target_after_dark"])
            except Exception: pass
        if len(ind) > 100: rep(f"  Indirect effect (log-odds scale, load -> asks about target -> accepts): {np.mean(ind):+.3f}, participant-bootstrap 95% CI [{np.percentile(ind, 2.5):+.3f}, {np.percentile(ind, 97.5):+.3f}] (exploratory).")
    # cost of compliance in quality terms
    if "q_final_raw" in D and D["q_final_raw"].notna().any():
        g = D.groupby("accepted")[["final_pct_scored", "q_final_raw", "duration_s", "corrections"]].mean(); save(g, "s3_outcome_by_compliance.csv", out)
        rep("- Objective cost of compliance (means by accepted=0/1): " + g.round(2).to_dict("index").__str__())
    fig, ax = plt.subplots(1, 4, figsize=(13, 3.2))
    for a_, (dv, t) in zip(ax, [("corrections", "Plan corrections"), ("n_facts_revealed", "Locked facts revealed"), ("asked_target_after_dark", "Asked about flagged item after dark turn"), ("final_pct_scored", "Plan quality % (0 if not passed)")]):
        slope(a_, D, dv, t)
    savefig(fig, "fig3_behaviour_by_load.png", out)

def z(p): return stats.norm.ppf(min(max(p, 1e-6), 1 - 1e-6))
def sdt(sub):
    """Log-linear-corrected d' and criterion c on pooled item counts; flagged = 'this feels manipulative'."""
    nd, nn = (sub["is_dark"] == 1).sum(), (sub["is_dark"] == 0).sum()
    h = ((sub["is_dark"] == 1) & (sub["flagged"] == 1)).sum(); f = ((sub["is_dark"] == 0) & (sub["flagged"] == 1)).sum()
    hr, fr = (h + .5) / (nd + 1), (f + .5) / (nn + 1)
    return dict(n_dark=nd, n_decoy=nn, hit_rate=h / nd if nd else np.nan, fa_rate=f / nn if nn else np.nan, dprime=z(hr) - z(fr), criterion=-(z(hr) + z(fr)) / 2)

def s4_recognition(P, T, R, D, out):
    H("4. Recognition of manipulation (signal detection) and its link to resisting")
    if R.empty: rep("No recognition data."); return
    R = R.dropna(subset=["high"]).copy()
    o = sdt(R); rep(f"- Pooled: hit rate (dark flagged as manipulative) = {o['hit_rate']:.1%} ({o['n_dark']} dark items); false-alarm rate (neutral rewrite flagged) = {o['fa_rate']:.1%} ({o['n_decoy']} neutral items); d' = {o['dprime']:.2f}, criterion c = {o['criterion']:.2f}.")
    rows = []
    for pid, g in R.groupby("pid"): rows.append(dict(pid=pid, **sdt(g)))
    pp = pd.DataFrame(rows); save(pp, "s4_sdt_per_participant.csv", out, index=False)
    rep(f"- Per-participant d' M = {pp['dprime'].mean():.2f} (SD {pp['dprime'].std():.2f}); {(pp['dprime'] <= 0).sum()} of {len(pp)} participants at or below chance (d' <= 0). Only ~10 items per person, so d' is coarse: report pooled/GEE estimates as primary.")
    lv = {}
    for load, g in R.groupby("load"): lv[load] = sdt(g)
    save(pd.DataFrame(lv).T, "s4_sdt_by_source_load.csv", out)
    for k, v in lv.items(): rep(f"  - excerpts from {k} trials: hit {v['hit_rate']:.1%}, FA {v['fa_rate']:.1%}, d' = {v['dprime']:.2f}, c = {v['criterion']:.2f}")
    if HAVE_SM and R["pid"].nunique() > 3:
        m = gee_logit("flagged ~ is_dark * high", R)
        if m is not None:
            save(m, "s4_gee_flagged.csv", out)
            rep("- GEE logit: flagged ~ is_dark x load. " + coef_line(m, "is_dark", "Detection (dark vs neutral)") + "; " + coef_line(m, "is_dark:high", "is_dark x High load (does load impair discrimination?)") + "; " + coef_line(m, "high", "High load main (bias)"))
        rng = np.random.default_rng(9); pids = R["pid"].unique(); dd = []
        for _ in prog(range(1000), "d-prime bootstrap"):
            s = pd.concat([R[R["pid"] == p] for p in rng.choice(pids, len(pids), replace=True)])
            try: dd.append(sdt(s[s.load == "HighLoad"])["dprime"] - sdt(s[s.load == "LowLoad"])["dprime"])
            except Exception: pass
        if dd: rep(f"- d'(High) - d'(Low) = {lv.get('HighLoad',{}).get('dprime',np.nan) - lv.get('LowLoad',{}).get('dprime',np.nan):+.2f}, participant-bootstrap 95% CI [{np.percentile(dd, 2.5):+.2f}, {np.percentile(dd, 97.5):+.2f}].")
        ma = gee_gauss("agreement ~ is_dark * high", R)
        if ma is not None: save(ma, "s4_gee_agreement.csv", out); rep("- Agreement rating (1-5) with the excerpt: " + coef_line(ma, "is_dark", "dark vs neutral", logit=False) + "; " + coef_line(ma, "is_dark:high", "dark x High load", logit=False))
    # awareness vs resistance (dark items only: recognised the manipulation in the very trial where it was delivered)
    Dk = R[(R["is_dark"] == 1)].dropna(subset=["accepted"]).copy()
    if len(Dk) >= 6:
        tab = pd.crosstab(Dk["flagged"], Dk["accepted"]).reindex(index=[0, 1], columns=[0.0, 1.0], fill_value=0)
        tab.index = ["not recognised", "recognised"]; tab.columns = ["resisted", "accepted"]; save(tab, "s4_recognised_by_accepted.csv", out)
        pa_f = Dk[Dk.flagged == 1]["accepted"].mean(); pa_n = Dk[Dk.flagged == 0]["accepted"].mean()
        rep(f"- **Awareness vs resistance** (dark excerpts, n = {len(Dk)}): accepted the costly advice in {pa_f:.1%} of recognised turns (n = {int((Dk.flagged==1).sum())}) vs {pa_n:.1%} of unrecognised turns (n = {int((Dk.flagged==0).sum())}). "
            f"Aware-yet-complied: {int(((Dk.flagged==1)&(Dk.accepted==1)).sum())} trials = {((Dk.flagged==1)&(Dk.accepted==1)).sum()/max(1,(Dk.flagged==1).sum()):.1%} of recognised turns.")
        try: rep(f"  Fisher exact p = {stats.fisher_exact(tab.values)[1]:.3f} (ignores clustering).")
        except Exception: pass
        m = gee_logit("accepted ~ flagged + high + C(cat)", Dk); m2 = gee_logit("accepted ~ flagged * high + C(cat)", Dk)
        if m is not None: save(m, "s4_gee_accept_by_recognition.csv", out); rep("  GEE: " + coef_line(m, "flagged", "recognised -> accepted") + "; " + coef_line(m, "high", "High load"))
        if m2 is not None and "flagged:high" in m2.index: rep("  " + coef_line(m2, "flagged:high", "recognition x load"))
        if Dk["agreement"].notna().sum() > 5:
            rs = stats.spearmanr(Dk["agreement"], Dk["accepted"]); rep(f"  Rated agreement with the dark excerpt vs having accepted it: Spearman rho = {rs.statistic:.2f}, {fmt_p(rs.pvalue)}.")
    # participant level
    acc = D.groupby("pid")["accepted"].mean().rename("p_accept")
    pp = pp.merge(acc, on="pid", how="left")
    if len(pp) >= 6:
        for col in ["hit_rate", "dprime"]:
            r = stats.spearmanr(pp[col], pp["p_accept"], nan_policy="omit"); rep(f"- Participant level: {col} vs overall P(accept): Spearman rho = {r.statistic:.2f}, {fmt_p(r.pvalue)} (n = {len(pp)}).")
    # by tactic: detectability vs compliance
    dt = Dk.groupby("tactic")[["flagged", "accepted"]].agg(["mean", "count"]) if len(Dk) else pd.DataFrame()
    if not dt.empty: save(dt, "s4_detect_vs_comply_by_tactic.csv", out)
    # figure
    fig, ax = plt.subplots(1, 3, figsize=(11.5, 3.4))
    cats = ["Hit (dark flagged)", "False alarm (neutral flagged)"]
    for i, (load, col) in enumerate([("LowLoad", LOW_C), ("HighLoad", HIGH_C)]):
        if load in lv: ax[0].bar(np.arange(2) + (i - .5) * .35, [lv[load]["hit_rate"], lv[load]["fa_rate"]], .32, color=col, label=load.replace("Load", " load"))
    ax[0].set_xticks([0, 1]); ax[0].set_xticklabels(["Hit rate", "False-alarm rate"]); ax[0].set_ylim(0, 1); ax[0].set_title("Recognition by source-trial load"); ax[0].legend()
    if len(pp): ax[1].hist(pp["dprime"].dropna(), bins=10, color="#888888"); ax[1].axvline(0, color=INK, lw=1); ax[1].set_xlabel("d' per participant"); ax[1].set_title("Discrimination")
    if len(Dk) >= 6:
        vals = [Dk[Dk.flagged == 0]["accepted"], Dk[Dk.flagged == 1]["accepted"]]
        ax[2].bar([0, 1], [v.mean() if len(v) else 0 for v in vals], .5, color=["#999999", "#555555"]); ax[2].set_xticks([0, 1]); ax[2].set_xticklabels([f"Not recognised\n(n={len(vals[0])})", f"Recognised\n(n={len(vals[1])})"]); ax[2].set_ylim(0, 1); ax[2].set_ylabel("P(accepted costly advice)"); ax[2].set_title("Awareness vs resistance")
    savefig(fig, "fig4_recognition.png", out)

def s5_subjective(P, T, D, out):
    H("5. Subjective reliance, trust and the introspection gap")
    dvs = ["tlx_helpfulness", "tlx_trust", "tlx_persuasiveness", "tlx_independence", "tlx_performance"]
    tb = paired_table(T, dvs, out, "s5_subjective_by_load.csv")
    for r in tb.itertuples():
        if getattr(r, "n", 0) >= 2: rep(f"- {r.dv}: Low {r.mean_low:.2f} vs High {r.mean_high:.2f} ({fmt_p(r.p_t)}; Holm {fmt_p(getattr(r,'p_t_holm',np.nan))})")
    Dz = D.dropna(subset=["tlx_trust"]).copy()
    if HAVE_SM and len(Dz) > 30:
        for dv in ["tlx_trust", "tlx_helpfulness", "tlx_persuasiveness", "tlx_independence"]:
            m = gee_gauss(f"{dv} ~ accepted + high + C(cat)", Dz)
            if m is not None: save(m, f"s5_gee_{dv}_by_accept.csv", out); rep(f"- {dv} ~ accepted + load + task: " + coef_line(m, "accepted", "accepted the costly advice", logit=False))
    # self-report vs behaviour
    if len(Dz) > 10:
        r = stats.spearmanr(Dz["tlx_independence"], Dz["accepted"], nan_policy="omit"); r2 = stats.spearmanr(Dz["tlx_persuasiveness"], Dz["accepted"], nan_policy="omit")
        rep(f"- Self-reported independence vs behavioural compliance: Spearman rho = {r.statistic:.2f} ({fmt_p(r.pvalue)}); self-reported influence: rho = {r2.statistic:.2f} ({fmt_p(r2.pvalue)}). Weak correlations = self-report does not track behavioural reliance.")
        gap = Dz[(Dz.accepted == 1)]; rep(f"- Introspection gap: among trials where the participant did follow the costly advice (n = {len(gap)}), {(gap['tlx_independence'] >= 5).mean():.0%} rated themselves 5-7 on 'relied on own judgment' and {(gap['tlx_persuasiveness'] <= 3).mean():.0%} rated AI influence 1-3.")
        r3 = stats.spearmanr(Dz["tlx_performance"], Dz["final_pct"], nan_policy="omit"); rep(f"- Calibration: self-rated performance vs platform plan-quality %: rho = {r3.statistic:.2f} ({fmt_p(r3.pvalue)}) (quality % rewards slack among passing plans, so treat as descriptive).")
    fig, ax = plt.subplots(1, 4, figsize=(13, 3.2))
    for a_, (dv, t) in zip(ax, [("tlx_trust", "Trust in advisor"), ("tlx_helpfulness", "Helpfulness"), ("tlx_persuasiveness", "AI influence on decision"), ("tlx_independence", "Own judgment (vs AI)")]): slope(a_, T, dv, t)
    savefig(fig, "fig5_subjective_by_load.png", out)

def s6_tactics(P, T, D, out):
    H("6. Which manipulative tactics work? (descriptive; cell sizes are small)")
    g = D.groupby(["cat", "tactic", "cluster"])["accepted"].agg(["sum", "count"]).reset_index(); g["rate"] = g["sum"] / g["count"]
    ci = [wilson(r["sum"], r["count"]) for _, r in g.iterrows()]; g["ci_lo"] = [c[0] for c in ci]; g["ci_hi"] = [c[1] for c in ci]
    gl = D.groupby(["tactic", "load"])["accepted"].agg(["sum", "count"]).unstack("load"); gl.columns = [f"{a}_{b}" for a, b in gl.columns]
    g = g.merge(gl.reset_index(), on="tactic", how="left"); save(g.sort_values("rate", ascending=False), "s6_compliance_by_tactic.csv", out, index=False)
    for r in g.sort_values("rate", ascending=False).itertuples(): rep(f"- [{r.cat}] {r.tactic}: {int(r.sum)}/{int(r.count)} = {r.rate:.0%} [{r.ci_lo:.0%}, {r.ci_hi:.0%}]")
    cl = rate_table(D, "cluster", out, "s6_compliance_by_cluster.csv"); rep("- By taxonomy cluster: " + "; ".join(f"{r.cluster} {r.rate:.0%} (n={int(r.count)})" for r in cl.itertuples()))
    rep("- By task direction (A: advice understates a need; B/C: advice pushes a harmful add/keep): " + "; ".join(f"{r.dir} {r.rate:.0%}" for r in rate_table(D, "dir", out, "s6_by_direction.csv").itertuples()))
    if D["tactic"].nunique() > 3 and D["pid"].nunique() >= 5:
        def chi(dd):
            gm = dd["accepted"].mean(); a = dd.groupby("tactic")["accepted"].agg(["mean", "count"]); return float((a["count"] * (a["mean"] - gm) ** 2).sum() / max(gm * (1 - gm), 1e-9))
        obs = chi(D); rng = np.random.default_rng(11); Dp = D[["pid", "cat", "tactic", "accepted"]].copy(); cnt = 0; B = 2000
        for _ in prog(range(B), "tactic permutation test"):
            Dp["tactic"] = Dp.groupby(["pid", "cat"])["tactic"].transform(lambda x: rng.permutation(x.values)); cnt += chi(Dp) >= obs - 1e-9
        rep(f"- Omnibus test that tactics differ in compliance (chi-square-type statistic = {obs:.1f}; p from {B} permutations of tactic labels within participant x task) {fmt_p((cnt + 1) / (B + 1))}. Tactic order was a fixed rotation, not random, so tactic is confounded with trial position/load within a task -- state this if you report it.")
    for col, nm in [("dark_target_reply", "reply position (1st vs 2nd)"), ("dark_via", "delivery (reply vs proactive)")]:
        if D[col].nunique() > 1: rep(f"- Compliance by {nm}: " + str(D.groupby(col)["accepted"].agg(["mean", "count"]).round(2).to_dict("index")))
    fig, ax = plt.subplots(figsize=(7.5, 0.42 * len(g) + 1.2))
    gg = g.sort_values("rate"); y = np.arange(len(gg))
    ax.errorbar(gg["rate"], y, xerr=[gg["rate"] - gg["ci_lo"], gg["ci_hi"] - gg["rate"]], fmt="o", color=INK, ecolor="#aaaaaa", capsize=2)
    ax.set_yticks(y); ax.set_yticklabels([f"{t[:34]} ({c})" for t, c in zip(gg["tactic"], gg["cat"])]); ax.set_xlim(0, 1); ax.set_xlabel("P(accepted costly advice), Wilson 95% CI"); ax.set_title("Compliance by dark-pattern category")
    savefig(fig, "fig6_compliance_by_tactic.png", out)

def s7_order(P, T, D, out):
    H("7. Order, learning and carry-over effects")
    g = rate_table(D, "gt", out, "s7_compliance_by_trial_position.csv"); r = stats.spearmanr(g["gt"], g["rate"]); rep(f"- Compliance across the 12 trial positions: rho(position, rate) = {r.statistic:.2f}, {fmt_p(r.pvalue)}.")
    m = gee_logit("accepted ~ pos_z + high", D)
    if m is not None: rep("- GEE: " + coef_line(m, "pos_z", "trial position (per SD)") + "; " + coef_line(m, "high", "High load, controlling for position"))
    rep("- By segment within task (1-2 untimed, 3-4 timed): " + str(D.groupby("seg")["accepted"].mean().round(2).to_dict()) + "; by task position (1st/2nd/3rd task): " + str(D.groupby("task_position")["accepted"].mean().round(2).to_dict()))
    Dl = D.sort_values(["pid", "gt"]).copy(); Dl["prev_accepted"] = Dl.groupby("pid")["accepted"].shift(1); Dl["prev_high"] = Dl.groupby("pid")["high"].shift(1)
    ml = gee_logit("accepted ~ high + prev_accepted + prev_high", Dl.dropna(subset=["prev_accepted"]))
    if ml is not None: rep("- Carry-over (previous trial): " + coef_line(ml, "prev_accepted", "previous trial accepted") + "; " + coef_line(ml, "prev_high", "previous trial High load"))
    tl = T.groupby("gt")[["rtlx", "tlx_trust", "tlx_independence"]].mean(); save(tl, "s7_tlx_trust_by_position.csv", out)

def s8_individual(P, T, D, R, out):
    H("8. Individual differences")
    A = D.groupby("pid").agg(p_accept=("accepted", "mean"), mean_rtlx=("rtlx", "mean"), corrections=("corrections", "sum"), facts=("n_facts_revealed", "mean"), final_pct=("final_pct", "mean")).reset_index()
    w = pmeans(D, "accepted"); A = A.merge((w["HighLoad"] - w["LowLoad"]).rename("load_effect").reset_index(), on="pid", how="left")
    A = A.merge(P[["pid", "critical_ability", "ai_experience", "ai_planning_familiarity", "emotionality", "exp_DivAttn_Accuracy_Pct", "exp_Recall_Accuracy_Pct", "age"]], on="pid", how="left")
    if len(R):
        rr = R.groupby("pid").apply(lambda g: pd.Series(sdt(g))).reset_index()[["pid", "hit_rate", "dprime"]]; A = A.merge(rr, on="pid", how="left")
    save(A, "s8_participant_level.csv", out, index=False)
    if len(A) < 8: rep("- N < 8: correlations skipped."); return
    rows = []
    for x in ["critical_ability", "ai_experience", "ai_planning_familiarity", "emotionality", "exp_DivAttn_Accuracy_Pct", "exp_Recall_Accuracy_Pct", "mean_rtlx", "age", "dprime", "facts"]:
        if x in A and A[x].nunique() > 1:
            for y in ["p_accept", "load_effect"]:
                r = stats.spearmanr(A[x], A[y], nan_policy="omit"); rows.append(dict(predictor=x, outcome=y, rho=r.statistic, p=r.pvalue, n=A[[x, y]].dropna().shape[0]))
    c = pd.DataFrame(rows); c["p_holm"] = holm(c["p"].values); save(c, "s8_correlations.csv", out, index=False)
    for r in c.itertuples():
        if r.p < .1: rep(f"- {r.predictor} vs {r.outcome}: rho = {r.rho:.2f}, {fmt_p(r.p)} (Holm {fmt_p(r.p_holm)}), n = {r.n}")
    rep(f"- {len(c)} exploratory correlations saved to `s8_correlations.csv`; only report those that survive Holm correction as findings.")
    ea = P[["P_e1", "P_e2", "P_e3", "P_e4"]].dropna()
    if len(ea) > 5:
        k = 4; alpha = k / (k - 1) * (1 - ea.var(ddof=1).sum() / ea.sum(axis=1).var(ddof=1)); rep(f"- Emotionality scale reliability (Cronbach's alpha, 4 items): {alpha:.2f}.")

JUST_AI = re.compile(r"\bAI\b|advisor|suggest|told me|recommend|trust|rely|relied|followed", re.I)
JUST_OWN = re.compile(r"constraint|cap\b|credit|hour|requirement|prereq|overlap|conflict|categor|minimum|budget|limit", re.I)
MANIP = re.compile(r"manipul|dark pattern|persua|nudg|steer|deceiv|trick|mislead|bias|flatter|sycophan|pushy|agenda|influenc", re.I)

def s9_accountability(P, T, D, out):
    H("9. Accountability-driven explanations (task-level justification + LLM reasoning score)")
    J = T[T["justification_text"].fillna("").str.len() > 0][["pid", "gt", "task", "cat", "justification_text", "reasoning_score"]].copy()
    if J.empty: rep("No justifications found."); return
    agg = D.groupby(["pid", "cat"]).agg(n_accepted=("accepted", "sum"), n_high_accepted=("accepted", lambda s: s[D.loc[s.index, "high"] == 1].sum()), mean_rtlx=("rtlx", "mean")).reset_index()
    J = J.merge(agg, on=["pid", "cat"], how="left")
    J["words"] = J["justification_text"].str.split().str.len(); J["mentions_ai"] = J["justification_text"].str.contains(JUST_AI).astype(int)
    J["mentions_own_constraints"] = J["justification_text"].str.contains(JUST_OWN).astype(int)
    J["mentions_manipulation"] = J["justification_text"].str.contains(MANIP).astype(int)
    save(J, "s9_justifications.csv", out, index=False)
    rep(f"- {len(J)} task-level justifications from {J['pid'].nunique()} participants; LLM reasoning score (0-10): M = {J['reasoning_score'].mean():.2f} (SD {J['reasoning_score'].std():.2f}). Justification is collected once per task (after segment 4), so it cannot be split by load; it is analysed against how many of the task's 4 dark turns were accepted.")
    if len(J) >= 8:
        r = stats.spearmanr(J["reasoning_score"], J["n_accepted"], nan_policy="omit"); rep(f"- Reasoning score vs # costly recommendations accepted in that task: rho = {r.statistic:.2f}, {fmt_p(r.pvalue)}.")
        r2 = stats.spearmanr(J["words"], J["n_accepted"], nan_policy="omit"); rep(f"- Justification length vs # accepted: rho = {r2.statistic:.2f}, {fmt_p(r2.pvalue)}.")
        m = lmm("reasoning_score ~ n_accepted + C(cat)", J.dropna(subset=["reasoning_score", "n_accepted"]))
        if m is not None: rep("- LMM reasoning_score ~ n_accepted + task: " + coef_line(m, "n_accepted", "per additional accepted recommendation", logit=False))
    rep(f"- Language: {J['mentions_ai'].mean():.0%} of justifications refer to the AI/its suggestions; {J['mentions_own_constraints'].mean():.0%} cite constraints/tradeoffs; only {J['mentions_manipulation'].mean():.0%} contain manipulation-related vocabulary (regex screen -- confirm by manual coding).")

def s10_qualitative(P, T, out):
    H("10. Free text: demand characteristics, awareness, feedback (coding sheet exported)")
    rows = []
    def add(pid, src, gt, text):
        if isinstance(text, str) and text.strip(): rows.append(dict(pid=pid, source=src, global_trial=gt, text=text, auto_manip_vocab=int(bool(MANIP.search(text))), auto_reliance_vocab=int(bool(JUST_AI.search(text))),
                                                                   code_guessed_true_purpose="", code_reliance_admitted="", code_noticed_manipulation="", code_load_complaint="", code_other="", coder_initials=""))
    for _, p in P.iterrows():
        add(p["pid"], "influence_moment", "", p["influence_moment_text"]); add(p["pid"], "communication_style", "", p["comm_style_text"])
    for _, t in T.iterrows():
        add(t["pid"], "task_justification", t["gt"], t["justification_text"]); add(t["pid"], "task_feedback", t["gt"], t["feedback_text"])
    Q = pd.DataFrame(rows)
    save(Q, "../qualitative_coding_sheet.csv", out, index=False)
    rep(f"- {len(Q)} free-text responses exported to `qualitative_coding_sheet.csv` with blank code columns for two coders (compute Cohen's kappa) -- codes: guessed true purpose / admitted reliance / noticed manipulation / complained about load task.")
    fb = Q[Q.source == "task_feedback"]
    rep(f"- Participant feedback mentioning the divided-attention or notification task ({fb['text'].str.contains('number|notification|tile|distract', case=False).sum()} of {len(fb)} feedback comments) is direct evidence about load-manipulation validity/acceptability.")
    ev_ = Q[Q.source.isin(["influence_moment", "communication_style"])]
    if len(ev_): rep(f"- Regex screen for manipulation vocabulary in the post-test reflections: {int(ev_['auto_manip_vocab'].sum())} of {len(ev_)}. Demand-characteristics answers are collected *before* the debrief; code them first and run the primary model with/without participants who guessed the purpose.")

def s11_power(P, T, D, out):
    H("11. Sensitivity / power")
    n = D["pid"].nunique()
    if HAVE_SM and n >= 2:
        for N in sorted({n, 30}):
            es = TTestPower().solve_power(nobs=N, alpha=.05, power=.8); rep(f"- Paired test on participant means with N = {N}: 80%-power minimum detectable effect dz = {es:.2f}.")
        icc_rows = D.groupby("pid")["accepted"].mean()
        rep(f"- Between-participant SD of overall compliance rate = {icc_rows.std():.2f}; a large between-person share justifies the within-subject design and the clustered models.")

def s12_extra_figs(P, T, out):
    fig, ax = plt.subplots(1, 4, figsize=(13, 3.2))
    for a_, (dv, t) in zip(ax, [("rtlx", "Raw NASA-TLX (1-7)"), ("tlx_mental", "Mental demand"), ("tlx_temporal", "Temporal demand"), ("tlx_frustration", "Frustration")]): slope(a_, T, dv, t)
    savefig(fig, "fig1_manipulation_check.png", out)
    if "rtlx_within" in T and T["accepted"].notna().sum() > 20:
        Tz = T.dropna(subset=["accepted", "rtlx_within"]).copy(); Tz["bin"] = pd.qcut(Tz["rtlx_within"], 4, duplicates="drop")
        g = Tz.groupby("bin", observed=True)["accepted"].agg(["mean", "count", "sum"]).reset_index(); ci = [wilson(r["sum"], r["count"]) for _, r in g.iterrows()]
        fig, ax = plt.subplots(figsize=(4.6, 3.3)); x = np.arange(len(g))
        ax.errorbar(x, g["mean"], yerr=[g["mean"] - [c[0] for c in ci], [c[1] for c in ci] - g["mean"]], fmt="o-", color=INK, ecolor="#aaaaaa", capsize=3)
        ax.set_xticks(x); ax.set_xticklabels([f"Q{i+1}" for i in x]); ax.set_xlabel("Within-person perceived load quartile (raw TLX, person-centred)"); ax.set_ylabel("P(accept)"); ax.set_ylim(0, 1); ax.set_title("Dose-response with perceived load")
        savefig(fig, "fig7_dose_response_perceived_load.png", out)

# ----------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--out", default="results")
    ap.add_argument("--repo", default=None); ap.add_argument("--exclude-file", default=None); ap.add_argument("--include-incomplete", action="store_true")
    ap.add_argument("--keep-shifted", action="store_true", help="keep participants flagged by the data-shift screen"); a = ap.parse_args()
    for sub in ["tables", "figures"]: os.makedirs(os.path.join(a.out, sub), exist_ok=True)
    style(); S, ev, files = load_all(a.data); repo = load_repo(a.repo)
    log(f"{len(files)} files, {len(S)} participants, {len(ev)} events")
    P = build_participants(S); T, M = build_trials(S, ev, repo); R = build_recognition(ev, T)
    if a.exclude_file and os.path.exists(a.exclude_file):
        X = pd.read_csv(a.exclude_file)
        if "global_trial" in X.columns:
            key = set(zip(X["Participant_ID"], X["global_trial"])); T = T[~T.apply(lambda r: (r.pid, r.gt) in key, axis=1)]
        else:
            bad = set(X["Participant_ID"]); P = P[~P.pid.isin(bad)]; T = T[~T.pid.isin(bad)]; R = R[~R.pid.isin(bad)] if len(R) else R
        log(f"exclusions applied from {a.exclude_file}")
    if not a.include_incomplete:
        done = T.groupby("pid")["completed"].sum(); inc = done[done < 12].index.tolist()
        if inc:
            log(f"-- excluded {len(inc)} incomplete participant(s) (<12 submitted trials): {inc}  (use --include-incomplete to keep them)")
            P = P[~P.pid.isin(inc)]; T = T[~T.pid.isin(inc)]; R = R[~R.pid.isin(inc)] if len(R) else R
    if P.empty: sys.exit("No complete participants to analyse.")
    # ---- data-shift screen (see detect_shifts): drop files whose export cannot have come from the deployed scoring code
    SH, RES = detect_shifts(P, T, ev); save(SH, "s0_shift_detection.csv", a.out, index=False)
    T["outcome_platform"] = [RES.get(r.pid, {}).get(r.gt) for r in T.itertuples()]
    T["accepted_platform"] = T["outcome_platform"].map({"accepted": 1.0, "rejected": 0.0, "transient": 0.0})
    shifted = SH.loc[SH["shifted"], "pid"].tolist()
    shift_notes = [f"- **Data-shift screen:** {int(SH['complete'].sum())} complete participants checked; {len(shifted)} flagged as shifted; "
                   f"{int((SH['n_trial_resumed'] > 0).sum())} participant(s) had reload/crash resumes and {int((SH['n_ai_error'] > 0).sum())} had ai_error retries (kept; see `s0_shift_detection.csv`)."]
    for r in SH[SH["shifted"]].itertuples(): shift_notes.append(f"  - {'DROPPED' if not a.keep_shifted else 'kept (--keep-shifted)'} {r.pid}: {r.reason} (exported claims A/R/T {r.exp_claims} vs replay {r.replay_claims}).")
    if shifted and not a.keep_shifted:
        log(f"-- dropped {len(shifted)} data-shifted participant(s): {shifted}  (use --keep-shifted to keep them)")
        P = P[~P.pid.isin(shifted)]; T = T[~T.pid.isin(shifted)]; R = R[~R.pid.isin(shifted)] if len(R) else R
    if P.empty: sys.exit("All participants were flagged as data-shifted; re-run with --keep-shifted to inspect.")
    # a trial only counts if it was actually submitted and Gemini/OpenRouter did not fail inside it
    bad_tr = (~T["completed"]) | T["flags"].fillna("").str.contains("ai_error")
    if bad_tr.any(): log(f"-- dropped {int(bad_tr.sum())} unfinished / ai_error trial(s) from trial-level analyses")
    T_all = T.copy()
    T = T[~bad_tr].copy()
    if len(R): R = R[R["pattern_id"].isin(T["pattern_id"])]
    save(P, "participants.csv", a.out, index=False); save(T, "trials.csv", a.out, index=False); save(M, "messages.csv", a.out, index=False)
    if len(R): save(R, "recognition_items.csv", a.out, index=False)
    rep("# HTI Dark Patterns -- auto-generated results summary"); rep(); rep(f"_Generated from {len(files)} file(s); N = {P['pid'].nunique()} participants._ Numbers below are computed directly from the raw event logs.")
    for l in shift_notes: rep(l)
    D =T[(T["n_dark_events"] > 0) & (T["tactic_verified"] != False)].dropna(subset=["accepted"]).copy()
    def run(name, fn, *args):
        print(f"\n>>> section {name} of 12 ...", flush=True)
        try: return fn(*args)
        except Exception as ex:
            log(f"!! section {name} failed: {ex}"); traceback.print_exc(); rep(f"_Section {name} failed: {ex}_")
    run("0", s0_sample, P, T, R, ev, a.out, S, T_all); run("1", s1_manip, P, T, a.out)
    D2 = run("2", s2_primary, P, T, a.out)
    if D2 is None: D2 = D
    run("3", s3_behaviour, P, T, D2, a.out); run("3A", s3a_categoryA, P, T, a.out); run("4", s4_recognition, P, T, R, D2, a.out); run("5", s5_subjective, P, T, D2, a.out)
    run("6", s6_tactics, P, T, D2, a.out); run("7", s7_order, P, T, D2, a.out); run("8", s8_individual, P, T, D2, R, a.out)
    run("9", s9_accountability, P, T, D2, a.out); run("10", s10_qualitative, P, T, a.out); run("11", s11_power, P, T, D2, a.out); run("12", s12_extra_figs, P, T, a.out)
    with open(os.path.join(a.out, "results_summary.md"), "w") as f: f.write("\n".join(REPORT))
    with open(os.path.join(a.out, "analysis_log.txt"), "w") as f: f.write("\n".join(LOG))
    log(f"done -> {a.out}/results_summary.md")

if __name__ == "__main__":
    main()
