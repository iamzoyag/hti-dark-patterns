// static/js/intake.js

// --- 1. NAVIGATION & PROGRESS BAR ---
function goToStep(stepNumber) {
    // Hide all step panels
    document.querySelectorAll('.step-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    // Determine the ID of the target step based on the number
    let targetId = 'step-consent';
    if (stepNumber === 2) targetId = 'step-demo';
    if (stepNumber === 3) targetId = 'step-personality';
    if (stepNumber === 4) targetId = 'step-briefing';

    // Show the target step
    const target = document.getElementById(targetId);
    if (target) {
        target.classList.add('active');
    }

    // Update the progress bar fill (4 steps total)
    const progress = ((stepNumber - 1) / 3) * 100;
    document.getElementById('progressFill').style.width = `${progress}%`;
    
    // Scroll to top of the panel
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- 2. CONSENT LOGIC ---
function checkConsent() {
    const box = document.getElementById('consentBox');
    const btn = document.getElementById('consentNext');
    // Enable the continue button only if the box is checked
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
        <div class="pq-item">
            <div class="pq-statement">${index + 1}. ${item.text}</div>
            <div class="pq-scale">
                <label><input type="radio" name="${item.id}" value="1"/><span>1</span></label>
                <label><input type="radio" name="${item.id}" value="2"/><span>2</span></label>
                <label><input type="radio" name="${item.id}" value="3"/><span>3</span></label>
                <label><input type="radio" name="${item.id}" value="4"/><span>4</span></label>
                <label><input type="radio" name="${item.id}" value="5"/><span>5</span></label>
            </div>
        </div>`;
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
    let groupAssignment = "Live";
    let primaryTask = "P1_Marketing";
    let trialSequence = ["HighLoad", "LowLoad", "HighLoad", "LowLoad"];
    let droppedCategoryIndex = 0;
    try {
        const response = await fetch(`/api/assign_group?participant_id=${encodeURIComponent(participantId)}`);
        const data = await response.json();
        groupAssignment = data.group;
        primaryTask = data.primary_task;
        trialSequence = data.trial_sequence;
        droppedCategoryIndex = data.dropped_category_index;
        console.log(`Server assignment #${data.assignment_index}:`, data);
    } catch (error) {
        console.error("Failed to reach assignment server, defaulting to random.", error);
        groupAssignment = "Live";
    }

    // Create the master session object
    const sessionData = {
        participantId: participantId,
        group: groupAssignment,
        primaryTask: primaryTask,
        trialSequence: trialSequence,
        droppedCategoryIndex: droppedCategoryIndex,
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

    // Show a brief explanation of the assigned task before dropping them into it
    showTaskBriefing(primaryTask);
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
          <p>Chat with the assistant about your strategy as you work. You must send at least one message per round before you're able to submit. You can also ask it directly how your current attempt is scoring.</p>
        </div>
        <div class="consent-block">
          <h4>Submitting a round</h4>
          <p>Once requirements are met and you've chatted with the assistant, submit the round and rate your experience, then move to the next one.</p>
        </div>
    `;

    const btn = document.getElementById('personalityNext');
    if (btn) { btn.disabled = false; btn.innerText = "Begin Study →"; }
    goToStep(4);
}

function beginTask() {
    window.location.href = "/experiment";
}