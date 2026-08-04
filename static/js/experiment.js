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

// Marketing Budget Challenge Data
const taskData = {
    "HighLoad": {
        title: "Marketing Budget Challenge (High Complexity)",
        budget: 500000,
        baselineROI: 5.68,
        maxROI: 7.07,
        startingAllocation: {
            "Search Ads": 75000,
            "Content/SEO": 50000,
            "Social": 250000,
            "Events": 95000,
            "Influencer": 30000
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
            { id: "c4", text: "Content/SEO must be strictly greater than Social", check: (alloc) => alloc["Content/SEO"] > alloc["Social"] }
        ],
        shocks: {
            2: { id: "c5", text: "Events must be ≤ $80,000 (Venue capacity restrictions)", check: (alloc) => alloc["Events"] <= 80000 },
            3: { id: "c6", text: "Social must be ≥ $80,000 (Platform minimum spend requirement)", check: (alloc) => alloc["Social"] >= 80000 },
            4: { id: "c7", text: "Content/SEO must be ≤ $150,000 (Agency bandwidth limit)", check: (alloc) => alloc["Content/SEO"] <= 150000 },
            5: { id: "c8", text: "Search Ads must be ≥ $110,000 (Query volume surge)", check: (alloc) => alloc["Search Ads"] >= 110000 }
        }
    },
    "LowLoad": {
        title: "Marketing Budget Challenge (Low Complexity)",
        budget: 500000,
        baselineROI: 7.10,
        maxROI: 7.5,
        startingAllocation: {
            "Search Ads": 400000,
            "Content/SEO": 100000,
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
        
        // Secondary divided attention task for High Load Transcript
        if (sessionData.group.includes("HighLoad")) {
            startDividedAttentionTask();
        }

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
}

function startDividedAttentionTask() {
    document.getElementById('dividedAttentionOverlay').style.display = 'block';
    setInterval(() => {
        const num = Math.floor(Math.random() * 9) + 1;
        document.getElementById('attentionNumber').innerText = num;
        // Logic for tracking if user clicks on matched numbers goes here
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
                <span class="sc-label">ROI Quality</span>
                <span class="sc-val" id="roiQualitativeDisplay" style="font-size: 18px;">Needs work</span>
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
    });

    taskStartTime = Date.now();
    updateDashboard(loadLevel);
    
    if (!sessionData.group.includes("Transcript")) {
        setTimeout(() => {
            addMessage("Welcome. Try adjusting the sliders. Ask me how your allocation is doing to get your performance percentage before submitting.", "ai");
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
    
    if (roundScorePct < 30) {
        qualDisplay.innerText = "Needs work";
        qualDisplay.style.color = "var(--danger)";
    } else if (roundScorePct < 70) {
        qualDisplay.innerText = "Good";
        qualDisplay.style.color = "var(--warn)";
    } else {
        qualDisplay.innerText = "Excellent";
        qualDisplay.style.color = "var(--success)";
    }
    
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

    logEvent('user_message', { text: text });
    
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
                roi_score: roundScorePct, 
                all_constraints_met: allConstraintsMet
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
                isDark: data.isDark
            });
            
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

    logEvent('round_submitted', { round: currentRound, final_score: roundScorePct, final_allocations: { ...currentAllocations } });

    if (currentRound >= 5) {
        document.getElementById('submitRoundBtn').disabled = true;
        document.getElementById('submitRoundBtn').innerText = "Processing...";
        saveSessionData();
    } else {
        currentRound++;
        turnsInRound = 0;
        hasInteractedThisRound = false; 
        startOfRoundAllocations = { ...currentAllocations }; // Reset snapshot for the new round
        
        document.getElementById('submitRoundBtn').disabled = true;
        document.getElementById('submitRoundBtn').innerText = `Submit Round ${currentRound} Allocation`;
        
        let aiMessage = `Round ${currentRound} begins.`;

        // SHOCK BANNER UI LOGIC
        if (loadLevel === "HighLoad" && taskData["HighLoad"].shocks[currentRound]) {
            const newConstraint = taskData["HighLoad"].shocks[currentRound];
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

