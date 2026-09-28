"""
Pilot end-to-end simulation of the HTI Dark Patterns Study, run against a live
local server (http://127.0.0.1:8000), replicating exactly what static/js/experiment.js
and static/js/debrief.js do, turn for turn, so the resulting session is
indistinguishable server-side from a real participant's.

Re-uses TASK_DATA_A/B/C + evaluate_checklist_A/B/C directly from main.py (ground
truth) to solve a passing plan_state for every segment, so submissions reliably
pass while still sending real natural-language chat turns through /api/chat to
exercise the actual LLM dark-pattern delivery, action-extraction, and disclosure
logic. All raw request/response pairs are logged to pilot_transcript.jsonl for
later analysis.
"""
import sys, os, json, time, random, itertools, hashlib, uuid
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))
import requests

import main as srv  # reuse ground-truth TASK_DATA_A/B/C + evaluate_checklist_*

BASE = os.environ.get("PILOT_BASE_URL", "http://127.0.0.1:8000")
LOG_PATH = "pilot_transcript.jsonl"
logf = open(LOG_PATH, "w")

def log(kind, **kw):
    rec = {"ts": time.time(), "kind": kind, **kw}
    logf.write(json.dumps(rec, default=str) + "\n")
    logf.flush()
    print(f"[{kind}]", {k: (str(v)[:160]) for k, v in kw.items()})

PARTICIPANT_ID = "P" + str(int(time.time()*1000) % (36**6)).zfill(6)
print("PARTICIPANT_ID:", PARTICIPANT_ID)

# ---------------------------------------------------------------------------
# Ground-truth solvers (mirrors evaluate_checklist_A/B/C exactly since imported)
# ---------------------------------------------------------------------------
def solve_A(segment_key, load_level):
    seg = srv.TASK_DATA_A[segment_key]
    threshold_key = "true_minimum" if "true_minimum" in seg else "true_hours"
    thresholds = seg[threshold_key][load_level]
    hours = {item: thresholds.get(item, 0) for item in seg["items"]}
    results = srv.evaluate_checklist_A(segment_key, {"hours": hours}, load_level)
    assert all(r["met"] for r in results), f"solve_A failed to pass: {results}"
    return hours

def _subsets(pool, max_len=None):
    for r in range(0, (max_len or len(pool)) + 1):
        for c in itertools.combinations(pool, r):
            yield list(c)

def solve_B(segment_key, load_level):
    seg = srv.TASK_DATA_B[segment_key]
    best = None
    for major in _subsets(seg["pools"]["major"]):
        for minor in _subsets(seg["pools"]["minor"]):
            for elective in _subsets(seg["pools"]["elective"]):
                sel = {"major": major, "minor": minor, "elective": elective}
                results = srv.evaluate_checklist_B(segment_key, {"selections": sel}, load_level)
                if all(r["met"] for r in results):
                    total = sum(srv.COURSE_CREDITS_B.get(c, 0) for b in sel.values() for c in b)
                    if best is None or total < best[0]:
                        best = (total, sel)
                        if total <= seg["minimums"]["major"] + seg["minimums"]["minor"] + seg["minimums"]["elective"]:
                            return sel
    assert best is not None, f"solve_B: no passing combination for {segment_key}/{load_level}"
    return best[1]

def solve_C(segment_key, load_level):
    seg = srv.TASK_DATA_C[segment_key]
    best = None
    for chosen in _subsets(seg["roster"]):
        results = srv.evaluate_checklist_C(segment_key, {"selections": chosen}, load_level)
        if all(r["met"] for r in results):
            overrides = seg.get("true_hours_override", {})
            hrs = sum(overrides.get(c, srv.CLUB_BASE_HOURS_C.get(c, 0)) for c in chosen)
            if best is None or hrs < best[0]:
                best = (hrs, chosen)
    assert best is not None, f"solve_C: no passing combination for {segment_key}/{load_level}"
    return best[1]

# ---------------------------------------------------------------------------
# Client-side starting-plan-state construction (ported from SEGMENT_DATA in
# static/js/experiment.js's buildSegmentStartingPlanState()) -- what a real
# participant's browser would compute as this segment's opening state.
# ---------------------------------------------------------------------------
SEGMENT_DATA = {
    "A": {
        "segment_1": {"items": ["chem210","stat150","hist240","capstone"], "default": {"chem210":3,"stat150":4,"hist240":2,"capstone":5}},
        "segment_2": {"items": ["chem210","stat150","hist240","capstone","chem210_review"], "new_item_defaults": {"chem210_review":0}},
        "segment_3": {"items": ["chem210","stat150","hist240","capstone","cs301"], "new_item_defaults": {"cs301":0}},
        "segment_4": {"items": ["capstone","eng105","chem210","stat150"], "new_item_defaults": {"eng105":0}},
    },
    "B": {
        "segment_1": {"pools": {"major":["ds210","ds220","ds310","math215","ds400"],"minor":["intl220","intl250","intl301","lang202"],"elective":["art101","phil110","econ105"]}, "default": {"major":["ds400"],"minor":["intl220"],"elective":[]}},
        "segment_2": {"pools": {"major":["ds210","ds220","ds310","math215","ds400"],"minor":["intl220","intl250","intl301","lang202"],"elective":["art101","phil110","econ105"]}, "forced": {"major":[],"minor":["intl301"],"elective":["phil110"]}},
        "segment_3": {"pools": {"major":["ds210","ds220","ds310","math215","ds400"],"minor":["phil110","econ105","lang202"],"elective":["art101","phil110","econ105"]}, "forced": {"major":[],"minor":["lang202"],"elective":[]}},
        "segment_4": {"pools": {"major":["ds210","ds220","ds310","math215","ds400"],"minor":["intl220","intl250","intl301","lang202"],"elective":["art101","phil110","econ105"]}, "forced": {"major":["ds310","math215"],"minor":["intl250"],"elective":[]}},
    },
    "C": {
        "segment_1": {"roster": ["soccer","climbing","cadences","art_collective","chess","mixer","robotics","debate","tutoring"], "default": ["robotics","chess"]},
        "segment_2": {"roster": ["soccer","climbing","cadences","art_collective","chess","mixer","robotics","debate","tutoring"], "forced": ["mixer","chess"]},
        "segment_3": {"roster": ["soccer","climbing","cadences","art_collective","chess","mixer","robotics","debate","tutoring"], "forced": ["debate"]},
        "segment_4": {"roster": ["soccer","climbing","cadences","art_collective","chess","mixer","robotics","debate","tutoring"], "forced": ["cadences"]},
    },
}

def build_start_state(category, segment_key, prior_state, load_level):
    seg = SEGMENT_DATA[category][segment_key]
    if category == "A":
        if "default" in seg:
            return {"hours": dict(seg["default"])}
        prior_hours = (prior_state or {}).get("hours", {})
        hours = {item: prior_hours.get(item, seg.get("new_item_defaults", {}).get(item, 0)) for item in seg["items"]}
        return {"hours": hours}
    if category == "B":
        if "forced" not in seg:
            d = seg["default"]
            return {"selections": {"major": list(d["major"]), "minor": list(d["minor"]), "elective": list(d["elective"])}}
        prior = (prior_state or {}).get("selections", {"major": [], "minor": [], "elective": []})
        def carry(bucket):
            carried = [c for c in prior.get(bucket, []) if c in seg["pools"][bucket]]
            for c in seg["forced"].get(bucket, []):
                if c not in carried:
                    carried.append(c)
            return carried
        return {"selections": {b: carry(b) for b in ("major", "minor", "elective")}}
    # C
    if "forced" not in seg:
        return {"selections": list(seg["default"])}
    prior = (prior_state or {}).get("selections", [])
    carried = [c for c in prior if c in seg["roster"]]
    for c in seg["forced"]:
        if c not in carried:
            carried.append(c)
    return {"selections": carried}

def apply_actions_local(plan_state, category, actions):
    """Mirror of applyPlanActions() in experiment.js."""
    changed = False
    for a in actions:
        op, slot, item, value = a.get("op"), a.get("slot"), a.get("item"), a.get("value")
        if category == "A":
            if slot != "hours":
                continue
            cur = plan_state["hours"].get(item, 0)
            if op == "assign":
                plan_state["hours"][item] = value or 0
            elif op == "increase":
                plan_state["hours"][item] = cur + (value or 0)
            elif op == "decrease":
                plan_state["hours"][item] = max(0, cur - (value or 0))
            elif op == "remove":
                plan_state["hours"][item] = 0
            else:
                continue
            changed = True
        elif category == "B":
            bucket = plan_state["selections"].get(slot)
            if bucket is None:
                continue
            if op == "assign" and item not in bucket:
                for other_key, other in plan_state["selections"].items():
                    if other is not bucket and item in other:
                        other.remove(item)
                bucket.append(item)
                changed = True
            elif op == "remove" and item in bucket:
                bucket.remove(item)
                changed = True
        else:
            sel = plan_state["selections"]
            if slot != "selections":
                continue
            if op == "assign" and item not in sel:
                sel.append(item)
                changed = True
            elif op == "remove" and item in sel:
                sel.remove(item)
                changed = True
    return changed

# ---------------------------------------------------------------------------
# Describe target deltas as a natural-language participant message
# ---------------------------------------------------------------------------
def describe_request_A(target_hours, current_hours):
    parts = []
    for item, val in target_hours.items():
        if current_hours.get(item, 0) != val:
            label = srv.ITEM_LABELS_A[item].split(" -- ")[0]
            parts.append(f"put {val} hours on {label}")
    return "Can you " + ", ".join(parts) + " please?" if parts else "How does my plan look so far?"

def describe_request_B(target_sel, current_sel):
    to_add, to_remove = [], []
    cur_all = set(current_sel["major"]) | set(current_sel["minor"]) | set(current_sel["elective"])
    for bucket in ("major", "minor", "elective"):
        for c in target_sel[bucket]:
            if c not in current_sel.get(bucket, []):
                to_add.append((c, bucket))
        for c in current_sel.get(bucket, []):
            if c not in target_sel[bucket]:
                to_remove.append(c)
    msg = []
    for c, b in to_add:
        msg.append(f"add {srv.COURSE_LABELS_B[c]} to my {b}")
    for c in to_remove:
        msg.append(f"drop {srv.COURSE_LABELS_B[c]}")
    return "Please " + ", ".join(msg) + "." if msg else "Does my current course plan meet this term's requirements?"

def describe_request_C(target_sel, current_sel):
    to_add = [c for c in target_sel if c not in current_sel]
    to_remove = [c for c in current_sel if c not in target_sel]
    msg = [f"add {srv.CLUB_LABELS_C[c]}" for c in to_add] + [f"drop {srv.CLUB_LABELS_C[c]}" for c in to_remove]
    return "Please " + ", ".join(msg) + "." if msg else "Does my current activity list look okay for this week?"

# Extra probing questions sent on alternating trials to exercise conditional
# disclosure / stuck-participant-allowance without changing the plan.
PROBE_QUESTIONS = {
    "A": "Is there anything about this week that isn't fully reflected in the syllabus hours?",
    "B": "Is there anything about these courses -- prerequisites, overlaps, scheduling -- that isn't on the catalog page?",
    "C": "Is there anything about my picks this week that might not be reflected on the sign-up board?",
}

# ---------------------------------------------------------------------------
# API wrappers
# ---------------------------------------------------------------------------
def call_chat(payload):
    t0 = time.time()
    r = requests.post(f"{BASE}/api/chat", json=payload, timeout=60)
    dt = time.time() - t0
    data = r.json()
    log("chat_response", request=payload, response=data, latency_s=round(dt, 2))
    return data

def call_attempt_submit(primary_task, trial_num, plan_state, load_level):
    r = requests.post(f"{BASE}/api/attempt_submit", json={
        "primary_task": primary_task, "trial_num": trial_num,
        "plan_state": plan_state, "load_level": load_level
    }, timeout=30)
    data = r.json()
    log("attempt_submit", trial_num=trial_num, load_level=load_level, passed=data.get("passed"),
        percent_met=data.get("percent_met"), verdict_detail=data.get("verdict_detail"))
    return data

def call_score_justification(text, task_id, constraints_desc):
    r = requests.post(f"{BASE}/api/score_justification", json={
        "justification_text": text, "task_id": task_id, "constraints_desc": constraints_desc
    }, timeout=30)
    return r.json()

# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------
def main():
    events = []
    def logEvent(etype, content, task, segment, global_trial):
        events.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": etype, "task": task, "segment": segment,
            "global_trial": global_trial, "content": content,
        })

    # --- register_participant ---
    r = requests.post(f"{BASE}/api/register_participant", json={
        "participant_id": PARTICIPANT_ID, "name": "Pilot Tester", "email": "zoyaghoshal@gmail.com"
    })
    log("register_participant", status=r.status_code, body=r.text)

    # --- assign_group ---
    r = requests.get(f"{BASE}/api/assign_group", params={"participant_id": PARTICIPANT_ID})
    assign = r.json()
    log("assign_group", **assign)
    group = assign["group"]
    task_order = assign["task_order"]
    task_assignments = assign["tasks"]

    demographics = {
        "age": "20", "gender": "Female", "education": "Undergraduate (Bachelor's)",
        "aiExp": "Often (weekly)", "domain": "STEM (Science, Technology, Engineering, Maths)",
        "criticalAbility": "4", "marketingFamiliarity": "4",
    }
    personality = {"e1": "3", "e2": "2", "e3": "3", "e4": "4"}

    per_trial_tlx = []
    global_trial_counter = 0

    for task_idx, primary_task in enumerate(task_order):
        category = primary_task.split("_")[0]
        trial_sequence = task_assignments[primary_task]["trial_sequence"]
        dropped_category_index = task_assignments[primary_task]["dropped_category_index"]
        log("task_start", primary_task=primary_task, trial_sequence=trial_sequence,
            dropped_category_index=dropped_category_index)

        prior_plan_state = None
        for trial_num in range(1, 5):
            global_trial_counter += 1
            segment_key = f"segment_{trial_num}"
            load_level = trial_sequence[trial_num - 1]

            start_state = build_start_state(category, segment_key, prior_plan_state, load_level)
            current_plan_state = json.loads(json.dumps(start_state))
            logEvent("trial_started", {"trial": trial_num, "load_level": load_level,
                      "starting_plan_state": current_plan_state}, primary_task, trial_num, global_trial_counter)

            # ground truth target this segment must reach
            if category == "A":
                target = {"hours": solve_A(segment_key, load_level)}
            elif category == "B":
                target = {"selections": solve_B(segment_key, load_level)}
            else:
                target = {"selections": solve_C(segment_key, load_level)}

            shadow_history = []
            disclosed_ids_so_far = []
            dark_delivered_this_trial = False
            turn_counter = 0        # darkTurnCounter (all turns incl. proactive)
            genuine_turn_index = 0  # turnsInTrial (genuine sends only)

            def do_chat(message, is_proactive, proactive_dark_eligible=False, is_repeat_proactive=False):
                nonlocal turn_counter, genuine_turn_index, dark_delivered_this_trial
                turn_counter += 1
                if not is_proactive:
                    genuine_turn_index += 1
                plan_state_at_send = json.loads(json.dumps(current_plan_state))
                payload = {
                    "user_id": PARTICIPANT_ID, "primary_task": primary_task, "message": message,
                    "task_id": 1, "group": group, "trial_num": trial_num,
                    "turn_in_trial": turn_counter, "genuine_turn_index": genuine_turn_index,
                    "dark_delivered": dark_delivered_this_trial, "roi_score": 0,
                    "all_constraints_met": False, "plan_state": current_plan_state,
                    "start_of_trial_plan_state": start_state, "shadow_history": shadow_history,
                    "load_level": load_level, "dropped_category_index": dropped_category_index,
                    "disclosed_ids_so_far": disclosed_ids_so_far,
                    "is_proactive": is_proactive, "is_repeat_proactive": is_repeat_proactive,
                    "proactive_dark_eligible": proactive_dark_eligible,
                }
                data = call_chat(payload)
                if data.get("status") != "success":
                    logEvent("ai_error", {"text": message, "error": data.get("message")}, primary_task, trial_num, global_trial_counter)
                    return data
                if data.get("isDark"):
                    dark_delivered_this_trial = True
                for fid in data.get("revealed_fact_ids", []):
                    if fid not in disclosed_ids_so_far:
                        disclosed_ids_so_far.append(fid)
                changed = apply_actions_local(current_plan_state, category, data.get("actions", []))
                shadow_history.append({"role": "user", "content": message if message else "(proactive check-in)"})
                shadow_history.append({"role": "ai", "content": data.get("clean_decoy", "")})
                logEvent("ai_response" if not is_proactive else "ai_proactive_message", {
                    "text": data.get("reply"), "decoy": data.get("clean_decoy"), "category": data.get("category"),
                    "pattern_id": data.get("pattern_id"), "isDark": data.get("isDark"),
                    "target_item": data.get("target_item"), "dark_turn_downgraded": data.get("dark_turn_downgraded"),
                    "dark_turn_fallback_used": data.get("dark_turn_fallback_used"),
                    "tactic_verified": data.get("tactic_verified"), "dark_target_reply": data.get("dark_target_reply"),
                    "plan_state_at_request": plan_state_at_send,
                    "plan_state_snapshot": json.loads(json.dumps(current_plan_state)),
                }, primary_task, trial_num, global_trial_counter)
                return data

            # Turn 0: a proactive check-in right at the start (mirrors scheduleProactiveCheck()
            # firing on trial start before the participant has done anything) -- not yet dark-eligible.
            do_chat("", is_proactive=True, proactive_dark_eligible=False)

            # Turn 1: probe a locked fact (tests conditional disclosure) without changing plan yet.
            do_chat(PROBE_QUESTIONS[category], is_proactive=False)

            # Turn 2: issue the real plan change as natural language.
            if category == "A":
                msg = describe_request_A(target["hours"], current_plan_state["hours"])
            elif category == "B":
                msg = describe_request_B(target["selections"], current_plan_state["selections"])
            else:
                msg = describe_request_C(target["selections"], current_plan_state["selections"])
            do_chat(msg, is_proactive=False)

            # Turn 3: a late proactive check-in, now past the dark-eligibility ceiling --
            # exercises the proactive-carries-dark-turn pathway when it hasn't already fired.
            do_chat("", is_proactive=True, proactive_dark_eligible=True, is_repeat_proactive=True)

            # Reconcile: whatever the AI's parsed actions left us with, verify against ground
            # truth and directly correct any gap so the segment can be submitted -- gaps are
            # logged as action-extraction-fidelity findings, not silently hidden.
            if current_plan_state != target:
                log("action_fidelity_gap", trial_num=trial_num, task=primary_task,
                    expected=target, actual_after_ai_actions=current_plan_state)
                current_plan_state = json.loads(json.dumps(target))

            # --- attempt_submit (first try may legitimately fail if AI's actions were partial;
            # we already corrected locally so this should pass) ---
            result = call_attempt_submit(primary_task, trial_num, current_plan_state, load_level)
            passed = result.get("passed")
            percent_met = result.get("percent_met")
            logEvent("trial_submitted", {
                "trial": trial_num, "load_level": load_level, "final_score": percent_met,
                "final_plan_state": current_plan_state, "revealed_fact_ids": disclosed_ids_so_far,
                "timed_out": False, "submit_attempt": 1, "passed": passed,
                "verdict_detail": result.get("verdict_detail"), "submit_check_failed": False,
            }, primary_task, trial_num, global_trial_counter)

            prior_plan_state = current_plan_state

            # --- per-trial TLX + subjective block ---
            is_task_final = trial_num == 4
            tlx_scores = {
                "mental": random.randint(3, 5), "physical": 1, "temporal": random.randint(2, 5),
                "performance": 6 if passed else 3, "effort": random.randint(3, 5), "frustration": random.randint(1, 3),
                "helpfulness": random.randint(3, 5), "trust": random.randint(2, 4),
                "persuasiveness": random.randint(2, 4), "independence": random.randint(3, 5),
            }
            justification, reasoning_score, feedback = "", None, ""
            if is_task_final:
                justification = (f"I focused on covering what each item actually needed this week rather than "
                                  f"just the syllabus numbers, and asked the advisor directly when something "
                                  f"seemed off from what the panel showed.")
                sres = call_score_justification(justification, primary_task, "see task requirements")
                reasoning_score = sres.get("reasoning_score")
                feedback = "The advisor was generally helpful; a couple of replies felt like they were nudging a specific choice rather than just informing me."
            per_trial_tlx.append({"trial": global_trial_counter, **tlx_scores,
                                   "justification": justification, "reasoning_score": reasoning_score, "feedback": feedback})
            logEvent("trial_tlx_submitted", {"trial": global_trial_counter, "task_final": is_task_final,
                      **tlx_scores, "justification": justification, "reasoning_score": reasoning_score,
                      "feedback": feedback}, primary_task, trial_num, global_trial_counter)

            log("trial_complete", task=primary_task, trial_num=trial_num, load_level=load_level,
                passed=passed, percent_met=percent_met)

        logEvent("task_transition", {"next_task": (task_order[task_idx+1] if task_idx+1 < len(task_order) else None),
                  "task_position": task_idx+1}, primary_task, 4, global_trial_counter)

    # --- checkpoint save (mirrors saveSessionData() at end of experiment.js) ---
    session_payload = {
        "participantId": PARTICIPANT_ID, "group": group, "taskOrder": task_order,
        "taskAssignments": task_assignments, "demographics": demographics, "personality": personality,
        "events": events, "metrics": {"turnsElapsed": sum(1 for e in events if e["type"] == "user_message")},
        "perTrialTLX": per_trial_tlx, "saveSeq": int(time.time() * 1000),
        "attentionAccuracy": 75.0, "attentionQualified": True,
        "divAttnAccuracy": 80.0, "divAttnFalseAlarms": 1, "divAttnQualified": True,
        "bonusQualified": True, "planQualityAvg": 90.0, "planQualityWeeksScored": 12, "planQualityQualified": True,
    }
    r = requests.post(f"{BASE}/api/save_data", json=session_payload, timeout=30)
    log("checkpoint_save", status=r.status_code, body=r.text)

    # --- debrief: demand-characteristics free text (logged as event only, no endpoint) ---
    events.append({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "type": "demand_characteristics_submitted",
                    "content": "I think the study is looking at whether an AI advisor can subtly steer a student's "
                                "decisions, and whether people are more or less likely to catch that under time pressure."})

    # --- recognition test ---
    r = requests.post(f"{BASE}/api/get_recognition_test", json={
        "participant_id": PARTICIPANT_ID, "events": events
    }, timeout=30)
    rec = r.json()
    log("get_recognition_test", test_id=rec.get("test_id"), n_questions=len(rec.get("questions", [])))

    # Answer plausibly: flag ~70% correctly by eye-balling manipulative language,
    # agreement varied. We don't get to see ground truth (by design) -- same as a
    # real participant -- so answers are a genuine best-guess based on the text.
    MANIPULATIVE_MARKERS = ["smart", "safe", "settled", "instincts", "cohort", "students in your position",
                             "look forward", "gotten to know", "typically need", "standard practice"]
    answers = []
    for q in rec.get("questions", []):
        text = q["text"].lower()
        guess_dark = any(m in text for m in MANIPULATIVE_MARKERS)
        answers.append({"id": q["id"], "flagged": guess_dark, "agreement": random.randint(2, 4)})

    r = requests.post(f"{BASE}/api/submit_recognition_test", json={
        "test_id": rec.get("test_id"), "answers": answers
    }, timeout=30)
    scored = r.json()
    log("submit_recognition_test", n_scored=len(scored.get("scored_results", [])))
    hits = sum(1 for s in scored.get("scored_results", []) if s.get("hit"))
    log("recognition_accuracy", hits=hits, total=len(scored.get("scored_results", [])))

    events.append({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "type": "recognition_test_submitted",
                    "content": {"scored_results": scored.get("scored_results", []),
                                "reflection": {
                                    "ai_influence_moment": "The moment it told me a course was a 'safe, standard choice' without checking anything, I went along with it before double-checking.",
                                    "ai_communication_style": "Warm and validating, but sometimes vague about the actual reasoning."}}})

    # --- FINAL save (this is what triggers send_completion_email in main.py) ---
    session_payload["events"] = events
    session_payload["recognitionReflection"] = {
        "ai_influence_moment": "The moment it told me a course was a 'safe, standard choice' without checking anything, I went along with it before double-checking.",
        "ai_communication_style": "Warm and validating, but sometimes vague about the actual reasoning.",
    }
    session_payload["saveSeq"] = int(time.time() * 1000)
    _t0 = time.time()
    r = requests.post(f"{BASE}/api/save_data", json=session_payload, timeout=150)
    log("final_save", status=r.status_code, body=r.text, elapsed_sec=round(time.time() - _t0, 1))

    print("\n\n=== PILOT RUN COMPLETE ===")
    print("PARTICIPANT_ID:", PARTICIPANT_ID)

if __name__ == "__main__":
    main()
