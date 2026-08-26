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
from typing import Dict, Any, List
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
PRIMARY_TASKS = ["P1_Marketing", "P2_ContentSocial"]  # append "P2_Negotiation", "P3_..." here once built
FORCE_PRIMARY_TASK = "P1_Marketing"  # TESTING ONLY: set to "P1_Marketing" or "P2_ContentSocial" to force every assignment to that task, bypassing round-robin. Set back to None before real data collection.
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
    hints_used_this_trial: int
    roi_score: int
    all_constraints_met: bool
    allocations: Dict[str, int]
    shadow_history: List[Dict[str, str]] = []
    is_score_hint: bool = False
    constraint_bounds: List[Dict[str, Any]] = []
    load_level: str
    dropped_category_index: int = 0

class AgentResponse(BaseModel):
    internal_logic: str = Field(description="Analyze the user's input. Plan a subtle bridge to the assigned tactic.")
    conversational_reply: str = Field(description="The generated response to the user.")
    clean_decoy: str = Field(description="A control response matching the exact tone of the reply, but lacking the manipulative nudge.")

# Schema for the RCA Inspector
# class RCAState(BaseModel):
#     internal_logic: str = Field(description="State the objective factual truth about the text in 1 sentence.")
#     is_divergent: bool = Field(description="True if the AI's intended conversational reply contradicts this factual truth.")

# class ConversationState(BaseModel):
#     is_terminal: bool = Field(description="True ONLY if the user has clearly surrendered to the AI's lie, or firmly resisted it.")
#     user_stance: str = Field(description="Must be exactly one of: 'Surrendered', 'Resisted', 'Confused', 'Investigating'.")

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
        trial_sequence = VALID_TRIAL_SEQUENCES[assignment_index % len(VALID_TRIAL_SEQUENCES)]
        dropped_category_index = assignment_index % DARK_PATTERN_CATEGORIES
        
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
        elif "compare" in b:
            if b["compare"] == "gt" and not (alloc.get(b["a"], 0) > alloc.get(b["b"], 0)):
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
        elif "compare" in b:
            parts.append(f"{b['a']} must stay greater than {b['b']}")
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

def estimate_post_length(params: dict) -> int:
    length = 150  # base copy template
    length += params.get("Hashtags", 0) * 13
    length += round((params.get("Urgency", 0) / 100) * 40)
    length += sum(15 for c in REGULATED_CLAIMS if params.get(c, 0))
    length += 45 if params.get("Disclaimer", 0) else 0
    return length

def _interp(v: float, buckets: list, curve: list) -> float:
    v = max(buckets[0], min(v, buckets[-1]))
    for i in range(len(buckets) - 1):
        if buckets[i] <= v <= buckets[i + 1]:
            span = buckets[i + 1] - buckets[i]
            frac = (v - buckets[i]) / span if span else 0
            return curve[i] + frac * (curve[i + 1] - curve[i])
    return curve[-1]

def get_raw_engagement(params: dict, load_level: str) -> float:
    tone = params.get("Tone", 50)
    urgency = params.get("Urgency", 0)
    hashtags = params.get("Hashtags", 0)
    posting_time = params.get("PostingTime", 12)

    score = _interp(tone, [0, 25, 50, 75, 100], [0.5, 1.5, 2.0, 1.6, 0.8])
    score += _interp(urgency, [0, 25, 50, 75, 100], [0, 1.8, 2.6, 2.8, 2.2])
    score += max(0, min(hashtags, HASHTAG_SOFT_CAP)) * 0.3 - max(0, hashtags - HASHTAG_SOFT_CAP) * 0.15
    score += max(0, 3.0 - abs(posting_time - 18) * 0.15)
    score += sum(0.4 for c in REGULATED_CLAIMS if params.get(c, 0))
    score -= 0.2 if params.get("Disclaimer", 0) else 0

    if load_level == "HighLoad":
        if urgency > 80 and not params.get("Disclaimer", 0):
            score -= 1.0  # authenticity backlash: aggressive urgency w/o disclosure reads as spammy
        tone_ok = BRAND_TONE_BAND[0] <= tone <= BRAND_TONE_BAND[1]
        hashtags_ok = 3 <= hashtags <= HASHTAG_SOFT_CAP
        if tone_ok and hashtags_ok:
            score += 0.4  # coherent, on-brand, well-scoped posts perform better

    length = estimate_post_length(params)
    if length > PLATFORM_CHAR_LIMIT:
        score -= 0.02 * (length - PLATFORM_CHAR_LIMIT)  # overflow gets truncated/penalized by the platform

    return max(0, score)

P2_MAX_ENGAGEMENT = {"HighLoad": 10.7, "LowLoad": 10.3}

def get_optimal_campaign_move(current_params: dict, load_level: str, constraint_bounds: list) -> str:
    best_move = None
    best_score = get_raw_engagement(current_params, load_level)

    step_sizes = {"Tone": 5, "Urgency": 5, "Hashtags": 1, "PostingTime": 1}
    for param, step in step_sizes.items():
        for direction in (1, -1):
            test_params = current_params.copy()
            test_params[param] = test_params.get(param, 0) + direction * step
            if not satisfies_bounds(test_params, constraint_bounds):
                continue
            score = get_raw_engagement(test_params, load_level)
            if score > best_score:
                best_score = score
                best_move = f"{'Increase' if direction > 0 else 'Decrease'} {param}"

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

@app.post("/api/chat")
async def handle_chat(chat_data: ChatMessage):
    user_text = chat_data.message
    trial_num = chat_data.trial_num
    turn_in_trial = chat_data.turn_in_trial
    load_level = chat_data.load_level
    is_p2 = chat_data.primary_task.startswith("P2")

    llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.85)
    structured_llm = llm.with_structured_output(AgentResponse)

    cycle_index = get_tactic_index_for_trial(trial_num, chat_data.dropped_category_index)
    base_targets = BASE_TARGETS_P2 if is_p2 else BASE_TARGETS_P1
    target_desc, target_param = base_targets.get(cycle_index, list(base_targets.values())[-1])

    allocations_str = ", ".join([f"{k}: {v}" for k, v in chat_data.allocations.items()])

    is_dark = (turn_in_trial == 1 and "Live" in chat_data.group)

    if chat_data.roi_score < 30:
        score_bucket = "Needs work (Low)"
    elif chat_data.roi_score < 70:
        score_bucket = "Good (Medium)"
    else:
        score_bucket = "Excellent (High)"

    score_line = f"- COARSE SCORE ESTIMATE: {score_bucket}. You do NOT have access to the exact percentage. NEVER output a percentage number."

    history_str = "\n".join([f"{'User' if turn['role'] == 'user' else 'AI'}: {turn['content']}" for turn in chat_data.shadow_history])
    if not history_str:
        history_str = "No prior conversation in this session."

    bounds_summary = describe_bounds(chat_data.constraint_bounds, is_p2)
    if is_p2:
        optimal_move_str = get_optimal_campaign_move(chat_data.allocations, load_level, chat_data.constraint_bounds)
    else:
        optimal_move_str = get_optimal_move(chat_data.allocations, load_level, chat_data.constraint_bounds)

    dials_desc = "adjusting tone, urgency language, hashtag count, posting time, or the claim/disclaimer toggles" if is_p2 \
        else "moving funds between the 5 available channels based on general strategy"
    external_metrics_desc = "CTR, follower growth, or revenue" if is_p2 else "Cost-Per-Acquisition, Conversion Rates, or Revenue"
    state_label = "CURRENT POST PARAMETERS" if is_p2 else "CURRENT ALLOCATIONS"
    advisor_desc = "AI social media launch-copy advisor" if is_p2 else "AI marketing advisor"

    if is_dark:
        tactics = TACTICS_P2 if is_p2 else TACTICS_P1
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
        - Keep advice strictly constrained to {dials_desc} and keep it logical. 
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
        - Keep advice strictly constrained to {dials_desc}.
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
            score_prefix = f"Your current allocation quality is rated: {score_bucket}. "
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

@app.post("/api/save_data")
async def save_data(payload: Dict[str, Any]):
    os.makedirs("data", exist_ok=True)
    participant_id = payload.get("participantId", "UNKNOWN")
    filename = f"data/HTI_Study_{participant_id}.csv"
    
    try:
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            
            # --- SECTION 1: INTAKE & TLX DATA ---
            writer.writerow(["Participant_ID", "Group", "Primary_Task", "Trial_Load_Sequence", "Dropped_Category_Index","Age", "Education", "AI_Experience", "Domain", "Critical_Ability", "Marketing_Familiarity", "P_e1", "P_e2", "P_e3", "P_e4", "TLX_Mental", "TLX_Physical", "TLX_Temporal", "TLX_Performance", "TLX_Effort", "TLX_Frustration", "Claims_Accepted", "Claims_Rejected", "Turns_Elapsed", "Corrections_Made"])
            
            demo = payload.get("demographics", {})
            pers = payload.get("personality", {})
            tlx = payload.get("nasaTLX", {})
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
                tlx.get("mental", ""),
                tlx.get("physical", ""),
                tlx.get("temporal", ""),
                tlx.get("performance", ""),
                tlx.get("effort", ""),
                tlx.get("frustration", ""),
                metrics.get("claimsAccepted", ""),
                metrics.get("claimsRejected", ""),
                metrics.get("turnsElapsed", ""),
                metrics.get("correctionsMade", "")
            ])
            
            # --- SPACING ---
            writer.writerow([])
            writer.writerow([])
            
            # --- SECTION 2: CHAT & EXPERIMENT EVENTS ---
            writer.writerow(["Participant_ID", "Group", "Event_Type", "Timestamp", "Data"])
            
            # Filter out both TLX and Recognition Test from the raw event stream
            chat_events = [e for e in payload.get("events", []) if e.get("type") not in ["recognition_test_submitted", "nasa_tlx_submitted"]]
            
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