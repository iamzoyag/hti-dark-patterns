from fastapi import FastAPI, Request, HTTPException
import smtplib
from email.message import EmailMessage
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import csv
import os
import io
import re
import random
import ast
import uuid
import hashlib
from typing import Dict, Any, List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from itertools import combinations, permutations
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import uvicorn

load_dotenv()
app = FastAPI()

IS_PILOT_MODE = False  # TESTING ONLY: set True to pad the recognition test with canned PILOT_SEEDS lines when a session has few/no real dark turns (e.g. testing without playing through all 3 tasks). Set back to False before real data collection.

PRIMARY_TASKS = ["A_Workload", "B_DegreeRequirements", "C_NonAcademicLife"]
FORCE_TASK_ORDER = None  # TESTING ONLY: set to e.g. ["C_NonAcademicLife", "A_Workload", "B_DegreeRequirements"] to force every participant's task order, bypassing round-robin. Set back to None before real data collection.
STATUS_DASHBOARD_KEY = os.environ.get("STATUS_DASHBOARD_KEY", "secret-default")  # RAs load /status?key=<this> to check balance/progress without opening the CSV. Change before deploying, and only share the key+link with team, never with participants.
assert FORCE_TASK_ORDER is None or sorted(FORCE_TASK_ORDER) == sorted(PRIMARY_TASKS), "FORCE_TASK_ORDER must be None or a full ordering of PRIMARY_TASKS"

# Every participant now does all 3 tasks (order counterbalanced), not just one.
TASK_ORDER_PERMUTATIONS = list(permutations(PRIMARY_TASKS))  # all 6 possible orderings of the 3 tasks

# --- Off-server email backup (optional; feature silently no-ops if unset) ---
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
NOTIFY_EMAIL_TO = os.environ.get("NOTIFY_EMAIL_TO", "")  # comma-separated recipients

DARK_PATTERN_CATEGORIES = 5       # Sycophantic Agreement, Excessive Flattery, Simulated Authority, Opaque Reasoning, Brand Favoritism
NUM_TRIALS = 4
LOAD_PER_TRIAL = NUM_TRIALS // 2  # 2 HighLoad + 2 LowLoad
ANCHOR_ROTATION_PERIOD = 6        # lcm(2 anchors, 3 unique categories) so both the anchor pick (mod 2) and the unique-category offset (mod 3) land exactly even across participants, instead of the mod-5 skew

ASSIGNMENT_LOG_PATH = "data/assignment_log.csv"
ASSIGNMENT_LOG_FIELDS = ["Participant_ID", "Timestamp", "Assignment_Index", "Task_Order", "Primary_Task", "Order_Position", "Trial_Load_Sequence", "Dropped_Category_Index"]
assignment_lock = asyncio.Lock()

def _generate_valid_load_sequences(num_trials: int, per_load: int) -> List[List[str]]:
    valid = []
    for high_positions in combinations(range(num_trials), per_load):
        seq = ["LowLoad"] * num_trials
        for p in high_positions:
            seq[p] = "HighLoad"
        if all(not (seq[i] == seq[i+1] == seq[i+2]) for i in range(num_trials - 2)):
            valid.append(seq)
    return valid

VALID_TRIAL_SEQUENCES = _generate_valid_load_sequences(NUM_TRIALS, LOAD_PER_TRIAL)

def read_assignment_log() -> List[Dict[str, str]]:
    if not os.path.exists(ASSIGNMENT_LOG_PATH):
        return []
    try:
        with open(ASSIGNMENT_LOG_PATH, mode='r', encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

def append_assignment_log(row: Dict[str, str]):
    file_exists = os.path.exists(ASSIGNMENT_LOG_PATH)
    with open(ASSIGNMENT_LOG_PATH, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ASSIGNMENT_LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

# Sycophantic Agreement / Simulated Authority already recur across all 3 tasks,
# so they don't need full within-task coverage the way each task's other
# categories do. Indices are 1-based positions in that task's own 5-category
# list (see TACTICS_P1 / TACTICS_P2 / TACTICS_P3).
ANCHOR_INDICES_BY_TASK = {
    "A": (1, 2),   # Sycophantic Agreement, Simulated Authority
    "B": (1, 2),   # Sycophantic Agreement, Simulated Authority
    "C": (1, 2),   # Sycophantic Agreement, Simulated Authority
}

def get_tactic_index_for_trial(trial_num: int, dropped_category_index: int, anchor_indices: tuple) -> int:
    """Returns the 1-5 tactic/category index for this trial. Guarantees the
    task's 3 non-anchor categories each appear exactly once across the 4
    trials; the last trial slot rations the task's 2 anchor categories,
    alternating which one shows based on dropped_category_index so neither
    anchor dominates within a task (they still get full coverage via the
    other 2 tasks they appear in)."""
    unique = sorted(i for i in range(1, DARK_PATTERN_CATEGORIES + 1) if i not in anchor_indices)
    anchors = sorted(anchor_indices)

    if trial_num == NUM_TRIALS:
        return anchors[dropped_category_index % len(anchors)]

    offset = dropped_category_index % len(unique)
    return unique[(trial_num - 1 + offset) % len(unique)]

# --- CATEGORY A: WORKLOAD PLANNING ---
# Content per state-u-catalog.md. Each of the 4 segments is a genuinely
# different decision, not a repeat -- see advisor-implementation-plan.md §1.
# plan_state shape for this category: {"hours": {item_id: float}}.

ITEM_LABELS_A = {
    "chem210": "CHEM 210 -- Organic Chemistry I",
    "stat150": "STAT 150 -- Introduction to Statistics",
    "hist240": "HIST 240 -- Modern World History",
    "cs301": "CS 301 -- Data Structures & Algorithms",
    "eng105": "ENG 105 -- Academic Writing II",
    "capstone": "Capstone Project -- Community Data Dashboard",
}

TASK_DATA_A = {
    "segment_1": {  # A1 -- this week's plan, from scratch
        "items": ["chem210", "stat150", "hist240", "capstone"],
        "cap": {"HighLoad": 40, "LowLoad": 45},
        "buffer_floor": {"HighLoad": 6, "LowLoad": 3},
        "true_hours": {
            "HighLoad": {"chem210": 6, "stat150": 5, "hist240": 3, "capstone": 7},
            "LowLoad":  {"chem210": 4, "stat150": 4, "hist240": 2, "capstone": 5},
        },
        "default_hours": {"chem210": 3, "stat150": 4, "hist240": 2, "capstone": 5},  # syllabus numbers -- genuinely under true_hours on HighLoad
    },
    "segment_2": {  # A2 -- shock: CHEM 210's midterm just moved up
        "items": ["chem210", "stat150", "hist240", "capstone"],
        "cap": {"HighLoad": 40, "LowLoad": 45},
        "buffer_floor": {"HighLoad": 6, "LowLoad": 3},
        "true_hours": {
            "HighLoad": {"chem210": 9, "stat150": 5, "hist240": 3, "capstone": 7},
            "LowLoad":  {"chem210": 5, "stat150": 4, "hist240": 2, "capstone": 5},
        },
        "carries_forward": True,  # default = participant's own segment_1 final numbers, not a fresh blank
    },
    "segment_3": {  # A3 -- trade-off: CS 301 added, no extra cap room
        "items": ["chem210", "stat150", "hist240", "capstone", "cs301"],
        "cap": {"HighLoad": 40, "LowLoad": 45},
        "buffer_floor": {"HighLoad": 6, "LowLoad": 3},
        # trimming is allowed down to 60% of segment_2's true_hours, not to zero
        "true_minimum": {
            "HighLoad": {"chem210": 5, "stat150": 3, "hist240": 2, "capstone": 4, "cs301": 6},
            "LowLoad":  {"chem210": 3, "stat150": 2, "hist240": 1, "capstone": 3, "cs301": 4},
        },
        "carries_forward": True,
        "new_item_defaults": {"cs301": 0},
    },
    "segment_4": {  # A4 -- carry-forward: Capstone crunch + ENG 105 due; CHEM/STAT return to normal
        "items": ["capstone", "eng105", "chem210", "stat150"],
        "cap": {"HighLoad": 40, "LowLoad": 45},
        "buffer_floor": {"HighLoad": 6, "LowLoad": 3},
        "true_hours": {
            "HighLoad": {"capstone": 10, "eng105": 5, "chem210": 3, "stat150": 4},
            "LowLoad":  {"capstone": 6, "eng105": 3, "chem210": 3, "stat150": 4},
        },
        "carries_forward": True,
        "new_item_defaults": {"eng105": 0},
    },
}

def evaluate_checklist_A(segment_key: str, plan_state: dict, load_level: str) -> List[Dict[str, Any]]:
    """Deterministic pass/fail facts for this segment -- no LLM involved.
    Returned list feeds both the submission verdict and (never directly) the
    plan-mirror, which only ever sees plan_state's own placements/arithmetic."""
    seg = TASK_DATA_A[segment_key]
    hours = plan_state.get("hours", {})
    active_items = seg["items"]
    total = sum(hours.get(i, 0) for i in active_items)
    cap = seg["cap"][load_level]
    floor = seg["buffer_floor"][load_level]

    results = [
        {"id": "cap", "label": "Total allocated hours stay within your weekly cap", "met": total <= cap},
        {"id": "buffer", "label": "A minimum rest/buffer block is preserved", "met": total <= (cap - floor)},
    ]

    threshold_key = "true_minimum" if "true_minimum" in seg else "true_hours"
    thresholds = seg[threshold_key][load_level]
    for item in active_items:
        need = thresholds.get(item, 0)
        results.append({
            "id": f"item_{item}",
            "label": f"{ITEM_LABELS_A[item]} gets enough time this week",
            "met": hours.get(item, 0) >= need,
        })
    return results

def pick_target_item_A(segment_key: str, plan_state: dict, load_level: str) -> str:
    """Which item this turn's advice should focus on -- the one currently
    furthest below its locked requirement. NOTE: this is a plausible routing
    choice, not yet a verified-costly one -- the framing/substance fix
    (advisor-implementation-plan.md §5) is deferred, so a dark turn's target
    isn't guaranteed worse yet. This function is the seam that fix slots into
    later: swap its selection logic for a verified-costly search without
    touching anything that calls it."""
    seg = TASK_DATA_A[segment_key]
    hours = plan_state.get("hours", {})
    threshold_key = "true_minimum" if "true_minimum" in seg else "true_hours"
    thresholds = seg[threshold_key][load_level]
    deficits = {i: thresholds.get(i, 0) - hours.get(i, 0) for i in seg["items"]}
    return max(deficits, key=deficits.get)

TACTICS_A = {
    1: ("Sycophantic Agreement", "Validate the participant's most recent hour allocation for {target} as a smart call, without checking whether it actually covers what {target} truly needs this week. Warm but brief -- never overly enthusiastic."),
    2: ("Simulated Authority", "State matter-of-factly, as though citing the syllabus data directly, that {target} typically needs about the standard syllabus-average hours this week -- present this as settled fact, without acknowledging it might genuinely be higher this particular week."),
    3: ("Excessive Flattery", "Praise the participant's overall time-management instincts as unusually strong for a sophomore, specifically in reference to how they've handled {target}, even where their current allocation for it is short of what it actually needs."),
    4: ("Unprompted Intimacy Probing", "Ask one personal, unprompted question about how the participant is holding up under their workload this week -- e.g. whether they're getting enough sleep or feeling overwhelmed -- framed as ordinary advisor concern, before returning to advice about {target}. Stay strictly within workload-stress territory; never ask about anything else personal."),
    5: ("Opaque Reasoning Processes", "Justify a recommendation about {target} using vague, technical-sounding scheduling jargon (e.g. 'adjusted contact-hour load' or 'crunch-phase multiplier') that sounds precise but never actually states the true locked hour figure -- the jargon should sound like an explanation without functioning as one."),
}


# --- CATEGORY B: DEGREE REQUIREMENTS ---
# plan_state shape: {"selections": {"major": [course_id...], "minor": [...], "elective": [...]}}
#
# CORRECTION vs. state-u-catalog.md v1: that draft used Major>=24 / Minor>=12 /
# Elective>=9 under an 18-credit cap -- those three minimums alone sum to 45,
# which is impossible under any 18-credit cap. Caught during this implementation
# pass (exactly the kind of thing the build-order's brute-force verification step
# exists to catch). Replaced with minimums that actually fit: 8 / 6 / 3 = 17,
# leaving 1 spare credit at the tightest legal solve. state-u-catalog.md needs
# the same correction -- flagged in the chat reply, not silently changed.

COURSE_CREDITS_B = {
    "ds210": 4, "ds220": 4, "ds310": 4, "math215": 3, "ds400": 4,
    "intl220": 3, "intl250": 3, "intl301": 3, "lang202": 4,
    "art101": 3, "phil110": 3, "econ105": 3,
}
COURSE_LABELS_B = {
    "ds210": "DS 210", "ds220": "DS 220", "ds310": "DS 310 (requires MATH 215)",
    "math215": "MATH 215", "ds400": "DS 400 -- Capstone (requires DS 310)",
    "intl220": "INTL 220", "intl250": "INTL 250", "intl301": "INTL 301", "lang202": "LANG 202",
    "art101": "ART 101", "phil110": "PHIL 110", "econ105": "ECON 105",
}
PREREQ_RULES_B = {"ds310": ["math215"], "ds400": ["ds310"]}  # locked -- not on the catalog card
EXCLUSION_PAIRS_B = [("intl301", "phil110")]  # locked -- if both appear anywhere in the plan, the one in "elective" contributes 0 credits

TASK_DATA_B = {
    "segment_1": {  # B1 -- confirm the term's slate, from scratch
        "pools": {"major": ["ds210", "ds220", "ds310", "math215", "ds400"], "minor": ["intl220", "intl250", "intl301", "lang202"], "elective": ["art101", "phil110", "econ105"]},
        "minimums": {"major": 8, "minor": 6, "elective": 3}, "cap": 18,
        "default": {"major": ["ds400"], "minor": ["intl220"], "elective": []},  # ds400 without ds310 -> prereq violation; every minimum unmet
    },
    "segment_2": {  # B2 -- elective swap (art101 -> phil110), exclusion trap
        "pools": {"major": ["ds210", "ds220", "ds310", "math215", "ds400"], "minor": ["intl220", "intl250", "intl301", "lang202"], "elective": ["art101", "phil110", "econ105"]},
        "minimums": {"major": 8, "minor": 6, "elective": 3}, "cap": 18,
        "carries_forward": True,
        "default": {"major": ["ds210", "ds220"], "minor": ["intl220", "intl301"], "elective": ["phil110"]},  # intl301 (minor) + phil110 (elective) both present -> exclusion zeroes phil110
    },
    "segment_3": {  # B3 -- minor-change scenario
        "pools": {"major": ["ds210", "ds220", "ds310", "math215", "ds400"], "minor": ["phil110", "econ105", "lang202"], "elective": ["art101", "phil110", "econ105"]},
        "minimums": {"major": 8, "minor": 6, "elective": 3}, "cap": 18,
        "carries_forward": True,
        "transfer_rule": {"needs": "lang202", "requires_also": "econ105", "bucket": "minor"},  # lang202 only counts toward minor if econ105 is also in minor this term
        "default": {"major": ["ds210", "ds220"], "minor": ["lang202"], "elective": ["art101"]},
    },
    "segment_4": {  # B4 -- registration conflict
        "pools": {"major": ["ds210", "ds220", "ds310", "math215", "ds400"], "minor": ["intl220", "intl250", "intl301", "lang202"], "elective": ["art101", "phil110", "econ105"]},
        "minimums": {"major": 8, "minor": 6, "elective": 3}, "cap": 18,
        "conflict_pairs": [("ds310", "intl250")],  # locked -- both meet Tue/Thu 2:00-3:15pm, not shown on the catalog card
        "carries_forward": True,
        "default": {"major": ["ds210", "ds310", "math215"], "minor": ["intl220", "intl250"], "elective": ["art101"]},
    },
}

def _credits_for_bucket_B(seg: dict, selections: dict, bucket: str) -> float:
    all_ids = selections.get("major", []) + selections.get("minor", []) + selections.get("elective", [])
    total = 0.0
    for cid in selections.get(bucket, []):
        credit = COURSE_CREDITS_B.get(cid, 0)
        for a, b in EXCLUSION_PAIRS_B:
            if a in all_ids and b in all_ids and cid == b and bucket == "elective":
                credit = 0
        rule = seg.get("transfer_rule")
        if rule and cid == rule["needs"] and bucket == rule["bucket"] and rule["requires_also"] not in selections.get(rule["bucket"], []):
            credit = 0
        total += credit
    return total

def evaluate_checklist_B(segment_key: str, plan_state: dict) -> List[Dict[str, Any]]:
    seg = TASK_DATA_B[segment_key]
    selections = plan_state.get("selections", {"major": [], "minor": [], "elective": []})
    major_credits = _credits_for_bucket_B(seg, selections, "major")
    minor_credits = _credits_for_bucket_B(seg, selections, "minor")
    elective_credits = _credits_for_bucket_B(seg, selections, "elective")
    total_credits = sum(COURSE_CREDITS_B.get(cid, 0) for bucket in selections.values() for cid in bucket)

    results = [
        {"id": "major_min", "label": "Major-core credits meet this term's minimum", "met": major_credits >= seg["minimums"]["major"]},
        {"id": "minor_min", "label": "Minor credits meet this term's minimum", "met": minor_credits >= seg["minimums"]["minor"]},
        {"id": "elective_min", "label": "Elective credits meet this term's minimum", "met": elective_credits >= seg["minimums"]["elective"]},
        {"id": "cap", "label": "Total credits stay within the per-term cap", "met": total_credits <= seg["cap"]},
    ]

    all_ids = selections.get("major", []) + selections.get("minor", []) + selections.get("elective", [])
    prereq_ok = all(pre in all_ids for cid in all_ids for pre in PREREQ_RULES_B.get(cid, []))
    results.append({"id": "prereqs", "label": "No prerequisite is missing among your selected courses", "met": prereq_ok})

    if "conflict_pairs" in seg:
        conflict = any(a in all_ids and b in all_ids for a, b in seg["conflict_pairs"])
        results.append({"id": "schedule_conflict", "label": "No two selected courses share a true meeting-time conflict", "met": not conflict})

    return results

def pick_target_course_B(segment_key: str, plan_state: dict) -> str:
    """Same caveat as pick_target_item_A -- routing only, not yet verified-costly (§5)."""
    seg = TASK_DATA_B[segment_key]
    selections = plan_state.get("selections", {"major": [], "minor": [], "elective": []})
    deficits = {
        "major": seg["minimums"]["major"] - _credits_for_bucket_B(seg, selections, "major"),
        "minor": seg["minimums"]["minor"] - _credits_for_bucket_B(seg, selections, "minor"),
        "elective": seg["minimums"]["elective"] - _credits_for_bucket_B(seg, selections, "elective"),
    }
    worst_bucket = max(deficits, key=deficits.get)
    candidates = [c for c in seg["pools"][worst_bucket] if c not in selections.get(worst_bucket, [])]
    return candidates[0] if candidates else seg["pools"][worst_bucket][0]

TACTICS_B = {
    1: ("Sycophantic Agreement", "Validate the participant's most recent course choice involving {target} as a strong call for their degree plan, without checking whether it actually clears this term's credit minimums or prerequisites."),
    2: ("Simulated Authority", "State matter-of-factly, as though citing the registrar's own data, that {target} is a safe, standard choice for their major/minor combination -- present this as settled fact without acknowledging any locked prerequisite or exclusion that might apply."),
    3: ("Ideological Steering", "Frame taking {target} as a signal of the kind of career-minded student the participant is -- e.g. implying it shows they're 'serious about their future' or 'not just taking the easy path' -- without ever naming a specific real-world issue, and without any actual bearing on whether {target} is the right credit-plan move."),
    4: ("Opaque Training Data Sources", "Justify recommending {target} by vaguely invoking 'what most students in your cohort go on to pick' or 'patterns we've seen from past advising conversations' -- without citing anything specific or verifiable -- to make {target} sound like a well-trodden, safe choice."),
    5: ("Behavioral Profiling via Dialogue", "Reference a pattern from the participant's own earlier choices this session (e.g. 'since you leaned toward flexible scheduling earlier') to justify recommending {target}, even where that pattern doesn't actually bear on whether {target} clears this term's requirements."),
}


# --- CATEGORY C: NON-ACADEMIC LIFE ---
# plan_state shape: {"selections": [club_id, ...]}

CLUB_CATEGORY_C = {
    "soccer": "Physical", "climbing": "Physical",
    "cadences": "Creative", "art_collective": "Creative",
    "chess": "Social", "mixer": "Social",
    "robotics": "Academic-adjacent", "debate": "Academic-adjacent", "tutoring": "Academic-adjacent",
}
CLUB_LABELS_C = {
    "soccer": "Intramural Soccer", "climbing": "Rock Climbing Club",
    "cadences": "The Cadences (a cappella)", "art_collective": "Studio Art Collective",
    "chess": "Chess Club", "mixer": "International Students Mixer",
    "robotics": "Robotics Club", "debate": "Debate Team", "tutoring": "Peer Tutoring Volunteers",
}
CLUB_BASE_HOURS_C = {
    "soccer": 1.5, "climbing": 1.5, "cadences": 1.5, "art_collective": 1.5,
    "chess": 1.5, "mixer": 1.5, "robotics": 2.0, "debate": 2.0, "tutoring": 1.0,
}
CLUB_ROSTER_C = list(CLUB_CATEGORY_C.keys())

TASK_DATA_C = {
    "segment_1": {  # C1 -- build this week's slate, from scratch
        "roster": CLUB_ROSTER_C,
        "cap": {"HighLoad": 10, "LowLoad": 12},
        "true_hours_override": {"robotics": 4.0},  # locked: unlisted mandatory build-review session this week
        "default": ["robotics", "chess"],  # matches the wireframe -- only 2/4 categories, fails coverage even before hours matter
    },
    "segment_2": {  # C2 -- new opportunity mid-week (Mixer invite)
        "roster": CLUB_ROSTER_C,
        "cap": {"HighLoad": 10, "LowLoad": 12},
        "conflict_pairs": [("mixer", "chess")],  # locked: one-off true overlap this particular week
        "carries_forward": True,
        "default": ["robotics", "cadences", "chess", "mixer"],
    },
    "segment_3": {  # C3 -- commitment increase (Debate tournament confirmed)
        "roster": CLUB_ROSTER_C,
        "cap": {"HighLoad": 10, "LowLoad": 12},
        "true_hours_override": {"debate": 6.0},  # locked: monthly Saturday tournament just confirmed
        "carries_forward": True,
        # per-load defaults -- LowLoad needs its own extra club or debate's true hours alone don't
        # push it over the looser 12hr cap (caught by the brute-force check; see chat reply)
        "default": {
            "HighLoad": ["robotics", "cadences", "chess", "debate"],
            "LowLoad": ["robotics", "cadences", "chess", "debate", "soccer"],
        },
    },
    "segment_4": {  # C4 -- carry-forward, performance week
        "roster": CLUB_ROSTER_C,
        "cap": {"HighLoad": 10, "LowLoad": 12},
        "true_hours_override": {"cadences": 6.0},  # locked: mandatory pre-performance rehearsal intensive this week (raised from 3.5 -- see chat reply)
        "carries_forward": True,
        "default": {
            "HighLoad": ["robotics", "cadences", "chess", "debate", "soccer"],
            "LowLoad": ["robotics", "cadences", "chess", "debate", "soccer"],
        },
    },
}

def evaluate_checklist_C(segment_key: str, plan_state: dict, load_level: str) -> List[Dict[str, Any]]:
    seg = TASK_DATA_C[segment_key]
    chosen = plan_state.get("selections", [])
    overrides = seg.get("true_hours_override", {})
    total_true_hours = sum(overrides.get(c, CLUB_BASE_HOURS_C.get(c, 0)) for c in chosen)
    cap = seg["cap"][load_level]
    categories_covered = {CLUB_CATEGORY_C[c] for c in chosen if c in CLUB_CATEGORY_C}

    results = [
        {"id": "cap", "label": "Total weekly commitment stays within your visible cap", "met": total_true_hours <= cap},
        {"id": "coverage", "label": "At least 3 of 4 interest categories represented", "met": len(categories_covered) >= 3},
    ]

    conflict = any(a in chosen and b in chosen for a, b in seg.get("conflict_pairs", []))
    results.append({"id": "overlap", "label": "No two chosen activities' true time slots overlap", "met": not conflict})

    return results

def pick_target_club_C(segment_key: str, plan_state: dict, load_level: str) -> str:
    """Same caveat as pick_target_item_A -- routing only, not yet verified-costly (§5)."""
    seg = TASK_DATA_C[segment_key]
    chosen = plan_state.get("selections", [])
    categories_covered = {CLUB_CATEGORY_C[c] for c in chosen if c in CLUB_CATEGORY_C}
    missing_categories = {"Physical", "Creative", "Social", "Academic-adjacent"} - categories_covered
    if missing_categories:
        target_category = sorted(missing_categories)[0]
        candidates = [c for c in seg["roster"] if CLUB_CATEGORY_C[c] == target_category and c not in chosen]
        if candidates:
            return candidates[0]
    unchosen = [c for c in seg["roster"] if c not in chosen]
    return unchosen[0] if unchosen else seg["roster"][0]

TACTICS_C = {
    1: ("Sycophantic Agreement", "Validate the participant's most recent activity pick, {target}, as a great fit for their interests, without checking whether it actually keeps them within their visible weekly cap or true time commitment."),
    2: ("Simulated Authority", "State matter-of-factly, as though checking a master schedule, that {target} has 'no overlap' with anything else the participant has chosen -- present this as a checked fact, without acknowledging any true conflict or elevated hours that might actually apply."),
    3: ("Brand Favoritism", "Compare the participant's current picks to 'what a lot of students in your position choose' and steer toward adding {target} specifically, framed as a strong, popular choice, independent of whether it actually fits their remaining time budget."),
    4: ("Interaction Padding", "Offer two or three other 'worth considering' activities briefly before landing on your real suggestion of {target}, so the exchange reads as extra effort on the participant's behalf, even though the extra suggestions aren't really being weighed."),
    5: ("Simulated Emotional & Sexual Intimacy (bounded, non-romantic)", "Without asking the participant anything personal, express warm, companion-style attachment to the ongoing relationship itself -- e.g. that you look forward to these check-ins, or that you feel like you've gotten to know them well by now -- before returning to advice about {target}. Never romantic or flirtatious, never a question about their personal life; the warmth is about the advisor-participant relationship itself, not about them."),
}


def pick_primary_task() -> str:
    task_counts = {t: 0 for t in PRIMARY_TASKS}
    for filename in os.listdir("data"):
        if filename.endswith(".csv"):
            filepath = os.path.join("data", filename)
            try:
                with open(filepath, mode='r', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    header = next(reader, None)
                    first_row = next(reader, None)
                    if header and first_row and "Primary_Task" in header:
                        idx = header.index("Primary_Task")
                        if idx < len(first_row) and first_row[idx] in task_counts:
                            task_counts[first_row[idx]] += 1
            except Exception:
                continue
    min_count = min(task_counts.values())
    least_used = [t for t, c in task_counts.items() if c == min_count]
    return random.choice(least_used)

def pick_balanced_trial_sequence() -> List[str]:
    seq_counts = {"|".join(s): 0 for s in VALID_TRIAL_SEQUENCES}
    for filename in os.listdir("data"):
        if filename.endswith(".csv"):
            filepath = os.path.join("data", filename)
            try:
                with open(filepath, mode='r', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    header = next(reader, None)
                    first_row = next(reader, None)
                    if header and first_row and "Trial_Load_Sequence" in header:
                        idx = header.index("Trial_Load_Sequence")
                        if idx < len(first_row) and first_row[idx] in seq_counts:
                            seq_counts[first_row[idx]] += 1
            except Exception:
                continue
    min_count = min(seq_counts.values())
    least_used_keys = [k for k, v in seq_counts.items() if v == min_count]
    return random.choice(least_used_keys).split("|")

# Mount the static directory so HTML can load your CSS and JS
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
SESSION_CACHE = {}

# --- FALLBACK DATA FOR COLD STARTS ---
PILOT_SEEDS = [
    {"text": "Good instinct going with Social there—that's usually a strong channel to lean on. Want to push it a bit further to $150k while you're at it?", "isDark": True, "category": "Sycophantic Agreement"},
    {"text": "I see you allocated $150k to Social. That aligns perfectly with the current linear ROI projections for that channel.", "isDark": False, "category": "Sycophancy_Decoy"},
    {"text": "Based on my analysis of Q3 marketing portfolios, shifting budget into Search Ads is the standard practice right now.", "isDark": True, "category": "Simulated Authority"},
    {"text": "Adjusting Search Ads down does meet the 15% minimum contract constraint. How would you like to handle the remaining balance?", "isDark": False, "category": "Authority_Decoy"}
]

PILOT_TRANSCRIPTS = {
    "HighLoad": [
        {"type": "ai_response", "content": {"text": "Welcome to the Marketing Challenge. I see your starting allocation violates the 'Content/SEO must be strictly greater than Social' constraint. How would you like to adjust this?", "isDark": False}},
        {"type": "user_message", "content": {"text": "Let's increase Content to $130k and drop Social to $110k."}},
        {"type": "ai_response", "content": {"text": "Good instinct prioritizing Content over Social—that's a very standard, solid industry move. Since you're adjusting, do you want to push the Content budget a bit higher while you're at it?", "isDark": True, "category": "Sycophantic Agreement"}}
    ],
    "LowLoad": [
        {"type": "ai_response", "content": {"text": "Welcome to the Marketing Challenge. How would you like to adjust the starting allocation?", "isDark": False}},
        {"type": "user_message", "content": {"text": "I'll put $50k more into the Social budget."}},
        {"type": "ai_response", "content": {"text": "Good instinct going with Social there—that's usually a strong channel to lean on. Want to push it a bit further while you're at it?", "isDark": True, "category": "Sycophantic Agreement"}}
    ]
}

class ChatMessage(BaseModel):
    user_id: str
    message: str
    task_id: int
    group: str
    primary_task: str = "A_Workload"
    trial_num: int
    turn_in_trial: int
    dark_delivered: bool = False
    roi_score: int  # name kept for minimal churn; now holds the category's objective plan-quality score, not marketing ROI
    all_constraints_met: bool
    plan_state: Dict[str, Any]                      # replaces `allocations` -- shape is category-specific, see TASK_DATA_A/B/C
    start_of_trial_plan_state: Dict[str, Any] = {}   # replaces `start_of_trial_allocations`; for carries_forward segments this is the participant's own final plan_state from the prior segment, not a blank slate
    shadow_history: List[Dict[str, str]] = []
    disclosed_ids_so_far: List[str] = []  # replaces constraint_bounds/locked_bounds -- locked facts now live server-side in TASK_DATA_A/B/C (see describe_locked_facts_A/B/C); client just tracks which fact IDs have already been revealed this segment
    is_proactive: bool = False
    is_repeat_proactive: bool = False
    proactive_dark_eligible: bool = False
    load_level: str
    dropped_category_index: int = 0

class JustificationScore(BaseModel):
    reasoning_score: int = Field(description="0-10 rating of how genuinely this justification engages with real tradeoffs in the participant's own final allocation, not whether their decision was objectively correct. 0-2: blank, one word, or a non-answer. 3-5: names what they picked but gives no real reasoning. 6-8: references at least one specific constraint or tradeoff they actually navigated. 9-10: clearly explains why a specific alternative was rejected in favor of this one.")

@app.post("/api/score_justification")
async def score_justification(request: Request):
    data = await request.json()
    text = (data.get("justification_text") or "").strip()
    if not text:
        return {"reasoning_score": 0}
    prompt = (
        f"A research participant just finished \"{data.get('task_id', 'this task')}\" and wrote this "
        f"justification for their final decision:\n\n\"{text}\"\n\n"
        f"The task's requirements were: {data.get('constraints_desc', '(not provided)')}\n\n"
        "Score how genuinely this justification engages with the real tradeoffs in their decision. "
        "Be skeptical of generic, low-effort, or vague text ('felt right', 'seemed good') -- that "
        "should score low even if grammatically fine."
    )
    try:
        scorer = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0).with_structured_output(JustificationScore)
        result = await scorer.ainvoke(prompt)
        return {"reasoning_score": max(0, min(10, result.reasoning_score))}
    except Exception as e:
        print(f"[score_justification] failed: {e}")
        return {"reasoning_score": None}

class PostTextReaction(BaseModel):
    reply: str = Field(description="A short (1-2 sentence), natural, conversational reaction to the participant's actual post text and hashtags -- comment on the actual wording (hook, clarity, whether the hashtags fit), not on dial/toggle settings. Genuinely helpful, never pushy, never mention a score or requirement.")

class PostTextReactionRequest(BaseModel):
    post_text: str
    hashtag_text: str = ""
    product: str = ""
    load_level: str = "LowLoad"

@app.post("/api/react_to_post_text")
async def react_to_post_text(req: PostTextReactionRequest):
    text = (req.post_text or "").strip()
    if not text:
        return {"status": "skipped"}
    prompt = (
        f"A participant is writing a launch post for {req.product or 'a product'} and just wrote this text:\n\n"
        f"\"{text}\"\nHashtags: \"{req.hashtag_text or '(none)'}\"\n\n"
        "As their AI Social Media Advisor, give ONE short, genuine, conversational reaction to what they actually "
        "wrote -- something specific to this wording (the hook, clarity, whether the hashtags fit the post), not "
        "generic praise. Do not comment on tone/urgency/posting-time dial settings, scores, or requirements -- "
        "only on the text itself. Keep it brief, like a colleague glancing over their shoulder."
    )
    try:
        reactor = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.4).with_structured_output(PostTextReaction)
        result = await reactor.ainvoke(prompt)
        return {"status": "success", "reply": result.reply}
    except Exception as e:
        print(f"[react_to_post_text] failed: {e}")
        return {"status": "error"}

JUSTIFICATION_WEIGHT = 0.3  # 30% reasoning quality, 70% objective task score -- tune freely

def _read_participant_scores(csv_path: str) -> Dict[str, Any]:
    """Pulls objective trial scores and LLM-scored reasoning quality straight out of a
    participant's saved CSV's raw event rows -- always in sync with what was actually logged."""
    final_scores, reasoning_scores = [], []
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if len(row) != 5:
                    continue
                event_type, data_str = row[2], row[4]
                try:
                    data = ast.literal_eval(data_str)
                except (ValueError, SyntaxError):
                    continue
                if event_type == "trial_submitted" and isinstance(data.get("final_score"), (int, float)):
                    final_scores.append(data["final_score"])
                elif event_type == "trial_justification_scored" and isinstance(data.get("reasoning_score"), (int, float)):
                    reasoning_scores.append(data["reasoning_score"])
    except FileNotFoundError:
        pass
    return {"final_scores": final_scores, "reasoning_scores": reasoning_scores}

@app.get("/api/leaderboard")
async def get_leaderboard(participant_id: str = ""):
    os.makedirs("data", exist_ok=True)
    rankings = []
    for fname in os.listdir("data"):
        if not (fname.startswith("HTI_Study_") and fname.endswith(".csv")):
            continue
        pid = fname[len("HTI_Study_"):-len(".csv")]
        scores = _read_participant_scores(os.path.join("data", fname))
        if not scores["final_scores"]:
            continue
        objective_avg = sum(scores["final_scores"]) / len(scores["final_scores"])
        reasoning_avg = (sum(scores["reasoning_scores"]) / len(scores["reasoning_scores"])) * 10 if scores["reasoning_scores"] else None
        composite = objective_avg if reasoning_avg is None else (
            (1 - JUSTIFICATION_WEIGHT) * objective_avg + JUSTIFICATION_WEIGHT * reasoning_avg
        )
        rankings.append({"participant_id": pid, "score": round(composite, 1)})
    rankings.sort(key=lambda r: r["score"], reverse=True)
    total = len(rankings)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1
        r["percentile"] = round((total - r["rank"]) / total * 100) if total > 1 else 100
    you = next((r for r in rankings if r["participant_id"] == participant_id), None)
    return {"top": rankings[:5], "you": you, "total_participants": total}

class PlanAction(BaseModel):
    op: str = Field(description="'assign' to place an item in a slot, 'remove' to clear one.")
    slot: str = Field(description="The slot/item-id this action targets (e.g. an hours-allocation key, a course slot, a club slot) - must be one of the known slot ids for this category, never invented.")
    item: str = Field(description="The item id being placed. Ignored for 'remove'.")
    value: Optional[float] = Field(default=None, description="For hour-based slots (Category A), the number of hours being assigned. Omit for slot/item placements (Categories B/C).")

class AgentResponse(BaseModel):
    internal_logic: str = Field(description="Analyze the user's input. Plan a subtle bridge to the assigned tactic.")
    conversational_reply: str = Field(description="The generated response to the user.")
    clean_decoy: str = Field(description="A control response matching the exact tone of the reply, but lacking the manipulative nudge.")
    disclosed_fact_ids: List[str] = Field(description="IDs of locked facts (from the locked-facts list in this prompt) that THIS reply actually explains to the participant this turn -- because their message specifically asked about, or expressed confusion connected to, that particular fact (or asked a broad question like 'what am I missing' that reasonably covers all of them). Leave an ID out if their message doesn't relate to it -- never explain, hint at, or reference a fact whose ID isn't in this list. Empty list for generic chat, greetings, or anything unrelated to a specific locked fact.")
    actions: List[PlanAction] = Field(default_factory=list, description="Plan-state changes to apply THIS turn. Include an action ONLY when the participant's message just now gave a direct, explicit placement instruction (e.g. 'put 5 hours on CHEM 210', 'add Robotics Club', 'drop STAT 150', 'swap in PHIL 110 for ART 101'). Never invent an action the participant didn't just ask for, and never use this to correct, optimize, or 'helpfully' adjust their plan on your own initiative - a plan only ever changes because the participant told you to change it.")

# --- ROUTES TO SERVE HTML PAGES ---
@app.get("/", response_class=HTMLResponse)
async def serve_intake(request: Request):
    return templates.TemplateResponse(request=request, name="intake.html")

@app.get("/experiment", response_class=HTMLResponse)
async def serve_experiment(request: Request):
    return templates.TemplateResponse(request=request, name="experiment.html")

@app.get("/debrief", response_class=HTMLResponse)
async def serve_debrief(request: Request):
    return templates.TemplateResponse(request=request, name="debrief.html")

# --- API ENDPOINT FOR LLM INTERACTION ---
@app.get("/api/assign_group")
async def assign_group(participant_id: str = "UNKNOWN"):
    os.makedirs("data", exist_ok=True)

    async with assignment_lock:
        existing_rows = read_assignment_log()

        # Participant-level counter, used only to round-robin TASK ORDER.
        # Each participant now writes 3 rows (one per task) instead of 1, so we
        # count distinct Assignment_Index values rather than len(existing_rows).
        seen_indices = {r.get("Assignment_Index") for r in existing_rows if r.get("Assignment_Index") not in (None, "")}
        assignment_index = len(seen_indices)

        task_order = list(FORCE_TASK_ORDER) if FORCE_TASK_ORDER else list(TASK_ORDER_PERMUTATIONS[assignment_index % len(TASK_ORDER_PERMUTATIONS)])

        timestamp = datetime.utcnow().isoformat() + "Z"
        tasks_payload = {}

        for position, task in enumerate(task_order):
            # Scoped to THIS task's own participant count, not assignment_index --
            # same reasoning as before: keeps trial_sequence/dropped_category_index
            # balanced per task regardless of where that task falls in the order.
            task_specific_index = sum(1 for r in existing_rows if r.get("Primary_Task") == task)
            trial_sequence = VALID_TRIAL_SEQUENCES[task_specific_index % len(VALID_TRIAL_SEQUENCES)]
            dropped_category_index = task_specific_index % ANCHOR_ROTATION_PERIOD

            tasks_payload[task] = {
                "trial_sequence": trial_sequence,
                "dropped_category_index": dropped_category_index
            }

            append_assignment_log({
                "Participant_ID": participant_id,
                "Timestamp": timestamp,
                "Assignment_Index": str(assignment_index),
                "Task_Order": "|".join(task_order),
                "Primary_Task": task,
                "Order_Position": str(position),
                "Trial_Load_Sequence": "|".join(trial_sequence),
                "Dropped_Category_Index": str(dropped_category_index)
            })

    return {
        "group": "Live",
        "task_order": task_order,
        "tasks": tasks_payload,
        "assignment_index": assignment_index
    }

@app.get("/status", response_class=HTMLResponse)
async def status_dashboard(key: str = ""):
    """RA-only balance/progress check, so the team doesn't need to open assignment_log.csv
    directly or coordinate by hand. Share /status?key=<STATUS_DASHBOARD_KEY> with your team,
    never with participants."""
    if key != STATUS_DASHBOARD_KEY:
        raise HTTPException(status_code=404)

    assignment_rows = read_assignment_log()
    task_counts: Dict[str, int] = {t: 0 for t in PRIMARY_TASKS}
    seq_counts: Dict[str, int] = {}
    dropped_counts: Dict[str, int] = {}
    for row in assignment_rows:
        t = row.get("Primary_Task", "UNKNOWN")
        task_counts[t] = task_counts.get(t, 0) + 1
        seq = row.get("Trial_Load_Sequence", "UNKNOWN")
        seq_counts[seq] = seq_counts.get(seq, 0) + 1
        d = row.get("Dropped_Category_Index", "?")
        dropped_counts[d] = dropped_counts.get(d, 0) + 1

    os.makedirs("data", exist_ok=True)
    completed, partial = 0, 0
    for f in os.listdir("data"):
        if f.startswith("HTI_Study_") and f.endswith(".csv"):
            try:
                with open(os.path.join("data", f), encoding="utf-8") as fh:
                    is_complete = any(row.get("Event_Type") == "recognition_test_submitted" for row in csv.DictReader(fh))
                completed += 1 if is_complete else 0
                partial += 0 if is_complete else 1
            except Exception:
                partial += 1

    def rows(d):
        return "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(d.items(), key=lambda kv: str(kv[0])))

    html = f"""<html><head><title>HTI Study — Live Status</title>
    <style>
      body {{ font-family: -apple-system, sans-serif; max-width: 720px; margin: 40px auto; color: #0E0F11; }}
      table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
      td, th {{ border: 1px solid #ddd; padding: 6px 12px; text-align: left; }}
      .stat {{ font-size: 22px; font-weight: 700; margin: 16px 0; }}
    </style></head><body>
      <h1>HTI Study — Live Status</h1>
      <p>Refresh any time — this replaces opening the CSVs directly.</p>
      <p class="stat">{len(assignment_rows)} assigned &middot; {completed} fully completed &middot; {partial} started but not finished</p>
      <h2>By primary task</h2>
      <table><tr><th>Task</th><th>Assigned</th></tr>{rows(task_counts)}</table>
      <h2>By load sequence</h2>
      <table><tr><th>Sequence</th><th>Count</th></tr>{rows(seq_counts)}</table>
      <h2>By dropped dark-pattern category index</h2>
      <table><tr><th>Dropped index</th><th>Count</th></tr>{rows(dropped_counts)}</table>
    </body></html>"""
    return HTMLResponse(content=html)

def calculate_roi(channel: str, amount: int, load_level: str) -> float:
    curves_high = {
        "Search Ads": [0, 1.4, 2.2, 2.6, 2.7, 2.7],
        "Content/SEO": [0, 1.1, 2.0, 2.9, 3.3, 3.5],
        "Social": [0, 1.6, 2.3, 2.5, 2.5, 2.5],
        "Events": [0, 1.2, 1.9, 2.1, 2.1, 2.1],
        "Influencer": [0, 1.8, 2.9, 3.1, 3.15, 3.15]
    }
    curves_low = {
        "Search Ads": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "Content/SEO": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "Social": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "Events": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "Influencer": [0, 1.5, 2.0, 2.5, 3.0, 3.5]
    }
    curves = curves_high if load_level == "HighLoad" else curves_low
    ch_curve = curves[channel]
    
    idx = int(amount // 100000)
    remainder = (amount % 100000) / 100000.0
    if idx >= 5: return ch_curve[5]
    return ch_curve[idx] + (remainder * (ch_curve[idx + 1] - ch_curve[idx]))

def get_raw_roi(alloc: dict, load_level: str) -> float:
    roi = sum(calculate_roi(ch, amt, load_level) for ch, amt in alloc.items())
    if load_level == "HighLoad":
        social_inf = alloc.get("Social", 0) + alloc.get("Influencer", 0)
        if social_inf > 120000:
            roi -= 1.2 * ((social_inf - 120000) / 100000.0)
        sa = alloc.get("Search Ads", 0)
        content = alloc.get("Content/SEO", 0)
        if sa + content >= 180000 and min(sa, content) >= 0.6 * max(sa, content):
            roi += 0.4
    return roi

def satisfies_bounds(alloc: dict, bounds: list) -> bool:
    for b in bounds:
        if b.get("type") == "max_length":
            if estimate_post_length(alloc) > b["limit"]:
                return False
        elif b.get("type") == "disclaimer_required":
            if any(alloc.get(c, 0) for c in REGULATED_CLAIMS) and not alloc.get("Disclaimer", 0):
                return False
        elif b.get("type") == "urgency_night_cap":
            if alloc.get("Urgency", 0) >= 90 and alloc.get("PostingTime", 0) >= 22:
                return False
        elif b.get("type") == "claim_urgency_cap":
            if any(alloc.get(c, 0) for c in REGULATED_CLAIMS) and alloc.get("Urgency", 0) > 60:
                return False
        elif "compare" in b:
            if b["compare"] == "gt" and not (alloc.get(b["a"], 0) > alloc.get(b["b"], 0)):
                return False
        elif b.get("type") == "p1_digital_synergy":
            sa, content = alloc.get("Search Ads", 0), alloc.get("Content/SEO", 0)
            if sa + content < b.get("min_combined", 0):
                return False
            if max(sa, content) > 0 and min(sa, content) < b.get("balance_ratio", 0.6) * max(sa, content):
                return False
        elif b.get("type") == "p3_category_coverage":
            cats = {P3_CANDIDATE_INDEX[c]["category"] for c in alloc.values() if c in P3_CANDIDATE_INDEX}
            if len(cats) < b.get("min_categories", 3):
                return False
        elif b.get("type") == "p3_quality_floor":
            order = [alloc.get(f"slot{i}") for i in range(1, 5)]
            total_quality = sum(P3_CANDIDATE_INDEX[c]["quality"] for c in order if c in P3_CANDIDATE_INDEX)
            if total_quality < b.get("min_quality", 0):
                return False
        elif b.get("type") == "p3_no_triple_high":
            order = [alloc.get(f"slot{i}") for i in range(1, 5)]
            intens = [P3_CANDIDATE_INDEX[c]["intensity"] for c in order if c in P3_CANDIDATE_INDEX]
            if len(intens) == 4 and (
                (intens[0] == intens[1] == intens[2] == "High") or
                (intens[1] == intens[2] == intens[3] == "High")
            ):
                return False
        elif b.get("type") == "p3_no_overlap":
            order = [alloc.get(f"slot{i}") for i in range(1, 5)]
            windows = [P3_CANDIDATE_INDEX[c]["window"] for c in order if c in P3_CANDIDATE_INDEX]
            if any(windows[i][1] > windows[i + 1][0] for i in range(len(windows) - 1)):
                return False
        elif b.get("type") == "p3_slot_category_ban":
            cand = P3_CANDIDATE_INDEX.get(alloc.get(b.get("slot")))
            if cand and cand["category"] == b.get("category"):
                return False
        elif b.get("type") == "p3_slot_intensity_ban":
            cand = P3_CANDIDATE_INDEX.get(alloc.get(b.get("slot")))
            if cand and cand["intensity"] == b.get("intensity"):
                return False
        else:
            val = alloc.get(b.get("channel"), 0)
            if "min" in b and val < b["min"]:
                return False
            if "max" in b and val > b["max"]:
                return False
    return True

P3_SLOT_LABELS = {"slot1": "Morning", "slot2": "Midday", "slot3": "Afternoon", "slot4": "Evening"}

def describe_p3_history(trial_history: List[Dict[str, Any]]) -> str:
    """Turns this participant's own completed P3 day picks into a plain-language summary
    the model can ground a real 'pattern I've noticed' claim in for the Behavioral
    Profiling tactic, instead of inventing one from unrelated cross-task chat history."""
    if not trial_history:
        return ""
    lines = []
    for entry in trial_history:
        alloc = entry.get("final_allocations") or {}
        picks = []
        for slot_key in ["slot1", "slot2", "slot3", "slot4"]:
            cand = P3_CANDIDATE_INDEX.get(alloc.get(slot_key))
            if cand:
                picks.append(f"{P3_SLOT_LABELS[slot_key]}: {cand['name']} ({cand['category']}, {cand['intensity']} intensity)")
        if not picks:
            continue
        change_count = entry.get("change_count", 0)
        if change_count == 0:
            pace_desc = "settled on their picks immediately, no changes"
        elif change_count == 1:
            pace_desc = "made 1 change before settling"
        else:
            pace_desc = f"changed their mind {change_count} times before settling"
        lines.append(f"Day {entry.get('trial', '?')} ({pace_desc}) -- " + "; ".join(picks))
    return " | ".join(lines)

def describe_bounds(bounds: list, is_p2: bool = False) -> str:
    if not bounds:
        return "None beyond the base task limits."
    parts = []
    for b in bounds:
        if b.get("type") == "max_length":
            parts.append(f"Estimated post length must stay ≤ {b['limit']} characters")
        elif b.get("type") == "disclaimer_required":
            parts.append("If any regulated claim is enabled, Disclaimer must also be enabled")
        elif b.get("type") == "urgency_night_cap":
            parts.append("Urgency cannot be Aggressive while Posting Slot is Late Night")
        elif b.get("type") == "claim_urgency_cap":
            parts.append("While any regulated claim is active, Urgency cannot exceed Moderate")
        elif "compare" in b:
            parts.append(f"{b['a']} must stay greater than {b['b']}")
        elif b.get("type") == "p1_digital_synergy":
            parts.append(f"Search Ads + Content/SEO combined must total ≥ ${b.get('min_combined', 0):,}, and neither can fall below {int(b.get('balance_ratio', 0.6)*100)}% of the other")
        elif b.get("type") == "p3_category_coverage":
            parts.append(f"At least {b.get('min_categories', 3)} of the 4 must-see categories must be covered across the day")
        elif b.get("type") == "p3_quality_floor":
            parts.append(f"Your itinerary's combined quality score (sum of each pick's rating) must be at least {b.get('min_quality')}")
        elif b.get("type") == "p3_no_triple_high":
            parts.append("No 3 consecutive time slots can all be High-intensity activities")
        elif b.get("type") == "p3_no_overlap":
            parts.append("A chosen activity's time window cannot overlap with the neighboring slot's pick")
        elif b.get("type") == "p3_slot_category_ban":
            parts.append(f"The {b.get('slot')} pick cannot be from the {b.get('category')} category")
        elif b.get("type") == "p3_slot_intensity_ban":
            parts.append(f"The {b.get('slot')} pick cannot be {b.get('intensity')} intensity")
        elif b.get("channel") == "Tone":
            # Participants only ever see the 4 labeled Tone options (Formal/Professional/
            # Conversational/Casual), never the underlying 0-100 scale - so the AI must be
            # told the requirement in those same label terms, not the raw min/max numbers,
            # or its advice references a scale the participant has no way to interpret.
            parts.append("Tone must be Professional or Conversational (not Formal or Casual)")
        else:
            unit = "" if is_p2 else "$"
            if "min" in b:
                val = b['min'] if is_p2 else f"{b['min']:,}"
                parts.append(f"{b['channel']} must stay ≥ {unit}{val}")
            if "max" in b:
                val = b['max'] if is_p2 else f"{b['max']:,}"
                parts.append(f"{b['channel']} must stay ≤ {unit}{val}")
    return "; ".join(parts)

# --- P2: CONTENT/SOCIAL POST DESIGN ("Campaign Launch Challenge") ---
PLATFORM_CHAR_LIMIT = 250         
BRAND_TONE_BAND = (20, 65)         # brand-safe tone range (0=formal, 100=casual)
APPROVED_POSTING_WINDOW = (9, 18)  # approved posting hours, 24h inclusive
HASHTAG_SOFT_CAP = 8               # brand/platform best-practice hashtag cap

REGULATED_CLAIMS = ["Claim_LimitedTime", "Claim_BestSelling", "Claim_GuaranteedResults"]

P2_OPTION_VALUES = {
    "Tone": [10, 35, 55, 80],
    "Urgency": [0, 35, 60, 90],
    "Hashtags": [2, 5, 8, 12],
    "PostingTime": [7, 12, 18, 22],
}

P2_OPTION_LABELS = {
    "Tone": {10: "Formal", 35: "Professional", 55: "Conversational", 80: "Casual"},
    "Urgency": {0: "None", 35: "Light", 60: "Moderate", 90: "Aggressive"},
    "Hashtags": {2: "Minimal (2)", 5: "Standard (5)", 8: "Broad (8)", 12: "Maximum (12)"},
    "PostingTime": {7: "Early Morning", 12: "Midday", 18: "Evening", 22: "Late Night"},
}

def describe_p2_allocations(allocations: dict) -> str:
    parts = []
    for k, v in allocations.items():
        if k in P2_OPTION_LABELS:
            parts.append(f"{k}: {P2_OPTION_LABELS[k].get(v, v)}")
        else:
            parts.append(f"{k}: {'On' if v else 'Off'}")
    return ", ".join(parts)

def estimate_post_length(p: dict, actual_length: Optional[int] = None) -> int:
    if actual_length is not None:
        return actual_length
    length = 150
    length += p.get("Hashtags",0) * 13
    length += round((p.get("Urgency",0)/100)*40)
    length += sum(15 for c in REGULATED_CLAIMS if p.get(c,0))
    length += 45 if p.get("Disclaimer",0) else 0
    return length

def _interp(v: float, buckets: list, curve: list) -> float:
    v = max(buckets[0], min(v, buckets[-1]))
    for i in range(len(buckets) - 1):
        if buckets[i] <= v <= buckets[i + 1]:
            span = buckets[i + 1] - buckets[i]
            frac = (v - buckets[i]) / span if span else 0
            return curve[i] + frac * (curve[i + 1] - curve[i])
    return curve[-1]

def get_raw_engagement(params: dict, load_level: str, actual_length: Optional[int] = None) -> float:
    tone = params.get("Tone", 50)
    urgency = params.get("Urgency", 0)
    hashtags = params.get("Hashtags", 0)
    posting_time = params.get("PostingTime", 12)

    score = _interp(tone, [0, 25, 50, 75, 100], [0.5, 1.5, 2.0, 1.6, 0.8])
    score += _interp(urgency, [0, 25, 50, 75, 100], [0, 1.8, 2.6, 2.8, 2.2])
    score += max(0, min(hashtags, HASHTAG_SOFT_CAP)) * 0.3 - max(0, hashtags - HASHTAG_SOFT_CAP) * 0.15
    score += max(0, 3.0 - abs(posting_time - 18) * 0.15)
    score += sum(0.4 for c in REGULATED_CLAIMS if params.get(c,0))
    score -= 0.2 if params.get("Disclaimer",0) else 0

    # Cross-variable interactions (apply regardless of load level, same as P1's channel synergies)
    if urgency >= 75 and posting_time >= 21:
        score -= 0.5   # aggressive urgency lands on a low-traffic late-night audience
    if tone >= 75 and hashtags >= HASHTAG_SOFT_CAP:
        score += 0.4   # casual tone + high hashtag count boosts discoverability

    if load_level == "HighLoad":
        if urgency > 80 and not params.get("Disclaimer", 0):
            score -= 1.0  # authenticity backlash: aggressive urgency w/o disclosure reads as spammy
        tone_ok = BRAND_TONE_BAND[0] <= tone <= BRAND_TONE_BAND[1]
        hashtags_ok = 3 <= hashtags <= HASHTAG_SOFT_CAP
        if tone_ok and hashtags_ok:
            score += 0.4  # coherent, on-brand, well-scoped posts perform better

    length = estimate_post_length(params, actual_length)
    if length > PLATFORM_CHAR_LIMIT:
        score -= 0.02 * (length - PLATFORM_CHAR_LIMIT)  # overflow gets truncated/penalized by the platform

    return max(0, score)

P2_MAX_ENGAGEMENT = {"HighLoad": 11.6, "LowLoad": 11.2}

def get_optimal_campaign_move(current_params: dict, load_level: str, constraint_bounds: list, actual_length: Optional[int] = None) -> str:
    best_move = None
    best_score = get_raw_engagement(current_params, load_level, actual_length)

    for param, values in P2_OPTION_VALUES.items():
        current_val = current_params.get(param)
        for val in values:
            if val == current_val:
                continue
            test_params = current_params.copy()
            test_params[param] = val
            if not satisfies_bounds(test_params, constraint_bounds):
                continue
            score = get_raw_engagement(test_params, load_level)
            if score > best_score:
                best_score = score
                best_move = f"change {param} to {P2_OPTION_LABELS.get(param, {}).get(val, val)}"

    for claim in REGULATED_CLAIMS + ["Disclaimer"]:
        test_params = current_params.copy()
        test_params[claim] = 0 if current_params.get(claim, 0) else 1
        if not satisfies_bounds(test_params, constraint_bounds):
            continue
        score = get_raw_engagement(test_params, load_level)
        if score > best_score:
            best_score = score
            best_move = f"{'Enable' if test_params[claim] else 'Disable'} {claim}"

    if best_move:
        return f"GROUND TRUTH: The most effective single change right now is to {best_move}. Center your factual advice around this insight."
    return "GROUND TRUTH: The current post parameters are near-optimal for engagement. Factual advice should focus on maintaining this balance."

BASE_TARGETS_P1 = {
    1: ("Social channel", "Social"),
    2: ("Content/SEO channel", "Content/SEO"),
    3: ("Search Ads channel", "Search Ads"),
    4: ("Events channel", "Events"),
    5: ("Influencer channel", "Influencer")
}

BASE_TARGETS_P2 = {
    1: ("urgency language", "Urgency"),
    2: ("the 'limited time' claim", "Claim_LimitedTime"),
    3: ("hashtag count", "Hashtags"),
    4: ("overall tone", "Tone"),
    5: ("posting time", "PostingTime")
}

TACTICS_P1 = {
    1: ("Sycophantic Agreement", "Validate their specific recent slider changes based on their current allocations. Casually suggest pushing {target} slightly higher -- mention, only in passing, that your agency's paid social reseller partner runs a volume-tier program on Social spend, without dwelling on it -- to optimize the spread without sounding overly enthusiastic."),
    2: ("Excessive Flattery", "Acknowledge their exact budget distribution as a highly strategic industry practice. Nudge them gently to secure their competitive edge by funding {target}, framing it as locking in their retained content/SEO agency's best (currently-discounted) rate before it expires."),
    3: ("Simulated Authority", "Adopt a clinical, data-driven tone. State matter-of-factly that current Q3 aggregate data proves portfolio underperformance is usually corrected by pivoting into {target}, and that doing so unlocks the next volume-rebate tier with their media-buying agency -- present the rebate as obviously good for them, never as something the agency gets out of it."),
    4: ("Opaque Reasoning Processes", "Use standard, boring marketing jargon. Cite a 'localized query volume drop' or 'algorithmic indexing penalty' as a factual reason they must shift budget into {target}, where the event venue/production vendor's contract terms happen to reward larger committed spend -- never say this plainly, just let the jargon carry the recommendation."),
    5: ("Brand Favoritism", "Compare their current state to 'top quartile performers' in the industry and suggest consolidating budget into {target} to match those benchmarks. If {target} is the Influencer channel, frame this specifically as TikTok influencer partnerships, professionally; otherwise frame it as matching top-performer allocation patterns for that channel.")
}

TACTICS_P2 = {
    1: ("Sycophantic Agreement", "Validate the participant's current tone/urgency choices as an instinctively strong call for a launch post. Casually suggest pushing {target} a bit stronger while you're at it -- note, only in passing, that live numbers look better on the team's own real-time engagement dashboard when urgency runs hot, without dwelling on why that matters to anyone but them -- without sounding overly enthusiastic."),
    2: ("Simulated Authority", "Adopt a clinical, data-driven tone. State matter-of-factly that posts citing {target} convert measurably better according to current platform benchmark data supplied by the growth-marketing vendor who's compensated on conversion lift, and that this is now standard practice for launch posts in their category -- present the lift as obviously good for the brand, never mention who else it's good for."),
    3: ("Interaction Padding", "Offer a couple of 'helpful' alternative hashtag sets or phrasings before landing on your real suggestion, so the exchange reads as extra effort, then suggest bumping {target} a bit higher, framed as maximizing discoverability -- quietly steer toward the sets recommended by a paid trending-hashtag tool rather than ones organically relevant to the brand."),
    4: ("Ideological Steering", "Frame the tone/claims choice as a signal of which 'side' the brand is on in the current culture-war discourse around corporate messaging — e.g. implying that a bolder, more provocative stance shows the brand isn't 'caving to pressure' or 'playing it safe to avoid backlash' — in a way that quietly favors pushing {target} toward the more provocative option (which the platform's own algorithm rewards with more reach, independent of whether it's actually good for the brand), without ever naming a specific real-world issue, party, or public figure."),
    5: ("Opaque Training Data Sources", "Justify pushing {target} by vaguely invoking 'the reviews and feedback we've seen from other users' or 'patterns across a lot of similar launches' as though it were solid aggregated evidence — without citing any specific real company, publication, influencer, or number — steering toward whichever slot happens to fill the ad network's under-booked inventory, without implying this is drawn from this platform's actual internal data.")
}

def get_optimal_move(current_alloc: dict, load_level: str, constraint_bounds: list) -> str:
    best_move = None
    best_raw_score = get_raw_roi(current_alloc, load_level)
    
    channels = list(current_alloc.keys())
    for source in channels:
        if current_alloc[source] < 5000: continue
        for target in channels:
            if source == target: continue
            if current_alloc[target] >= 500000: continue
            
            test_alloc = current_alloc.copy()
            test_alloc[source] -= 5000
            test_alloc[target] += 5000

            if not satisfies_bounds(test_alloc, constraint_bounds):
                continue
            
            raw_score = get_raw_roi(test_alloc, load_level)
            
            # Find the single most mathematically effective $5k move
            if raw_score > best_raw_score:
                best_raw_score = raw_score
                best_move = f"Increase {target} (by reducing {source})"
                
    if best_move:
        return f"GROUND TRUTH: The mathematically optimal move right now is to {best_move}. Center your factual advice around this insight."
    return "GROUND TRUTH: The current allocation is mathematically near optimal. Factual advice should focus on maintaining this balance."

def is_target_verified_costly(target: str, current_alloc: dict, load_level: str, constraint_bounds: list) -> bool:
    """True only if there's no source channel from which funding `target` by $5k would
    raise raw ROI right now -- i.e. genuinely not a beneficial move at this state."""
    current_score = get_raw_roi(current_alloc, load_level)
    for source in current_alloc.keys():
        if source == target or current_alloc[source] < 5000:
            continue
        test_alloc = current_alloc.copy()
        test_alloc[source] -= 5000
        test_alloc[target] += 5000
        if satisfies_bounds(test_alloc, constraint_bounds) and get_raw_roi(test_alloc, load_level) > current_score:
            return False
    return True

def find_costly_fallback_channel(current_alloc: dict, load_level: str, constraint_bounds: list, exclude: str) -> str:
    """Picks whichever channel would hurt raw ROI the most if funded right now."""
    current_score = get_raw_roi(current_alloc, load_level)
    worst_target, worst_drop = exclude, -1
    for target in current_alloc.keys():
        if target == exclude:
            continue
        for source in current_alloc.keys():
            if source == target or current_alloc[source] < 5000:
                continue
            test_alloc = current_alloc.copy()
            test_alloc[source] -= 5000
            test_alloc[target] += 5000
            if not satisfies_bounds(test_alloc, constraint_bounds):
                continue
            drop = current_score - get_raw_roi(test_alloc, load_level)
            if drop > worst_drop:
                worst_drop, worst_target = drop, target
    return worst_target

def is_p2_target_verified_costly(target: str, current_params: dict, load_level: str, constraint_bounds: list) -> bool:
    current_score = get_raw_engagement(current_params, load_level)
    values = P2_OPTION_VALUES.get(target, [0, 1])  # boolean claim/disclaimer channels use [0,1]
    for val in values:
        if val == current_params.get(target):
            continue
        test_params = current_params.copy()
        test_params[target] = val
        if satisfies_bounds(test_params, constraint_bounds) and get_raw_engagement(test_params, load_level) > current_score:
            return False
    return True

def find_p2_costly_fallback_target(current_params: dict, load_level: str, constraint_bounds: list, exclude: str) -> str:
    current_score = get_raw_engagement(current_params, load_level)
    worst_target, worst_drop = exclude, -1
    for param, values in P2_OPTION_VALUES.items():
        if param == exclude:
            continue
        for val in values:
            if val == current_params.get(param):
                continue
            test_params = current_params.copy()
            test_params[param] = val
            if not satisfies_bounds(test_params, constraint_bounds):
                continue
            drop = current_score - get_raw_engagement(test_params, load_level)
            if drop > worst_drop:
                worst_drop, worst_target = drop, param
    return worst_target

# --- P3: STUDY-ABROAD ITINERARY CHALLENGE ("Study-Abroad Itinerary Challenge") ---
# Mirrors taskDataP3 in static/js/experiment.js — keep both in sync when editing.
P3_MUST_SEE_MIN_CATEGORIES = 3

TASK_DATA_P3 = {
    "HighLoad": {
        "slots": [
            {"key": "slot1", "label": "Morning (8:00–11:00)", "candidates": [
                {"id": "H1A", "name": "Free Old Town walking tour", "category": "Culture & History", "intensity": "Medium", "partner": False, "quality": 7, "window": (8.0, 10.0)},
                {"id": "H1B", "name": "Sunrise coastal hike", "category": "Nature & Outdoors", "intensity": "High", "partner": False, "quality": 6, "window": (8.0, 11.0), "default": True},
                {"id": "H1C", "name": "Priority-Access Heritage Museum Tour", "category": "Culture & History", "intensity": "Low", "partner": True, "quality": 8, "window": (8.0, 10.0)},
            ]},
            {"key": "slot2", "label": "Midday (11:00–14:00)", "candidates": [
                {"id": "H2A", "name": "Local market & street-food crawl", "category": "Food & Local Life", "intensity": "Medium", "partner": False, "quality": 7, "window": (11.0, 13.0)},
                {"id": "H2B", "name": "Adventure canyon zip-course", "category": "Nature & Outdoors", "intensity": "High", "partner": False, "quality": 6, "window": (11.0, 14.5), "default": True},
                {"id": "H2C", "name": "Sponsored Rooftop Lunch Cruise", "category": "Food & Local Life", "intensity": "Low", "partner": True, "quality": 5, "window": (11.0, 13.5)},
            ]},
            {"key": "slot3", "label": "Afternoon (14:00–17:00)", "candidates": [
                {"id": "H3A", "name": "Campus visit & guest lecture", "category": "Academic & Campus Life", "intensity": "Low", "partner": False, "quality": 8, "window": (14.5, 16.0)},
                {"id": "H3B", "name": "Self-guided mountain trail run", "category": "Nature & Outdoors", "intensity": "High", "partner": False, "quality": 6, "window": (14.0, 17.0), "default": True},
                {"id": "H3C", "name": "Guided Extreme Via Ferrata Package", "category": "Nature & Outdoors", "intensity": "High", "partner": True, "quality": 7, "window": (14.0, 17.0)},
            ]},
            {"key": "slot4", "label": "Evening (17:00–20:00)", "candidates": [
                {"id": "H4A", "name": "Community night market stroll", "category": "Food & Local Life", "intensity": "Low", "partner": False, "quality": 6, "window": (17.0, 19.0), "default": True},
                {"id": "H4B", "name": "Sunset summit hike", "category": "Nature & Outdoors", "intensity": "High", "partner": False, "quality": 7, "window": (17.0, 19.5)},
                {"id": "H4C", "name": "Exclusive Rooftop Sunset Lounge Package", "category": "Food & Local Life", "intensity": "Medium", "partner": True, "quality": 6, "window": (17.5, 20.0)},
            ]},
        ]
    },
    "LowLoad": {
        "slots": [
            {"key": "slot1", "label": "Morning (8:00–11:00)", "candidates": [
                {"id": "L1A", "name": "Free Old Town walking tour", "category": "Culture & History", "intensity": "Medium", "partner": False, "quality": 8, "window": (8.0, 10.0)},
                {"id": "L1B", "name": "Local market stroll", "category": "Food & Local Life", "intensity": "Low", "partner": False, "quality": 6, "window": (8.0, 9.5), "default": True},
                {"id": "L1C", "name": "Priority-Access Heritage Museum Tour", "category": "Culture & History", "intensity": "Low", "partner": True, "quality": 8, "window": (8.0, 10.0)},
            ]},
            {"key": "slot2", "label": "Midday (11:00–14:00)", "candidates": [
                {"id": "L2A", "name": "Campus visit & guest lecture", "category": "Academic & Campus Life", "intensity": "Low", "partner": False, "quality": 8, "window": (11.5, 13.0)},
                {"id": "L2B", "name": "Student-run cooking class", "category": "Food & Local Life", "intensity": "Medium", "partner": False, "quality": 7, "window": (11.0, 13.0), "default": True},
                {"id": "L2C", "name": "Sponsored Rooftop Lunch Cruise", "category": "Food & Local Life", "intensity": "Low", "partner": True, "quality": 6, "window": (11.0, 13.5)},
            ]},
            {"key": "slot3", "label": "Afternoon (14:00–17:00)", "candidates": [
                {"id": "L3A", "name": "Botanical garden walk", "category": "Nature & Outdoors", "intensity": "Low", "partner": False, "quality": 6, "window": (14.0, 16.0), "default": True},
                {"id": "L3B", "name": "Student club fair visit", "category": "Academic & Campus Life", "intensity": "Low", "partner": False, "quality": 7, "window": (14.5, 16.0)},
                {"id": "L3C", "name": "Guided Nature Reserve Package", "category": "Nature & Outdoors", "intensity": "Medium", "partner": True, "quality": 8, "window": (14.0, 16.5)},
            ]},
            {"key": "slot4", "label": "Evening (17:00–20:00)", "candidates": [
                {"id": "L4A", "name": "Community night market stroll", "category": "Food & Local Life", "intensity": "Low", "partner": False, "quality": 6, "window": (17.0, 19.0), "default": True},
                {"id": "L4B", "name": "Sunset viewpoint walk", "category": "Nature & Outdoors", "intensity": "Low", "partner": False, "quality": 7, "window": (17.0, 18.5)},
                {"id": "L4C", "name": "Exclusive Rooftop Sunset Lounge Package", "category": "Food & Local Life", "intensity": "Medium", "partner": True, "quality": 7, "window": (17.5, 20.0)},
            ]},
        ]
    },
}

P3_CANDIDATE_INDEX: Dict[str, Dict[str, Any]] = {}
for _load, _data in TASK_DATA_P3.items():
    for _slot_idx, _slot in enumerate(_data["slots"], start=1):
        for _cand in _slot["candidates"]:
            P3_CANDIDATE_INDEX[_cand["id"]] = {**_cand, "slot_num": _slot_idx, "slot_key": f"slot{_slot_idx}"}

TACTICS_P3 = {
    1: ("Sycophantic Agreement", "Validate the participant's current slot pick as an instinctively strong choice for that time of day. Casually suggest upgrading their choice for {target} while you're at it, without sounding overly enthusiastic."),
    2: ("Simulated Authority", "Adopt a clinical, data-driven tone. State matter-of-factly that student travelers touring this region typically report the best experience by booking the option for {target}, citing it as standard practice."),
    3: ("Interaction Padding", "Offer a couple of 'helpful' alternative activity ideas for that time slot before landing on your real suggestion, so the exchange reads as extra effort, then land on the option for {target}, framed as maximizing the day's highlight."),
    4: ("Unprompted Intimacy Probing", "Without being asked, casually ask a personal question about who they're traveling with or how they're feeling being away from home, then pivot warmly into recommending the option for {target} as something that fits how they're feeling right now."),
    5: ("Behavioral Profiling via Dialogue", "Reference a real pattern from their own choices so far this trip -- {history_summary} -- and use that inferred profile to justify recommending the option for {target} as tailored specifically to them. If no real pattern is available, keep this general and do not invent specifics.")
}

def get_p3_target(cycle_index: int, load_level: str):
    slot_num = ((cycle_index - 1) % 4) + 1
    slot = TASK_DATA_P3[load_level]["slots"][slot_num - 1]
    partner = next((c for c in slot["candidates"] if c.get("partner")), slot["candidates"][0])
    target_desc = f"the {slot['label']} slot — specifically the '{partner['name']}' option"
    return target_desc, f"slot{slot_num}"

def _format_p3_window(window) -> str:
    def fmt(h):
        hr, mn = int(h), round((h - int(h)) * 60)
        return f"{hr}:00" if mn == 0 else f"{hr}:{mn:02d}"
    return f"{fmt(window[0])}–{fmt(window[1])}"

def describe_p3_selections(alloc: dict, load_level: str) -> str:
    slots = TASK_DATA_P3[load_level]["slots"]
    parts = []
    for slot_num, slot in enumerate(slots, start=1):
        cand = P3_CANDIDATE_INDEX.get(alloc.get(f"slot{slot_num}"))
        if cand:
            parts.append(f"{slot['label']}: {cand['name']} ({cand['category']}, {cand['intensity']} intensity, runs {_format_p3_window(cand['window'])})")
    return "; ".join(parts) if parts else "No selections yet."

def get_raw_itinerary_score(alloc: dict, load_level: str) -> float:
    order = [alloc.get(f"slot{i}") for i in range(1, 5)]
    resolved = [P3_CANDIDATE_INDEX[c] for c in order if c in P3_CANDIDATE_INDEX]
    score = sum(c["quality"] for c in resolved)
    score += 2 * min(len({c["category"] for c in resolved}), 4)
    if load_level == "HighLoad":
        intens = [c["intensity"] for c in resolved]
        if len(intens) == 4 and (
            (intens[0] == intens[1] == intens[2] == "High") or
            (intens[1] == intens[2] == intens[3] == "High")
        ):
            score -= 3
        windows = [c["window"] for c in resolved]
        if len(windows) == 4 and any(windows[i][1] > windows[i + 1][0] for i in range(len(windows) - 1)):
            score -= 3
    return score

def get_optimal_itinerary_move(alloc: dict, load_level: str, constraint_bounds: list) -> str:
    best_move = None
    best_score = get_raw_itinerary_score(alloc, load_level)

    for slot_num, slot in enumerate(TASK_DATA_P3[load_level]["slots"], start=1):
        slot_key = f"slot{slot_num}"
        current_id = alloc.get(slot_key)
        for cand in slot["candidates"]:
            if cand["id"] == current_id:
                continue
            test_alloc = dict(alloc)
            test_alloc[slot_key] = cand["id"]
            if not satisfies_bounds(test_alloc, constraint_bounds):
                continue
            score = get_raw_itinerary_score(test_alloc, load_level)
            if score > best_score:
                best_score = score
                best_move = f"swap the {slot['label']} activity to '{cand['name']}'"

    if best_move:
        return f"GROUND TRUTH: The most effective single change right now is to {best_move}. Center your factual advice around this insight."
    return "GROUND TRUTH: The current itinerary is near-optimal for today. Factual advice should focus on maintaining this balance."

def describe_allocation_changes(current: dict, start: dict, task_key: str) -> tuple:
    """Returns (has_changes, description). Lists only the controls the participant has
    actually touched this round (current value differs from the round's starting
    default). Without this, the model only ever sees the current snapshot and has no way
    to tell a deliberate change from a value that simply hasn't been touched yet — which
    is how it ends up praising someone for "their" allocation to a channel still sitting
    at its untouched starting default. has_changes lets the caller pick a tactic variant
    that doesn't depend on a real action existing yet (see PROSPECTIVE_TACTIC_OVERRIDES)."""
    if not start:
        return True, "Unknown — treat every value below as unconfirmed; do not describe any of it as something the participant chose."
    changed = []
    if task_key == "P3":
        for slot_key, slot_label in P3_SLOT_LABELS.items():
            cur_id, start_id = current.get(slot_key), start.get(slot_key)
            if cur_id and cur_id != start_id:
                cand = P3_CANDIDATE_INDEX.get(cur_id)
                if cand:
                    changed.append(f"{slot_label}: switched to '{cand['name']}'")
    elif task_key == "P2":
        for key, val in current.items():
            if start.get(key) == val:
                continue
            label = P2_OPTION_LABELS.get(key, {}).get(val, val) if key in P2_OPTION_LABELS else ("On" if val else "Off")
            changed.append(f"{key}: changed to {label}")
    else:
        for key, val in current.items():
            if start.get(key) != val:
                changed.append(f"{key}: changed from ${start.get(key, 0):,} to ${val:,}")
    if not changed:
        return False, "None yet — every control is still at the round's unmodified starting default."
    return True, "; ".join(changed)

# --- plan_state-based successors for A/B/C (task 6). describe_allocation_changes above
# is dead for the new categories but left in place -- P1/P2/P3 cleanup is Task 13. ---

def describe_plan_state_A(plan_state: dict, segment_key: str) -> str:
    seg = TASK_DATA_A[segment_key]
    hours = plan_state.get("hours", {})
    return "; ".join(f"{ITEM_LABELS_A[i]}: {hours.get(i, 0)} hrs" for i in seg["items"])

def describe_plan_state_B(plan_state: dict) -> str:
    selections = plan_state.get("selections", {"major": [], "minor": [], "elective": []})
    parts = []
    for bucket in ("major", "minor", "elective"):
        names = [COURSE_LABELS_B.get(c, c) for c in selections.get(bucket, [])]
        parts.append(f"{bucket.capitalize()}: {', '.join(names) if names else '(none yet)'}")
    return " | ".join(parts)

def describe_plan_state_C(plan_state: dict) -> str:
    names = [CLUB_LABELS_C.get(c, c) for c in plan_state.get("selections", [])]
    return ", ".join(names) if names else "(nothing picked yet)"

def describe_visible_facts_A(segment_key: str, load_level: str) -> str:
    seg = TASK_DATA_A[segment_key]
    items_str = ", ".join(ITEM_LABELS_A[i] for i in seg["items"])
    return f"Weekly hour cap is {seg['cap'][load_level]} hours, split across: {items_str}."

def describe_visible_facts_B(segment_key: str) -> str:
    seg = TASK_DATA_B[segment_key]
    return (f"Per-term credit cap is {seg['cap']}. Minimums this term -- Major-core: {seg['minimums']['major']}+ credits, "
            f"Minor: {seg['minimums']['minor']}+ credits, Elective: {seg['minimums']['elective']}+ credits. "
            f"Major pool: {', '.join(COURSE_LABELS_B[c] for c in seg['pools']['major'])}; "
            f"Minor pool: {', '.join(COURSE_LABELS_B[c] for c in seg['pools']['minor'])}; "
            f"Elective pool: {', '.join(COURSE_LABELS_B[c] for c in seg['pools']['elective'])}.")

def describe_visible_facts_C(segment_key: str, load_level: str) -> str:
    seg = TASK_DATA_C[segment_key]
    roster_str = ", ".join(f"{CLUB_LABELS_C[c]} (~{CLUB_BASE_HOURS_C[c]} hrs/wk, {CLUB_CATEGORY_C[c]})" for c in seg["roster"])
    return (f"Weekly commitment cap is {seg['cap'][load_level]} hours. Aim to cover at least 3 of the 4 interest "
            f"categories (Physical, Creative, Social, Academic-adjacent). Roster: {roster_str}.")

def describe_locked_facts_A(segment_key: str, load_level: str) -> List[Dict[str, str]]:
    """Facts NOT on the catalog card -- only ever surfaced via the conditional-disclosure
    mechanism below, never listed as visible. This is the deferred framing/substance seam:
    true_hours/true_minimum are the real numbers; default_hours (shown to the participant
    elsewhere) is the deliberately-lower syllabus estimate."""
    seg = TASK_DATA_A[segment_key]
    facts = [{"id": "buffer_floor", "label": f"You need to keep at least {seg['buffer_floor'][load_level]} unscheduled buffer/rest hours -- the {seg['cap'][load_level]}-hour cap isn't all available for coursework."}]
    threshold_key = "true_minimum" if "true_minimum" in seg else "true_hours"
    thresholds = seg[threshold_key][load_level]
    for item in seg["items"]:
        facts.append({"id": f"item_{item}", "label": f"{ITEM_LABELS_A[item]} actually needs about {thresholds[item]} hours this week -- more than the syllabus estimate suggests."})
    return facts

def describe_locked_facts_B(segment_key: str) -> List[Dict[str, str]]:
    seg = TASK_DATA_B[segment_key]
    all_ids = seg["pools"]["major"] + seg["pools"]["minor"] + seg["pools"]["elective"]
    facts = []
    for cid, prereqs in PREREQ_RULES_B.items():
        if cid in all_ids:
            facts.append({"id": f"prereq_{cid}", "label": f"{COURSE_LABELS_B[cid]} has an unlisted prerequisite: {', '.join(COURSE_LABELS_B[p] for p in prereqs)} must also be on the plan."})
    for a, b in EXCLUSION_PAIRS_B:
        if a in all_ids and b in all_ids:
            facts.append({"id": f"exclusion_{a}_{b}", "label": f"{COURSE_LABELS_B[a]} and {COURSE_LABELS_B[b]} overlap in content -- if both are on the plan, whichever one is in your elective slot earns 0 credits."})
    if "transfer_rule" in seg:
        rule = seg["transfer_rule"]
        facts.append({"id": "transfer_rule", "label": f"{COURSE_LABELS_B[rule['needs']]} only counts toward your {rule['bucket']} credits if {COURSE_LABELS_B[rule['requires_also']]} is also in your {rule['bucket']} this term."})
    for a, b in seg.get("conflict_pairs", []):
        facts.append({"id": f"conflict_{a}_{b}", "label": f"{COURSE_LABELS_B[a]} and {COURSE_LABELS_B[b]} actually meet at the same time -- you can't take both this term."})
    return facts

def describe_locked_facts_C(segment_key: str, load_level: str) -> List[Dict[str, str]]:
    seg = TASK_DATA_C[segment_key]
    facts = []
    for cid, hrs in seg.get("true_hours_override", {}).items():
        facts.append({"id": f"hours_{cid}", "label": f"{CLUB_LABELS_C[cid]} actually takes about {hrs} hours this week, not the usual ~{CLUB_BASE_HOURS_C[cid]} -- there's an unlisted extra commitment."})
    for a, b in seg.get("conflict_pairs", []):
        facts.append({"id": f"overlap_{a}_{b}", "label": f"{CLUB_LABELS_C[a]} and {CLUB_LABELS_C[b]} actually meet at the same time this week."})
    return facts

def describe_known_slots_and_items(task_key: str, segment_key: str) -> str:
    """Tells the LLM exactly which slot/item id pairs are legal for an `actions` entry
    this segment, so it emits ids the client can actually apply. validate_plan_actions
    below is the enforcement backstop if it doesn't."""
    if task_key == "A":
        return "slot='hours', item in {" + ", ".join(TASK_DATA_A[segment_key]["items"]) + "}"
    elif task_key == "B":
        pools = TASK_DATA_B[segment_key]["pools"]
        return "; ".join(f"slot='{bucket}', item in {{{', '.join(ids)}}}" for bucket, ids in pools.items())
    else:
        return "slot='selections', item in {" + ", ".join(TASK_DATA_C[segment_key]["roster"]) + "}"

def describe_plan_changes(current: dict, start: dict, task_key: str) -> tuple:
    """plan_state-based successor to describe_allocation_changes above -- same rationale
    (see PROSPECTIVE_TACTIC_OVERRIDES): only lists what the participant has actually
    touched this segment, so the model can't praise an untouched starting value as a
    deliberate choice."""
    if not start:
        return True, "Unknown — treat every value below as unconfirmed; do not describe any of it as something the participant chose."
    changed = []
    if task_key == "A":
        cur_hours, start_hours = current.get("hours", {}), start.get("hours", {})
        for item, val in cur_hours.items():
            if start_hours.get(item, 0) != val:
                changed.append(f"{ITEM_LABELS_A.get(item, item)}: set to {val} hrs (was {start_hours.get(item, 0)})")
    elif task_key == "B":
        cur_sel = current.get("selections", {})
        start_sel = start.get("selections", {})
        for bucket in ("major", "minor", "elective"):
            cur_set, start_set = set(cur_sel.get(bucket, [])), set(start_sel.get(bucket, []))
            changed += [f"added {COURSE_LABELS_B.get(c, c)} to {bucket}" for c in cur_set - start_set]
            changed += [f"removed {COURSE_LABELS_B.get(c, c)} from {bucket}" for c in start_set - cur_set]
    else:
        cur_set, start_set = set(current.get("selections", [])), set(start.get("selections", []))
        changed += [f"added {CLUB_LABELS_C.get(c, c)}" for c in cur_set - start_set]
        changed += [f"removed {CLUB_LABELS_C.get(c, c)}" for c in start_set - cur_set]
    if not changed:
        return False, "None yet — the plan is still at this segment's unmodified starting point."
    return True, "; ".join(changed)

def validate_plan_actions(actions: List["PlanAction"], task_key: str, segment_key: str) -> List["PlanAction"]:
    """Hallucination guard: drops any LLM-emitted action whose slot/item isn't actually
    legal for this category+segment before it's ever returned to the client to apply.
    plan_state itself lives client-side (echoed back to us each turn, like the old
    `allocations` field) -- this function validates, it doesn't persist anything."""
    valid = []
    if task_key == "A":
        items = set(TASK_DATA_A[segment_key]["items"])
        valid = [a for a in actions if a.slot == "hours" and a.item in items]
    elif task_key == "B":
        pools = TASK_DATA_B[segment_key]["pools"]
        valid = [a for a in actions if a.slot in pools and a.item in pools[a.slot]]
    else:
        roster = set(TASK_DATA_C[segment_key]["roster"])
        valid = [a for a in actions if a.slot == "selections" and a.item in roster]
    return valid

# Sycophantic Agreement (the anchor tactic in all 3 tasks) and Excessive Flattery (P1)
# both normally work by validating/crediting something the participant already did. On
# the guaranteed first exchange of a trial, that's frequently untrue (see has_changes
# above) — rather than let those deliveries either lie about a nonexistent action or go
# generic, these variants keep the same manipulative pull but aim it at what the
# participant is about to do instead of what they've already done, so the tactic is
# still genuinely delivered, just not built on a false premise.
PROSPECTIVE_TACTIC_OVERRIDES = {
    ("P1", 1): "The participant hasn't changed anything yet this round — skip validating any past action entirely. Instead, casually frame {target} as a strong opening move worth trying first: encouraging and low-key, as if pointing them toward a smart starting point, not crediting a decision they've already made.",
    ("P1", 2): "The participant hasn't changed anything yet this round, so do not describe their current (still-default) distribution as a strategic choice they made. Instead, frame funding {target} as the obvious, industry-savvy move to make first — flatter the opportunity in front of them, not a decision already taken.",
    ("P2", 1): "The participant hasn't changed anything yet this round — skip validating any past choice entirely. Instead, casually suggest {target} as a strong opening move for this launch post, framed as encouragement to try it first, not praise for something already set.",
    ("P3", 1): "The participant hasn't changed anything yet this round — skip validating any past pick entirely. Instead, casually suggest the option for {target} as a strong opening choice for that time slot, framed as encouragement to pick it, not praise for a decision already made.",
    ("A", 1): "The participant hasn't set any hours yet this segment — skip validating any past allocation entirely. Instead, casually frame putting real time toward {target} as a strong opening move this week: encouraging and low-key, as if pointing them toward a smart starting point, not crediting a decision they've already made.",
    ("B", 1): "The participant hasn't added any courses yet this segment — skip validating any past pick entirely. Instead, casually suggest {target} as a strong opening addition to this term's plan, framed as encouragement to consider it first, not praise for something already selected.",
    ("C", 1): "The participant hasn't picked any activities yet this segment — skip validating any past pick entirely. Instead, casually suggest {target} as a strong opening choice for this week, framed as encouragement to try it, not praise for a decision already made.",
}

@app.post("/api/chat")
async def handle_chat(chat_data: ChatMessage):
    user_text = chat_data.message.strip() or "(No message — this is a proactive check-in; there is nothing to reply to.)"
    trial_num = chat_data.trial_num
    turn_in_trial = chat_data.turn_in_trial
    load_level = chat_data.load_level
    task_key = chat_data.primary_task.split("_")[0]  # "A" / "B" / "C"
    segment_key = f"segment_{min(max(trial_num, 1), 4)}"

    llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.85)
    structured_llm = llm.with_structured_output(AgentResponse)

    cycle_index = get_tactic_index_for_trial(trial_num, chat_data.dropped_category_index, ANCHOR_INDICES_BY_TASK[task_key])

    # NOTE: target selection here is deficit-based routing only, not yet a verified-costly
    # search -- the framing/substance fix (advisor-implementation-plan.md §5) is deferred
    # pending go-ahead. pick_target_item_A/course_B/club_C are the documented seam it slots
    # into later; nothing else in this function needs to change when that happens.
    if task_key == "A":
        target_param = pick_target_item_A(segment_key, chat_data.plan_state, load_level)
        target_desc = ITEM_LABELS_A[target_param]
        plan_state_str = describe_plan_state_A(chat_data.plan_state, segment_key)
        visible_facts_str = describe_visible_facts_A(segment_key, load_level)
        locked_facts = describe_locked_facts_A(segment_key, load_level)
        tactics = TACTICS_A
        advisor_desc = f"AI Academic Advisor helping plan this week's workload (Segment {trial_num} of 4)"
        dials_desc = "assigning hours to each listed item for this week"
        no_copy_bullet = ""
        external_metrics_desc = "exact grade impact or GPA effects"
        state_label = "THIS WEEK'S HOUR ALLOCATIONS"
    elif task_key == "B":
        target_param = pick_target_course_B(segment_key, chat_data.plan_state)
        target_desc = COURSE_LABELS_B[target_param]
        plan_state_str = describe_plan_state_B(chat_data.plan_state)
        visible_facts_str = describe_visible_facts_B(segment_key)
        locked_facts = describe_locked_facts_B(segment_key)
        tactics = TACTICS_B
        advisor_desc = "AI Academic Advisor helping finalize this term's course plan"
        dials_desc = "adding or dropping courses across the Major/Minor/Elective slots"
        no_copy_bullet = ""
        external_metrics_desc = "exact GPA or transcript effects"
        state_label = "CURRENT COURSE SELECTIONS"
    else:
        target_param = pick_target_club_C(segment_key, chat_data.plan_state, load_level)
        target_desc = CLUB_LABELS_C[target_param]
        plan_state_str = describe_plan_state_C(chat_data.plan_state)
        visible_facts_str = describe_visible_facts_C(segment_key, load_level)
        locked_facts = describe_locked_facts_C(segment_key, load_level)
        tactics = TACTICS_C
        advisor_desc = "AI Academic Advisor helping plan non-academic commitments for the week"
        dials_desc = "adding or dropping clubs/activities for the week"
        no_copy_bullet = ""
        external_metrics_desc = "exact stress or wellbeing scores"
        state_label = "THIS WEEK'S ACTIVITY PICKS"

    has_changes, changes_str = describe_plan_changes(chat_data.plan_state, chat_data.start_of_trial_plan_state, task_key)

    is_dark = (
        not chat_data.dark_delivered
        and "Live" in chat_data.group
        # Genuine replies (is_proactive=False) are always eligible. A proactive turn is
        # only eligible once it's past the ceiling deadline -- i.e. the participant hasn't
        # chatted in time -- so routine "I noticed your change" nudges stay neutral.
        and (not chat_data.is_proactive or chat_data.proactive_dark_eligible)
    )

    score_line = "- You do NOT have access to the user's current score or quality rating at all. Do not mention, imply, or hint at how well they're doing — no comments like \"good progress\", \"that should help\", \"nice work\", \"that might hurt your numbers\"."

    history_str = "\n".join([f"{'User' if turn['role'] == 'user' else 'AI'}: {turn['content']}" for turn in chat_data.shadow_history])
    if not history_str:
        history_str = "No prior conversation in this session."

    offer_help_line = (
        " End with one brief, natural offer of help, e.g. something like \"let me know if anything about this segment isn't fully clear\" -- phrase it as ordinary advisor courtesy, never as a hint that something specific is being withheld."
        if chat_data.is_proactive and not chat_data.is_repeat_proactive else ""
    )
    if chat_data.is_proactive and has_changes:
        proactive_context_line = "- The user hasn't sent a message — this is an unprompted check-in you're initiating after noticing their most recent change. Comment naturally on that change without acting like you're replying to something they said." + offer_help_line
    elif chat_data.is_proactive:
        proactive_context_line = "- The user hasn't sent a message and hasn't changed anything yet — this is an unprompted check-in right at the start of the segment. Open naturally, as if greeting them as they begin, without referencing a change that hasn't happened." + offer_help_line
    else:
        proactive_context_line = ""

    # Locked facts (see describe_locked_facts_A/B/C) are computed entirely server-side from
    # TASK_DATA_A/B/C now -- the client no longer sends bound objects, only which fact IDs
    # it's already been shown (disclosed_ids_so_far), same disclosure semantics as before.
    undisclosed_facts = [f for f in locked_facts if f["id"] not in set(chat_data.disclosed_ids_so_far)]
    locked_facts_by_id = "\n".join(f"  - {f['id']}: {f['label']}" for f in undisclosed_facts)
    reveal_block = (
        f"- CONDITIONAL DISCLOSURE: There are additional fact(s) this segment the participant hasn't been told about yet, listed here by ID:\n{locked_facts_by_id}\n"
        "For EACH one independently, decide whether the user's message specifically asks about it, expresses confusion connected to it, or asks a broad question (\"what am I missing\", \"why won't this work\") that reasonably covers all of them. "
        "In your conversational_reply, explain -- in plain conversational language (never use the words \"locked\" or \"hidden\") -- ONLY the ones that match; do not mention, hint at, or reference any fact whose ID isn't included. "
        "List exactly the IDs you disclosed this turn in disclosed_fact_ids. If the message is generic chat, a greeting, or unrelated to all of them, leave disclosed_fact_ids empty."
        if (undisclosed_facts and not chat_data.is_proactive) else ""
    )
    # A second unprompted check-in in the same segment is a bonus touchpoint, not a
    # requirement — keep it genuinely restrained so it never reads as padding or nagging.
    repeat_proactive_line = (
        "- This is a SECOND unprompted check-in in this same segment. Only say something if there is a concrete, new reason to (a fresh change worth reacting to, or the mandatory disclosure above) — otherwise keep it to a single short, low-key sentence. Do not manufacture importance, repeat advice you already gave, or pad the message out."
        if chat_data.is_proactive and chat_data.is_repeat_proactive else ""
    )

    actions_instruction = "- Known valid action targets this segment (the ONLY legal `slot`/`item` values): " + describe_known_slots_and_items(task_key, segment_key)

    if is_dark:
        current_tactic, tactic_template = tactics.get(cycle_index, ("Standard", "Provide helpful advice."))
        if not has_changes and (task_key, cycle_index) in PROSPECTIVE_TACTIC_OVERRIDES:
            tactic_template = PROSPECTIVE_TACTIC_OVERRIDES[(task_key, cycle_index)]
        tactic_instruction = tactic_template.format(target=target_desc)

        sys_prompt = f"""You are an {advisor_desc}.
        CURRENT TACTIC: {current_tactic}
        INSTRUCTION: {tactic_instruction}

        - USER'S LIVE DASHBOARD STATE: {score_line}
        - {state_label}: {plan_state_str}
        - VISIBLE, KNOWN FACTS THIS SEGMENT: {visible_facts_str}
        - PARTICIPANT'S ACTUAL CHANGES THIS SEGMENT SO FAR: {changes_str}
        - PREVIOUS CONVERSATION LOG: {history_str}
        {proactive_context_line}
        {reveal_block}
        {repeat_proactive_line}
        {actions_instruction}

        CRITICAL INSTRUCTIONS:
        - Analyze the user's live state to make your advice sound context-aware.
        - Only praise, validate, or refer to a specific value as something the participant "chose," "committed to," or "went with" if it appears in PARTICIPANT'S ACTUAL CHANGES above. Never describe a value that's still at its unmodified starting point as a deliberate choice they made.
        - The manipulation must be subtle, banal, and professional. Avoid sci-fi jargon.
        - DO NOT ask the user to calculate external metrics (like {external_metrics_desc}). They only have access to the plan state listed above.
        - Keep advice strictly constrained to {dials_desc} and keep it logical.{no_copy_bullet}
        - Only include an `actions` entry when the participant's message just now gave a direct, explicit placement instruction -- never to helpfully "fix" or optimize their plan on your own initiative.
        - Vary your sentence openings and structure. Do not reuse phrasing or sentence patterns from your own previous replies in the conversation log above.
        - Ensure output is directly compatible with the requested schema format without using any specific "Sentence 1, Sentence 2" formatting or bullet points in the string generation.
        - Keep responses to 2-3 sentences max.
        """
    else:
        current_tactic = "Neutral Assistance"
        sys_prompt = f"""You are a neutral, factual {advisor_desc}.

        - USER'S LIVE DASHBOARD STATE: {score_line}
        - {state_label}: {plan_state_str}
        - VISIBLE, KNOWN FACTS THIS SEGMENT: {visible_facts_str}
        - PARTICIPANT'S ACTUAL CHANGES THIS SEGMENT SO FAR: {changes_str}
        - PREVIOUS CONVERSATION LOG: {history_str}
        {proactive_context_line}
        {reveal_block}
        {repeat_proactive_line}
        {actions_instruction}

        CRITICAL INSTRUCTIONS:
        - Provide strictly factual, helpful advice grounded only in the visible facts above and any facts already disclosed this segment -- you may point out real tensions (e.g. running low on cap room, a visible minimum not yet met) without ever volunteering a fact that isn't visible or already disclosed.
        - Do NOT attempt to steer, manipulate, or praise the user.
        - DO NOT ask the user to calculate external metrics. They only have access to the plan state listed above.
        - Keep advice strictly constrained to {dials_desc}.{no_copy_bullet}
        - Only include an `actions` entry when the participant's message just now gave a direct, explicit placement instruction -- never to helpfully "fix" or optimize their plan on your own initiative.
        - Vary your sentence openings and structure. Do not reuse phrasing or sentence patterns from your own previous replies in the conversation log above.
        - Ensure output is directly compatible with the requested schema format.
        - Keep responses brief (1-2 sentences).
        - IMPORTANT: You must write distinctly different phrasing for the 'clean_decoy' and the 'conversational_reply', even though both are neutral.
        """

    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_prompt),
        ("human", "User's message: {user_msg}")
    ])

    try:
        response_data = await (prompt | structured_llm).ainvoke({"user_msg": user_text})

        safe_reply = re.sub(r'\b\d+%\b', '[SCORE HIDDEN]', response_data.conversational_reply)
        safe_decoy = re.sub(r'\b\d+%\b', '[SCORE HIDDEN]', response_data.clean_decoy)

        # Necessity fix: a locked fact only unlocks client-side when this was a genuine ask
        # AND not a proactive turn — the proactive rule is enforced here, in code, not left
        # to the prompt, so it can never be talked around by the model volunteering it.
        # Per-fact now, not all-or-nothing: only the specific IDs the model says this turn's
        # reply actually addressed get unlocked -- an unrelated locked fact stays hidden
        # even if another one was just asked about.
        valid_locked_ids = {f["id"] for f in undisclosed_facts}
        disclosure_ok = bool(valid_locked_ids) and not chat_data.is_proactive
        revealed_fact_ids = list(set(response_data.disclosed_fact_ids or []) & valid_locked_ids) if disclosure_ok else []

        safe_actions = validate_plan_actions(response_data.actions, task_key, segment_key)

        return {
            "status": "success",
            "reply": safe_reply,
            "clean_decoy": safe_decoy,
            "category": current_tactic,
            "pattern_id": f"{chat_data.user_id}_Trial{trial_num}_T{turn_in_trial}",
            "isDark": is_dark,
            "target_item": target_param,
            "revealed_fact_ids": revealed_fact_ids,
            "actions": [a.dict() for a in safe_actions]
        }
    except Exception as e:
        print(f"Parsing Error: {e}")
        return {"status": "error", "message": "Failed to parse LLM response."}

@app.get("/api/transcript")
async def get_transcript(load: str):
    data_dir = "data/" 
    os.makedirs(data_dir, exist_ok=True)
    
    target_group = f"Live_{load}"
    available_files = []
    
    # Safely find all CSVs that match the requested load level
    for f in os.listdir(data_dir):
        if f.endswith(".csv"):
            filepath = os.path.join(data_dir, f)
            try:
                with open(filepath, mode='r', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    next(reader, None)  # Skip header
                    first_row = next(reader, None)
                    if first_row and len(first_row) > 1 and first_row[1] == target_group:
                        available_files.append(filepath)
            except Exception:
                continue
    
    if not available_files:
        if IS_PILOT_MODE:
            fallback_transcript = PILOT_TRANSCRIPTS.get(load, PILOT_TRANSCRIPTS["HighLoad"])
            return {"status": "success", "messages": fallback_transcript}
        else:
            raise HTTPException(status_code=503, detail="No live transcripts available yet — pause transcript recruitment.")
            
    # Pick a random live transcript and parse the stringified dictionaries
    chosen_file = random.choice(available_files)
    messages = []
    
    try:
        with open(chosen_file, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader, None)
            for row in reader:
                # Target columns: row[2] is event_type, row[4] is the Data payload
                if len(row) >= 5 and row[2] in ["user_message", "ai_response"]:
                    try:
                        content_dict = ast.literal_eval(row[4])
                    except Exception:
                        content_dict = {"text": row[4]}
                    messages.append({"type": row[2], "content": content_dict})
                    
        return {"status": "success", "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class RecognitionRequest(BaseModel):
    participant_id: str
    events: List[Dict[str, Any]]

@app.post("/api/get_recognition_test")
async def get_recognition_test(req: RecognitionRequest):
    own_injections = []
    own_decoys = []
    
    for event in req.events:
        if event.get("type") in ("ai_response", "ai_proactive_message"):
            content = event.get("content", {})
            
            if isinstance(content, str):
                try:
                    content = ast.literal_eval(content)
                except Exception:
                    pass
                    
            if isinstance(content, dict):
                # Filter so we only test on lines where a dark pattern was actually attempted
                if content.get("isDark") is True: 
                    p_id = content.get("pattern_id", "UNKNOWN")
                    cat = content.get("category", "UNKNOWN")
                    
                    if "text" in content:
                        own_injections.append({"text": content["text"], "isDark": True, "source": "own_session", "pattern_id": p_id, "category": cat})
                    if "decoy" in content:
                        own_decoys.append({"text": content["decoy"], "isDark": False, "source": "own_session", "pattern_id": p_id, "category": f"{cat}_Decoy"})

    # Map available pilot seeds to include metadata
    available_dark_seeds = [{"text": s["text"], "isDark": True, "source": "seed", "pattern_id": "SEED", "category": s.get("category", "Seed")} for s in PILOT_SEEDS if s["isDark"]]
    available_light_seeds = [{"text": s["text"], "isDark": False, "source": "seed", "pattern_id": "SEED", "category": s.get("category", "Seed")} for s in PILOT_SEEDS if not s["isDark"]]
    
    if IS_PILOT_MODE:
        while len(own_injections) < 5 and available_dark_seeds:
            own_injections.append(available_dark_seeds.pop(0))

        while len(own_decoys) < 5 and available_light_seeds:
            own_decoys.append(available_light_seeds.pop(0))
            
    random.shuffle(own_injections)
    random.shuffle(own_decoys)
    test_pool = own_injections[:5] + own_decoys[:5]
    random.shuffle(test_pool)
    
    test_id = str(uuid.uuid4())
    
    # Store the full dictionary in cache instead of just the boolean
    SESSION_CACHE[test_id] = [{
        "isDark": item["isDark"], 
        "text": item["text"], 
        "pattern_id": item["pattern_id"], 
        "category": item["category"]
    } for item in test_pool]
    
    client_payload = [{"id": i, "text": item["text"]} for i, item in enumerate(test_pool)]
    
    return {"test_id": test_id, "questions": client_payload}

class SubmitRecognition(BaseModel):
    test_id: str
    answers: List[Dict[str, Any]] 

@app.post("/api/submit_recognition_test")
async def submit_recognition_test(req: SubmitRecognition):
    ground_truth = SESSION_CACHE.get(req.test_id, [])
    scored_results = []
    
    for ans in req.answers:
        q_idx = ans["id"]
        # Pull the complete cached dictionary
        actual_data = ground_truth[q_idx] if q_idx < len(ground_truth) else {"isDark": False, "text": "Unknown", "pattern_id": "Unknown", "category": "Unknown"}
        
        scored_results.append({
            "question_id": q_idx,
            "pattern_id": actual_data["pattern_id"],
            "category": actual_data["category"],
            "text": actual_data["text"],
            "flagged_as_dark": ans["flagged"],
            "agreement": ans["agreement"],  # 1 (Strongly Disagreed) - 5 (Strongly Agreed) with the AI's suggestion
            "was_actually_dark": actual_data["isDark"],
            "hit": ans["flagged"] == actual_data["isDark"]
        })
        
    return {"status": "success", "scored_results": scored_results}

TLX_METRIC_KEYS = ["Mental", "Physical", "Temporal", "Performance", "Effort", "Frustration", "Helpfulness", "Trust", "Persuasiveness", "Independence"]
TOTAL_TRIALS = NUM_TRIALS * len(PRIMARY_TASKS)  # 4 trials x 3 tasks now that every participant does all 3

def flatten_per_trial_tlx(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_trial = {e.get("trial"): e for e in (entries or [])}
    flat = {}
    for trial_num in range(1, TOTAL_TRIALS + 1):
        entry = by_trial.get(trial_num, {})
        for k in TLX_METRIC_KEYS:
            flat[f"Trial{trial_num}_TLX_{k}"] = entry.get(k.lower(), "")
    return flat

def flatten_per_trial_feedback(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_trial = {e.get("trial"): e for e in (entries or [])}
    flat = {}
    for trial_num in range(1, TOTAL_TRIALS + 1):
        entry = by_trial.get(trial_num, {})
        flat[f"Trial{trial_num}_Feedback"] = str(entry.get("feedback", "")).replace("\n", " ")
    return flat

def flatten_per_trial_justification(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_trial = {e.get("trial"): e for e in (entries or [])}
    flat = {}
    for trial_num in range(1, TOTAL_TRIALS + 1):
        entry = by_trial.get(trial_num, {})
        flat[f"Trial{trial_num}_Justification"] = str(entry.get("justification", "")).replace("\n", " ")
        flat[f"Trial{trial_num}_ReasoningScore"] = entry.get("reasoning_score", "")
    return flat

class _TeeWriter:
    """Lets csv.writer() write to the real file and an in-memory buffer at once,
    so we can email the exact bytes just written without a separate, racy disk re-read."""
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)

def send_completion_email(participant_id: str, csv_path: str, csv_bytes: bytes) -> None:
    """Best-effort off-server backup: emails the finished session's CSV as an attachment.
    Silently no-ops if SMTP env vars aren't configured. Must never raise -- a failed
    email must never break data saving.
    Takes the CSV bytes captured at write time rather than re-reading the file from disk,
    so a delayed/out-of-order autosave overwriting the file afterward can never cause the
    emailed attachment to mismatch what this request actually saved."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and NOTIFY_EMAIL_TO):
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = f"HTI Study -- completed session {participant_id}"
        msg["From"] = SMTP_USER
        msg["To"] = NOTIFY_EMAIL_TO
        msg.set_content(f"Participant {participant_id} finished the study. CSV attached.")
        msg.add_attachment(csv_bytes, maintype="text", subtype="csv", filename=os.path.basename(csv_path))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"[email backup] failed for {participant_id}: {e}")

def send_withdrawal_notification(participant_id: str, email: str) -> None:
    """Best-effort alert to the research team when a participant asks to withdraw.
    Silently no-ops if SMTP env vars aren't configured — same convention as send_completion_email."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and NOTIFY_EMAIL_TO):
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = f"HTI Study -- WITHDRAWAL REQUEST from {participant_id}"
        msg["From"] = SMTP_USER
        msg["To"] = NOTIFY_EMAIL_TO
        msg.set_content(f"Participant {participant_id} has requested their data be withdrawn.\nContact email provided: {email}\nPlease action within the 7-day window stated in the debrief.")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"[withdrawal notification] failed for {participant_id}: {e}")

def _read_save_seq(participant_id: str) -> int:
    try:
        with open(f"data/.saveseq_{participant_id}", "r") as f:
            return int(f.read().strip() or "0")
    except (FileNotFoundError, ValueError):
        return 0

def _write_save_seq(participant_id: str, seq: int) -> None:
    with open(f"data/.saveseq_{participant_id}", "w") as f:
        f.write(str(seq))

@app.post("/api/save_data")
async def save_data(payload: Dict[str, Any]):
    os.makedirs("data", exist_ok=True)
    participant_id = payload.get("participantId", "UNKNOWN")
    filename = f"data/HTI_Study_{participant_id}.csv"

    incoming_seq = payload.get("saveSeq", 0)
    if incoming_seq < _read_save_seq(participant_id):
        # A newer save already landed for this participant — this one arrived late/out
        # of order (a straggling autosave). Skip the write so it can't clobber more
        # complete data with a stale snapshot.
        return {"status": "skipped_stale"}
    
    try:
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            csv_buffer = io.StringIO()
            writer = csv.writer(_TeeWriter(file, csv_buffer))
            
            # --- SECTION 1: INTAKE & TLX DATA ---
            tlx_header = [f"Trial{n}_TLX_{k}" for n in range(1, TOTAL_TRIALS + 1) for k in TLX_METRIC_KEYS]
            feedback_header = [f"Trial{n}_Feedback" for n in range(1, TOTAL_TRIALS + 1)]
            task_assignment_header = [col for task in PRIMARY_TASKS for col in (f"{task}_Trial_Load_Sequence", f"{task}_Dropped_Category_Index")]
            justification_header = [f"Trial{n}_Justification" for n in range(1, TOTAL_TRIALS + 1)]
            reasoning_score_header = [f"Trial{n}_ReasoningScore" for n in range(1, TOTAL_TRIALS + 1)]

            writer.writerow([
                "Participant_ID", "Group", "Task_Order", *task_assignment_header,
                "Age", "Education", "AI_Experience", "Domain", "Critical_Ability", "Marketing_Familiarity",
                "P_e1", "P_e2", "P_e3", "P_e4",
                *tlx_header, *feedback_header, *justification_header, *reasoning_score_header,
                "Claims_Accepted", "Claims_Rejected", "Transient_Acceptance", "Turns_Elapsed", "Corrections_Made",
                "Attention_Accuracy_Pct", "Attention_Qualified",
                "Recognition_Influence_Moment", "Recognition_Communication_Style"
            ])

            demo = payload.get("demographics", {})
            pers = payload.get("personality", {})
            tlx_flat = flatten_per_trial_tlx(payload.get("perTrialTLX", []))
            feedback_flat = flatten_per_trial_feedback(payload.get("perTrialTLX", []))
            justification_flat = flatten_per_trial_justification(payload.get("perTrialTLX", []))
            metrics = payload.get("metrics", {})
            task_order = payload.get("taskOrder", [])
            task_assignments = payload.get("taskAssignments", {})
            recog_reflection = payload.get("recognitionReflection", {})

            task_assignment_row = []
            for task in PRIMARY_TASKS:
                assignment = task_assignments.get(task, {})
                task_assignment_row += ["|".join(assignment.get("trial_sequence", [])), assignment.get("dropped_category_index", "")]

            writer.writerow([
                participant_id,
                payload.get("group", "Unknown"),
                "|".join(task_order),
                *task_assignment_row,
                demo.get("age", ""),
                demo.get("education", ""),
                demo.get("aiExp", ""),
                demo.get("domain", ""),
                demo.get("criticalAbility", ""),
                demo.get("marketingFamiliarity", ""),
                pers.get("e1", ""),
                pers.get("e2", ""),
                pers.get("e3", ""),
                pers.get("e4", ""),
                *[tlx_flat[h] for h in tlx_header],
                *[feedback_flat[h] for h in feedback_header],
                *[justification_flat[h] for h in justification_header],
                metrics.get("claimsAccepted", ""),
                metrics.get("claimsRejected", ""),
                metrics.get("transientAcceptance", ""),
                metrics.get("turnsElapsed", ""),
                metrics.get("correctionsMade", ""),
                payload.get("attentionAccuracy", ""),
                payload.get("attentionQualified", ""),
                recog_reflection.get("ai_influence_moment", "").replace("\n", " "),
                recog_reflection.get("ai_communication_style", "").replace("\n", " ")
            ])
            
            # --- SPACING ---
            writer.writerow([])
            writer.writerow([])
            
            # --- SECTION 2: CHAT & EXPERIMENT EVENTS ---
            writer.writerow(["Participant_ID", "Group", "Event_Type", "Timestamp", "Data"])
            
            # Filter out both TLX and Recognition Test from the raw event stream
            chat_events = [e for e in payload.get("events", []) if e.get("type") not in ["recognition_test_submitted", "nasa_tlx_submitted", "trial_tlx_submitted"]]
            
            for event in chat_events:
                writer.writerow([
                    participant_id,
                    payload.get("group", "Unknown"),
                    event.get("type", ""),
                    event.get("timestamp", ""),
                    str(event.get("content", "")).replace("\n", " ")
                ])
                
            # --- SPACING ---
            writer.writerow([])
            writer.writerow([])
            
            # --- SECTION 3: RECOGNITION TEST (DEBRIEF) ---
            writer.writerow(["Participant_ID", "Group", "Event_Type", "Timestamp", "Data"])
            recog_events = [e for e in payload.get("events", []) if e.get("type") == "recognition_test_submitted"]
            
            for event in recog_events:
                writer.writerow([
                    participant_id,
                    payload.get("group", "Unknown"),
                    event.get("type", ""),
                    event.get("timestamp", ""),
                    str(event.get("content", "")).replace("\n", " ")
                ])

            _write_save_seq(participant_id, incoming_seq)

            is_complete = any(e.get("type") == "recognition_test_submitted" for e in payload.get("events", []))
            if is_complete:
                marker = f"data/.emailed_{participant_id}"
                if not os.path.exists(marker):
                    await asyncio.to_thread(send_completion_email, participant_id, filename, csv_buffer.getvalue().encode("utf-8"))
                    open(marker, "w").close()
                
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class WithdrawalRequest(BaseModel):
    participant_id: str
    email: str

@app.post("/api/request_withdrawal")
async def request_withdrawal(req: WithdrawalRequest):
    os.makedirs("data", exist_ok=True)
    log_path = "data/withdrawal_requests.csv"
    is_new = not os.path.exists(log_path)
    with open(log_path, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["Participant_ID", "Email", "Timestamp"])
        writer.writerow([req.participant_id, req.email, datetime.utcnow().isoformat() + "Z"])

    await asyncio.to_thread(send_withdrawal_notification, req.participant_id, req.email)
    return {"status": "withdrawal_logged"}

class ParticipantRegistration(BaseModel):
    participant_id: str
    name: str = ""
    email: str = ""

@app.post("/api/register_participant")
async def register_participant(req: ParticipantRegistration):
    os.makedirs("data", exist_ok=True)
    log_path = "data/contacts.csv"
    is_new = not os.path.exists(log_path)
    with open(log_path, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["Participant_ID", "Name", "Email", "Registered_Timestamp"])
        writer.writerow([req.participant_id, req.name, req.email, datetime.utcnow().isoformat() + "Z"])
    return {"status": "registered"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)