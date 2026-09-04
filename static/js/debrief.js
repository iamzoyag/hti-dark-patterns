// static/js/debrief.js

document.addEventListener('DOMContentLoaded', () => {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) { window.location.href = '/'; return; }
    const session = JSON.parse(rawData);

    // NASA-TLX is now collected per-trial in experiment.js.
    const recognitionComplete = localStorage.getItem(`hti_recognition_done_${session.participantId}`);
    if (!recognitionComplete) {
        hideAllSections();
        document.getElementById('recognitionSection').classList.add('active');
        buildRecognitionTest();
    } else {
        showDebrief();
    }
});

let currentTestId = null;
let touchedConfidenceSliders = new Set();


async function buildRecognitionTest() {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    const session = JSON.parse(rawData);

    try {
        const response = await fetch('/api/get_recognition_test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ participant_id: session.participantId, events: session.events })
        });

        if (!response.ok) {
            throw new Error(`Recognition test endpoint returned ${response.status}`);
        }

        const data = await response.json();
        if (!data.questions || !data.test_id) {
            throw new Error('Recognition test response missing expected fields');
        }

        currentTestId = data.test_id;
        
        const container = document.getElementById('recognitionQuestions');
        let html = '';
        
        data.questions.forEach((q) => {
            html += `
            <div class="consent-block" style="margin-bottom: 24px;">
                <p style="font-family: var(--mono); font-size: 12px; margin-bottom: 8px;">Excerpt ${q.id + 1}</p>
                <blockquote style="font-style: italic; border-left: 2px solid var(--accent); padding-left: 10px; margin-bottom: 12px;">"${q.text}"</blockquote>
                
                <label style="font-size: 13px; font-weight: 500;">Did this response attempt to influence you unfairly?</label>
                <div style="margin-top: 8px; margin-bottom: 12px;">
                    <label><input type="radio" name="rec_flag_${q.id}" value="true"> Yes</label><br>
                    <label style="margin-top: 6px; display: inline-block;"><input type="radio" name="rec_flag_${q.id}" value="false"> No</label>
                </div>
                
                <label style="font-size: 13px; font-weight: 500;">Confidence in your answer (1-5):</label>
                <input type="range" name="rec_conf_${q.id}" min="1" max="5" value="3" style="width: 100%; margin-top: 8px;">
            </div>`;
        });
        
        container.innerHTML = html;

        const totalQuestions = data.questions.length;
        touchedConfidenceSliders = new Set();

        container.querySelectorAll('input[type="range"]').forEach(slider => {
            slider.addEventListener('input', () => {
                touchedConfidenceSliders.add(slider.name);
                updateRecognitionSubmitState(totalQuestions);
            });
        });
        container.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', () => updateRecognitionSubmitState(totalQuestions));
        });

        updateRecognitionSubmitState(totalQuestions);
        
        hideAllSections();
        document.getElementById('recognitionSection').classList.add('active');
        
    } catch (error) {
        console.error("Failed to load recognition test", error);
        showDebrief(); // Fallback to debrief if network fails
    }
}

function updateRecognitionSubmitState(totalQuestions) {
    const btn = document.getElementById('recogSubmitBtn');
    if (!btn) return;

    const answeredFlags = new Set(
        Array.from(document.querySelectorAll('[name^="rec_flag_"]:checked')).map(el => el.name)
    ).size;

    btn.disabled = !(touchedConfidenceSliders.size >= totalQuestions && answeredFlags >= totalQuestions);
}

async function submitRecognitionTest() {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    const session = JSON.parse(rawData);
    
    // Gather UI answers
    const answers = [];
    const questionBlocks = document.querySelectorAll('[name^="rec_flag_"]');
    const uniqueIds = [...new Set(Array.from(questionBlocks).map(el => el.name.split('_')[2]))];
    
    uniqueIds.forEach(id => {
        const flaggedValue = document.querySelector(`input[name="rec_flag_${id}"]:checked`)?.value;
        const confidenceValue = document.querySelector(`input[name="rec_conf_${id}"]`)?.value;
        
        if (flaggedValue) {
            answers.push({
                id: parseInt(id),
                flagged: flaggedValue === "true",
                confidence: parseInt(confidenceValue)
            });
        }
    });
    
    try {
        const response = await fetch('/api/submit_recognition_test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                test_id: currentTestId,
                answers: answers
            })
        });
        
        const data = await response.json();
        
        // 1. Save to session object
        session.recognitionTestResults = data.scored_results;
        
        // 2. Push it as an event so the Python backend writes it to the CSV
        session.events.push({
            timestamp: new Date().toISOString(),
            type: 'recognition_test_submitted',
            content: data.scored_results
        });

        localStorage.setItem('hti_session', JSON.stringify(session));
        localStorage.setItem(`hti_recognition_done_${session.participantId}`, 'true');
        
        // 3. FORCE FINAL SAVE (Awaited)
        await fetch('/api/save_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(session)
        }).catch(err => console.error("Final save failed:", err));

        showPerformanceSummary();

    } catch (error) {
        console.error("Failed to submit test", error);
        showPerformanceSummary();
    }
}

// Every task's live score (trialScorePct in experiment.js) is already normalized against
// that load level's maximum achievable ROI/engagement/itinerary quality — i.e. it's already
// "% of optimal", so the genuine stake here is just aggregating the final_score already
// logged on each trial_submitted event. No new backend computation needed.
const PERFORMANCE_TASK_LABELS = {
    "P1_Marketing": "Marketing Budget",
    "P2_ContentSocial": "Social Media Post",
    "P3_TripPlanning": "Trip Itinerary"
};

function computePerformanceSummary(session) {
    const submitted = (session.events || []).filter(e => e.type === 'trial_submitted');
    const order = session.taskOrder || [];
    const byTask = {};

    submitted.forEach((e, i) => {
        const task = order[Math.floor(i / 4)] || "Unknown";
        const score = e.content?.final_score;
        if (typeof score !== 'number') return;
        (byTask[task] = byTask[task] || []).push(score);
    });

    const perTask = order
        .filter(task => byTask[task]?.length)
        .map(task => ({
            label: PERFORMANCE_TASK_LABELS[task] || task,
            avg: Math.round(byTask[task].reduce((a, b) => a + b, 0) / byTask[task].length)
        }));

    const allScores = submitted.map(e => e.content?.final_score).filter(s => typeof s === 'number');
    const overall = allScores.length ? Math.round(allScores.reduce((a, b) => a + b, 0) / allScores.length) : null;

    return { overall, perTask, roundsCompleted: allScores.length };
}

function showPerformanceSummary() {
    hideAllSections();
    document.getElementById('performanceSection').classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });

    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    const session = JSON.parse(rawData);
    const { overall, perTask, roundsCompleted } = computePerformanceSummary(session);

    const headline = document.getElementById('perfHeadline');
    if (headline) {
        headline.textContent = overall !== null
            ? `On average, your choices captured ${overall}% of the best possible outcome across the ${roundsCompleted} round${roundsCompleted === 1 ? '' : 's'} you completed.`
            : "We weren't able to compute a performance summary for this session.";
    }

    const breakdown = document.getElementById('perfBreakdown');
    if (breakdown) {
        breakdown.innerHTML = perTask.map(t => `
            <div class="stat-card">
                <span class="sc-val">${t.avg}%</span>
                <span class="sc-label">${t.label}</span>
            </div>
        `).join('');
    }
}

function showDebrief() {
    hideAllSections();
    document.getElementById('debriefSection').classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- UI TRANSITION ---
function showDataExport() {
    // 1. Swap the active panels
    hideAllSections();
    document.getElementById('exportSection').classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // 2. Load and render the data
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;

    const session = JSON.parse(rawData);

    // 3. Populate the JSON preview box
    document.getElementById('jsonPreview').textContent = JSON.stringify(session, null, 2);

    // 4. Populate the beautiful stat cards
    const statsContainer = document.getElementById('exportStats');
    statsContainer.innerHTML = `
        <div class="stat-card">
            <span class="sc-val">${session.group}</span>
            <span class="sc-label">Assignment Group</span>
        </div>
        <div class="stat-card">
            <span class="sc-val">${session.events.filter(e => e.type === 'user_message').length}</span>
            <span class="sc-label">Total Messages Sent</span>
        </div>
        <div class="stat-card">
            <span class="sc-val">${session.participantId}</span>
            <span class="sc-label">Participant ID</span>
        </div>
        <div class="stat-card">
            <span class="sc-val">${session.attentionAccuracy ?? '—'}% ${session.attentionQualified ? '✓' : '✗'}</span>
            <span class="sc-label">Attention Task Accuracy</span>
        </div>
    `;
}

// --- UTILITY FUNCTIONS ---
function copyJSON() {
    const jsonText = document.getElementById('jsonPreview').textContent;
    navigator.clipboard.writeText(jsonText).then(() => {
        const btn = document.querySelector('.btn-copy');
        btn.innerText = "Copied!";
        setTimeout(() => btn.innerText = "Copy", 2000);
    });
}

function downloadJSON() {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    
    const blob = new Blob([rawData], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    
    const link = document.createElement("a");
    link.href = url;
    link.download = `HTI_Study_${JSON.parse(rawData).participantId}.json`;
    document.body.appendChild(link);
    link.click();
    
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

function flattenPerTrialTLX(perTrialTLX, totalTrials) {
    const keys = ["Mental","Physical","Temporal","Performance","Effort","Frustration"];
    const byTrial = {};
    (perTrialTLX || []).forEach(t => { byTrial[t.trial] = t; });
    const flat = {};
    for (let trialNum = 1; trialNum <= totalTrials; trialNum++) {
        const entry = byTrial[trialNum] || {};
        keys.forEach(k => {
            const val = entry[k.toLowerCase()];
            flat[`Trial${trialNum}_TLX_${k}`] = val !== undefined ? val : "";
        });
    }
    return flat;
}

function downloadCSV() {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    
    const session = JSON.parse(rawData);
    
    // 1. Add TLX headers
    let csvContent = "Participant_ID,Group,Age,Education,AI_Exp,Domain,Crit_Ability,Mkt_Familiarity,P_e1,P_e2,P_e3,P_e4," +
        "Trial1_TLX_Mental,Trial1_TLX_Physical,Trial1_TLX_Temporal,Trial1_TLX_Performance,Trial1_TLX_Effort,Trial1_TLX_Frustration," +
        "Trial2_TLX_Mental,Trial2_TLX_Physical,Trial2_TLX_Temporal,Trial2_TLX_Performance,Trial2_TLX_Effort,Trial2_TLX_Frustration," +
        "Trial3_TLX_Mental,Trial3_TLX_Physical,Trial3_TLX_Temporal,Trial3_TLX_Performance,Trial3_TLX_Effort,Trial3_TLX_Frustration," +
        "Trial4_TLX_Mental,Trial4_TLX_Physical,Trial4_TLX_Temporal,Trial4_TLX_Performance,Trial4_TLX_Effort,Trial4_TLX_Frustration," +
        "Claims_Accepted,Claims_Rejected,Transient_Acceptance,Turns_Elapsed,Corrections_Made,Timestamp,Event_Type,Message,Is_Dark,Category,Pattern_ID,Decoy_Text,Backspaces,WPM,Pause_MS,Keystrokes_Array,Scrolls_Array\n";
    
    // 2. Extract demographics, personality, per-trial TLX, and outcome metrics
    const demo = session.demographics || {};
    const pers = session.personality || {};
    const metrics = session.metrics || {};
    
    const demoCols = `${demo.age || ""},${demo.education || ""},${demo.aiExp || ""},${demo.domain || ""},${demo.criticalAbility || ""},${demo.marketingFamiliarity || ""}`;
    const persCols = `${pers.e1 || ""},${pers.e2 || ""},${pers.e3 || ""},${pers.e4 || ""}`;
    const totalTrials = (session.taskOrder?.length || 1) * 4;
    const tlxFlat = flattenPerTrialTLX(session.perTrialTLX, totalTrials);
    const TLX_KEYS = ["Mental","Physical","Temporal","Performance","Effort","Frustration"];
    const tlxCols = Array.from({ length: totalTrials }, (_, i) => i + 1)
        .map(t => TLX_KEYS.map(k => tlxFlat[`Trial${t}_TLX_${k}`]).join(","))
        .join(",");
    const metricsCols = `${metrics.claimsAccepted ?? ""},${metrics.claimsRejected ?? ""},${metrics.transientAcceptance ?? ""},${metrics.turnsElapsed ?? ""},${metrics.correctionsMade ?? ""}`;
    
    // Filter out the raw TLX events so they don't also print as standalone rows
    const filteredEvents = session.events.filter(e => e.type !== 'trial_tlx_submitted' && e.type !== 'nasa_tlx_submitted');
    
    filteredEvents.forEach(event => {
        let rawText = "";
        let isDark = "";
        let category = "";
        let patternId = "";
        let decoy = "";
        
        let backspaces = 0;
        let wpm = 0;
        let pauseMs = 0;
        let keystrokesStr = "[]";
        let scrollsStr = "[]";

        if (event.content) {
            // Check if it's the recognition test payload
            if (event.type === 'recognition_test_submitted') {
                rawText = JSON.stringify(event.content).replace(/"/g, '""');
            }
            else if (typeof event.content === 'string') {
                rawText = event.content;
            } else {
                rawText = event.content.text || "";
                isDark = event.content.isDark !== undefined ? event.content.isDark : "";
                category = event.content.category || "";
                patternId = event.content.pattern_id || "";
                decoy = event.content.decoy || "";
                
                if (event.content.telemetry) {
                    backspaces = event.content.telemetry.backspaces || 0;
                    wpm = event.content.telemetry.wpm || 0;
                    pauseMs = event.content.telemetry.pause_ms || 0;
                    
                    if (event.content.telemetry.keystrokes) {
                        keystrokesStr = JSON.stringify(event.content.telemetry.keystrokes).replace(/"/g, '""');
                    }
                    if (event.content.telemetry.scrollEvents) {
                        scrollsStr = JSON.stringify(event.content.telemetry.scrollEvents).replace(/"/g, '""');
                    }
                }
            }
        }
        
        const cleanText = rawText.replace(/,/g, ";").replace(/\n/g, " ").replace(/"/g, '""');
        const cleanDecoy = decoy.replace(/,/g, ";").replace(/\n/g, " ").replace(/"/g, '""');
        
        // 3. Inject tlxCols into the final row string
        let row = `${session.participantId},${session.group},${demoCols},${persCols},${tlxCols},${metricsCols},${event.timestamp},${event.type},"${cleanText}",${isDark},${category},${patternId},"${cleanDecoy}",${backspaces},${wpm},${pauseMs},"${keystrokesStr}","${scrollsStr}"`;
        
        csvContent += row + "\n";
    });

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    
    const link = document.createElement("a");
    link.href = url;
    link.download = `HTI_Study_${session.participantId}_Telemetry.csv`;
    document.body.appendChild(link);
    link.click();
    
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

const tlxItems = [
    { id: "mental", label: "Mental Demand", desc: "How mentally demanding was the task?", left: "Very Low", right: "Very High" },
    { id: "physical", label: "Physical Demand", desc: "How physically demanding was the task?", left: "Very Low", right: "Very High" },
    { id: "temporal", label: "Temporal Demand", desc: "How hurried or rushed was the pace of the task?", left: "Very Low", right: "Very High" },
    { id: "performance", label: "Performance", desc: "How successful were you in accomplishing what you were asked to do?", left: "Perfect", right: "Failure" },
    { id: "effort", label: "Effort", desc: "How hard did you have to work to accomplish your level of performance?", left: "Very Low", right: "Very High" },
    { id: "frustration", label: "Frustration", desc: "How insecure, discouraged, irritated, stressed, and annoyed were you?", left: "Very Low", right: "Very High" }
];

function buildTLX() {
    hideAllSections();
    document.getElementById('tlxSection').classList.add('active');

    const container = document.getElementById('tlxQuestions');
    if (!container) return;

    let html = '';
    tlxItems.forEach(item => {
        html += `
        <div style="margin-bottom: 20px; padding: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);">
            <div style="font-weight: 600; font-size: 14px;">${item.label}</div>
            <div style="font-size: 12px; color: var(--ink-3); margin-bottom: 12px;">${item.desc}</div>
            <div style="display: flex; justify-content: space-between; font-size: 11px; font-family: var(--mono); color: var(--ink-4);">
                <span>${item.left}</span>
                <span>${item.right}</span>
            </div>
            <input type="range" id="tlx_${item.id}" min="0" max="100" step="5" value="50" style="width: 100%; margin-top: 8px;">
        </div>`;
    });
    container.innerHTML = html;
}

async function submitTLX() {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    const session = JSON.parse(rawData);

    const tlxScores = {};
    tlxItems.forEach(item => {
        tlxScores[item.id] = parseInt(document.getElementById(`tlx_${item.id}`).value);
    });

    session.nasaTLX = tlxScores;
    session.events.push({
        timestamp: new Date().toISOString(),
        type: 'nasa_tlx_submitted',
        content: tlxScores
    });

    localStorage.setItem('hti_session', JSON.stringify(session));
    
    // FORCE MIDWAY SAVE: Ensures TLX hits the CSV even if they drop off before the final test
    await fetch('/api/save_data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(session)
    }).catch(err => console.error("Midway save failed:", err));
    
    hideAllSections();
    document.getElementById('recognitionSection').classList.add('active');
    buildRecognitionTest(); 
}

function hideAllSections() {
    ['debriefSection', 'tlxSection', 'recognitionSection', 'performanceSection', 'exportSection'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
    });
}