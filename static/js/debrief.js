// static/js/debrief.js

document.addEventListener('DOMContentLoaded', () => {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) { window.location.href = '/'; return; }
    const session = JSON.parse(rawData);

    // Only build the test if this specific participant hasn't already completed it
    const recognitionComplete = localStorage.getItem(`hti_recognition_done_${session.participantId}`);
    if (!recognitionComplete) {
        buildRecognitionTest();
    } else {
        showDebrief(); // Skip straight to debrief if already done
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
                
                <label style="font-size: 13px; font-weight: 500;">Confidence in your answer (1-5):</label>
                <input type="range" name="rec_conf_${q.id}" min="1" max="5" value="3" style="width: 100%; margin-top: 8px;">
            </div>`;
        });
        
        container.innerHTML = html;
        
        document.getElementById('debriefSection').classList.remove('active');
        document.getElementById('exportSection').classList.remove('active');
        document.getElementById('recognitionSection').classList.add('active');
        
    } catch (error) {
        console.error("Failed to load recognition test", error);
        showDebrief(); // Fallback to debrief if network fails
    }
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
        
        // Append scored results to session data for final export
        session.recognitionTestResults = data.scored_results;
        localStorage.setItem('hti_session', JSON.stringify(session));
        localStorage.setItem(`hti_recognition_done_${session.participantId}`, 'true');
        
        showDebrief();
        
    } catch (error) {
        console.error("Failed to submit test", error);
        showDebrief();
    }
}

function showDebrief() {
    document.getElementById('recognitionSection').classList.remove('active');
    document.getElementById('exportSection').classList.remove('active');
    document.getElementById('debriefSection').classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- UI TRANSITION ---
function showDataExport() {
    // 1. Swap the active panels
    document.getElementById('debriefSection').classList.remove('active');
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

function downloadCSV() {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    
    const session = JSON.parse(rawData);
    let csvContent = "Participant_ID,Group,Task,Timestamp,Sender,Message,Pause_MS,Backspaces\n";
    
    session.events.forEach(event => {
        let cleanText = event.content.text ? event.content.text.replace(/,/g, "").replace(/\n/g, " ") : 
                        (typeof event.content === 'string' ? event.content.replace(/,/g, "").replace(/\n/g, " ") : "");
        let pause = event.content.pause_ms || 0;
        let backspaces = event.content.backspaces || 0;
        
        let row = `${session.participantId},${session.group},${event.task || 1},${event.timestamp},${event.type},"${cleanText}",${pause},${backspaces}`;
        csvContent += row + "\n";
    });

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    
    const link = document.createElement("a");
    link.href = url;
    link.download = `HTI_Study_${session.participantId}.csv`;
    document.body.appendChild(link);
    link.click();
    
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}