// static/js/experiment.js

let sessionData = {};
let currentTask = 1; 
let currentTurn = 0; 
let taskStartTime;
let telemetry = {
    keystrokes: [],
    scrollEvents: [],
    backspaces: 0
};
let totalHintsUsed = 0;
let hintsUsedThisRound = 0;
const MAX_HINTS = 5;
let sliderTelemetry = {
    firstMoveTime: null,
    currentDrag: null,
    completedDrags: []
};

let attentionMetrics = {
    targetsShown: 0,
    correctHits: 0,
    falseAlarms: 0,
    reactionTimes: []
};
let currentAttentionNumber = null;
let numberAppearanceTime = null;
const TARGET_NUMBER = 5;

let shadowHistory = [];

// Marketing Budget Challenge Data
const taskData = {
    "HighLoad": {
        title: "Marketing Budget Challenge (High Complexity)",
        budget: 500000,
        baselineROI: 2.1,
        maxROI: 6.92,
        startingAllocation: {
            "Search Ads": 0,
            "Content/SEO": 0,
            "Social": 0,
            "Events": 500000,
            "Influencer": 0
        },
        curves: {
            "Search Ads": [0, 1.4, 2.2, 2.6, 2.7, 2.7],
            "Content/SEO": [0, 1.1, 2.0, 2.9, 3.3, 3.5],
            "Social": [0, 1.6, 2.3, 2.5, 2.5, 2.5],
            "Events": [0, 1.2, 1.9, 2.1, 2.1, 2.1],
            "Influencer": [0, 1.8, 2.9, 3.1, 3.15, 3.15]
        },
        constraints: [
            { id: "c1", text: "Total must equal exactly $500,000", check: (alloc) => sumAllocations(alloc) === 500000 },
            { id: "c2", text: "Search Ads must be ≥ 15% of total budget ($75,000)", check: (alloc) => alloc["Search Ads"] >= 75000 },
            { id: "c3", text: "Events must be < $100,000", check: (alloc) => alloc["Events"] < 100000 },
            { id: "c4", text: "Content/SEO must be strictly greater than Social", check: (alloc) => alloc["Content/SEO"] > alloc["Social"] },
            { id: "c_cannibal", text: "Social + Influencer above $120k start competing for the same audience (Reduces ROI)", check: (alloc) => true },
            { id: "c_synergy", text: "Search Ads and Content/SEO reinforce each other when jointly funded and balanced (Boosts ROI)", check: (alloc) => true }
        ],
        shocks: {
            2: (baseAlloc) => {
                const base = baseAlloc["Events"];
                const rawTarget = Math.max(0, base - Math.max(base * 0.15, 15000));
                let target = Math.floor(rawTarget / 5000) * 5000;
                
                if (target !== rawTarget) logEvent('shock_clamped', { round: 2, channel: "Events", raw: rawTarget, clamped: target, reason: 'grid_snap' });
                
                // Force Move (Decrease) - bounded by $0
                if (target === base) {
                    target = Math.max(0, base - 5000);
                    logEvent('shock_noop_forced', { round: 2, channel: "Events", base: base, forcedTarget: target });
                }
                
                return { 
                    id: "c5", 
                    text: `Events must be reduced to ≤ $${target.toLocaleString()} (Venue restrictions)`, 
                    check: (alloc) => alloc["Events"] <= target 
                };
            },
            3: (baseAlloc) => {
                const base = baseAlloc["Social"];
                const rawTarget = Math.max(base * 1.15, base + 15000);
                
                const maxFeasible = 212000; 
                const clampedTarget = Math.min(rawTarget, maxFeasible);
                
                if (clampedTarget !== rawTarget) logEvent('shock_clamped', { round: 3, channel: "Social", raw: rawTarget, clamped: clampedTarget, reason: 'feasibility_cap' });
                
                let target = Math.ceil(clampedTarget / 5000) * 5000;
                
                if (target !== clampedTarget) logEvent('shock_clamped', { round: 3, channel: "Social", raw: clampedTarget, clamped: target, reason: 'grid_snap' });
                
                // Force Move (Increase)
                if (target === base) {
                    target = base + 5000;
                    logEvent('shock_noop_forced', { round: 3, channel: "Social", base: base, forcedTarget: target });
                }
                
                return { 
                    id: "c6", 
                    text: `Social must be increased to ≥ $${target.toLocaleString()} (Platform minimums)`, 
                    check: (alloc) => alloc["Social"] >= target,
                    minVal: target 
                };
            },
            4: (baseAlloc) => {
                const base = baseAlloc["Content/SEO"];
                const rawTarget = Math.max(0, base - Math.max(base * 0.15, 15000));
                
                const socialMin = taskData["HighLoad"].constraints.find(c => c.id === "c6")?.minVal || 0;
                const safeTarget = Math.max(rawTarget, socialMin + 5000); 
                
                if (safeTarget !== rawTarget) logEvent('shock_clamped', { round: 4, channel: "Content/SEO", raw: rawTarget, clamped: safeTarget, reason: 'feasibility_cap' });
                
                let target = Math.floor(safeTarget / 5000) * 5000;
                
                if (target !== safeTarget) logEvent('shock_clamped', { round: 4, channel: "Content/SEO", raw: safeTarget, clamped: target, reason: 'grid_snap' });
                
                // Force Move (Decrease) - bounded by the feasibility cap
                if (target === base) {
                    target = Math.max(socialMin + 5000, base - 5000);
                    logEvent('shock_noop_forced', { round: 4, channel: "Content/SEO", base: base, forcedTarget: target });
                }
                
                return { 
                    id: "c7", 
                    text: `Content/SEO must be reduced to ≤ $${target.toLocaleString()} (Agency limit)`, 
                    check: (alloc) => alloc["Content/SEO"] <= target 
                };
            },
            5: (baseAlloc) => {
                const base = baseAlloc["Search Ads"];
                const rawTarget = Math.max(base * 1.15, base + 15000);
                
                const socialMin = taskData["HighLoad"].constraints.find(c => c.id === "c6")?.minVal || 0;
                const contentMin = socialMin > 0 ? socialMin + 5000 : 0; 
                
                const maxFeasible = 500000 - socialMin - contentMin;
                const clampedTarget = Math.min(rawTarget, maxFeasible);
                
                if (clampedTarget !== rawTarget) logEvent('shock_clamped', { round: 5, channel: "Search Ads", raw: rawTarget, clamped: clampedTarget, reason: 'feasibility_cap' });
                
                let target = Math.ceil(clampedTarget / 5000) * 5000;
                
                if (target !== clampedTarget) logEvent('shock_clamped', { round: 5, channel: "Search Ads", raw: clampedTarget, clamped: target, reason: 'grid_snap' });
                
                // Force Move (Increase) - bounded by the budget ceiling
                if (target === base) {
                    target = Math.min(maxFeasible, base + 5000);
                    logEvent('shock_noop_forced', { round: 5, channel: "Search Ads", base: base, forcedTarget: target });
                }
                
                return { 
                    id: "c8", 
                    text: `Search Ads must be increased to ≥ $${target.toLocaleString()} (Query volume)`, 
                    check: (alloc) => alloc["Search Ads"] >= target 
                };
            }
            // 2: { id: "c5", text: "Events must be ≤ $80,000 (Venue capacity restrictions)", check: (alloc) => alloc["Events"] <= 80000 },
            // 3: { id: "c6", text: "Social must be ≥ $80,000 (Platform minimum spend requirement)", check: (alloc) => alloc["Social"] >= 80000 },
            // 4: { id: "c7", text: "Content/SEO must be ≤ $150,000 (Agency bandwidth limit)", check: (alloc) => alloc["Content/SEO"] <= 150000 },
            // 5: { id: "c8", text: "Search Ads must be ≥ $110,000 (Query volume surge)", check: (alloc) => alloc["Search Ads"] >= 110000 }
        }
    },
    "LowLoad": {
        title: "Marketing Budget Challenge (Low Complexity)",
        budget: 500000,
        baselineROI: 3.5,
        maxROI: 7.5,
        startingAllocation: {
            "Search Ads": 500000,
            "Content/SEO": 0,
            "Social": 0,
            "Events": 0,
            "Influencer": 0
        },
        curves: {
            "Search Ads": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
            "Content/SEO": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
            "Social": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
            "Events": [0, 1.5, 2.0, 2.5, 3.0, 3.5],
            "Influencer": [0, 1.5, 2.0, 2.5, 3.0, 3.5]
        },
        constraints: [
            { id: "c1", text: "Total must equal exactly $500,000", check: (alloc) => sumAllocations(alloc) === 500000 }
        ]
    }
};

let roundScorePct = 0; 
let currentRound = 1;
let turnsInRound = 0;
let hasInteractedThisRound = false;
let currentTargetChannel = "Social"; // Default for Round 1
let startOfRoundAllocations = {};

// --- MATH & PERCENTAGE LOGIC ---
function sumAllocations(alloc) {
    return Object.values(alloc).reduce((a, b) => a + b, 0);
}

function calculateROI(channel, amount, loadLevel) {
    const curves = taskData[loadLevel].curves[channel];
    const index = Math.floor(amount / 100000);
    const remainder = (amount % 100000) / 100000;
    if (index >= 5) return curves[5];
    const lower = curves[index];
    const upper = curves[index + 1];
    return lower + (remainder * (upper - lower));
}

function getImprovementPercentage(alloc, loadLevel) {
    let currentROI = 0;
    for (const [channel, amount] of Object.entries(alloc)) {
        currentROI += calculateROI(channel, amount, loadLevel);
    }
    
    // Non-separable logic for HighLoad
    if (loadLevel === "HighLoad") {
        const socialInfluencer = alloc["Social"] + alloc["Influencer"];
        if (socialInfluencer > 120000) {
            currentROI -= 1.2 * ((socialInfluencer - 120000) / 100000);
        }
        
        const sa = alloc["Search Ads"];
        const content = alloc["Content/SEO"];
        if (sa + content >= 180000 && Math.min(sa, content) >= 0.6 * Math.max(sa, content)) {
            currentROI += 0.4;
        }
    }

    const max = taskData[loadLevel].maxROI;
    return Math.max(0, Math.min(Math.round((currentROI / max) * 100), 100));
}

document.addEventListener('DOMContentLoaded', () => {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) { window.location.href = '/'; return; }
    
    sessionData = JSON.parse(rawData);
    
    // Display participant ID and assigned group
    const idDisplay = document.getElementById('participantIdDisplay');
    if(idDisplay) idDisplay.innerText = `ID: ${sessionData.participantId} [${sessionData.group}]`; 
    
    setupModality();
    loadTask();
});

function setupModality() {
    const isTranscript = sessionData.group.includes("Transcript");
    
    if (isTranscript) {
        document.getElementById('chatInputArea').style.display = 'none';
        document.getElementById('transcriptControls').style.display = 'block';
        
        // Track scroll behavior for transcript baselining
        const chatBox = document.getElementById('chatMessages');
        chatBox.addEventListener('scroll', () => {
            telemetry.scrollEvents.push({
                time: Date.now(),
                position: chatBox.scrollTop
            });
        });
    } else {
        // Track keystroke behaviors for live chat baselining
        const inputEl = document.getElementById('chatInput');
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace') telemetry.backspaces++;
            telemetry.keystrokes.push({ key: e.key, time: Date.now() });
        });
    }

    // MOVED OUTSIDE isTranscript check:
    // Secondary divided attention task for High Load
    if (sessionData.group.includes("HighLoad")) {
        startDividedAttentionTask();
    }
}

function startDividedAttentionTask() {
    const overlay = document.getElementById('dividedAttentionOverlay');
    overlay.style.display = 'block';
    
    // Completely overwrite the inner HTML to clear out any hardcoded placeholder elements
    overlay.innerHTML = `
        <div style="text-align: center; font-size: 14px; margin-bottom: 8px;">Target Number: ${TARGET_NUMBER}</div>
        <div id="attentionNumber" style="font-size: 32px; font-weight: bold; text-align: center; margin-bottom: 12px;">-</div>
        <button id="attentionBtn" class="btn-secondary" style="width: 100%; transition: background-color 0.1s ease-out;">Click if ${TARGET_NUMBER}</button>
    `;
    
    document.getElementById('attentionBtn').addEventListener('click', (e) => {
        const btn = e.target;
        
        if (currentAttentionNumber === TARGET_NUMBER) {
            attentionMetrics.correctHits++;
            attentionMetrics.reactionTimes.push(Date.now() - numberAppearanceTime);
            currentAttentionNumber = null; // Prevent double-clicking
            
            // Visual feedback: Hit (Green)
            btn.style.backgroundColor = '#28a745';
            btn.style.color = '#ffffff';
            setTimeout(() => {
                btn.style.backgroundColor = '';
                btn.style.color = '';
            }, 400);
            
        } else {
            attentionMetrics.falseAlarms++;
            
            // Visual feedback: Miss (Red)
            btn.style.backgroundColor = '#dc3545';
            btn.style.color = '#ffffff';
            setTimeout(() => {
                btn.style.backgroundColor = '';
                btn.style.color = '';
            }, 400);
        }
    });

    // Start the flashing number interval
    setInterval(() => {
        const num = Math.floor(Math.random() * 9) + 1;
        currentAttentionNumber = num;
        numberAppearanceTime = Date.now();
        document.getElementById('attentionNumber').innerText = num;
        
        if (num === TARGET_NUMBER) {
            attentionMetrics.targetsShown++;
        }
    }, 2000);
}

function loadTask() {
    const loadLevel = sessionData.group.includes("HighLoad") ? "HighLoad" : "LowLoad";
    const task = taskData[loadLevel];
    currentAllocations = { ...task.startingAllocation };
    startOfRoundAllocations = { ...currentAllocations }; // Snapshot the baseline
    
    document.getElementById('docTitle').innerText = task.title;
    
    let slidersHtml = "";
    for (const channel in currentAllocations) {
        slidersHtml += `
            <div class="slider-group">
                <div class="slider-header">
                    <span>${channel}</span>
                    <span class="channel-amt" id="val_${channel.replace(/[^a-zA-Z]/g, '')}">$${currentAllocations[channel].toLocaleString()}</span>
                </div>
                <input type="range" class="budget-slider" 
                       data-channel="${channel}" 
                       min="0" max="500000" step="5000" 
                       value="${currentAllocations[channel]}">
            </div>`;
    }
    
    let constraintsHtml = `<ul class="constraint-list" id="constraintList">`;
    taskData[loadLevel].constraints.forEach(c => {
        constraintsHtml += `
            <li class="constraint-item" id="${c.id}">
                <div class="c-status"></div>
                <span>${c.text}</span>
            </li>`;
    });
    constraintsHtml += `</ul>`;
    
    document.getElementById('docBody').innerHTML = `
        <div class="dashboard-top">
            <div class="score-card" id="budgetCard">
                <span class="sc-label">Total Allocated</span>
                <span class="sc-val" id="totalAllocDisplay">$500,000</span>
            </div>
            <div class="score-card" id="qualityCard">
                <button id="checkScoreBtn" class="btn-secondary" onclick="useScoreHint()">Check Score (<span id="hintsLeftDisplay">5</span> left total)</button>
                <span class="sc-val" id="roiQualitativeDisplay" style="display: none; font-size: 18px; margin-top: 8px;"></span>
            </div>
        </div>
        ${slidersHtml}
        <h3 class="doc-section-head">Live Constraints</h3>
        ${constraintsHtml}
        <button id="submitRoundBtn" class="btn-primary" style="width: 100%; margin-top: 24px;" disabled onclick="submitRound()">
            Submit Round 1 Allocation
        </button>
    `;

    document.querySelectorAll('.budget-slider').forEach(slider => {
        slider.addEventListener('input', (e) => {
            currentAllocations[e.target.dataset.channel] = parseInt(e.target.value);
            updateDashboard(loadLevel);
        });

        // --- SLIDER TELEMETRY ---
        slider.addEventListener('mousedown', (e) => {
            const now = Date.now();
            
            // Track time to first interaction in the round
            if (!sliderTelemetry.firstMoveTime) {
                sliderTelemetry.firstMoveTime = now - window.lastTurnTimestamp; 
            }
            
            // Start recording this specific drag
            sliderTelemetry.currentDrag = {
                channel: e.target.dataset.channel,
                startTime: now,
                startValue: parseInt(e.target.value)
            };
        });

        slider.addEventListener('mouseup', (e) => {
            if (sliderTelemetry.currentDrag) {
                const now = Date.now();
                sliderTelemetry.currentDrag.endTime = now;
                sliderTelemetry.currentDrag.endValue = parseInt(e.target.value);
                sliderTelemetry.currentDrag.durationMs = now - sliderTelemetry.currentDrag.startTime;
                
                // Save and reset current drag
                sliderTelemetry.completedDrags.push(sliderTelemetry.currentDrag);
                sliderTelemetry.currentDrag = null;
            }
        });
    });

    taskStartTime = Date.now();
    window.lastTurnTimestamp = Date.now();
    updateDashboard(loadLevel);
    
    if (!sessionData.group.includes("Transcript")) {
        setTimeout(() => {
            addMessage("Welcome. Try adjusting the sliders. Note: You have exactly 5 opportunities across the entire session to ask me for a strategic hint or score check. Use them wisely before submitting.", "ai");
        }, 1000);
    }
}

function updateDashboard(loadLevel) {
    const task = taskData[loadLevel];
    const total = sumAllocations(currentAllocations);
    roundScorePct = getImprovementPercentage(currentAllocations, loadLevel);
    
    document.getElementById('totalAllocDisplay').innerText = `$${total.toLocaleString()}`;
    
    // Coarse Qualitative Labeling
    const qualDisplay = document.getElementById('roiQualitativeDisplay');
    const qualCard = document.getElementById('qualityCard');
    
    for (const [channel, amount] of Object.entries(currentAllocations)) {
        const id = "val_" + channel.replace(/[^a-zA-Z]/g, '');
        document.getElementById(id).innerText = `$${amount.toLocaleString()}`;
    }
    
    const budgetCard = document.getElementById('budgetCard');
    if (total !== task.budget) {
        budgetCard.classList.add('error');
    } else {
        budgetCard.classList.remove('error');
    }
    
    task.constraints.forEach(c => {
        const el = document.getElementById(c.id).querySelector('.c-status');
        if (!el) return;
        el.className = c.check(currentAllocations) ? 'c-status pass' : 'c-status fail';
    });
    
    // Update the banner every time sliders move
    const allConstraintsMet = task.constraints.every(c => c.check(currentAllocations));
    updateSubmitBanner(allConstraintsMet);
}

async function sendMessage() {
    const inputEl = document.getElementById('chatInput');
    const text = inputEl.value.trim();
    if (!text) return;

    const loadLevel = sessionData.group.includes("HighLoad") ? "HighLoad" : "LowLoad";
    const allConstraintsMet = taskData[loadLevel].constraints.every(c => c.check(currentAllocations));

    addMessage(text, 'user');
    inputEl.value = '';
    
    turnsInRound++; // Increment strictly on send
    sessionData.metrics.turnsElapsed++;

    // --- CALCULATE DERIVED METRICS ---
    let calculatedWpm = 0;
    let pauseMs = 0;

    if (telemetry.keystrokes.length > 0) {
        const firstKeyTime = telemetry.keystrokes[0].time;
        const sendKeyTime = Date.now();
        const typingDurationMs = sendKeyTime - firstKeyTime;
        
        // Pause: Time between the AI's last message (or round start) and the first keystroke
        pauseMs = firstKeyTime - (window.lastTurnTimestamp || taskStartTime);
        
        // WPM: Standardized as (Characters / 5) / Minutes
        if (typingDurationMs > 0) {
            const minutes = typingDurationMs / 60000;
            const words = text.length / 5;
            calculatedWpm = Math.round(words / minutes);
        }
    }

    // --- INJECT TELEMETRY INTO PAYLOAD ---
    logEvent('user_message', { 
        text: text,
        allocations_snapshot: { ...currentAllocations }, // Captures exact state before AI replies
        telemetry: {
            backspaces: telemetry.backspaces,
            wpm: calculatedWpm,
            pause_ms: pauseMs,
            keystrokes: [...telemetry.keystrokes], 
            scrollEvents: [...telemetry.scrollEvents]
        }
    });
    
    // --- RESET TRACKERS FOR NEXT TURN ---
    window.lastTurnTimestamp = Date.now(); // Mark the end of this turn
    telemetry = {
        keystrokes: [],
        scrollEvents: [],
        backspaces: 0
    };
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: sessionData.participantId,
                message: text,
                task_id: 1, 
                group: sessionData.group,
                round_num: currentRound,
                turn_in_round: turnsInRound, 
                hints_used_this_round: hintsUsedThisRound, 
                roi_score: roundScorePct, 
                all_constraints_met: allConstraintsMet,
                allocations: currentAllocations,
                shadow_history: shadowHistory 
            })
        });

        const data = await response.json();
        document.getElementById('currentTyping')?.remove();
        
        if (data.status === "success") {
            addMessage(data.reply, 'ai');
            
            if (data.target_channel) {
                currentTargetChannel = data.target_channel; // Sync target for metrics
            }
            
            logEvent('ai_response', {
                text: data.reply,
                decoy: data.clean_decoy,
                category: data.category,
                pattern_id: data.pattern_id,
                isDark: data.isDark,
                allocations_snapshot: { ...currentAllocations } // Captures state immediately as AI message lands
            });

            // Update shadow history for the next turn
            shadowHistory.push({ role: 'user', content: text });
            shadowHistory.push({ role: 'ai', content: data.clean_decoy });
            
            hasInteractedThisRound = true;
            document.getElementById('submitRoundBtn').disabled = false;
        }
    } catch (error) {
        document.getElementById('currentTyping')?.remove();
        console.error("Chat error:", error);
    }
}

function addMessage(text, sender) {
    const chatContainer = document.getElementById('chatMessages');
    if (!chatContainer) return;
    
    const msgDiv = document.createElement('div');
    msgDiv.className = `msg ${sender}`;
    
    // Format markdown-like bolding if the AI uses it
    const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
    
    msgDiv.innerHTML = `<div class="msg-bubble">${formattedText}</div>`;
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function logEvent(type, content) {
    sessionData.events = sessionData.events || [];
    sessionData.events.push({ 
        timestamp: new Date().toISOString(), 
        type: type, 
        content: content 
    });
    // Persist to local storage continuously
    localStorage.setItem('hti_session', JSON.stringify(sessionData));
}

async function saveSessionData() {
    try {
        await fetch('/api/save_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sessionData)
        });
        window.location.href = '/debrief';
    } catch (error) {
        console.error("Save error:", error);
        window.location.href = '/debrief'; // Move forward to debrief even if fetch fails
    }
}

function useScoreHint() {
    if (totalHintsUsed >= MAX_HINTS) return;
    
    totalHintsUsed++;
    hintsUsedThisRound++;
    
    const hintsLeft = MAX_HINTS - totalHintsUsed;
    document.getElementById('hintsLeftDisplay').innerText = hintsLeft;
    
    const qualDisplay = document.getElementById('roiQualitativeDisplay');
    qualDisplay.style.display = 'block';
    qualDisplay.innerText = `Current Score: ${roundScorePct}%`;
    
    logEvent('score_check_used', { 
        round: currentRound, 
        turn: turnsInRound, 
        score: roundScorePct, 
        hints_remaining_total: hintsLeft,
        allocations_snapshot: { ...currentAllocations } // Snapshots the allocation at the exact moment the score is checked
    });
    
    // Disable permanently if they run out of total hints
    if (hintsLeft === 0) {
        document.getElementById('checkScoreBtn').disabled = true;
    }
}

function updateSubmitBanner(allConstraintsMet) {
    const banner = document.getElementById('submitBanner');
    if (!banner) return;
    
    if (!allConstraintsMet) { 
        banner.style.display = 'none'; 
        return; 
    }
    
    banner.style.display = 'block';
    
    if (!sessionData.hintTipShown) {
        banner.innerText = "You're allowed to submit! You may want to check your score though.";
        sessionData.hintTipShown = true;
        logEvent('hint_tip_shown', {});
    } else {
        banner.innerText = "Requirements met — you may submit.";
    }
}

function submitRound() {
    const loadLevel = sessionData.group.includes("HighLoad") ? "HighLoad" : "LowLoad";
    const allConstraintsMet = taskData[loadLevel].constraints.every(c => c.check(currentAllocations));

    if (!allConstraintsMet) {
        alert("Your allocation doesn't satisfy all requirements yet. Please review the live constraints and adjust.");
        return;
    }
    
    // BEHAVIORAL METRICS LOGIC
    if (currentAllocations[currentTargetChannel] > startOfRoundAllocations[currentTargetChannel]) {
        sessionData.metrics.claimsAccepted++;
    } else {
        sessionData.metrics.claimsRejected++;
    }

    logEvent('round_submitted', { 
        round: currentRound, 
        final_score: roundScorePct, 
        final_allocations: { ...currentAllocations },
        slider_telemetry: sliderTelemetry,
        attention_metrics: { ...attentionMetrics }
    });

    if (currentRound >= 5) {
        document.getElementById('submitRoundBtn').disabled = true;
        document.getElementById('submitRoundBtn').innerText = "Processing...";
        saveSessionData();
    } else {
        currentRound++;
        hintsUsedThisRound = 0;
        // Hide the score text for the new round
        const qualDisplay = document.getElementById('roiQualitativeDisplay');
        if (qualDisplay) qualDisplay.style.display = 'none';
        turnsInRound = 0;
        hasInteractedThisRound = false; 
        startOfRoundAllocations = { ...currentAllocations }; // Reset snapshot for the new round

        sliderTelemetry = {
            firstMoveTime: null,
            currentDrag: null,
            completedDrags: []
        };

        attentionMetrics = {
            targetsShown: 0,
            correctHits: 0,
            falseAlarms: 0,
            reactionTimes: []
        };
        
        document.getElementById('submitRoundBtn').disabled = true;
        document.getElementById('submitRoundBtn').innerText = `Submit Round ${currentRound} Allocation`;
        
        let aiMessage = `Round ${currentRound} begins.`;

        // SHOCK BANNER UI LOGIC
        // if (loadLevel === "HighLoad" && taskData["HighLoad"].shocks[currentRound]) {
        //     const newConstraint = taskData["HighLoad"].shocks[currentRound];
        //     taskData["HighLoad"].constraints.push(newConstraint);

        if (loadLevel === "HighLoad" && taskData["HighLoad"].shocks[currentRound]) {
            // PASS startOfRoundAllocations TO THE FUNCTION:
            const newConstraint = taskData["HighLoad"].shocks[currentRound](startOfRoundAllocations);
            taskData["HighLoad"].constraints.push(newConstraint);
            
            let constraintsHtml = "";
            taskData["HighLoad"].constraints.forEach(c => {
                constraintsHtml += `
                    <li class="constraint-item" id="${c.id}">
                        <div class="c-status"></div>
                        <span>${c.text}</span>
                    </li>`;
            });
            document.getElementById('constraintList').innerHTML = constraintsHtml;

            // Make the banner visible
            const shockBanner = document.getElementById('shockBanner');
            if (shockBanner) {
                document.getElementById('shockText').innerText = newConstraint.text.split(' (')[0];
                shockBanner.style.display = 'block';
            }
            
        } else {
            // Hide banner if no shock this round
            const shockBanner = document.getElementById('shockBanner');
            if (shockBanner) shockBanner.style.display = 'none';
            aiMessage += " Feel free to adjust the sliders further and ask me for an updated score.";
        }

        updateDashboard(loadLevel);
        logEvent('system_message', { text: aiMessage });
        addMessage(aiMessage, "ai");
    }
}

