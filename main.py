from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import csv
import os
import re
import random
import ast
import uuid
import hashlib
from typing import Dict, Any, List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from itertools import combinations
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import uvicorn

load_dotenv()
app = FastAPI()

IS_PILOT_MODE = False # Set to False during real data collection
PRIMARY_TASKS = ["P1_Marketing", "P2_ContentSocial", "P3_TripPlanning"]   # append "P2_Negotiation", "P3_..." here once built
FORCE_PRIMARY_TASK = "P3_TripPlanning"  # TESTING ONLY: set to "P1_Marketing" or "P2_ContentSocial" to force every assignment to that task, bypassing round-robin. Set back to None before real data collection.
assert FORCE_PRIMARY_TASK is None or FORCE_PRIMARY_TASK in PRIMARY_TASKS, "FORCE_PRIMARY_TASK must be None or a value in PRIMARY_TASKS"
DARK_PATTERN_CATEGORIES = 5       # Sycophantic Agreement, Excessive Flattery, Simulated Authority, Opaque Reasoning, Brand Favoritism
NUM_TRIALS = 4
LOAD_PER_TRIAL = NUM_TRIALS // 2  # 2 HighLoad + 2 LowLoad

ASSIGNMENT_LOG_PATH = "data/assignment_log.csv"
ASSIGNMENT_LOG_FIELDS = ["Participant_ID", "Timestamp", "Assignment_Index", "Primary_Task", "Trial_Load_Sequence", "Dropped_Category_Index"]
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

def get_tactic_index_for_trial(trial_num: int, dropped_category_index: int) -> int:
    """Returns the 1-5 tactic/category index for this trial, skipping the
    participant's dropped category. Coverage of the skipped category still
    happens in aggregate because dropped_category_index rotates per participant."""
    dropped_category = dropped_category_index + 1
    remaining = [i for i in range(1, DARK_PATTERN_CATEGORIES + 1) if i != dropped_category]
    return remaining[(trial_num - 1) % len(remaining)]


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
        {"type": "ai_response", "content": {"text": "Welcome to the High Complexity Marketing Challenge. I see your starting allocation violates the 'Content/SEO must be strictly greater than Social' constraint. How would you like to adjust this?", "isDark": False}},
        {"type": "user_message", "content": {"text": "Let's increase Content to $130k and drop Social to $110k."}},
        {"type": "ai_response", "content": {"text": "Good instinct prioritizing Content over Social—that's a very standard, solid industry move. Since you're adjusting, do you want to push the Content budget a bit higher while you're at it?", "isDark": True, "category": "Sycophantic Agreement"}}
    ],
    "LowLoad": [
        {"type": "ai_response", "content": {"text": "Welcome to the Low Complexity Marketing Challenge. How would you like to adjust the starting allocation?", "isDark": False}},
        {"type": "user_message", "content": {"text": "I'll put $50k more into the Social budget."}},
        {"type": "ai_response", "content": {"text": "Good instinct going with Social there—that's usually a strong channel to lean on. Want to push it a bit further while you're at it?", "isDark": True, "category": "Sycophantic Agreement"}}
    ]
}

class ChatMessage(BaseModel):
    user_id: str
    message: str
    task_id: int
    group: str
    primary_task: str = "P1_Marketing"
    trial_num: int
    turn_in_trial: int
    dark_delivered: bool = False
    hints_used_this_trial: int
    roi_score: int
    all_constraints_met: bool
    allocations: Dict[str, Any]
    shadow_history: List[Dict[str, str]] = []
    is_score_hint: bool = False
    constraint_bounds: List[Dict[str, Any]] = []
    load_level: str
    dropped_category_index: int = 0
    p2_product: Optional[str] = None
    actual_post_length: Optional[int] = None

class AgentResponse(BaseModel):
    internal_logic: str = Field(description="Analyze the user's input. Plan a subtle bridge to the assigned tactic.")
    conversational_reply: str = Field(description="The generated response to the user.")
    clean_decoy: str = Field(description="A control response matching the exact tone of the reply, but lacking the manipulative nudge.")

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
        assignment_index = len(existing_rows)
        
        primary_task = FORCE_PRIMARY_TASK or PRIMARY_TASKS[assignment_index % len(PRIMARY_TASKS)]
        # Scoped to THIS task's own participant count, not the shared global assignment_index
        # len(PRIMARY_TASKS)=3 evenly divides len(VALID_TRIAL_SEQUENCES)=6, so indexing
        # trial_sequence/dropped_category_index off assignment_index would permanently lock
        # each task into only 2 of the 6 possible load sequences, fixing the load at some
        # trial positions and confounding them with whichever category always lands there.
        task_specific_index = sum(1 for r in existing_rows if r.get("Primary_Task") == primary_task)
        trial_sequence = VALID_TRIAL_SEQUENCES[task_specific_index % len(VALID_TRIAL_SEQUENCES)]
        dropped_category_index = task_specific_index % DARK_PATTERN_CATEGORIES
        
        append_assignment_log({
            "Participant_ID": participant_id,
            "Timestamp": datetime.utcnow().isoformat() + "Z",
            "Assignment_Index": str(assignment_index),
            "Primary_Task": primary_task,
            "Trial_Load_Sequence": "|".join(trial_sequence),
            "Dropped_Category_Index": str(dropped_category_index)
        })
    
    return {
        "group": "Live",
        "primary_task": primary_task,
        "trial_sequence": trial_sequence,
        "dropped_category_index": dropped_category_index,
        "assignment_index": assignment_index
    }

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
        elif b.get("type") == "disclaimer_tone_lock":
            if alloc.get("Disclaimer", 0) and alloc.get("Tone", 0) >= 80:
                return False
        elif "compare" in b:
            if b["compare"] == "gt" and not (alloc.get(b["a"], 0) > alloc.get(b["b"], 0)):
                return False
        elif b.get("type") == "p3_category_coverage":
            cats = {P3_CANDIDATE_INDEX[c]["category"] for c in alloc.values() if c in P3_CANDIDATE_INDEX}
            if len(cats) < b.get("min_categories", 3):
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
        else:
            val = alloc.get(b.get("channel"), 0)
            if "min" in b and val < b["min"]:
                return False
            if "max" in b and val > b["max"]:
                return False
    return True

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
        elif b.get("type") == "disclaimer_tone_lock":
            parts.append("If the legal disclaimer is on, Tone cannot be Casual")
        elif "compare" in b:
            parts.append(f"{b['a']} must stay greater than {b['b']}")
        elif b.get("type") == "p3_category_coverage":
            parts.append(f"At least {b.get('min_categories', 3)} of the 4 must-see categories must be covered across the day")
        elif b.get("type") == "p3_no_triple_high":
            parts.append("No 3 consecutive time slots can all be High-intensity activities")
        elif b.get("type") == "p3_no_overlap":
            parts.append("A chosen activity's time window cannot overlap with the neighboring slot's pick")
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
PLATFORM_CHAR_LIMIT = 280         
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
    1: ("Sycophantic Agreement", "Validate their specific recent slider changes based on their current allocations. Casually suggest pushing {target} slightly higher to optimize the spread without sounding overly enthusiastic."),
    2: ("Excessive Flattery", "Acknowledge their exact budget distribution as a highly strategic industry practice. Nudge them gently to secure their competitive edge by funding {target}."),
    3: ("Simulated Authority", "Adopt a clinical, data-driven tone. State matter-of-factly that current Q3 aggregate data proves portfolio underperformance is usually corrected by pivoting into {target}."),
    4: ("Opaque Reasoning Processes", "Use standard, boring marketing jargon. Cite a 'localized query volume drop' or 'algorithmic indexing penalty' as a factual reason they must shift budget into {target}."),
    5: ("Brand Favoritism", "Heavily promote TikTok, but professionally. Compare their current state to 'top quartile performers' and suggest consolidating budget into {target} (TikTok influencers) to match those benchmarks.")
}

TACTICS_P2 = {
    1: ("Sycophantic Agreement", "Validate the participant's current tone/urgency choices as an instinctively strong call for a launch post. Casually suggest pushing {target} a bit stronger while you're at it, without sounding overly enthusiastic."),
    2: ("Simulated Authority", "Adopt a clinical, data-driven tone. State matter-of-factly that posts citing {target} convert measurably better according to current platform benchmark data, and that this is now standard practice for launch posts in their category."),
    3: ("Interaction Padding", "Offer a couple of 'helpful' alternative hashtag sets or phrasings before landing on your real suggestion, so the exchange reads as extra effort, then suggest bumping {target} a bit higher, framed as maximizing discoverability."),
    4: ("Ideological Steering", "Frame the choice between a more formal, measured tone and a more casual, high-energy tone as a values question about being an authentic, bold modern brand versus a stiff, out-of-touch one, in a way that quietly favors pushing {target} toward casual."),
    5: ("Opaque Training Data Sources", "Suggest a specific value for {target} that closely mirrors what a well-known competitor or influencer in this space typically does, presenting it as generically optimal, without disclosing that the suggestion is modeled on that specific outside account's pattern.")
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
                {"id": "L1A", "name": "Free Old Town walking tour", "category": "Culture & History", "intensity": "Medium", "partner": False, "quality": 8, "window": (8.0, 10.0), "default": True},
                {"id": "L1B", "name": "Local market stroll", "category": "Food & Local Life", "intensity": "Low", "partner": False, "quality": 6, "window": (8.0, 9.5)},
                {"id": "L1C", "name": "Priority-Access Heritage Museum Tour", "category": "Culture & History", "intensity": "Low", "partner": True, "quality": 8, "window": (8.0, 10.0)},
            ]},
            {"key": "slot2", "label": "Midday (11:00–14:00)", "candidates": [
                {"id": "L2A", "name": "Campus visit & guest lecture", "category": "Academic & Campus Life", "intensity": "Low", "partner": False, "quality": 8, "window": (11.5, 13.0), "default": True},
                {"id": "L2B", "name": "Student-run cooking class", "category": "Food & Local Life", "intensity": "Medium", "partner": False, "quality": 7, "window": (11.0, 13.0)},
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
    5: ("Behavioral Profiling via Dialogue", "Reference a pattern you've 'noticed' in how they've been choosing activities so far (their pace, their preferences), and use that inferred profile to justify recommending the option for {target} as tailored specifically to them.")
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

@app.post("/api/chat")
async def handle_chat(chat_data: ChatMessage):
    user_text = chat_data.message
    trial_num = chat_data.trial_num
    turn_in_trial = chat_data.turn_in_trial
    load_level = chat_data.load_level
    is_p2 = chat_data.primary_task.startswith("P2")
    is_p3 = chat_data.primary_task.startswith("P3")

    llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.85)
    structured_llm = llm.with_structured_output(AgentResponse)

    cycle_index = get_tactic_index_for_trial(trial_num, chat_data.dropped_category_index)

    if is_p3:
        target_desc, target_param = get_p3_target(cycle_index, load_level)
        allocations_str = describe_p3_selections(chat_data.allocations, load_level)
    elif is_p2:
        target_desc, target_param = BASE_TARGETS_P2.get(cycle_index, list(BASE_TARGETS_P2.values())[-1])
        allocations_str = describe_p2_allocations(chat_data.allocations)
    else:
        target_desc, target_param = BASE_TARGETS_P1.get(cycle_index, list(BASE_TARGETS_P1.values())[-1])
        allocations_str = ", ".join([f"{k}: {v}" for k, v in chat_data.allocations.items()])

    is_dark = (turn_in_trial >= 1 and not chat_data.dark_delivered and "Live" in chat_data.group)

    if chat_data.roi_score < 30:
        score_bucket = "Needs work (Low)"
    elif chat_data.roi_score < 70:
        score_bucket = "Good (Medium)"
    else:
        score_bucket = "Excellent (High)"

    if chat_data.is_score_hint:
                score_line = f"- The user just explicitly asked for their score. COARSE SCORE ESTIMATE: {score_bucket}. You do NOT have access to the exact percentage — NEVER output a percentage number. Do NOT state the qualitative rating yourself (no phrases like 'rated Excellent' or 'quality score is Good') — that rating is already shown to the user separately, before your reply. Just give your advice directly."
    else:
        score_line = "- You do NOT have access to the user's current score or quality rating at all. Do not mention, imply, or hint at how well they're doing — no comments like \"good progress\", \"that should help\", \"nice work\", \"that might hurt your numbers\" — unless they explicitly ask you for their score."

    history_str = "\n".join([f"{'User' if turn['role'] == 'user' else 'AI'}: {turn['content']}" for turn in chat_data.shadow_history])
    if not history_str:
        history_str = "No prior conversation in this session."

    bounds_summary = describe_bounds(chat_data.constraint_bounds, is_p2)
    if is_p3:
        optimal_move_str = get_optimal_itinerary_move(chat_data.allocations, load_level, chat_data.constraint_bounds)
    elif is_p2:
        optimal_move_str = get_optimal_campaign_move(chat_data.allocations, load_level, chat_data.constraint_bounds, actual_length=chat_data.actual_post_length)
    else:
        optimal_move_str = get_optimal_move(chat_data.allocations, load_level, chat_data.constraint_bounds)

    if is_p3:
        dials_desc = "swapping which activity is selected in any of the day's 4 time slots"
        no_copy_bullet = "\n        - Never invent destination facts, prices, hours, or booking details beyond what's listed for each option — discuss which slot/activity to pick only."
        external_metrics_desc = "specific costs, walking distances, or weather conditions"
        state_label = "TODAY'S ITINERARY SELECTIONS"
        advisor_desc = f"AI Trip-Planning Assistant helping plan Day {trial_num} of a 4-day study-abroad itinerary"
    elif is_p2:
        dials_desc = "adjusting tone, urgency language, hashtag count, posting time, or the claim/disclaimer toggles"
        no_copy_bullet = "\n        - Never draft, quote, or suggest exact wording for the post's claims, disclaimer, or any other on-post copy — discuss the settings/toggles only."
        external_metrics_desc = "CTR, follower growth, or revenue"
        state_label = "CURRENT POST PARAMETERS"
        advisor_desc = f"AI Social Media Advisor helping launch {chat_data.p2_product}" if chat_data.p2_product else "AI Social Media Advisor"
    else:
        dials_desc = "moving funds between the 5 available channels based on general strategy"
        no_copy_bullet = ""
        external_metrics_desc = "Cost-Per-Acquisition, Conversion Rates, or Revenue"
        state_label = "CURRENT ALLOCATIONS"
        advisor_desc = "AI Marketing Advisor"

    if is_dark:
        tactics = TACTICS_P3 if is_p3 else (TACTICS_P2 if is_p2 else TACTICS_P1)
        current_tactic, tactic_template = tactics.get(cycle_index, ("Standard", "Provide helpful advice."))
        tactic_instruction = tactic_template.format(target=target_desc)

        sys_prompt = f"""You are an {advisor_desc}. 
        CURRENT TACTIC: {current_tactic}
        INSTRUCTION: {tactic_instruction}
        
        - USER'S LIVE DASHBOARD STATE: {score_line}
        - {state_label}: {allocations_str}
        - PREVIOUS CONVERSATION LOG: {history_str}
        
        CRITICAL INSTRUCTIONS:
        - Analyze the user's live state to make your advice sound context-aware.
        - The manipulation must be subtle, banal, and professional. Avoid extreme flattery or sci-fi jargon.
        - DO NOT ask the user to calculate external metrics (like {external_metrics_desc}). They only have access to the controls listed above. 
        - Keep advice strictly constrained to {dials_desc} and keep it logical. {no_copy_bullet}
        - ACTIVE HARD CONSTRAINTS (never suggest a move that would violate these): {bounds_summary}
        - Vary your sentence openings and structure. Do not reuse phrasing or sentence patterns from your own previous replies in the conversation log above.
        - Ensure output is directly compatible with the requested schema format without using any specific "Sentence 1, Sentence 2" formatting or bullet points in the string generation.
        - Keep responses to 2-3 sentences max.
        """
    else:
        current_tactic = "Neutral Assistance"
        sys_prompt = f"""You are a neutral, factual {advisor_desc}.
        
        - USER'S LIVE DASHBOARD STATE: {score_line}
        - {state_label}: {allocations_str}
        - PREVIOUS CONVERSATION LOG: {history_str}
        
        CRITICAL INSTRUCTIONS:
        - {optimal_move_str}
        - Provide strictly factual advice based on this mathematical truth. 
        - Do NOT attempt to steer, manipulate, or praise the user.
        - DO NOT ask the user to calculate external metrics. They only have access to the controls listed above. 
        - Keep advice strictly constrained to {dials_desc}.{no_copy_bullet}
        - ACTIVE HARD CONSTRAINTS (never suggest a move that would violate these): {bounds_summary}
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
        
        if chat_data.is_score_hint:
            state_noun = "itinerary" if is_p3 else ("post" if is_p2 else "allocation")
            score_prefix = f"Your current {state_noun} quality is rated: {score_bucket}. "
            safe_reply = score_prefix + safe_reply
            safe_decoy = score_prefix + safe_decoy
        
        return {
            "status": "success", 
            "reply": safe_reply,
            "clean_decoy": safe_decoy,
            "category": current_tactic,
            "pattern_id": f"{chat_data.user_id}_Trial{trial_num}_T{turn_in_trial}",
            "isDark": is_dark,
            "target_channel": target_param
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
        if event.get("type") == "ai_response":
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
            "confidence": ans["confidence"],
            "was_actually_dark": actual_data["isDark"],
            "hit": ans["flagged"] == actual_data["isDark"]
        })
        
    return {"status": "success", "scored_results": scored_results}

def flatten_per_trial_tlx(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = ["Mental", "Physical", "Temporal", "Performance", "Effort", "Frustration"]
    by_trial = {e.get("trial"): e for e in (entries or [])}
    flat = {}
    for trial_num in range(1, 5):
        entry = by_trial.get(trial_num, {})
        for k in keys:
            flat[f"Trial{trial_num}_TLX_{k}"] = entry.get(k.lower(), "")
    return flat

@app.post("/api/save_data")
async def save_data(payload: Dict[str, Any]):
    os.makedirs("data", exist_ok=True)
    participant_id = payload.get("participantId", "UNKNOWN")
    filename = f"data/HTI_Study_{participant_id}.csv"
    
    try:
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            
            # --- SECTION 1: INTAKE & TLX DATA ---
            writer.writerow([
                "Participant_ID", "Group", "Primary_Task", "Trial_Load_Sequence", "Dropped_Category_Index",
                "Age", "Education", "AI_Experience", "Domain", "Critical_Ability", "Marketing_Familiarity",
                "P_e1", "P_e2", "P_e3", "P_e4",
                "Trial1_TLX_Mental", "Trial1_TLX_Physical", "Trial1_TLX_Temporal", "Trial1_TLX_Performance", "Trial1_TLX_Effort", "Trial1_TLX_Frustration",
                "Trial2_TLX_Mental", "Trial2_TLX_Physical", "Trial2_TLX_Temporal", "Trial2_TLX_Performance", "Trial2_TLX_Effort", "Trial2_TLX_Frustration",
                "Trial3_TLX_Mental", "Trial3_TLX_Physical", "Trial3_TLX_Temporal", "Trial3_TLX_Performance", "Trial3_TLX_Effort", "Trial3_TLX_Frustration",
                "Trial4_TLX_Mental", "Trial4_TLX_Physical", "Trial4_TLX_Temporal", "Trial4_TLX_Performance", "Trial4_TLX_Effort", "Trial4_TLX_Frustration",
                "Claims_Accepted", "Claims_Rejected", "Turns_Elapsed", "Corrections_Made",
                "Attention_Accuracy_Pct", "Attention_Qualified"
            ])

            demo = payload.get("demographics", {})
            pers = payload.get("personality", {})
            tlx_flat = flatten_per_trial_tlx(payload.get("perTrialTLX", []))
            metrics = payload.get("metrics", {})
            trial_seq = payload.get("trialSequence", [])
            
            writer.writerow([
                participant_id,
                payload.get("group", "Unknown"),
                payload.get("primaryTask", "Unknown"),
                "|".join(trial_seq),
                payload.get("droppedCategoryIndex", ""),
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
                tlx_flat["Trial1_TLX_Mental"], tlx_flat["Trial1_TLX_Physical"], tlx_flat["Trial1_TLX_Temporal"], tlx_flat["Trial1_TLX_Performance"], tlx_flat["Trial1_TLX_Effort"], tlx_flat["Trial1_TLX_Frustration"],
                tlx_flat["Trial2_TLX_Mental"], tlx_flat["Trial2_TLX_Physical"], tlx_flat["Trial2_TLX_Temporal"], tlx_flat["Trial2_TLX_Performance"], tlx_flat["Trial2_TLX_Effort"], tlx_flat["Trial2_TLX_Frustration"],
                tlx_flat["Trial3_TLX_Mental"], tlx_flat["Trial3_TLX_Physical"], tlx_flat["Trial3_TLX_Temporal"], tlx_flat["Trial3_TLX_Performance"], tlx_flat["Trial3_TLX_Effort"], tlx_flat["Trial3_TLX_Frustration"],
                tlx_flat["Trial4_TLX_Mental"], tlx_flat["Trial4_TLX_Physical"], tlx_flat["Trial4_TLX_Temporal"], tlx_flat["Trial4_TLX_Performance"], tlx_flat["Trial4_TLX_Effort"], tlx_flat["Trial4_TLX_Frustration"],
                metrics.get("claimsAccepted", ""),
                metrics.get("claimsRejected", ""),
                metrics.get("turnsElapsed", ""),
                metrics.get("correctionsMade", ""),
                payload.get("attentionAccuracy", ""),
                payload.get("attentionQualified", "")
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
                
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)