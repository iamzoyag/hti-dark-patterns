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
                
                <label style="font-size: 13px; font-weight: 500;">How much did you agree with what the AI said here?</label>
                <div class="likert-row" style="margin-top:8px; margin-bottom:12px;">
                    <span class="likert-label-end">Strongly Disagree</span>
                    <label class="likert-option"><input type="radio" name="rec_agree_${q.id}" value="1"><span>1</span></label>
                    <label class="likert-option"><input type="radio" name="rec_agree_${q.id}" value="2"><span>2</span></label>
                    <label class="likert-option"><input type="radio" name="rec_agree_${q.id}" value="3"><span>3</span></label>
                    <label class="likert-option"><input type="radio" name="rec_agree_${q.id}" value="4"><span>4</span></label>
                    <label class="likert-option"><input type="radio" name="rec_agree_${q.id}" value="5"><span>5</span></label>
                    <span class="likert-label-end">Strongly Agree</span>
                </div>
            </div>`;
        });
        
        container.innerHTML = html;

        const totalQuestions = data.questions.length;
        touchedAgreementSliders = new Set();

        container.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', () => updateRecognitionSubmitState(totalQuestions));
        });

        document.getElementById('recogReflect1')?.addEventListener('input', () => updateRecognitionSubmitState(totalQuestions));
        document.getElementById('recogReflect2')?.addEventListener('input', () => updateRecognitionSubmitState(totalQuestions));
        
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
    const answeredAgreement = new Set(
        Array.from(document.querySelectorAll('[name^="rec_agree_"]:checked')).map(el => el.name)
    ).size;

    const reflect1 = document.getElementById('recogReflect1')?.value.trim().length > 0;
    const reflect2 = document.getElementById('recogReflect2')?.value.trim().length > 0;

    btn.disabled = !(answeredAgreement >= totalQuestions && answeredFlags >= totalQuestions && reflect1 && reflect2);
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
        const agreementValue = document.querySelector(`input[name="rec_agree_${id}"]:checked`)?.value;
        
        if (flaggedValue) {
            answers.push({
                id: parseInt(id),
                flagged: flaggedValue === "true",
                agreement: parseInt(agreementValue)
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

        const reflection = {
            ai_influence_moment: document.getElementById('recogReflect1')?.value.trim() || '',
            ai_communication_style: document.getElementById('recogReflect2')?.value.trim() || ''
        };
        
        // 1. Save to session object
        session.recognitionTestResults = data.scored_results;
        session.recognitionReflection = reflection;
        
        // 2. Push it as an event so the Python backend writes it to the CSV
        session.events.push({
            timestamp: new Date().toISOString(),
            type: 'recognition_test_submitted',
            content: { scored_results: data.scored_results, reflection }
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

function finishDebrief() {
    const dcResponse = document.getElementById('dcText')?.value.trim() || '';
    const rawData = localStorage.getItem('hti_session');
    if (rawData) {
        const session = JSON.parse(rawData);
        session.events.push({
            timestamp: new Date().toISOString(),
            type: 'demand_characteristics_submitted',
            content: dcResponse
        });
        localStorage.setItem('hti_session', JSON.stringify(session));
        fetch('/api/save_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(session)
        }).catch(err => console.error("Debrief save failed:", err));
    }

    hideAllSections();
    document.getElementById('withdrawSection').classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function submitWithdrawal() {
    const rawData = localStorage.getItem('hti_session');
    const session = rawData ? JSON.parse(rawData) : null;
    const email = document.getElementById('withdrawEmail')?.value.trim() || '';
    const btn = document.getElementById('withdrawSubmitBtn');
    const confirmMsg = document.getElementById('withdrawConfirm');

    if (email && session) {
        try {
            await fetch('/api/request_withdrawal', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ participant_id: session.participantId, email })
            });
        } catch (err) {
            console.error("Withdrawal request failed:", err);
        }
        confirmMsg.textContent = "Your request has been logged. The research team will remove your data within 7 days.";
    } else {
        confirmMsg.textContent = "Thank you for participating!";
    }

    confirmMsg.style.display = 'block';
    btn.disabled = true;
    btn.style.display = 'none';
    document.getElementById('withdrawEmail').disabled = true;
}

function hideAllSections() {
    ['debriefSection', 'recognitionSection', 'performanceSection', 'withdrawSection'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
    });
}