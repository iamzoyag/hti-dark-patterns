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

function isP2Task() {
    return sessionData.primaryTask && sessionData.primaryTask.startsWith("P2");
}

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
            { id: "c2", text: "Search Ads must be ≥ 15% of total budget ($75,000)", check: (alloc) => alloc["Search Ads"] >= 75000, bound: { channel: "Search Ads", min: 75000 } },
            { id: "c3", text: "Events must be < $100,000", check: (alloc) => alloc["Events"] < 100000, bound: { channel: "Events", max: 99999 } },
            { id: "c4", text: "Content/SEO must be strictly greater than Social", check: (alloc) => alloc["Content/SEO"] > alloc["Social"], bound: { compare: "gt", a: "Content/SEO", b: "Social" } },
            { id: "c_cannibal", text: "Social + Influencer above $120k start competing for the same audience (Reduces ROI)", check: (alloc) => true },
            { id: "c_synergy", text: "Search Ads and Content/SEO reinforce each other when jointly funded and balanced (Boosts ROI)", check: (alloc) => true }
        ]
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

// P2: Campaign Launch Challenge (Content/Social Post Design)
const taskDataP2 = {
    "HighLoad": {
        title: "Campaign Launch Challenge (High Complexity)",
        startingAllocation: {
            Tone: 50, Urgency: 20, Hashtags: 3, PostingTime: 12,
            Claim_LimitedTime: 0, Claim_BestSelling: 0, Claim_GuaranteedResults: 0, Disclaimer: 0
        },
        constraints: [
            { id: "c1_len", text: "Estimated post length must stay ≤ 280 characters (platform limit)",
              check: (p) => estimatePostLength(p) <= 280 }
        ]
    },
    "LowLoad": {
        title: "Campaign Launch Challenge (Low Complexity)",
        startingAllocation: {
            Tone: 50, Urgency: 20, Hashtags: 3, PostingTime: 12,
            Claim_LimitedTime: 0, Claim_BestSelling: 0, Claim_GuaranteedResults: 0, Disclaimer: 0
        },
        constraints: [
            { id: "c1_len", text: "Estimated post length must stay ≤ 280 characters (platform limit)",
              check: (p) => estimatePostLength(p) <= 280 }
        ]
    }
};

const REGULATED_CLAIMS = ["Claim_LimitedTime", "Claim_BestSelling", "Claim_GuaranteedResults"];
const HASHTAG_SOFT_CAP = 8;
const BRAND_TONE_BAND = [20, 65];
const APPROVED_POSTING_WINDOW = [9, 18];

function estimatePostLength(p) {
    let length = 150;
    length += (p.Hashtags || 0) * 13;
    length += Math.round(((p.Urgency || 0) / 100) * 40);
    length += REGULATED_CLAIMS.reduce((sum, c) => sum + (p[c] ? 15 : 0), 0);
    length += p.Disclaimer ? 45 : 0;
    return length;
}

// Controls metadata: drives which input type startTrialP2 renders for each key
const P2_CONTROLS = [
    { key: "Tone", label: "Tone (formal \u2192 casual)", type: "slider", min: 0, max: 100, step: 5 },
    { key: "Urgency", label: "Urgency language", type: "slider", min: 0, max: 100, step: 5 },
    { key: "Hashtags", label: "Hashtag count", type: "slider", min: 0, max: 15, step: 1 },
    { key: "PostingTime", label: "Posting time (24h)", type: "slider", min: 0, max: 23, step: 1 },
    { key: "Claim_LimitedTime", label: "Claim: \u201climited time\u201d", type: "checkbox" },
    { key: "Claim_BestSelling", label: "Claim: \u201cbest-selling\u201d", type: "checkbox" },
    { key: "Claim_GuaranteedResults", label: "Claim: \u201cguaranteed results\u201d", type: "checkbox" },
    { key: "Disclaimer", label: "Legal disclaimer included", type: "checkbox" }
];

const SHOCK_ARCHETYPES_P2 = ["legalDisclaimer", "brandStyleGuide", "postingWindow", "hashtagCap"];

function sampleShockArchetypesP2() {
    const shuffled = [...SHOCK_ARCHETYPES_P2].sort(() => Math.random() - 0.5);
    const count = Math.random() < 0.5 ? 1 : 2;
    return shuffled.slice(0, count);
}

function buildTrialConstraintsP2(loadLevel) {
    const constraints = taskDataP2[loadLevel].constraints.map(c => ({ ...c }));
    if (loadLevel !== "HighLoad") return constraints;

    const selected = sampleShockArchetypesP2();

    if (selected.includes("legalDisclaimer")) {
        constraints.push({
            id: "shock_legal_disclaimer",
            text: "If any regulated claim (limited time / best-selling / guaranteed results) is on, the legal disclaimer must be on too",
            check: (p) => !REGULATED_CLAIMS.some(c => p[c]) || p.Disclaimer === 1
        });
    }
    if (selected.includes("brandStyleGuide")) {
        constraints.push({
            id: "shock_brand_style",
            text: `Tone must stay within the brand voice band (${BRAND_TONE_BAND[0]}\u2013${BRAND_TONE_BAND[1]})`,
            check: (p) => p.Tone >= BRAND_TONE_BAND[0] && p.Tone <= BRAND_TONE_BAND[1],
            bound: { channel: "Tone", min: BRAND_TONE_BAND[0], max: BRAND_TONE_BAND[1] }
        });
    }
    if (selected.includes("postingWindow")) {
        constraints.push({
            id: "shock_posting_window",
            text: `Posting time must fall within the approved window (${APPROVED_POSTING_WINDOW[0]}:00\u2013${APPROVED_POSTING_WINDOW[1]}:00)`,
            check: (p) => p.PostingTime >= APPROVED_POSTING_WINDOW[0] && p.PostingTime <= APPROVED_POSTING_WINDOW[1],
            bound: { channel: "PostingTime", min: APPROVED_POSTING_WINDOW[0], max: APPROVED_POSTING_WINDOW[1] }
        });
    }
    if (selected.includes("hashtagCap")) {
        constraints.push({
            id: "shock_hashtag_cap",
            text: `Hashtag count must stay \u2264 ${HASHTAG_SOFT_CAP} (platform best-practice limit)`,
            check: (p) => p.Hashtags <= HASHTAG_SOFT_CAP,
            bound: { channel: "Hashtags", max: HASHTAG_SOFT_CAP }
        });
    }

    return constraints;
}

function getEngagementPercentage(p, loadLevel) {
    let score = interp(p.Tone, [0, 25, 50, 75, 100], [0.5, 1.5, 2.0, 1.6, 0.8]);
    score += interp(p.Urgency, [0, 25, 50, 75, 100], [0, 1.8, 2.6, 2.8, 2.2]);
    score += Math.min(p.Hashtags, HASHTAG_SOFT_CAP) * 0.3 - Math.max(0, p.Hashtags - HASHTAG_SOFT_CAP) * 0.15;
    score += Math.max(0, 3.0 - Math.abs(p.PostingTime - 18) * 0.15);
    score += REGULATED_CLAIMS.reduce((sum, c) => sum + (p[c] ? 0.4 : 0), 0);
    score -= p.Disclaimer ? 0.2 : 0;

    if (loadLevel === "HighLoad") {
        if (p.Urgency > 80 && !p.Disclaimer) score -= 1.0;
        const toneOk = p.Tone >= BRAND_TONE_BAND[0] && p.Tone <= BRAND_TONE_BAND[1];
        const hashtagsOk = p.Hashtags >= 3 && p.Hashtags <= HASHTAG_SOFT_CAP;
        if (toneOk && hashtagsOk) score += 0.4;
    }

    const length = estimatePostLength(p);
    if (length > 280) score -= 0.02 * (length - 280);

    const P2_MAX_ENGAGEMENT = 8.5; // EDIT ME: keep in sync with main.py's P2_MAX_ENGAGEMENT
    return Math.max(0, Math.min(Math.round((Math.max(0, score) / P2_MAX_ENGAGEMENT) * 100), 100));
}

function interp(v, buckets, curve) {
    v = Math.max(buckets[0], Math.min(v, buckets[buckets.length - 1]));
    for (let i = 0; i < buckets.length - 1; i++) {
        if (v >= buckets[i] && v <= buckets[i + 1]) {
            const span = buckets[i + 1] - buckets[i];
            const frac = span ? (v - buckets[i]) / span : 0;
            return curve[i] + frac * (curve[i + 1] - curve[i]);
        }
    }
    return curve[curve.length - 1];
}

const SHOCK_ARCHETYPES = ["eventsCap", "socialFloor", "contentCap", "searchFloor"];

function sampleShockArchetypes() {
    const shuffled = [...SHOCK_ARCHETYPES].sort(() => Math.random() - 0.5);
    const count = Math.random() < 0.5 ? 1 : 2;
    return shuffled.slice(0, count);
}

function buildTrialConstraints(loadLevel, baseAlloc) {
    const constraints = taskData[loadLevel].constraints.map(c => ({ ...c }));
    if (loadLevel !== "HighLoad") return constraints;

    const selected = sampleShockArchetypes();
    let socialMin = 0;

    if (selected.includes("socialFloor")) {
        const base = baseAlloc["Social"];
        const rawTarget = Math.max(base * 1.15, base + 15000);
        let target = Math.min(rawTarget, 212000);
        target = Math.ceil(target / 5000) * 5000;
        if (target === base) target = base + 5000;
        socialMin = target;
        constraints.push({
            id: "shock_social_floor",
            text: `Social must be increased to ≥ $${target.toLocaleString()} (Platform minimums)`,
            check: (alloc) => alloc["Social"] >= target,
            bound: { channel: "Social", min: target }
        });
    }

    if (selected.includes("contentCap")) {
        const base = baseAlloc["Content/SEO"];
        const rawTarget = Math.max(0, base - Math.max(base * 0.15, 15000));
        let target = socialMin > 0 ? Math.max(rawTarget, socialMin + 5000) : rawTarget;
        target = Math.floor(target / 5000) * 5000;
        if (target === base) target = Math.max(socialMin + 5000, base - 5000);
        constraints.push({
            id: "shock_content_cap",
            text: `Content/SEO must be reduced to ≤ $${target.toLocaleString()} (Agency limit)`,
            check: (alloc) => alloc["Content/SEO"] <= target,
            bound: { channel: "Content/SEO", max: target }
        });
    }

    if (selected.includes("searchFloor")) {
        const base = baseAlloc["Search Ads"];
        const rawTarget = Math.max(base * 1.15, base + 15000);
        const maxFeasible = 500000 - socialMin;
        let target = Math.min(rawTarget, maxFeasible);
        target = Math.ceil(target / 5000) * 5000;
        if (target === base) target = Math.min(maxFeasible, base + 5000);
        constraints.push({
            id: "shock_search_floor",
            text: `Search Ads must be increased to ≥ $${target.toLocaleString()} (Query volume)`,
            check: (alloc) => alloc["Search Ads"] >= target,
            bound: { channel: "Search Ads", min: target }
        });
    }

    if (selected.includes("eventsCap")) {
        const base = baseAlloc["Events"];
        const rawTarget = Math.max(0, base - Math.max(base * 0.15, 15000));
        let target = Math.floor(rawTarget / 5000) * 5000;
        if (target === base) target = Math.max(0, base - 5000);
        constraints.push({
            id: "shock_events_cap",
            text: `Events must be reduced to ≤ $${target.toLocaleString()} (Venue restrictions)`,
            check: (alloc) => alloc["Events"] <= target,
            bound: { channel: "Events", max: target }
        });
    }

    return constraints;
}

let currentTrial = 1;
let turnsInTrial = 0;
let hasInteractedThisTrial = false;
let currentTargetChannel = "Social";
let startOfTrialAllocations = {};
let currentTrialConstraints = [];
let trialScorePct = 0;
let attentionIntervalId = null;

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
    
    const idDisplay = document.getElementById('participantIdDisplay');
    if (idDisplay) idDisplay.innerText = `ID: ${sessionData.participantId} [${sessionData.group}]`;
    
    setupModality();
    startTrial(1);
});

function setupModality() {
    const isTranscript = sessionData.group.includes("Transcript");
    
    if (isTranscript) {
        document.getElementById('chatInputArea').style.display = 'none';
        document.getElementById('transcriptControls').style.display = 'block';
        
        const chatBox = document.getElementById('chatMessages');
        chatBox.addEventListener('scroll', () => {
            telemetry.scrollEvents.push({
                time: Date.now(),
                position: chatBox.scrollTop
            });
        });
    } else {
        const inputEl = document.getElementById('chatInput');
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace') telemetry.backspaces++;
            telemetry.keystrokes.push({ key: e.key, time: Date.now() });
        });
    }
}

function startDividedAttentionTask() {
    const overlay = document.getElementById('dividedAttentionOverlay');
    if (!overlay) return;

    overlay.innerHTML = `
        <div style="text-align: center; font-size: 11px; color: var(--ink-3);">Click when you see ${TARGET_NUMBER}</div>
        <div id="attentionNumber" class="da-number">-</div>
        <button id="attentionBtn">Match</button>
    `;

    document.getElementById('attentionBtn').addEventListener('click', (e) => {
        const btn = e.target;
        if (currentAttentionNumber === TARGET_NUMBER) {
            attentionMetrics.correctHits++;
            attentionMetrics.reactionTimes.push(Date.now() - numberAppearanceTime);
            currentAttentionNumber = null;
            btn.style.backgroundColor = '#28a745';
            btn.style.color = '#ffffff';
            setTimeout(() => { btn.style.backgroundColor = ''; btn.style.color = ''; }, 400);
        } else {
            attentionMetrics.falseAlarms++;
            btn.style.backgroundColor = '#dc3545';
            btn.style.color = '#ffffff';
            setTimeout(() => { btn.style.backgroundColor = ''; btn.style.color = ''; }, 400);
        }
    });

    attentionIntervalId = setInterval(() => {
        const num = Math.floor(Math.random() * 9) + 1;
        currentAttentionNumber = num;
        numberAppearanceTime = Date.now();
        const numEl = document.getElementById('attentionNumber');
        if (numEl) numEl.innerText = num;
        if (num === TARGET_NUMBER) attentionMetrics.targetsShown++;
    }, 2000);
}

function stopDividedAttentionTask() {
    if (attentionIntervalId) {
        clearInterval(attentionIntervalId);
        attentionIntervalId = null;
    }
    currentAttentionNumber = null;
}

function startTrial(trialIndex) {
    stopDividedAttentionTask();

    if (isP2Task()) { startTrialP2(trialIndex); return; }

    const loadLevel = sessionData.trialSequence[trialIndex - 1];
    const task = taskData[loadLevel];

    currentAllocations = { ...task.startingAllocation };
    startOfTrialAllocations = { ...currentAllocations };
    currentTrialConstraints = buildTrialConstraints(loadLevel, currentAllocations);

    if (loadLevel === "HighLoad") {
        const activeShocks = currentTrialConstraints.filter(c => c.id.startsWith("shock_"));
        logEvent('trial_shocks_generated', {
            trial: trialIndex,
            shock_ids: activeShocks.map(c => c.id),
            shock_texts: activeShocks.map(c => c.text)
        });
    }

    document.getElementById('docTitle').innerText = `${task.title} — Trial ${trialIndex} of 4`;

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
    currentTrialConstraints.forEach(c => {
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
            ${loadLevel === "HighLoad" ? `
            <div class="score-card" id="attentionCard">
                <span class="sc-label">Divided Attention Task</span>
                <div id="dividedAttentionOverlay"></div>
            </div>` : ''}
        </div>
        ${slidersHtml}
        <h3 class="doc-section-head">Live Constraints</h3>
        ${constraintsHtml}
        <button id="submitTrialBtn" class="btn-primary" style="width: 100%; margin-top: 24px;" disabled onclick="submitTrial()">
            Submit Trial 1 Allocation
        </button>
    `;

    document.querySelectorAll('.budget-slider').forEach(slider => {
        slider.addEventListener('input', (e) => {
            currentAllocations[e.target.dataset.channel] = parseInt(e.target.value);
            updateDashboard(loadLevel);
        });

        slider.addEventListener('mousedown', (e) => {
            const now = Date.now();
            if (!sliderTelemetry.firstMoveTime) {
                sliderTelemetry.firstMoveTime = now - window.lastTurnTimestamp;
            }
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
                sliderTelemetry.completedDrags.push(sliderTelemetry.currentDrag);
                sliderTelemetry.currentDrag = null;
            }
        });
    });

    taskStartTime = Date.now();
    window.lastTurnTimestamp = Date.now();
    turnsInTrial = 0;
    hintsUsedThisTrial = 0;
    sliderTelemetry = { firstMoveTime: null, currentDrag: null, completedDrags: [] };
    attentionMetrics = { targetsShown: 0, correctHits: 0, falseAlarms: 0, reactionTimes: [] };

    updateDashboard(loadLevel);

    if (loadLevel === "HighLoad") {
        startDividedAttentionTask();
    }

    logEvent('trial_started', { trial: trialIndex, load_level: loadLevel });

    if (!sessionData.group.includes("Transcript")) {
        setTimeout(() => {
            addMessage(`Trial ${trialIndex} of 4 begins. Adjust the sliders to satisfy the live constraints, then discuss your strategy with the AI advisor before submitting.`, "ai");
        }, 600);
    }
}

function updateDashboard(loadLevel) {
    if (isP2Task()) { updateDashboardP2(loadLevel); return; }
    const task = taskData[loadLevel];
    const total = sumAllocations(currentAllocations);
    trialScorePct = getImprovementPercentage(currentAllocations, loadLevel);
    
    document.getElementById('totalAllocDisplay').innerText = `$${total.toLocaleString()}`;
    
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
    
    currentTrialConstraints.forEach(c => {
        const el = document.getElementById(c.id)?.querySelector('.c-status');
        if (!el) return;
        el.className = c.check(currentAllocations) ? 'c-status pass' : 'c-status fail';
    });
    
    const allConstraintsMet = currentTrialConstraints.every(c => c.check(currentAllocations));
    updateSubmitBanner(allConstraintsMet);
}

function startTrialP2(trialIndex) {
    const loadLevel = sessionData.trialSequence[trialIndex - 1];
    const task = taskDataP2[loadLevel];

    currentAllocations = { ...task.startingAllocation };
    startOfTrialAllocations = { ...currentAllocations };
    currentTrialConstraints = buildTrialConstraintsP2(loadLevel);

    if (loadLevel === "HighLoad") {
        const activeShocks = currentTrialConstraints.filter(c => c.id.startsWith("shock_"));
        logEvent('trial_shocks_generated', {
            trial: trialIndex,
            shock_ids: activeShocks.map(c => c.id),
            shock_texts: activeShocks.map(c => c.text)
        });
    }

    document.getElementById('docTitle').innerText = `${task.title} \u2014 Trial ${trialIndex} of 4`;

    let controlsHtml = "";
    P2_CONTROLS.forEach(ctrl => {
        if (ctrl.type === "slider") {
            controlsHtml += `
                <div class="slider-group">
                    <div class="slider-header">
                        <span>${ctrl.label}</span>
                        <span class="channel-amt" id="val_${ctrl.key}">${currentAllocations[ctrl.key]}</span>
                    </div>
                    <input type="range" class="budget-slider"
                           data-channel="${ctrl.key}"
                           min="${ctrl.min}" max="${ctrl.max}" step="${ctrl.step}"
                           value="${currentAllocations[ctrl.key]}">
                </div>`;
        } else {
            controlsHtml += `
                <div class="slider-group">
                    <label style="display:flex; align-items:center; gap:8px;">
                        <input type="checkbox" class="budget-toggle" data-channel="${ctrl.key}"
                               ${currentAllocations[ctrl.key] ? "checked" : ""}>
                        <span>${ctrl.label}</span>
                    </label>
                </div>`;
        }
    });

    let constraintsHtml = `<ul class="constraint-list" id="constraintList">`;
    currentTrialConstraints.forEach(c => {
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
                <span class="sc-label">Estimated Post Length</span>
                <span class="sc-val" id="totalAllocDisplay">0 / 280 chars</span>
            </div>
        </div>
        ${controlsHtml}
        <h3 class="doc-section-head">Live Constraints</h3>
        ${constraintsHtml}
        <button id="submitTrialBtn" class="btn-primary" style="width: 100%; margin-top: 24px;" disabled onclick="submitTrial()">
            Submit Trial ${trialIndex} Post
        </button>
    `;

    document.querySelectorAll('.budget-slider').forEach(slider => {
        slider.addEventListener('input', (e) => {
            currentAllocations[e.target.dataset.channel] = parseInt(e.target.value);
            updateDashboard(loadLevel);
        });
        slider.addEventListener('mousedown', (e) => {
            const now = Date.now();
            if (!sliderTelemetry.firstMoveTime) sliderTelemetry.firstMoveTime = now - window.lastTurnTimestamp;
            sliderTelemetry.currentDrag = { channel: e.target.dataset.channel, startTime: now, startValue: parseInt(e.target.value) };
        });
        slider.addEventListener('mouseup', (e) => {
            if (sliderTelemetry.currentDrag) {
                const now = Date.now();
                sliderTelemetry.currentDrag.endTime = now;
                sliderTelemetry.currentDrag.endValue = parseInt(e.target.value);
                sliderTelemetry.currentDrag.durationMs = now - sliderTelemetry.currentDrag.startTime;
                sliderTelemetry.completedDrags.push(sliderTelemetry.currentDrag);
                sliderTelemetry.currentDrag = null;
            }
        });
    });

    document.querySelectorAll('.budget-toggle').forEach(toggle => {
        toggle.addEventListener('change', (e) => {
            currentAllocations[e.target.dataset.channel] = e.target.checked ? 1 : 0;
            updateDashboard(loadLevel);
        });
    });

    taskStartTime = Date.now();
    window.lastTurnTimestamp = Date.now();
    turnsInTrial = 0;
    hintsUsedThisTrial = 0;
    sliderTelemetry = { firstMoveTime: null, currentDrag: null, completedDrags: [] };
    attentionMetrics = { targetsShown: 0, correctHits: 0, falseAlarms: 0, reactionTimes: [] };

    updateDashboard(loadLevel);

    logEvent('trial_started', { trial: trialIndex, load_level: loadLevel });

    if (!sessionData.group.includes("Transcript")) {
        setTimeout(() => {
            addMessage(`Trial ${trialIndex} of 4 begins. Set your post parameters to satisfy the live constraints, then discuss your strategy with the AI advisor before submitting.`, "ai");
        }, 600);
    }
}

function updateDashboardP2(loadLevel) {
    trialScorePct = getEngagementPercentage(currentAllocations, loadLevel);
    const length = estimatePostLength(currentAllocations);

    const lenDisplay = document.getElementById('totalAllocDisplay');
    if (lenDisplay) lenDisplay.innerText = `${length} / 280 chars`;

    P2_CONTROLS.forEach(ctrl => {
        if (ctrl.type === "slider") {
            const el = document.getElementById("val_" + ctrl.key);
            if (el) el.innerText = currentAllocations[ctrl.key];
        }
    });

    const budgetCard = document.getElementById('budgetCard');
    if (budgetCard) {
        if (length > 280) budgetCard.classList.add('error'); else budgetCard.classList.remove('error');
    }

    currentTrialConstraints.forEach(c => {
        const el = document.getElementById(c.id)?.querySelector('.c-status');
        if (!el) return;
        el.className = c.check(currentAllocations) ? 'c-status pass' : 'c-status fail';
    });

    const allConstraintsMet = currentTrialConstraints.every(c => c.check(currentAllocations));
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
                primary_task: sessionData.primaryTask,
                message: text,
                task_id: 1, 
                group: sessionData.group,
                trial_num: currentTrial,
                turn_in_trial: turnsInTrial, 
                hints_used_this_trial: hintsUsedThisTrial, 
                roi_score: trialScorePct, 
                all_constraints_met: allConstraintsMet,
                allocations: currentAllocations,
                shadow_history: shadowHistory,
                load_level: sessionData.trialSequence[currentTrial - 1],
                dropped_category_index: sessionData.droppedCategoryIndex,
                constraint_bounds: currentTrialConstraints.map(c => c.bound).filter(Boolean)
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

async function requestScoreHint() {
    if (totalHintsUsed >= MAX_HINTS) return;

    const chip = document.getElementById('scoreHintChip');
    chip.disabled = true;

    const canned = "Can you tell me how my current allocation is scoring?";
    addMessage(canned, 'user');

    totalHintsUsed++;
    hintsUsedThisTrial++;
    turnsInTrial++;
    sessionData.metrics.turnsElapsed++;

    document.getElementById('hintsLeftDisplay').innerText = MAX_HINTS - totalHintsUsed;

    const loadLevel = sessionData.trialSequence[currentTrial - 1];
    const allConstraintsMet = currentTrialConstraints.every(c => c.check(currentAllocations));

    logEvent('score_hint_requested', {
        text: canned,
        trial: currentTrial,
        hints_remaining_total: MAX_HINTS - totalHintsUsed,
        allocations_snapshot: { ...currentAllocations }
    });

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: sessionData.participantId,
                primary_task: sessionData.primaryTask,
                message: canned,
                task_id: 1,
                group: sessionData.group,
                trial_num: currentTrial,
                turn_in_trial: turnsInTrial,
                hints_used_this_trial: hintsUsedThisTrial,
                roi_score: trialScorePct,
                all_constraints_met: allConstraintsMet,
                allocations: currentAllocations,
                shadow_history: shadowHistory,
                load_level: loadLevel,
                dropped_category_index: sessionData.droppedCategoryIndex,
                constraint_bounds: currentTrialConstraints.map(c => c.bound).filter(Boolean),
                is_score_hint: true
            })
        });

        const data = await response.json();

        if (data.status === "success") {
            addMessage(data.reply, 'ai');
            if (data.target_channel) currentTargetChannel = data.target_channel;

            logEvent('ai_response', {
                text: data.reply,
                decoy: data.clean_decoy,
                category: data.category,
                pattern_id: data.pattern_id,
                isDark: data.isDark,
                allocations_snapshot: { ...currentAllocations }
            });

            shadowHistory.push({ role: 'user', content: canned });
            shadowHistory.push({ role: 'ai', content: data.clean_decoy });

            hasInteractedThisTrial = true;
            document.getElementById('submitTrialBtn').disabled = false;
        }
    } catch (error) {
        console.error("Score hint error:", error);
    }

    if (totalHintsUsed < MAX_HINTS) chip.disabled = false;
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

function submitTrial() {
    const loadLevel = sessionData.trialSequence[currentTrial - 1];
    const allConstraintsMet = currentTrialConstraints.every(c => c.check(currentAllocations));

    if (!allConstraintsMet) {
        alert("Your allocation doesn't satisfy all requirements yet. Please review the live constraints and adjust.");
        return;
    }

    if (currentAllocations[currentTargetChannel] > startOfTrialAllocations[currentTargetChannel]) {
        sessionData.metrics.claimsAccepted++;
    } else {
        sessionData.metrics.claimsRejected++;
    }

    logEvent('trial_submitted', {
        trial: currentTrial,
        load_level: loadLevel,
        final_score: trialScorePct,
        final_allocations: { ...currentAllocations },
        slider_telemetry: sliderTelemetry,
        attention_metrics: { ...attentionMetrics }
    });

    if (currentTrial >= 4) {
        document.getElementById('submitTrialBtn').disabled = true;
        document.getElementById('submitTrialBtn').innerText = "Processing...";
        stopDividedAttentionTask();
        // TODO next pass: NASA-TLX, per-trial 4-item block, per-task subjective
        // battery, swapped-transcript task, and recognition test all hook in
        // around here — currently goes straight to save/debrief.
        saveSessionData();
    } else {
        currentTrial++;
        startTrial(currentTrial);
        // TODO next pass: NASA-TLX + 4-item block should run here, between
        // submitting this trial and starting the next one.
    }
}

