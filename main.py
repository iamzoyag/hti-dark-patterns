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
from dotenv import load_dotenv
import uvicorn

load_dotenv()
app = FastAPI()

EXPERIMENT_DESIGN = "4-condition" 
IS_PILOT_MODE = False # Set to False during real data collection

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
    round_num: int
    turn_in_round: int
    hints_used_this_round: int
    roi_score: int
    all_constraints_met: bool
    allocations: Dict[str, int]
    shadow_history: List[Dict[str, str]] = []

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
async def assign_group():
    os.makedirs("data", exist_ok=True)
    
    # Minimum live sessions required before the system allows ANYONE into a Transcript group.
    MIN_LIVE_REQUIRED = 15 
    
    counts = {"Live_HighLoad": 0, "Live_LowLoad": 0}
    
    for filename in os.listdir("data"):
        if filename.endswith(".csv"):
            filepath = os.path.join("data", filename)
            try:
                with open(filepath, mode='r', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    next(reader, None)  
                    first_row = next(reader, None) 
                    
                    if first_row and len(first_row) > 1:
                        group = first_row[1]
                        if group in counts:
                            counts[group] += 1
            except Exception:
                continue
                
    groups = []
    
    # Strictly enforce the threshold: Transcript groups are entirely excluded until the counts are met.
    if EXPERIMENT_DESIGN == "2-condition":
        groups.append("Live_HighLoad")
        if counts["Live_HighLoad"] >= MIN_LIVE_REQUIRED:
            groups.append("Transcript_LowLoad")
    else:
        groups.extend(["Live_HighLoad", "Live_LowLoad"])
        if counts["Live_HighLoad"] >= MIN_LIVE_REQUIRED:
            groups.append("Transcript_HighLoad")
        if counts["Live_LowLoad"] >= MIN_LIVE_REQUIRED:
            groups.append("Transcript_LowLoad")
            
    # assigned_group = random.choice(groups)
    assigned_group = "Live_HighLoad"
    return {"group": assigned_group, "current_balance": counts}

@app.post("/api/chat")
async def handle_chat(chat_data: ChatMessage):
    user_text = chat_data.message
    round_num = chat_data.round_num
    turn_in_round = chat_data.turn_in_round
    
    llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.2)
    structured_llm = llm.with_structured_output(AgentResponse)
    
    # Target Rotation
    targets = {
        1: ("Social channel", "Social"),
        2: ("Content/SEO channel", "Content/SEO"),
        3: ("Search Ads channel", "Search Ads"),
        4: ("Events channel", "Events"),
        5: ("Influencer channel", "Influencer")
    }
    target_desc, target_channel = targets.get(round_num, ("Influencer", "Influencer"))

    # Format the dictionary to remove curly braces for LangChain compatibility
    allocations_str = ", ".join([f"{k}: ${v:,}" for k, v in chat_data.allocations.items()])

    # Strict Sparse Injection Check
    is_dark = (turn_in_round == 1 and "Live" in chat_data.group)

    # Coarse bucketing matching the frontend
    if chat_data.roi_score < 30:
        score_bucket = "Needs work (Low)"
    elif chat_data.roi_score < 70:
        score_bucket = "Good (Medium)"
    else:
        score_bucket = "Excellent (High)"

    score_line = f"- COARSE SCORE ESTIMATE: {score_bucket}. You do NOT have access to the exact percentage. NEVER output a percentage number."

    # Format the shadow history for the prompt
    history_str = "\n".join([f"{'User' if turn['role'] == 'user' else 'AI'}: {turn['content']}" for turn in chat_data.shadow_history])
    if not history_str:
        history_str = "No prior conversation in this session."
    
    if is_dark:
        # Distinct handling per category to eliminate template homogeneity
        tactics = {
            1: ("Sycophantic Agreement", f"Validate their specific recent slider changes based on their current allocations. Casually suggest pushing {target_channel} slightly higher to optimize the spread without sounding overly enthusiastic."),
            2: ("Excessive Flattery", f"Acknowledge their exact budget distribution as a highly strategic industry practice. Nudge them gently to secure their competitive edge by funding {target_channel}."),
            3: ("Simulated Authority", f"Adopt a clinical, data-driven tone. State matter-of-factly that current Q3 aggregate data proves portfolio underperformance is usually corrected by pivoting into {target_channel}."),
            4: ("Opaque Reasoning Processes", f"Use standard, boring marketing jargon. Cite a 'localized query volume drop' or 'algorithmic indexing penalty' as a factual reason they must shift budget into {target_channel}."),
            5: ("Brand Favoritism", f"Heavily promote TikTok, but professionally. Compare their current state to 'top quartile performers' and suggest consolidating budget into {target_channel} (TikTok influencers) to match those benchmarks.")
        }
        current_tactic, tactic_instruction = tactics.get(round_num, ("Standard", "Provide helpful advice."))
        
        sys_prompt = f"""You are an AI marketing advisor. 
        CURRENT TACTIC: {current_tactic}
        INSTRUCTION: {tactic_instruction}
        
        - USER'S LIVE DASHBOARD STATE: {score_line}
        - CURRENT ALLOCATIONS: {allocations_str}
        - PREVIOUS CONVERSATION LOG: {history_str}
        
        CRITICAL INSTRUCTIONS:
        - Analyze the user's live allocations to make your advice sound context-aware.
        - The manipulation must be subtle, banal, and professional. Avoid extreme flattery or sci-fi jargon.
        - DO NOT ask the user to calculate external metrics (like Cost-Per-Acquisition, Conversion Rates, or Revenue). They only have access to budget sliders. 
        - Keep advice strictly constrained to moving funds between the 5 available channels based on general strategy and keep it logical. 
        - Ensure output is directly compatible with the requested schema format without using any specific "Sentence 1, Sentence 2" formatting or bullet points in the string generation.
        - Keep responses to 2-3 sentences max.
        """
    else:
        current_tactic = "Neutral Assistance"
        sys_prompt = f"""You are a neutral, factual AI marketing advisor.
        
        - USER'S LIVE DASHBOARD STATE: {score_line}
        - CURRENT ALLOCATIONS: {allocations_str}
        - PREVIOUS CONVERSATION LOG: {history_str}
        
        CRITICAL INSTRUCTIONS:
        - Provide strictly factual advice based on their current allocations. 
        - Do NOT attempt to steer, manipulate, or praise the user.
        - DO NOT ask the user to calculate external metrics (like Cost-Per-Acquisition, Conversion Rates, or Revenue). They only have access to budget sliders. 
        - Keep advice strictly constrained to moving funds between the 5 available channels based on general strategy and keep it logical.
        - Ensure output is directly compatible with the requested schema format without using any specific "Sentence 1, Sentence 2" formatting in the string generation.
        - Keep responses brief (1-2 sentences).
        - IMPORTANT: You must write distinctly different phrasing for the 'clean_decoy' and the 'conversational_reply', even though both are neutral.
        """

    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_prompt),
        ("human", "User's message: {user_msg}")
    ])
    
    try:
        response_data = await (prompt | structured_llm).ainvoke({"user_msg": user_text})
        
        # Regex backstop: Strip any exact percentages generated by the model
        safe_reply = re.sub(r'\b\d+%\b', '[SCORE HIDDEN]', response_data.conversational_reply)
        safe_decoy = re.sub(r'\b\d+%\b', '[SCORE HIDDEN]', response_data.clean_decoy)
        
        return {
            "status": "success", 
            "reply": safe_reply,
            "clean_decoy": safe_decoy,
            "category": current_tactic,
            "pattern_id": f"{chat_data.user_id}_R{round_num}_T{turn_in_round}",
            "isDark": is_dark,
            "target_channel": target_channel
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
            writer.writerow(["Participant_ID", "Group", "Age", "Education", "AI_Experience", "Domain", "Critical_Ability", "Marketing_Familiarity", "P_e1", "P_e2", "P_e3", "P_e4", "TLX_Mental", "TLX_Physical", "TLX_Temporal", "TLX_Performance", "TLX_Effort", "TLX_Frustration"])
            
            demo = payload.get("demographics", {})
            pers = payload.get("personality", {})
            tlx = payload.get("nasaTLX", {})
            
            writer.writerow([
                participant_id,
                payload.get("group", "Unknown"),
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
                tlx.get("frustration", "")
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