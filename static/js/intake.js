// static/js/intake.js

// --- 1. NAVIGATION & PROGRESS BAR ---
function goToStep(stepNumber) {
    document.querySelectorAll('.step-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    let targetId = 'step-landing';
    if (stepNumber === 2) targetId = 'step-personality';
    if (stepNumber === 3) targetId = 'step-briefing';

    const target = document.getElementById(targetId);
    if (target) {
        target.classList.add('active');
    }

    // Update the progress bar fill (3 steps total)
    const progress = ((stepNumber - 1) / 2) * 100;
    document.getElementById('progressFill').style.width = `${progress}%`;

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- 2. CONSENT LOGIC ---
function checkConsent() {
    const box = document.getElementById('consentBox');
    const btn = document.getElementById('landingNext');
    btn.disabled = !box.checked;
}

function checkBriefing() {
    const box = document.getElementById('briefingBox');
    const btn = document.getElementById('briefingNext');
    btn.disabled = !box.checked;
}

// --- 3. PERSONALITY SCALE (Emotionality) ---
// These are standard items measuring vulnerability to emotional pressure
const personalityItems = [
    { id: "e1", text: "I often worry about things that might go wrong." },
    { id: "e2", text: "I find it difficult to approach tasks when I feel pressured." },
    { id: "e3", text: "I tend to seek reassurance from others when making decisions." },
    { id: "e4", text: "I am easily moved by the emotional experiences of others." }
];

function renderPersonalityScale() {
    const container = document.getElementById('personalityScale');
    if (!container) return;

    let html = '';
    personalityItems.forEach((item, index) => {
        html += `
        <tr class="pq-row">
            <td class="pq-statement-cell">${index + 1}. ${item.text}</td>
            <td><label class="pq-radio-cell"><input type="radio" name="${item.id}" value="1"/></label></td>
            <td><label class="pq-radio-cell"><input type="radio" name="${item.id}" value="2"/></label></td>
            <td><label class="pq-radio-cell"><input type="radio" name="${item.id}" value="3"/></label></td>
            <td><label class="pq-radio-cell"><input type="radio" name="${item.id}" value="4"/></label></td>
            <td><label class="pq-radio-cell"><input type="radio" name="${item.id}" value="5"/></label></td>
        </tr>`;
    });
    container.innerHTML = html;
}

// Inject the questions when the page loads
document.addEventListener('DOMContentLoaded', () => {
    renderPersonalityScale();
});

// --- 4. START EXPERIMENT & SAVE DATA ---
async function startExperiment() {
    // Disable the button to prevent double-clicking while waiting for the server
    const btn = document.getElementById('personalityNext');
    btn.disabled = true;
    btn.innerText = "Assigning...";

    localStorage.removeItem('hti_session');
    localStorage.removeItem('hti_recognition_done');

    // Generate a random Participant ID
    const participantId = 'P' + Math.floor(Math.random() * 100000).toString().padStart(5, '0');

    // Gather Demographics
    const demoData = {
        age: document.getElementById('age').value,
        education: document.getElementById('education').value,
        aiExp: document.getElementById('aiExp').value,
        domain: document.getElementById('domain').value,
        criticalAbility: document.querySelector('input[name="critAbility"]:checked')?.value || null,
        marketingFamiliarity: document.querySelector('input[name="mktFamiliarity"]:checked')?.value || null
    };

    // Gather Personality scores
    const personalityData = {};
    personalityItems.forEach(item => {
        personalityData[item.id] = document.querySelector(`input[name="${item.id}"]:checked`)?.value || null;
    });

    // --- Ask the backend to dynamically balance the assignment ---
    // Every participant now does all 3 tasks, in a round-robin-counterbalanced order.
    let groupAssignment = "Live";
    let taskOrder = ["P1_Marketing", "P2_ContentSocial", "P3_TripPlanning"];
    let taskAssignments = {
        "P1_Marketing": { trial_sequence: ["HighLoad", "LowLoad", "HighLoad", "LowLoad"], dropped_category_index: 0 },
        "P2_ContentSocial": { trial_sequence: ["HighLoad", "LowLoad", "HighLoad", "LowLoad"], dropped_category_index: 0 },
        "P3_TripPlanning": { trial_sequence: ["HighLoad", "LowLoad", "HighLoad", "LowLoad"], dropped_category_index: 0 }
    };
    try {
        const response = await fetch(`/api/assign_group?participant_id=${encodeURIComponent(participantId)}`);
        const data = await response.json();
        groupAssignment = data.group;
        taskOrder = data.task_order;
        taskAssignments = data.tasks;
        console.log(`Server assignment #${data.assignment_index}:`, data);
    } catch (error) {
        console.error("Failed to reach assignment server, defaulting to round-robin fallback.", error);
        groupAssignment = "Live";
    }

    const firstTask = taskOrder[0];

    // Create the master session object
    const sessionData = {
        participantId: participantId,
        group: groupAssignment,
        taskOrder: taskOrder,
        currentTaskIndex: 0,
        taskAssignments: taskAssignments,
        primaryTask: firstTask,
        trialSequence: taskAssignments[firstTask].trial_sequence,
        droppedCategoryIndex: taskAssignments[firstTask].dropped_category_index,
        startTime: new Date().toISOString(),
        demographics: demoData,
        personality: personalityData,
        events: [],      
        metrics: {
            correctionsMade: 0,
            claimsAccepted: 0,
            claimsRejected: 0,
            transientAcceptance: 0,
            turnsElapsed: 0
        }
    };

    // Save to localStorage so the /experiment page can pick it up
    localStorage.setItem('hti_session', JSON.stringify(sessionData));

    // Show a brief explanation of the FIRST assigned task before dropping them into it
    showTaskBriefing(firstTask);
}

// --- 4. TASK BRIEFING ---
const TASK_BRIEFINGS = {
    "P1_Marketing": {
        title: "Marketing Budget Challenge",
        objective: "Allocate a fixed $500,000 budget across 5 marketing channels (Search Ads, Content/SEO, Social, Events, Influencer). <strong>Your goal is to maximize your allocation's modeled ROI</strong> while satisfying the round's requirements.",
        advisor: "AI Marketing Advisor"
    },
    "P2_ContentSocial": {
        title: "Campaign Launch Challenge",
        objective: "Configure a social media launch post — tone, urgency, hashtags, posting time, and claims/disclaimer. <strong>Your goal is to maximize the post's modeled engagement</strong> while satisfying the round's requirements.",
        advisor: "AI Social Media Advisor"
    },
    "P3_TripPlanning": {
        title: "Study-Abroad Itinerary Challenge",
        objective: "Plan a 4-day study-abroad trip by picking one activity for each time slot of the day. <strong>Your goal is to maximize your itinerary's overall quality</strong> while satisfying the round's requirements.",
        advisor: "AI Trip-Planning Assistant"
    }
};

function showTaskBriefing(primaryTask) {
    const briefing = TASK_BRIEFINGS[primaryTask] || TASK_BRIEFINGS["P1_Marketing"];

    document.getElementById('briefingTitle').innerText = briefing.title;
    document.getElementById('taskBriefingContent').innerHTML = `
        <div class="consent-block highlight-block">
          <h4>Your objective</h4>
          <p>${briefing.objective}</p>
        </div>
        <div class="consent-block">
          <h4>How it's structured</h4>
          <p>You'll complete <strong>4 rounds</strong>. Each round starts with a preset configuration that does <em>not</em> yet meet the round's requirements — adjust it until the "Live Constraints" panel shows everything satisfied. Some rounds have more requirements to juggle than others.</p>
        </div>
        <div class="consent-block">
          <h4>Using the ${briefing.advisor}</h4>
          <p>The assistant will chime in on its own as you make changes — you don't need to message it first, though you're welcome to chat with it any time.</p>
        </div>
        <div class="consent-block">
          <h4>Submitting a round</h4>
          <p>Once all requirements are met, submit the round and rate your experience, then move to the next one.</p>
        </div>
    `;

    const btn = document.getElementById('personalityNext');
    if (btn) { btn.disabled = false; btn.innerText = "Begin Study →"; }

    // Reset the proceed checkbox/button each time the briefing is (re)shown
    const briefBox = document.getElementById('briefingBox');
    const briefBtn = document.getElementById('briefingNext');
    if (briefBox) briefBox.checked = false;
    if (briefBtn) briefBtn.disabled = true;

    goToStep(3);
}

function beginTask() {
    window.location.href = "/experiment";
}