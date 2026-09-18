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

// Proactive advisor check-in: fires automatically after a debounced pause following a
// substantive plan change (or a fallback ceiling for the first one, if they never
// pause). Capped per segment and cooldown-spaced so it can't stack up or nag — see
// scheduleProactiveCheck()/attemptProactiveFire()/triggerProactiveAdvisorNote().
let proactiveFireCount = 0;
let lastProactiveFireTime = null;
let hasSubstantiveChangeSinceLastFire = false;
let proactiveDebounceTimer = null;
let proactiveCeilingTimer = null;
const PROACTIVE_DEBOUNCE_MS = 6000;
const PROACTIVE_CEILING_MS = 45000;   // safety net for the FIRST guaranteed exchange only --> long enough to give a genuine, participant-initiated message priority over this fallback
const PROACTIVE_COOLDOWN_MS = 15000;  // min gap between any two proactive fires
const MAX_PROACTIVE_FIRES_PER_TRIAL = 2;
const TRIAL_TIME_LIMIT_MS = {
    A: { HighLoad: 192000, LowLoad: 240000 }, // 3:12 vs 4:00 (20% less time)
    B: { HighLoad: 192000, LowLoad: 240000 },
    C: { HighLoad: 144000, LowLoad: 180000 }, // 2:24 vs 3:00
};
let trialTimerInterval = null;
let trialTimerDeadline = null;
let isAiRequestInFlight = false;
let perfScore = 50;
let perfDriftTimer = null;

function nudgePerfScore(delta) {
    perfScore = Math.max(4, Math.min(92, perfScore + delta + (Math.random() * 4 - 2)));
    updatePerfScoreDisplay();
}
function updatePerfScoreDisplay() {
    const fill = document.getElementById('perfMeterFill');
    const val = document.getElementById('perfMeterVal');
    if (!fill || !val) return;
    const rounded = Math.round(perfScore);
    val.textContent = rounded;
    fill.style.width = rounded + '%';
    fill.classList.remove('low', 'mid', 'high');
    fill.classList.add(rounded < 35 ? 'low' : rounded < 70 ? 'mid' : 'high');
}
function startPerfDrift() {
    stopPerfDrift();
    perfDriftTimer = setInterval(() => nudgePerfScore(Math.random() < 0.5 ? -2 : 1), 12000);
}
function stopPerfDrift() {
    if (perfDriftTimer) { clearInterval(perfDriftTimer); perfDriftTimer = null; }
}

// The LLM sometimes replies fast enough that the AI's message lands almost instantly,
// which reads as abrupt/unnatural. This tops up the visible "typing" pause to a believable
// minimum without ever slowing down an already-slow reply.
const MIN_AI_RESPONSE_DELAY_MS = 1400;
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

let shadowHistory = [];
let darkTurnCounter = 0; // advances on every send/proactive fire; forms part of the research pattern_id, not a gate on anything
let darkDeliveredThisTrial = false;

let lastAiMessageTime = null; // when the most recent AI message landed — used to measure how long the participant sat with it before acting
let messageDwellTelemetry = {}; // patternId -> { totalVisibleMs, visibleSince, firstVisibleAt } — actual time each AI bubble spent visible, not just "was sent"
let dwellObserver = null;

// ============================================================
// COGNITIVE LOAD -- IN-CHAT NOTIFICATIONS 
// ============================================================
let currentLoadLevel = null; // set in startSegment(); read by renderPlanMirror + scheduleNotifications
let notificationTimers = [];
let notificationsShownThisSegment = []; // this segment only -- feeds this segment's recall-check probe
let sessionNotificationTotals = { recallChecks: 0, recalledCorrect: 0 }; // session-wide, across every segment/task -- feeds the final bonus calc
const NOTIFICATION_ACCURACY_THRESHOLD = 0.6; // TEMP -- fraction of recall checks that must be correct to qualify for the completion bonus; revisit once real sessions are timed
const NOTIFICATION_VISIBLE_MS = 6000; // how long a notification bubble stays before it auto-removes
const NOTIFICATION_INTERVAL_MS = { HighLoad: 18000, LowLoad: 85000 }; // TEMP values, same spirit as TRIAL_TIME_LIMIT_MS -- revisit once real segments have been timed

// All task-irrelevant on purpose -- ordinary campus/phone notices with zero bearing on
// workload/degree/club content, so they can't be confused with real advisor content or
// hint at any locked fact.
const NOTIFICATION_BANK = [
    { id: "n1", text: "📶 Campus WiFi: scheduled maintenance tonight 11pm–1am" },
    { id: "n2", text: "🔋 Battery at 20% — consider plugging in" },
    { id: "n3", text: "🌧️ Weather: rain expected after 4pm today" },
    { id: "n4", text: "🍽️ Dining Hall: grilled cheese special until 2pm" },
    { id: "n5", text: "📦 Package delivered to your mailroom locker" },
    { id: "n6", text: "🚌 Campus Shuttle: Route 2 running 10 min behind schedule" },
    { id: "n7", text: "🎟️ Student Center: movie night tickets go on sale at 6pm" },
    { id: "n8", text: "🧺 Laundry Room (Hall B): 2 machines now available" },
    { id: "n9", text: "📚 Library: extended hours this week for finals prep" },
    { id: "n10", text: "🔑 Lost & Found: a set of keys was turned in at the front desk" },
    { id: "n11", text: "🅿️ Parking Services: Lot C closed for repaving tomorrow" },
    { id: "n12", text: "☕ Coffee cart outside the quad — 2-for-1 until 11am" },
    { id: "n13", text: "📱 App Update: a new version of the campus app is available" },
    { id: "n14", text: "🏋️ Rec Center: pool closed for cleaning this afternoon" },
    { id: "n15", text: "📬 Mail Services: outgoing mail pickup moved to 3pm today" },
    { id: "n16", text: "🔔 Fire alarm test scheduled in North Hall at 1pm — no action needed" },
];

function clearNotificationTimers() {
    notificationTimers.forEach(t => clearTimeout(t));
    notificationTimers = [];
}

// Schedules a run of notification bubbles across the segment's time limit, spaced by
// load level. Recurses via its own setTimeout rather than setInterval so each firing can
// stop cleanly once it's within NOTIFICATION_VISIBLE_MS + 5s of the deadline (a bubble
// that lands with no time left to notice it isn't a fair probe).
function scheduleNotifications(loadLevel, timeLimitMs) {
    clearNotificationTimers();
    notificationsShownThisSegment = [];
    const interval = NOTIFICATION_INTERVAL_MS[loadLevel] || NOTIFICATION_INTERVAL_MS.LowLoad;
    const fireOnce = (delay) => {
        if (delay >= timeLimitMs - (NOTIFICATION_VISIBLE_MS + 5000)) return;
        const t = setTimeout(() => {
            const unseen = NOTIFICATION_BANK.filter(n => !notificationsShownThisSegment.some(s => s.id === n.id));
            const pool = unseen.length ? unseen : NOTIFICATION_BANK;
            const item = pool[Math.floor(Math.random() * pool.length)];
            notificationsShownThisSegment.push(item);
            showNotificationBubble(item);
            fireOnce(delay + interval);
        }, delay);
        notificationTimers.push(t);
    };
    fireOnce(Math.round(interval * 0.4)); // first one lands partway in, not the instant the segment opens
}

// Renders directly into the chat log (not a separate widget) so it's a genuine
// competitor for attention with the real conversation, then removes itself --
// unlike AI/user messages, it does NOT persist in the transcript.
function showNotificationBubble(item) {
    const chatContainer = document.getElementById('chatMessages');
    if (!chatContainer) return;
    const div = document.createElement('div');
    div.className = 'msg notification';
    div.innerHTML = `<div class="msg-bubble"><span class="notification-tag">Notification</span>${item.text}</div>`;
    chatContainer.appendChild(div);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    logEvent('notification_shown', { id: item.id, text: item.text });
    // Fades/slides out instead of vanishing instantly (see .notification-leaving in
    // experiment.css) -- purely cosmetic, doesn't change when it's logged or how long
    // it's actually legible for the recall check.
    setTimeout(() => {
        div.classList.add('notification-leaving');
        setTimeout(() => div.remove(), 250);
    }, NOTIFICATION_VISIBLE_MS);
}

const RECALL_PROBE_COUNT = { HighLoad: 4, LowLoad: 2 }; // independent old/new probes per segment -- each its own 50/50 real-vs-decoy draw

function showRecallCheck(loadLevel, onDone) {
    const probeCount = RECALL_PROBE_COUNT[loadLevel] || RECALL_PROBE_COUNT.LowLoad;
    if (!notificationsShownThisSegment.length) {
        logEvent('recall_check_skipped', { trial: currentTrial });
        onDone();
        return;
    }
    const overlay = document.getElementById('recallCheckOverlay');
    const textEl = document.getElementById('recallCheckText');
    const yesBtn = document.getElementById('recallCheckYesBtn');
    const noBtn = document.getElementById('recallCheckNoBtn');
    const eyebrowEl = document.getElementById('recallCheckEyebrow');
    if (!overlay || !textEl || !yesBtn || !noBtn) { onDone(); return; }

    const usedIds = new Set(); // avoid probing the same item twice in one round where a distinct choice exists

    const pickProbe = () => {
        const wasShown = Math.random() < 0.5;
        let pool;
        if (wasShown) {
            pool = notificationsShownThisSegment.filter(n => !usedIds.has(n.id));
            if (!pool.length) pool = notificationsShownThisSegment;
        } else {
            const unseen = NOTIFICATION_BANK.filter(n => !notificationsShownThisSegment.some(s => s.id === n.id));
            pool = unseen.filter(n => !usedIds.has(n.id));
            if (!pool.length) pool = unseen.length ? unseen : notificationsShownThisSegment.filter(n => !usedIds.has(n.id));
            if (!pool.length) pool = notificationsShownThisSegment;
        }
        return { probeItem: pool[Math.floor(Math.random() * pool.length)], wasShown };
    };

    const runProbe = (probeNumber) => {
        const { probeItem, wasShown } = pickProbe();
        usedIds.add(probeItem.id);
        if (eyebrowEl) eyebrowEl.innerText = `One Quick Thing (${probeNumber} of ${probeCount})`;
        textEl.innerText = `"${probeItem.text}"`;

        const resolve = (answeredYes) => {
            const correct = answeredYes === wasShown;
            sessionNotificationTotals.recallChecks++;
            if (correct) sessionNotificationTotals.recalledCorrect++;
            logEvent('recall_check_answered', { trial: currentTrial, probe_number: probeNumber, probe_id: probeItem.id, was_shown: wasShown, answered_yes: answeredYes, correct });
            if (probeNumber < probeCount) {
                runProbe(probeNumber + 1);
            } else {
                overlay.style.display = 'none';
                onDone();
            }
        };
        yesBtn.onclick = () => resolve(true);
        noBtn.onclick = () => resolve(false);

        overlay.style.display = 'flex';
    };

    runProbe(1);
}

// Called only on the very last segment's submission -- turns the session-wide recall
// tally into the exact fields main.py's CSV export reads. "" (not 0) when no checks ever
// ran, so it reads as "not applicable" rather than a real 0% score.
function finalizeAttentionBonus() {
    const { recallChecks, recalledCorrect } = sessionNotificationTotals;
    const accuracy = recallChecks > 0 ? recalledCorrect / recallChecks : null;
    sessionData.attentionAccuracy = accuracy === null ? "" : Math.round(accuracy * 100) / 100;
    sessionData.attentionQualified = accuracy !== null && accuracy >= NOTIFICATION_ACCURACY_THRESHOLD;
    logEvent('attention_bonus_computed', { recall_checks: recallChecks, recalled_correct: recalledCorrect, accuracy, qualified: sessionData.attentionQualified });
}

const TLX_ITEMS = [ // keep in sync with tlxItems in debrief.js
    { id: "mental", label: "Mental Demand", desc: "How mentally demanding was that round?", left: "Low Mental Demand", right: "High Mental Demand" },
    { id: "physical", label: "Physical Demand", desc: "How physically demanding was that round?", left: "Low Physical Demand", right: "High Physical Demand" },
    { id: "temporal", label: "Temporal Demand", desc: "How hurried or rushed was the pace?", left: "Low Temporal Demand", right: "High Temporal Demand" },
    { id: "performance", label: "Performance", desc: "How successful were you in that round?", left: "Failure", right: "Perfect" },
    { id: "effort", label: "Effort", desc: "How hard did you have to work?", left: "Low Effort", right: "High Effort" },
    { id: "frustration", label: "Frustration", desc: "How insecure, discouraged, or stressed were you?", left: "Low Frustration", right: "High Frustration" }
];

// Subjective check-in questions shown below the TLX table, every round, in the same per-trial window.
const SUBJECTIVE_ITEMS = [
    { id: "helpfulness", label: "Helpfulness", desc: "How helpful were the AI's suggestions this round?", left: "Not helpful at all", right: "Extremely helpful" },
    { id: "trust", label: "Trust", desc: "How much did you trust the AI's advice this round?", left: "Not at all", right: "Completely" },
    { id: "persuasiveness", label: "Influence", desc: "How much did the AI's suggestions influence your final decision this round?", left: "Not at all", right: "A great deal" },
    { id: "independence", label: "Independence", desc: "How much did you rely on your own judgment vs. the AI this round?", left: "Entirely the AI", right: "Entirely my own judgment" }
];

const PT_BOX_MIN = 1, PT_BOX_MAX = 7; // NASA-TLX: 1-7 scale
const SQ_BOX_MIN = 1, SQ_BOX_MAX = 5; // subjective / post-task questions: 1-5 scale

function renderTLXItem(item) {
    let cells = '';
    for (let v = PT_BOX_MIN; v <= PT_BOX_MAX; v++) {
        cells += `<label class="tlx-cell"><input type="radio" name="ptq_${item.id}" value="${v}"><span>${v}</span></label>`;
    }
    return `
    <div class="tlx-item" data-key="${item.id}">
        <span class="tlx-item-label">${item.label}</span>
        <span class="tlx-item-desc">${item.desc}</span>
        <div class="tlx-scale-row">
            <span class="likert-label-end">${item.left}</span>
            <div class="tlx-track">${cells}</div>
            <span class="likert-label-end">${item.right}</span>
        </div>
    </div>`;
}

function renderSubjectiveItem(item) {
    let cells = '';
    for (let v = SQ_BOX_MIN; v <= SQ_BOX_MAX; v++) {
        cells += `<label class="tlx-cell"><input type="radio" name="ptq_${item.id}" value="${v}"><span>${v}</span></label>`;
    }
    return `
    <div class="sq-item tlx-item" data-key="${item.id}">
        <span class="tlx-item-label">${item.label}</span>
        <span class="tlx-item-desc">${item.desc}</span>
        <div class="tlx-scale-row">
            <span class="likert-label-end">${item.left}</span>
            <div class="tlx-track">${cells}</div>
            <span class="likert-label-end">${item.right}</span>
        </div>
    </div>`;
}

// isTaskFinal: true only on the trial-4 submission for a task
// below the regular per-round questions in this same overlay, instead of a separate screen.
function showPerTrialTLX(trialIndex, isTaskFinal, onContinue) {
    const overlay = document.getElementById('perTrialTlxOverlay');
    const container = document.getElementById('perTrialTlxQuestions');
    const btn = document.getElementById('perTrialTlxContinueBtn');
    if (!overlay || !container || !btn) { onContinue(); return; }

    const feedbackBlock = isTaskFinal ? `
        <div class="trial-feedback-block" style="margin-top:16px;">
            <label class="tlx-item-label" for="perTaskJustificationText">In a sentence or two, why did you land on your final choices for this task? *</label>
            <textarea id="perTaskJustificationText" rows="3" placeholder="Required — explain your reasoning, not just what you picked." style="width:100%; margin-top:8px; font-family:inherit; font-size:14px; padding:10px; border:1px solid #ccc; border-radius:6px; resize:vertical;"></textarea>
        </div>
        <div class="trial-feedback-block" style="margin-top:16px;">
            <label class="tlx-item-label" for="perTrialFeedbackText">Anything about that task overall? (optional)</label>
            <textarea id="perTrialFeedbackText" rows="3" placeholder="Optional — leave blank if you'd rather not." style="width:100%; margin-top:8px; font-family:inherit; font-size:14px; padding:10px; border:1px solid #ccc; border-radius:6px; resize:vertical;"></textarea>
        </div>` : '';

    let html = TLX_ITEMS.map(renderTLXItem).join('') +
        `<div class="survey-questions">${SUBJECTIVE_ITEMS.map(renderSubjectiveItem).join('')}</div>` +
        feedbackBlock;
    container.innerHTML = html;

    const touched = new Set();
    btn.disabled = true;
    const ALL_ITEMS = [...TLX_ITEMS, ...SUBJECTIVE_ITEMS];
    const refreshBtnState = () => {
        const justificationOk = !isTaskFinal || document.getElementById('perTaskJustificationText')?.value.trim().length > 0;
        btn.disabled = touched.size < ALL_ITEMS.length || !justificationOk;
    };

    container.querySelectorAll('.tlx-item').forEach(row => {
        row.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', () => {
                touched.add(row.dataset.key);
                refreshBtnState();
            });
        });
    });
    document.getElementById('perTaskJustificationText')?.addEventListener('input', refreshBtnState);

    btn.onclick = async () => {
        const scores = {};
        container.querySelectorAll('.tlx-item').forEach(row => {
            const checked = row.querySelector('input[type="radio"]:checked');
            if (checked) scores[row.dataset.key] = parseInt(checked.value);
        });
        const justificationText = document.getElementById('perTaskJustificationText')?.value.trim() || '';
        const feedbackText = document.getElementById('perTrialFeedbackText')?.value.trim() || '';

        btn.disabled = true;
        const originalLabel = btn.textContent;
        if (isTaskFinal) btn.textContent = "Scoring...";

        let reasoningScore = null;
        if (isTaskFinal && justificationText) {
            try {
                const constraintsDesc = `Locked facts revealed to the participant this segment: ${revealedFactsThisSegment.join(', ') || '(none)'}`;
                const res = await fetch('/api/score_justification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ justification_text: justificationText, task_id: sessionData.primaryTask, constraints_desc: constraintsDesc })
                });
                reasoningScore = (await res.json()).reasoning_score;
            } catch (err) {
                console.error("Justification scoring failed:", err);
            }
        }

        sessionData.perTrialTLX = sessionData.perTrialTLX || [];
        sessionData.perTrialTLX.push({ trial: trialIndex, ...scores, justification: justificationText, reasoning_score: reasoningScore, feedback: feedbackText });
        logEvent('trial_tlx_submitted', { trial: trialIndex, task_final: isTaskFinal, ...scores, justification: justificationText, reasoning_score: reasoningScore, feedback: feedbackText });
        if (reasoningScore !== null) logEvent('trial_justification_scored', { trial: trialIndex, reasoning_score: reasoningScore });

        btn.textContent = originalLabel;
        overlay.style.display = 'none';
        onContinue();
    };

    overlay.style.display = 'flex';
    // The card is a fixed element that's reused every trial — without this it keeps
    // whatever scroll position it was left at (often scrolled down to the Continue
    // button), so the next trial's questions open already scrolled past Mental Demand.
    const card = overlay.querySelector('.overlay-card');
    if (card) card.scrollTop = 0;
}

// ============================================================
// SEGMENT_DATA -- client-side mirror of main.py's TASK_DATA_A/B/C, but ONLY the
// pieces needed to render labels and initialize a segment's starting plan_state.
// Deliberately does NOT include caps, minimums, true_hours, prereqs, exclusions, or
// anything else that would hand the participant the answer key client-side -- that's
// the whole point of the necessity redesign (see ai-assistant-necessity-redesign.md).
// The real evaluation only ever happens server-side, against TASK_DATA_A/B/C in main.py.
// ============================================================
const SEGMENT_DATA = {
    A: {
        itemLabels: {
            chem210: "CHEM 210 -- Organic Chemistry I",
            stat150: "STAT 150 -- Introduction to Statistics",
            hist240: "HIST 240 -- Modern World History",
            cs301: "CS 301 -- Data Structures & Algorithms",
            eng105: "ENG 105 -- Academic Writing II",
            capstone: "Capstone Project -- Community Data Dashboard",
        },
        // Visible weekly hour cap only -- NOT the locked buffer_floor or true_hours from
        // TASK_DATA_A in main.py. Same across all 4 segments, so one flat lookup suffices.
        capByLoad: { HighLoad: 40, LowLoad: 45 },
        segments: {
            segment_1: { items: ["chem210", "stat150", "hist240", "capstone"], default: { chem210: 3, stat150: 4, hist240: 2, capstone: 5 } },
            segment_2: { items: ["chem210", "stat150", "hist240", "capstone"] }, // carry-forward: no scripted default, see buildSegmentStartingPlanState
            segment_3: { items: ["chem210", "stat150", "hist240", "capstone", "cs301"], newItemDefaults: { cs301: 0 } },
            segment_4: { items: ["capstone", "eng105", "chem210", "stat150"], newItemDefaults: { eng105: 0 } },
        }
    },
    B: {
        courseLabels: {
            ds210: "DS 210", ds220: "DS 220", ds310: "DS 310",
            math215: "MATH 215", ds400: "DS 400 -- Capstone",
            intl220: "INTL 220", intl250: "INTL 250", intl301: "INTL 301", lang202: "LANG 202",
            art101: "ART 101", phil110: "PHIL 110", econ105: "ECON 105",
        },
        courseDescriptions: {
            ds210: "Intro to Data Science — data wrangling & visualization",
            ds220: "Applied Statistics — hypothesis testing & regression",
            ds310: "Machine Learning Fundamentals",
            math215: "Linear Algebra for Data Science",
            ds400: "Capstone — term-long applied data project",
            intl220: "Intro to Global Studies",
            intl250: "Comparative Politics",
            intl301: "International Economic Policy",
            lang202: "Intermediate Language II",
            art101: "Intro to Visual Art",
            phil110: "Intro to Philosophy",
            econ105: "Principles of Economics",
        },
        // Visible catalog facts only: per-term credit cap and Major/Minor/Elective
        // minimums (the term's stated degree requirements -- the task's premise, not a
        // secret) and each course's own credit-hours (printed on the course catalog).
        // Constant across all 4 segments. Deliberately does NOT include prereqs,
        // exclusion pairs, conflict pairs, or the transfer_rule -- those stay locked,
        // same as TASK_DATA_B in main.py.
        capByLoad: { HighLoad: 17, LowLoad: 18 },
        minimums: { major: 8, minor: 6, elective: 3 },
        courseCredits: {
            ds210: 4, ds220: 4, ds310: 4, math215: 3, ds400: 4,
            intl220: 3, intl250: 3, intl301: 3, lang202: 4,
            art101: 3, phil110: 3, econ105: 3,
        },
        segments: {
            segment_1: { pools: { major: ["ds210", "ds220", "ds310", "math215", "ds400"], minor: ["intl220", "intl250", "intl301", "lang202"], elective: ["art101", "phil110", "econ105"] }, default: { major: ["ds400"], minor: ["intl220"], elective: [] } },
            segment_2: { pools: { major: ["ds210", "ds220", "ds310", "math215", "ds400"], minor: ["intl220", "intl250", "intl301", "lang202"], elective: ["art101", "phil110", "econ105"] }, default: { major: ["ds210", "ds220"], minor: ["intl220", "intl301"], elective: ["phil110"] } },
            segment_3: { pools: { major: ["ds210", "ds220", "ds310", "math215", "ds400"], minor: ["phil110", "econ105", "lang202"], elective: ["art101", "phil110", "econ105"] }, default: { major: ["ds210", "ds220"], minor: ["lang202"], elective: ["art101"] } },
            segment_4: { pools: { major: ["ds210", "ds220", "ds310", "math215", "ds400"], minor: ["intl220", "intl250", "intl301", "lang202"], elective: ["art101", "phil110", "econ105"] }, default: { major: ["ds210", "ds310", "math215"], minor: ["intl220", "intl250"], elective: ["art101"] } },
        }
    },
    C: {
        clubLabels: {
            soccer: "Intramural Soccer", climbing: "Rock Climbing Club",
            cadences: "The Cadences (a cappella)", art_collective: "Studio Art Collective",
            chess: "Chess Club", mixer: "International Students Mixer",
            robotics: "Robotics Club", debate: "Debate Team", tutoring: "Peer Tutoring Volunteers",
        },
        // Visible activities-fair facts only: each club's listed category (how it's
        // labeled on the sign-up board) and advertised weekly hours, plus the visible
        // weekly cap by load level. Deliberately does NOT include true_hours_override or
        // conflict_pairs -- those stay locked, same as TASK_DATA_C in main.py.
        clubCategories: {
            soccer: "Physical", climbing: "Physical",
            cadences: "Creative", art_collective: "Creative",
            chess: "Social", mixer: "Social",
            robotics: "Academic-adjacent", debate: "Academic-adjacent", tutoring: "Academic-adjacent",
        },
        clubBaseHours: {
            soccer: 1.5, climbing: 1.5, cadences: 1.5, art_collective: 1.5,
            chess: 1.5, mixer: 1.5, robotics: 2.0, debate: 2.0, tutoring: 1.0,
        },
        capByLoad: { HighLoad: 10, LowLoad: 12 },
        segments: {
            segment_1: { roster: ["soccer", "climbing", "cadences", "art_collective", "chess", "mixer", "robotics", "debate", "tutoring"], default: ["robotics", "chess"] },
            segment_2: { roster: ["soccer", "climbing", "cadences", "art_collective", "chess", "mixer", "robotics", "debate", "tutoring"], default: ["robotics", "cadences", "chess", "mixer"] },
            segment_3: { roster: ["soccer", "climbing", "cadences", "art_collective", "chess", "mixer", "robotics", "debate", "tutoring"], default: { HighLoad: ["robotics", "cadences", "chess", "debate"], LowLoad: ["robotics", "cadences", "chess", "debate", "soccer"] } },
            segment_4: { roster: ["soccer", "climbing", "cadences", "art_collective", "chess", "mixer", "robotics", "debate", "tutoring"], default: { HighLoad: ["robotics", "cadences", "chess", "debate", "soccer"], LowLoad: ["robotics", "cadences", "chess", "debate", "soccer"] } },
        }
    }
};

const CATEGORY_META = {
    A: { advisorName: "AI Academic Advisor", pageTitle: "Workload Planning", docLabel: "THIS WEEK'S PLAN", placeholder: "Tell your advisor what to change (e.g. \"put 5 hours on CHEM 210\")..." },
    B: { advisorName: "AI Academic Advisor", pageTitle: "Degree Requirements", docLabel: "CURRENT COURSE PLAN", placeholder: "Tell your advisor what to add or drop..." },
    C: { advisorName: "AI Academic Advisor", pageTitle: "Non-Academic Life", docLabel: "THIS WEEK'S ACTIVITIES", placeholder: "Tell your advisor what to add or drop..." },
};

const TASK_BRIEFINGS = {
    "A_Workload": {
        title: "Workload Planning",
        objective: "You're a sophomore at Plaksha University building this week's study-hours plan across your courses and capstone, within a weekly cap. <strong>Get each item the hours it actually needs this week</strong>: the syllabus-listed hours are a semester average, so a specific week can need more (say, a midterm), and part of your cap has to stay unscheduled as rest. Your advisor knows this week's real numbers if you ask; matching the syllabus alone isn't guaranteed to pass review.",
        advisor: "AI Academic Advisor",
    },
    "B_DegreeRequirements": {
        title: "Degree Requirements",
        objective: "You're finalizing your course plan for the term at Plaksha University, meeting minimum credits across Major, Global Studies Minor, and Elective within an 18-credit cap. <strong>Clear the term's actual requirements</strong>, not just the credit minimums: the catalog lists titles and credits, but not every prerequisite, content overlap, or scheduling conflict between courses. Your advisor can tell you if a course you're considering has one; the registrar checks everything before enrollment opens.",
        advisor: "AI Academic Advisor",
    },
    "C_NonAcademicLife": {
        title: "Non-Academic Life",
        objective: "You're planning your non-academic commitments for the week at Plaksha University, clubs, sports, and activities, within a weekly hour cap and covering at least 3 of 4 interest categories (Physical, Creative, Social, Academic-adjacent). <strong>Build a slate that's actually workable this week</strong>, not just balanced on paper: the sign-up board lists each activity's usual hours and meeting time, but a specific week can run longer (a tournament, a rehearsal) or overlap with something else you've picked. Your advisor can tell you if that applies to something you're considering.",
        advisor: "AI Academic Advisor",
    },
};

let submitAttemptsThisTrial = 0; // resets each segment (see startSegment) -- drives the escalating rejection copy below
const SUBMIT_REJECTION_MESSAGES = [
    "This plan doesn't fully meet review standards yet — take another look.",
    "Still short of what's needed for sign-off. If you're not sure what's being flagged, your advisor may be able to tell you."
];
const SUBMIT_PASS_MESSAGE = "Reviewed. This plan holds up. Moving on to the next week.";

const SEGMENT_OPENING_LINES = {
    A: {
        segment_1: (loadLevel) => `This week's plan is due for advisor review ahead of your midterm check-in. Build a study-hours plan across Chem 210, Stat 150, Hist 240, and your capstone that actually covers what each of them needs this week — not just one that looks reasonable at a glance. Your total for the week is capped at ${SEGMENT_DATA.A.capByLoad[loadLevel]} hours.`,
        segment_2: (loadLevel) => `Chem 210's midterm just got moved up. Your plan from last week needs a fresh look — make sure it still genuinely covers everything, Chem 210 included, before it goes back to your advisor. (Weekly cap is still ${SEGMENT_DATA.A.capByLoad[loadLevel]} hours.)`,
        segment_3: (loadLevel) => `CS 301 just got added to your plate, and your weekly cap hasn't grown to match. Rework your hours so everything — including CS 301 — actually gets what it needs, within this week's ${SEGMENT_DATA.A.capByLoad[loadLevel]}-hour cap.`,
        segment_4: (loadLevel) => `Capstone crunch is here and ENG 105 is due, while Chem 210 and Stat 150 settle back to a normal week. Update your plan so it holds up across all four, within this week's ${SEGMENT_DATA.A.capByLoad[loadLevel]}-hour cap.`,
    },
    B: {
        segment_1: "Your course selections this term lock in your actual registration — the registrar checks them against your degree requirements before enrollment opens. Build a slate across Major (8+ credits), your Global Studies Minor (6+ credits), and Elective (3+ credits) that stays within this term's 18-credit cap.",
        segment_2: "You're swapping an elective this term. Make sure your updated slate still clears every requirement — Major (8+ credits), Global Studies Minor (6+), Elective (3+) — within the 18-credit cap.",
        segment_3: "Your Global Studies Minor course options have changed for this term. Rework your slate so it still clears Major (8+ credits), Minor (6+), and Elective (3+) credits, within the 18-credit cap.",
        segment_4: "A scheduling conflict just came up in your registration. Adjust your slate so everything still fits — Major (8+ credits), Global Studies Minor (6+), Elective (3+) — within the 18-credit cap.",
    },
    C: {
        segment_1: (loadLevel) => `Your activity picks get folded into your RA's end-of-month wellness check-in. Build a weekly slate of clubs and activities that's genuinely well-rounded and workable — not just one that looks balanced. This week's activities cap is ${SEGMENT_DATA.C.capByLoad[loadLevel]} hours.`,
        segment_2: (loadLevel) => `A new opportunity came up mid-week. Update your slate so it's still genuinely workable with everything you're now considering, within this week's ${SEGMENT_DATA.C.capByLoad[loadLevel]}-hour cap.`,
        segment_3: (loadLevel) => `One of your existing commitments just grew. Rework your slate so it still genuinely fits within this week's ${SEGMENT_DATA.C.capByLoad[loadLevel]}-hour cap.`,
        segment_4: (loadLevel) => `Performance week is here. Update your slate one more time so it still genuinely holds up within this week's ${SEGMENT_DATA.C.capByLoad[loadLevel]}-hour cap.`,
    },
};

let currentTrial = 1; // segment index, 1-4 -- name kept for minimal churn with existing TLX/save-data code
let turnsInTrial = 0;
let hasInteractedThisTrial = false;

// plan_state lives entirely client-side and is echoed to the server each turn (like the
// old `allocations`), then only ever changed here via applyPlanActions() -- the LLM's
// validated `actions`, which only fire when the participant explicitly asked for a change.
let currentPlanState = {};
let startOfTrialPlanState = {};
let currentTargetItem = null;
let lastChangedItemIds = []; // item ids applyPlanActions() just touched -- read once by renderPlanMirror() to flash those rows, then cleared
let disclosedIdsSoFar = [];      // fact IDs already revealed this segment -- sent to /api/chat each turn
let revealedFactsThisSegment = []; // same list, kept around for the TLX justification-scoring prompt

function getCategory() {
    return (sessionData.primaryTask || "A_Workload").split("_")[0];
}

document.addEventListener('DOMContentLoaded', () => {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) { window.location.href = '/'; return; }

    sessionData = JSON.parse(rawData);

    const idDisplay = document.getElementById('participantIdDisplay');
    if (idDisplay) idDisplay.innerText = `ID: ${sessionData.participantId} [${sessionData.group}]`;

    setupModality();
    if (!sessionData.tutorialCompleted) {
        startTutorial();
    } else {
        startSegment(1);
    }
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
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
}

function advanceToNextTask() {
    sessionData.currentTaskIndex++;
    const nextTask = sessionData.taskOrder[sessionData.currentTaskIndex];
    const nextAssignment = sessionData.taskAssignments[nextTask];

    sessionData.primaryTask = nextTask;
    sessionData.trialSequence = nextAssignment.trial_sequence;
    sessionData.droppedCategoryIndex = nextAssignment.dropped_category_index;
    currentTrial = 1;
    shadowHistory = [];

    logEvent('task_transition', { next_task: nextTask, task_position: sessionData.currentTaskIndex });

    showTaskBriefingOverlay(nextTask);
}

function continueToNextTask() {
    document.getElementById('taskTransitionOverlay').style.display = 'none';
    startSegment(1);
}

// ============================================================
// TUTORIAL / PRACTICE ROUND — runs once, before Task 1's Segment 1.
// Entirely self-contained (own state, own DOM content, no /api/chat or /api/save_data
// calls) so nothing here is recorded or affects real metrics. Rewritten so the ONE
// practice action is a chat message, not a slider/toggle -- the old version trained
// participants that talking to the assistant was optional (see finding #4 in
// ai-assistant-necessity-redesign.md); this one requires it to unlock Continue.
// ============================================================
let isTutorialActive = false;
let tutorialStep = 0; // 0 = hours demo, 1 = add/remove demo, 2 = add/drop demo, 3 = done
let tutorialPlanState = { hours: { practice_item: 0 }, clubs: [], courses: [] };
const PRACTICE_CLUB_ROSTER = ["Chess Club", "Soccer Club"];
const PRACTICE_COURSE_ROSTER = ["PHIL 101", "ART 101"];

function renderTutorialPlanMirror() {
    const hrs = tutorialPlanState.hours.practice_item;
    const clubRows = PRACTICE_CLUB_ROSTER.map(name => {
        const picked = tutorialPlanState.clubs.includes(name);
        return `<div class="plan-mirror-row${picked ? '' : ' plan-mirror-row-unplaced'}"><span>${name}</span><span>${picked ? 'Added' : 'Not added'}</span></div>`;
    }).join('');
    const courseRows = PRACTICE_COURSE_ROSTER.map(name => {
        const picked = tutorialPlanState.courses.includes(name);
        return `<div class="plan-mirror-row${picked ? '' : ' plan-mirror-row-unplaced'}"><span>${name}</span><span>${picked ? '3 cr' : 'Available'}</span></div>`;
    }).join('');
    return `
        <div class="plan-mirror-bucket">
            <div class="plan-mirror-bucket-label">Hours-based item</div>
            <div class="plan-mirror-row"><span>Practice Course</span><span>${hrs} hrs</span></div>
        </div>
        <div class="plan-mirror-bucket">
            <div class="plan-mirror-bucket-label">Add/remove item</div>
            ${clubRows}
        </div>
        <div class="plan-mirror-bucket">
            <div class="plan-mirror-bucket-label">Add/drop item</div>
            ${courseRows}
        </div>`;
}

function startTutorial() {
    isTutorialActive = true;
    tutorialStep = 0;
    tutorialPlanState = { hours: { practice_item: 0 }, clubs: [], courses: [] };

    const chatNameEl = document.querySelector('.chat-ai-name');
    if (chatNameEl) chatNameEl.innerText = "AI Practice Assistant";
    document.title = "Interface Walkthrough";
    const chatInputEl = document.getElementById('chatInput');
    if (chatInputEl) chatInputEl.placeholder = 'Try: "put 3 hours on the practice course"';

    // Shows a static example so participants know where the real countdown will be —
    // see the note about it below and the CSS bump making it more visible generally.
    const timerEl = document.getElementById('trialTimerDisplay');
    if (timerEl) { timerEl.innerText = '⏱ 4:00'; timerEl.title = 'Example — every real round has one of these, counting down.'; }

    document.getElementById('docTitle').innerText = "Practice · not recorded";
    document.getElementById('docBody').innerHTML = `
        <div class="dashboard-top">
            <div class="score-card">
                <span class="sc-label">Mode</span>
                <span class="sc-val" style="font-size:16px;">Practice</span>
            </div>
        </div>
        <div id="tutorialPlanSummary">${renderTutorialPlanMirror()}</div>
        <button id="tutorialSubmitBtn" class="btn-primary" style="width: 100%; margin-top: 24px;" disabled onclick="submitTutorialRound()">
            Continue to Task 1
        </button>
    `;

    setTimeout(() => showTypingIndicator(), 500);
    setTimeout(() => {
        document.getElementById('currentTyping')?.remove();
        addMessage("Welcome! I'm your practice advisor. Everything here works by chat, there's nothing to click or drag. Let's walk through the three ways you'll update your plan.", "ai");
    }, 1600);
    setTimeout(() => showTypingIndicator(), 2600);
    setTimeout(() => {
        document.getElementById('currentTyping')?.remove();
        addMessage('First: type an amount to set hours on an item. Try "put 3 hours on the practice course."', "ai");
    }, MIN_AI_RESPONSE_DELAY_MS + 2600);
}

function sendTutorialMessage() {
    const inputEl = document.getElementById('chatInput');
    const text = inputEl.value.trim();
    if (!text) return;
    addMessage(text, 'user');
    inputEl.value = '';
    showTypingIndicator();
    const lower = text.toLowerCase();

    setTimeout(() => {
        document.getElementById('currentTyping')?.remove();

        if (tutorialStep === 0) {
            const match = text.match(/\d+/);
            const hours = match ? Math.max(1, Math.min(20, parseInt(match[0]))) : 3;
            tutorialPlanState.hours.practice_item = hours;
            tutorialStep = 1;
            addMessage(`Got it, ${hours} hours on the practice course. That's how every hours-based item works: say a number, I update it.`, 'ai');
            setTimeout(() => addMessage('Next: try adding an activity, like "add Chess Club."', 'ai'), 900);
        } else if (tutorialStep === 1) {
            const club = PRACTICE_CLUB_ROSTER.find(c => lower.includes(c.toLowerCase())) || PRACTICE_CLUB_ROSTER[0];
            if (!tutorialPlanState.clubs.includes(club)) tutorialPlanState.clubs.push(club);
            tutorialStep = 2;
            addMessage(`Added ${club}. Some rounds work the same way with courses instead of clubs.`, 'ai');
            setTimeout(() => addMessage('Try "add PHIL 101" (you can "drop" something the same way).', 'ai'), 900);
        } else if (tutorialStep === 2) {
            const course = PRACTICE_COURSE_ROSTER.find(c => lower.includes(c.toLowerCase())) || PRACTICE_COURSE_ROSTER[0];
            const isDrop = /\bdrop\b|\bremove\b/.test(lower);
            if (isDrop) {
                tutorialPlanState.courses = tutorialPlanState.courses.filter(c => c !== course);
            } else if (!tutorialPlanState.courses.includes(course)) {
                tutorialPlanState.courses.push(course);
            }
            tutorialStep = 3;
            addMessage(`${isDrop ? 'Dropped' : 'Added'} ${course}. That's all three: hours, adding, and dropping.`, 'ai');
            setTimeout(() => addMessage("A countdown timer like the one now showing next to your plan runs in every real round. If it hits zero, your plan submits as-is. Whenever you're ready, hit Continue to Task 1.", 'ai'), 900);
        }

        document.getElementById('tutorialPlanSummary').innerHTML = renderTutorialPlanMirror();
        if (tutorialStep === 3) document.getElementById('tutorialSubmitBtn').disabled = false;
    }, MIN_AI_RESPONSE_DELAY_MS);
}

function submitTutorialRound() {
    isTutorialActive = false;
    sessionData.tutorialCompleted = true;
    localStorage.setItem('hti_session', JSON.stringify(sessionData));
    showTaskBriefingOverlay(sessionData.primaryTask);
}

async function buildInterimComparisonBlock() {
    try {
        const res = await fetch(`/api/leaderboard?participant_id=${encodeURIComponent(sessionData.participantId)}`);
        const data = await res.json();
        if (!data.you) return "";
        return `
        <div class="consent-block">
          <h4>How you're doing so far</h4>
          <p>So far, you're outperforming <strong>${data.you.percentile}%</strong> of participants who've reached this point (rank ${data.you.rank} of ${data.total_participants}).</p>
        </div>`;
    } catch (e) {
        return "";
    }
}

// Shows the assigned task's full briefing (objective, structure, advisor, etc.) in
// the same overlay used for between-task transitions, gated behind an "I understand"
// checkbox — mirrors the consent-style gate the old intake-page briefing step used.
async function showTaskBriefingOverlay(taskId) {
    const briefing = TASK_BRIEFINGS[taskId] || TASK_BRIEFINGS["A_Workload"];
    const leaderboardBlockHtml = sessionData.currentTaskIndex > 0 ? await buildInterimComparisonBlock() : "";

    document.getElementById('taskTransitionTitle').innerText = briefing.title;
    document.getElementById('taskTransitionBody').innerHTML = `
        <div class="consent-block highlight-block">
          <h4>Your objective</h4>
          <p>${briefing.objective}</p>
        </div>
        <div class="consent-block">
          <h4>How it works</h4>
          <p>You'll go through <strong>4 weeks</strong>, each a new situation. To change your plan, type what you want in plain language to your ${briefing.advisor} (e.g. "put 5 hours on Chem 210," "add Robotics Club," "drop Art 101"). There are no other controls. The panel on the left updates as soon as a change lands.</p>
        </div>
        <div class="consent-block">
          <h4>Using the ${briefing.advisor}</h4>
          <p>The ${briefing.advisor} may know things about a week that aren't shown on the panel. Ask directly if something seems off or missing; it will only tell you what you ask about.</p>
        </div>
        <div class="consent-block highlight-block">
          <h4>How this gets evaluated</h4>
          <p>After each task, briefly explain the reasoning behind your final decisions. Some explanations may be reviewed by the research team or shown, anonymized, to other participants.</p>
        </div>
        ${leaderboardBlockHtml}
        <div class="consent-block">
          <h4>Submitting each week</h4>
          <p>Submit whenever you're ready. If your plan doesn't clear that week's requirements, you'll get a short note and can keep adjusting. Watch the countdown timer next to your plan header: when it hits zero, whatever's currently in your plan is submitted automatically.</p>
        </div>
        <label class="checkbox-row" id="taskBriefingCheck" style="margin-top:16px;">
          <input type="checkbox" id="taskBriefingBox" onchange="onTaskBriefingCheckChange()"/>
          <span class="checkbox-custom"></span>
          <span>I understand the task instructions and wish to proceed.</span>
        </label>
    `;

    const btn = document.getElementById('taskTransitionContinueBtn');
    btn.disabled = true;
    btn.onclick = () => {
        document.getElementById('taskTransitionOverlay').style.display = 'none';
        startSegment(1);
    };

    const transitionOverlay = document.getElementById('taskTransitionOverlay');
    transitionOverlay.style.display = 'flex';
    // Reused across every task's briefing -- without this it keeps whatever scroll
    // position it was left at, so the next task's instructions can open already
    // scrolled past the top.
    const transitionCard = transitionOverlay.querySelector('.overlay-card');
    if (transitionCard) transitionCard.scrollTop = 0;
}

function onTaskBriefingCheckChange() {
    const box = document.getElementById('taskBriefingBox');
    const btn = document.getElementById('taskTransitionContinueBtn');
    if (box && btn) btn.disabled = !box.checked;
}

function buildSegmentStartingPlanState(category, segmentKey, priorEndingPlanState, loadLevel) {
    const seg = SEGMENT_DATA[category].segments[segmentKey];
    if (category === "A") {
        if (seg.default) return { hours: { ...seg.default } };
        const priorHours = (priorEndingPlanState && priorEndingPlanState.hours) || {};
        const hours = {};
        seg.items.forEach(item => {
            hours[item] = (item in priorHours) ? priorHours[item] : (seg.newItemDefaults?.[item] ?? 0);
        });
        return { hours };
    }
    if (category === "B") {
        const d = seg.default;
        return { selections: { major: [...d.major], minor: [...d.minor], elective: [...d.elective] } };
    }
    // category === "C"
    const d = Array.isArray(seg.default) ? seg.default : seg.default[loadLevel];
    return { selections: [...d] };
}

// Applies the server-validated `actions` array (see validate_plan_actions in main.py)
// onto currentPlanState. Actions only ever exist because the participant explicitly
// asked for a specific change in their last message -- nothing here invents or
// "helpfully" adjusts anything on its own. Returns true if anything actually changed.
function applyPlanActions(actions) {
    if (!actions || !actions.length) return false;
    const category = getCategory();
    let changed = false;
    const touched = new Set(); // item ids this call actually changed -- for the plan-mirror flash
    actions.forEach(a => {
        if (category === "A") {
            if (a.slot !== "hours") return;
            if (a.op === "assign") { currentPlanState.hours[a.item] = a.value ?? 0; changed = true; touched.add(a.item); }
            else if (a.op === "remove") { currentPlanState.hours[a.item] = 0; changed = true; touched.add(a.item); }
        } else if (category === "B") {
            const bucket = currentPlanState.selections[a.slot];
            if (!bucket) return;
            if (a.op === "assign" && !bucket.includes(a.item)) { bucket.push(a.item); changed = true; touched.add(a.item); }
            else if (a.op === "remove") {
                const idx = bucket.indexOf(a.item);
                if (idx !== -1) { bucket.splice(idx, 1); changed = true; touched.add(a.item); }
            }
        } else {
            if (a.slot !== "selections") return;
            if (a.op === "assign" && !currentPlanState.selections.includes(a.item)) { currentPlanState.selections.push(a.item); changed = true; touched.add(a.item); }
            else if (a.op === "remove") {
                const idx = currentPlanState.selections.indexOf(a.item);
                if (idx !== -1) { currentPlanState.selections.splice(idx, 1); changed = true; touched.add(a.item); }
            }
        }
    });
    if (changed) lastChangedItemIds = Array.from(touched);
    return changed;
}

function renderPlanMirror() {
    const el = document.getElementById('planStateSummary');
    if (!el) return;
    const category = getCategory();
    // this only decides which rows just
    // changed, so they can get a brief neutral highlight (no color-by-validity; same
    // accent-dim tint used elsewhere as chrome, never green/red -- see plan-mirror-flash
    // in experiment.css). One-shot: read then clear, so it never replays on an unrelated re-render.
    const flashed = new Set(lastChangedItemIds);
    lastChangedItemIds = [];
    if (category === "A") el.innerHTML = renderPlanMirrorA(flashed);
    else if (category === "B") el.innerHTML = renderPlanMirrorB(flashed);
    else el.innerHTML = renderPlanMirrorC(flashed);
    if (flashed.size > 0) pulseDocPanel();
}

// A brief neutral glow around the WHOLE plan panel (not just the changed row) so a
// change registers even if the participant's eyes are still on the chat side -- same
// accent-dim tint as the per-row flash, never a correctness signal. Re-triggerable:
// removes then force-re-adds the class via a reflow, so back-to-back changes each get
// their own pulse instead of silently no-op'ing because the previous one is still running.
function pulseDocPanel() {
    const panel = document.getElementById('docPanel');
    if (!panel) return;
    panel.classList.remove('doc-panel-pulse');
    void panel.offsetWidth;
    panel.classList.add('doc-panel-pulse');
}

function renderPlanMirrorA(flashed = new Set()) {
    const hours = currentPlanState.hours || {};
    const cap = SEGMENT_DATA.A.capByLoad[currentLoadLevel];
    const items = SEGMENT_DATA.A.segments[`segment_${currentTrial}`].items;
    const rows = items.map(k => {
        const v = hours[k] || 0;
        const cls = `plan-mirror-row${v === 0 ? ' plan-mirror-row-unplaced' : ''}${flashed.has(k) ? ' plan-mirror-flash' : ''}`;
        return `<div class="${cls}" data-item="${k}"><span>${SEGMENT_DATA.A.itemLabels[k] || k}</span><span>${v} hrs</span></div>`;
    }).join('');
    const total = Object.values(hours).reduce((sum, v) => sum + (v || 0), 0);
    return `
        ${rows}
        <div class="plan-mirror-total"><span>Total this week</span><span>${total} / ${cap} hrs</span></div>`;
}

function renderPlanMirrorB(flashed = new Set()) {
    const s = currentPlanState.selections || { major: [], minor: [], elective: [] };
    const creditsFor = (cid) => SEGMENT_DATA.B.courseCredits[cid] ?? 0;
    const pools = SEGMENT_DATA.B.segments[`segment_${currentTrial}`].pools;
    const bucketBlock = (bucket, label) => {
        const ids = s[bucket] || [];
        const rows = (pools[bucket] || []).map(cid => {
            const selected = ids.includes(cid);
            const cls = `plan-mirror-row${selected ? '' : ' plan-mirror-row-unplaced'}${flashed.has(cid) ? ' plan-mirror-flash' : ''}`;
            const availableTag = selected ? '' : ' <span class="plan-mirror-min">(available)</span>';
            const desc = SEGMENT_DATA.B.courseDescriptions[cid] ? ` <span class="plan-mirror-min">— ${SEGMENT_DATA.B.courseDescriptions[cid]}</span>` : '';
            return `<div class="${cls}" data-item="${cid}"><span>${SEGMENT_DATA.B.courseLabels[cid] || cid}${desc}${availableTag}</span><span>${creditsFor(cid)} cr</span></div>`;
        }).join('');
        const subtotal = ids.reduce((sum, cid) => sum + creditsFor(cid), 0);
        return `
        <div class="plan-mirror-bucket">
            <div class="plan-mirror-bucket-label">${label} <span class="plan-mirror-min">(min ${SEGMENT_DATA.B.minimums[bucket]} cr)</span></div>
            ${rows}
            <div class="plan-mirror-subtotal"><span>Subtotal</span><span>${subtotal} cr</span></div>
        </div>`;
    };
    const totalCredits = ["major", "minor", "elective"].reduce((sum, b) => sum + (s[b] || []).reduce((s2, cid) => s2 + creditsFor(cid), 0), 0);
    return `
        ${bucketBlock('major', 'Major')}
        ${bucketBlock('minor', 'Minor (Global Studies)')}
        ${bucketBlock('elective', 'Elective')}
        <div class="plan-mirror-total"><span>Total this term</span><span>${totalCredits} / ${SEGMENT_DATA.B.capByLoad[currentLoadLevel]} cr</span></div>`;
}

function renderPlanMirrorC(flashed = new Set()) {
    const chosen = currentPlanState.selections || [];
    const cap = SEGMENT_DATA.C.capByLoad[currentLoadLevel];
    const roster = SEGMENT_DATA.C.segments[`segment_${currentTrial}`].roster;
    const rows = roster.map(cid => {
        const selected = chosen.includes(cid);
        const cls = `plan-mirror-row${selected ? '' : ' plan-mirror-row-unplaced'}${flashed.has(cid) ? ' plan-mirror-flash' : ''}`;
        const availableTag = selected ? '' : ' <span class="plan-mirror-min">(not in your plan)</span>';
        return `<div class="${cls}" data-item="${cid}"><span>${SEGMENT_DATA.C.clubLabels[cid] || cid} <span class="plan-mirror-min">(${SEGMENT_DATA.C.clubCategories[cid] || ''})</span>${availableTag}</span><span>${SEGMENT_DATA.C.clubBaseHours[cid] ?? 0} hrs</span></div>`;
    }).join('');
    const totalHours = chosen.reduce((sum, cid) => sum + (SEGMENT_DATA.C.clubBaseHours[cid] ?? 0), 0);
    const categoriesCovered = new Set(chosen.map(cid => SEGMENT_DATA.C.clubCategories[cid]).filter(Boolean));
    return `
        ${rows}
        <div class="plan-mirror-total"><span>Total this week</span><span>${totalHours} / ${cap} hrs</span></div>
        <div class="plan-mirror-total"><span>Interest categories represented</span><span>${categoriesCovered.size} / 4</span></div>`;
}

// Doc-panel body: label + the real plan-mirror (renderPlanMirror) + submit button.
function updateDoc() {
    const category = getCategory();
    const meta = CATEGORY_META[category];
    document.getElementById('docBody').innerHTML = `
        <div class="dashboard-top">
            <div class="score-card">
                <span class="sc-label">${meta.docLabel}</span>
            </div>
        </div>
        <div class="consent-block" id="planStateSummary" style="font-size:13px; line-height:1.6;"></div>
        <button id="submitSegmentBtn" class="btn-primary" style="width: 100%; margin-top: 24px;" onclick="submitSegment()">
            Submit This Segment
        </button>
    `;
    renderPlanMirror();
}

function startSegment(segmentIndex) {
    const category = getCategory();
    const meta = CATEGORY_META[category];
    const segmentKey = `segment_${segmentIndex}`;
    const loadLevel = sessionData.trialSequence[segmentIndex - 1];
    currentLoadLevel = loadLevel; // read by renderPlanMirror (A/C's visible cap is per-load)

    startTrialTimer(TRIAL_TIME_LIMIT_MS[category][loadLevel], handleTrialTimeout);

    const chatNameEl = document.querySelector('.chat-ai-name');
    if (chatNameEl) chatNameEl.innerText = meta.advisorName;
    document.title = meta.pageTitle;
    const chatInputEl = document.getElementById('chatInput');
    if (chatInputEl) chatInputEl.placeholder = meta.placeholder;

    currentPlanState = buildSegmentStartingPlanState(category, segmentKey, currentPlanState, loadLevel);
    startOfTrialPlanState = JSON.parse(JSON.stringify(currentPlanState));
    disclosedIdsSoFar = [];
    revealedFactsThisSegment = [];
    currentTargetItem = null;

    document.getElementById('docTitle').innerText = `${meta.pageTitle} — Week ${segmentIndex} of 4`;
    updateDoc();

    taskStartTime = Date.now();
    window.lastTurnTimestamp = Date.now();
    turnsInTrial = 0;
    hasInteractedThisTrial = false;
    submitAttemptsThisTrial = 0;
    darkTurnCounter = 0;
    darkDeliveredThisTrial = false;
    lastAiMessageTime = null;
    messageDwellTelemetry = {};
    resetProactiveState();
    scheduleProactiveCheck(); // guarantees a check-in even if the participant never types anything
    scheduleNotifications(loadLevel, TRIAL_TIME_LIMIT_MS[category][loadLevel]);
    startPerfDrift();

    logEvent('trial_started', { trial: segmentIndex, load_level: loadLevel, starting_plan_state: JSON.parse(JSON.stringify(currentPlanState)) }); 

    if (!sessionData.group.includes("Transcript")) {
        setTimeout(() => {
            const rawOpening = SEGMENT_OPENING_LINES[category]?.[segmentKey];
            const opening = typeof rawOpening === 'function' ? rawOpening(loadLevel) : (rawOpening || `Week ${segmentIndex} of 4 begins.`);
            addSegmentBriefLine(opening);
        }, 600);
    }
}

function startTrialTimer(limitMs, onExpire) {
    stopTrialTimer();
    trialTimerDeadline = Date.now() + limitMs;
    updateTrialTimerDisplay();
    trialTimerInterval = setInterval(() => {
        const remaining = trialTimerDeadline - Date.now();
        if (remaining <= 0) { stopTrialTimer(); onExpire(); return; }
        updateTrialTimerDisplay(remaining);
    }, 250);
}

function stopTrialTimer() {
    if (trialTimerInterval) { clearInterval(trialTimerInterval); trialTimerInterval = null; }
    trialTimerDeadline = null;
    const el = document.getElementById('trialTimerDisplay');
    if (el) el.className = 'trial-timer';
}

function updateTrialTimerDisplay(remainingMsOverride) {
    const el = document.getElementById('trialTimerDisplay');
    if (!el || trialTimerDeadline === null) return;
    const remaining = remainingMsOverride ?? Math.max(0, trialTimerDeadline - Date.now());
    const totalSec = Math.ceil(remaining / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    el.innerText = `⏱ ${m}:${String(s).padStart(2, '0')}`;
    el.className = 'trial-timer' + (totalSec <= 10 ? ' trial-timer-danger' : totalSec <= 20 ? ' trial-timer-warning' : '');
}

// Time runs out: submit whatever is currently set. This is what makes the clock a real
// cost of not asking — never a block on typing or submitting.
function handleTrialTimeout() {
    logEvent('trial_timed_out', { trial: currentTrial });
    submitSegment(true);
}

async function sendMessage() {
    if (isTutorialActive) { sendTutorialMessage(); return; }

    const inputEl = document.getElementById('chatInput');
    const text = inputEl.value.trim();
    if (!text) return;
    if (isAiRequestInFlight) return; // a reply is already pending — ignore repeat clicks instead of stacking requests

    isAiRequestInFlight = true;
    const sendBtn = document.querySelector('.send-btn');
    if (sendBtn) sendBtn.disabled = true;

    cancelProactiveTimers(); // they're about to get a real reply to what they just wrote — don't let the automatic check-in land on top of it

    darkTurnCounter++;
    const planStateAtSend = JSON.parse(JSON.stringify(currentPlanState));

    addMessage(text, 'user');
    inputEl.value = '';
    showTypingIndicator();
    const requestStart = Date.now();

    turnsInTrial++; // Increment strictly on send
    sessionData.metrics.turnsElapsed++;

    // --- CALCULATE DERIVED METRICS ---
    let calculatedWpm = 0;
    let pauseMs = 0;

    if (telemetry.keystrokes.length > 0) {
        const firstKeyTime = telemetry.keystrokes[0].time;
        const sendKeyTime = Date.now();
        const typingDurationMs = sendKeyTime - firstKeyTime;

        pauseMs = firstKeyTime - (window.lastTurnTimestamp || taskStartTime);

        if (typingDurationMs > 0) {
            const minutes = typingDurationMs / 60000;
            const words = text.length / 5;
            calculatedWpm = Math.round(words / minutes);
        }
    }

    logEvent('user_message', {
        text: text,
        plan_state_snapshot: JSON.parse(JSON.stringify(currentPlanState)), // Captures exact state before AI replies
        telemetry: {
            backspaces: telemetry.backspaces,
            wpm: calculatedWpm,
            pause_ms: pauseMs,
            keystrokes: [...telemetry.keystrokes],
            scrollEvents: [...telemetry.scrollEvents]
        }
    });

    window.lastTurnTimestamp = Date.now();
    telemetry = { keystrokes: [], scrollEvents: [], backspaces: 0 };

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
                turn_in_trial: darkTurnCounter,
                dark_delivered: darkDeliveredThisTrial,
                roi_score: 0,                
                all_constraints_met: false, 
                plan_state: currentPlanState,
                start_of_trial_plan_state: startOfTrialPlanState,
                shadow_history: shadowHistory,
                load_level: sessionData.trialSequence[currentTrial - 1],
                dropped_category_index: sessionData.droppedCategoryIndex,
                disclosed_ids_so_far: disclosedIdsSoFar
            })
        });

        const data = await response.json();
        const elapsed = Date.now() - requestStart;
        if (elapsed < MIN_AI_RESPONSE_DELAY_MS) await sleep(MIN_AI_RESPONSE_DELAY_MS - elapsed);
        document.getElementById('currentTyping')?.remove();

        if (data.status === "success") {
            addMessage(data.reply, 'ai', data.pattern_id, data.isDark, data.category);
            lastAiMessageTime = Date.now();

            if (data.target_item) currentTargetItem = data.target_item;
            if (data.isDark) darkDeliveredThisTrial = true;

            logEvent('ai_response', {
                text: data.reply,
                decoy: data.clean_decoy,
                category: data.category,
                pattern_id: data.pattern_id,
                isDark: data.isDark,
                target_item: data.target_item || null, 
                dark_turn_downgraded: data.dark_turn_downgraded || false,
                dark_turn_fallback_used: data.dark_turn_fallback_used || null,
                plan_state_at_request: planStateAtSend, // State the AI actually saw when generating this reply
                plan_state_snapshot: JSON.parse(JSON.stringify(currentPlanState)) // Captures state immediately as AI message lands
            });

            shadowHistory.push({ role: 'user', content: text });
            shadowHistory.push({ role: 'ai', content: data.clean_decoy });

            // Only reveal what the backend judged a genuine ask (see revealed_fact_ids /
            // disclosure_ok in main.py) — sending any message no longer unlocks
            // everything by default.
            revealLockedFacts(data.revealed_fact_ids || []);

            const planChanged = applyPlanActions(data.actions || []);
            if (planChanged) {
                logEvent('plan_actions_applied', { actions: data.actions, plan_state_snapshot: JSON.parse(JSON.stringify(currentPlanState)) });
                renderPlanMirror();
                nudgePerfScore(2 + Math.random() * 3);
                scheduleProactiveCheck();
            }

            cancelProactiveTimers();
            proactiveFireCount = Math.min(proactiveFireCount + 1, MAX_PROACTIVE_FIRES_PER_TRIAL);
            lastProactiveFireTime = Date.now();
            hasSubstantiveChangeSinceLastFire = false;

            nudgePerfScore(Math.random() < 0.75 ? (3 + Math.random() * 5) : -(2 + Math.random() * 4));
            hasInteractedThisTrial = true;
        }
    } catch (error) {
        document.getElementById('currentTyping')?.remove();
        console.error("Chat error:", error);
    } finally {
        isAiRequestInFlight = false;
        if (sendBtn) sendBtn.disabled = false;
    }
}

// --- PROACTIVE ADVISOR CHECK-IN ---
// Fires at most twice per segment: ~6s after the participant's first substantive plan
// change followed by a pause, with a ~45s fallback ceiling so it still fires even if
// they never pause. This is the guaranteed exchange that carries the segment's
// dark-pattern tactic (see is_dark in main.py) and reveals any locked facts — never a
// "send a message" instruction, since it fires on its own.
function resetProactiveState() {
    cancelProactiveTimers();
    proactiveFireCount = 0;
    lastProactiveFireTime = null;
    hasSubstantiveChangeSinceLastFire = false;
}

function cancelProactiveTimers() {
    clearTimeout(proactiveDebounceTimer);
    clearTimeout(proactiveCeilingTimer);
    proactiveDebounceTimer = null;
    proactiveCeilingTimer = null;
}

function scheduleProactiveCheck() {
    if (proactiveFireCount >= MAX_PROACTIVE_FIRES_PER_TRIAL || sessionData.group.includes("Transcript")) return;

    hasSubstantiveChangeSinceLastFire = true;

    // The ceiling is a safety net only for the FIRST guaranteed exchange of the segment —
    // any second fire is a bonus touchpoint and only ever happens if the debounce settles
    // naturally, so it never forces an interjection the way the first one has to.
    if (proactiveFireCount === 0 && !proactiveCeilingTimer) {
        proactiveCeilingTimer = setTimeout(() => attemptProactiveFire(), PROACTIVE_CEILING_MS);
    }
    clearTimeout(proactiveDebounceTimer);
    proactiveDebounceTimer = setTimeout(() => attemptProactiveFire(), PROACTIVE_DEBOUNCE_MS);
}

// The debounce/ceiling landed — fire now, unless we're still inside the cooldown from
// the last exchange (manual or automatic), in which case wait out the remainder instead
// of firing early and stacking two AI turns close together.
function attemptProactiveFire() {
    if (proactiveFireCount >= MAX_PROACTIVE_FIRES_PER_TRIAL || !hasSubstantiveChangeSinceLastFire) return;

    const elapsed = lastProactiveFireTime ? Date.now() - lastProactiveFireTime : Infinity;
    if (elapsed < PROACTIVE_COOLDOWN_MS || isAiRequestInFlight) {
        const wait = elapsed < PROACTIVE_COOLDOWN_MS ? (PROACTIVE_COOLDOWN_MS - elapsed) : 1000;
        clearTimeout(proactiveDebounceTimer);
        proactiveDebounceTimer = setTimeout(() => attemptProactiveFire(), wait);
        return;
    }

    triggerProactiveAdvisorNote();
}

// Tracks which locked-fact IDs have been revealed this segment (see
// describe_locked_facts_A/B/C in main.py) so future /api/chat calls send
// disclosed_ids_so_far and never get the same fact re-disclosed.
function revealLockedFacts(ids) {
    if (!ids || !ids.length) return;
    ids.forEach(id => {
        if (!disclosedIdsSoFar.includes(id)) {
            disclosedIdsSoFar.push(id);
            revealedFactsThisSegment.push(id);
            logEvent('fact_revealed', { id });
        }
    });
}

async function triggerProactiveAdvisorNote() {
    if (proactiveFireCount >= MAX_PROACTIVE_FIRES_PER_TRIAL || sessionData.group.includes("Transcript")) return;
    if (isAiRequestInFlight) return; // defense in depth — attemptProactiveFire should already have deferred this
    cancelProactiveTimers();
    const isFirstFire = proactiveFireCount === 0;
    proactiveFireCount++;
    lastProactiveFireTime = Date.now();
    hasSubstantiveChangeSinceLastFire = false;
    cancelProactiveTimers();

    isAiRequestInFlight = true;
    const sendBtn = document.querySelector('.send-btn');
    if (sendBtn) sendBtn.disabled = true;
    showTypingIndicator();
    const requestStart = Date.now();

    const loadLevel = sessionData.trialSequence[currentTrial - 1];
    darkTurnCounter++;
    const planStateAtSend = JSON.parse(JSON.stringify(currentPlanState));

    // True last resort: the participant hasn't chatted in time. Any proactive fire before
    // this deadline (e.g. reacting to a plan edit) stays neutral commentary, so the dark
    // tactic is deprioritized behind the participant actually starting a chat on their own.
    const proactiveDarkEligible = (Date.now() - taskStartTime) >= PROACTIVE_CEILING_MS;

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: sessionData.participantId,
                primary_task: sessionData.primaryTask,
                message: "",
                task_id: 1,
                group: sessionData.group,
                trial_num: currentTrial,
                turn_in_trial: darkTurnCounter,
                dark_delivered: darkDeliveredThisTrial,
                roi_score: 0,
                all_constraints_met: false,
                plan_state: currentPlanState,
                start_of_trial_plan_state: startOfTrialPlanState,
                shadow_history: shadowHistory,
                load_level: loadLevel,
                dropped_category_index: sessionData.droppedCategoryIndex,
                disclosed_ids_so_far: disclosedIdsSoFar,
                is_proactive: true,
                is_repeat_proactive: !isFirstFire,
                proactive_dark_eligible: proactiveDarkEligible
            })
        });

        const data = await response.json();
        const elapsed = Date.now() - requestStart;
        if (elapsed < MIN_AI_RESPONSE_DELAY_MS) await sleep(MIN_AI_RESPONSE_DELAY_MS - elapsed);
        document.getElementById('currentTyping')?.remove();
        if (data.status !== "success") return;

        addMessage(data.reply, 'ai', data.pattern_id, data.isDark, data.category);
        lastAiMessageTime = Date.now();
        if (data.target_item) currentTargetItem = data.target_item;
        if (data.isDark) darkDeliveredThisTrial = true;

        logEvent('ai_proactive_message', {
            text: data.reply,
            decoy: data.clean_decoy,
            category: data.category,
            pattern_id: data.pattern_id,
            isDark: data.isDark,
            target_item: data.target_item || null, 
            dark_turn_downgraded: data.dark_turn_downgraded || false,
            is_repeat: !isFirstFire,
            revealed_ids: data.revealed_fact_ids || [],
            plan_state_at_request: planStateAtSend,
            plan_state_snapshot: JSON.parse(JSON.stringify(currentPlanState))
        });

        shadowHistory.push({ role: 'ai', content: data.clean_decoy });

        // Proactive turns never reveal (enforced server-side, not just by prompt) — this
        // will always resolve to [], kept symmetric with sendMessage() on purpose.
        revealLockedFacts(data.revealed_fact_ids || []);

        const planChanged = applyPlanActions(data.actions || []);
        if (planChanged) {
            logEvent('plan_actions_applied', { actions: data.actions, plan_state_snapshot: JSON.parse(JSON.stringify(currentPlanState)) });
            renderPlanMirror();
            nudgePerfScore(2 + Math.random() * 3);
        }

        hasInteractedThisTrial = true;
    } catch (error) {
        document.getElementById('currentTyping')?.remove();
        console.error("Proactive advisor note failed:", error);
    } finally {
        isAiRequestInFlight = false;
        if (sendBtn) sendBtn.disabled = false;
    }
}

// --- AI MESSAGE DWELL TRACKING ---
// Tracks how long each AI chat bubble actually stayed visible in the chat panel's
// viewport (not merely "was added to the DOM"), keyed by the backend's pattern_id so it
// can be joined back to that message's isDark/category in ai_response/ai_proactive_message.
function getDwellObserver() {
    if (dwellObserver) return dwellObserver;
    const chatContainer = document.getElementById('chatMessages');
    dwellObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            const patternId = entry.target.dataset.patternId;
            const rec = patternId && messageDwellTelemetry[patternId];
            if (!rec) return;
            if (entry.isIntersecting) {
                if (!rec.visibleSince) {
                    rec.visibleSince = Date.now();
                    if (!rec.firstVisibleAt) rec.firstVisibleAt = rec.visibleSince;
                }
            } else if (rec.visibleSince) {
                rec.totalVisibleMs += Date.now() - rec.visibleSince;
                rec.visibleSince = null;
            }
        });
    }, { root: chatContainer, threshold: 0.5 });
    return dwellObserver;
}

// Called at segment submission so a message still on-screen (visibleSince still set)
// gets its final open interval counted instead of losing that last stretch.
function finalizeMessageDwellTelemetry() {
    const now = Date.now();
    Object.values(messageDwellTelemetry).forEach(rec => {
        if (rec.visibleSince) {
            rec.totalVisibleMs += now - rec.visibleSince;
            rec.visibleSince = null;
        }
    });
    return { ...messageDwellTelemetry };
}

function showTypingIndicator() {
    const chatContainer = document.getElementById('chatMessages');
    if (!chatContainer || document.getElementById('currentTyping')) return;
    const msgDiv = document.createElement('div');
    msgDiv.id = 'currentTyping';
    msgDiv.className = 'msg ai typing-indicator';
    msgDiv.innerHTML = `<div class="msg-bubble"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>`;
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function addScriptedLine(text) {
    const chatContainer = document.getElementById('chatMessages');
    if (!chatContainer) return;
    const msgDiv = document.createElement('div');
    msgDiv.className = 'msg scripted';
    const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
    msgDiv.innerHTML = `<div class="msg-bubble">${formattedText}</div>`;
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    logEvent('scripted_line_shown', { text });
}

function addSegmentBriefLine(text) {
    const chatContainer = document.getElementById('chatMessages');
    if (!chatContainer) return;
    const msgDiv = document.createElement('div');
    msgDiv.className = 'msg scripted';
    msgDiv.innerHTML = `<div class="msg-bubble"><span class="segment-brief-tag">This week</span>${text}</div>`;
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function addMessage(text, sender, patternId = null, isDark = false, category = null) {
    const chatContainer = document.getElementById('chatMessages');
    if (!chatContainer) return;

    const msgDiv = document.createElement('div');
    msgDiv.className = `msg ${sender}${isDark ? ' manipulative' : ''}`;

    // Format markdown-like bolding if the AI uses it
    const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');

    // researcher-mode-only tag: hidden by default (see body.researcher-mode in experiment.css),
    // only visible after running document.body.classList.add('researcher-mode') in console.
    const tagHtml = isDark ? `<span class="manipulation-tag">${category || 'DARK PATTERN'}</span>` : '';
    msgDiv.innerHTML = `<div class="msg-bubble">${formattedText}${tagHtml}</div>`;
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    if (sender === 'ai' && patternId) {
        msgDiv.dataset.patternId = patternId;
        messageDwellTelemetry[patternId] = { totalVisibleMs: 0, visibleSince: null, firstVisibleAt: null };
        getDwellObserver().observe(msgDiv);
    }
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

// Fire-and-forget save after each of segments 1-3, so a participant who drops off
// mid-session still leaves their completed segments on the server, not just in their
// own browser's localStorage. /api/save_data overwrites the file each time, so later
// calls (here or in debrief.js) simply supersede this with a more complete version.
async function autosaveProgress() {
    try {
        sessionData.saveSeq = Date.now();
        await fetch('/api/save_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sessionData)
        });
    } catch (error) {
        console.error("Autosave error (next segment or the final save will retry this):", error);
    }
}

async function saveSessionData() {
    for (let attempt = 1; attempt <= 2; attempt++) {
        try {
            sessionData.saveSeq = Date.now();
            const response = await fetch('/api/save_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sessionData)
            });
            if (!response.ok) throw new Error(`Save endpoint returned ${response.status}`);
            window.location.href = '/debrief';
            return;
        } catch (error) {
            console.error(`Save attempt ${attempt} failed:`, error);
            if (attempt === 2) {
                alert("We couldn't confirm your data was saved due to a connection issue. Please stay on this page and try again.");
                window.location.href = '/debrief';
            }
        }
    }
}

async function submitSegment(forced = false) {
    stopTrialTimer();
    clearNotificationTimers(); // no more bubbles competing for attention once they're done with this segment
    stopPerfDrift();
    const loadLevel = sessionData.trialSequence[currentTrial - 1];

    const btn = document.getElementById('submitSegmentBtn');
    if (btn) { btn.disabled = true; btn.innerText = "Checking..."; }

    let passed = true;
    let verdictDetail = null;
    let percentMet = null;
    try {
        const res = await fetch('/api/attempt_submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                primary_task: sessionData.primaryTask,
                trial_num: currentTrial,
                plan_state: currentPlanState,
                load_level: loadLevel
            })
        });
        const data = await res.json();
        if (data.status === "success") {
            passed = data.passed;
            verdictDetail = data.verdict_detail;
            percentMet = data.percent_met;
        }
    } catch (error) {
        console.error("attempt_submit failed -- treating as a pass so a network blip never traps someone on a segment:", error);
    }

    if (passed) nudgePerfScore(8 + Math.random() * 6);
    else nudgePerfScore(-(6 + Math.random() * 6));

    logEvent('trial_submitted', {
        trial: currentTrial,
        load_level: loadLevel,
        final_score: percentMet, // real plan-quality score (% of this segment's checklist met) -- read by debrief.js's performance summary and the CSV
        final_plan_state: JSON.parse(JSON.stringify(currentPlanState)),
        revealed_fact_ids: [...revealedFactsThisSegment],
        message_dwell_telemetry: finalizeMessageDwellTelemetry(),
        timed_out: !!forced,
        submit_attempt: submitAttemptsThisTrial + 1,
        passed,
        verdict_detail: verdictDetail
    });

    if (forced) {
        addScriptedLine("Time's up for this week — your plan moves forward as-is.");
    } else if (!passed) {
        submitAttemptsThisTrial++;
        const rejectionLine = SUBMIT_REJECTION_MESSAGES[Math.min(submitAttemptsThisTrial - 1, SUBMIT_REJECTION_MESSAGES.length - 1)];
        addScriptedLine(verdictDetail ? `${rejectionLine} Specifically: ${verdictDetail}` : rejectionLine);
        if (btn) { btn.disabled = false; btn.innerText = "Submit This Week"; }
        return; // stays on this segment -- participant keeps chatting and can resubmit
    } else {
        addScriptedLine(SUBMIT_PASS_MESSAGE);
    }

    // A global (session-wide) trial number, so TLX ratings from task 2's segment 1
    // don't overwrite task 1's segment 1 in sessionData.perTrialTLX.
    const globalTrialNumber = (sessionData.currentTaskIndex * 4) + currentTrial;
    const isLastTaskInOrder = sessionData.currentTaskIndex >= sessionData.taskOrder.length - 1;

    // One recall-check probe per segment, gating everything else -- see showRecallCheck().
    showRecallCheck(loadLevel, () => {
        if (currentTrial >= 4 && isLastTaskInOrder) {
            finalizeAttentionBonus(); // last segment of the whole session -- settle the bonus fields before saving
            if (btn) btn.innerText = "Processing...";
            showPerTrialTLX(globalTrialNumber, true, () => {
                saveSessionData();
            });
        } else if (currentTrial >= 4) {
            showPerTrialTLX(globalTrialNumber, true, () => {
                autosaveProgress();
                advanceToNextTask();
            });
        } else {
            showPerTrialTLX(globalTrialNumber, false, () => {
                autosaveProgress(); // don't wait on this — keep moving even if it's slow/fails
                currentTrial++;
                startSegment(currentTrial);
            });
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('chatInput')?.addEventListener('paste', (e) => {
        const pasted = (e.clipboardData || window.clipboardData).getData('text');
        logEvent('chat_input_pasted', { pasted_text: pasted, length: pasted.length });
    });
});

document.addEventListener('copy', (e) => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;
    const anchorEl = selection.anchorNode?.nodeType === 3 ? selection.anchorNode.parentElement : selection.anchorNode;
    const aiMessageEl = anchorEl?.closest?.('.ai-message');
    if (!aiMessageEl) return;
    const copiedText = selection.toString();
    logEvent('ai_response_copied', {
        trial: currentTrial,
        copied_text: copiedText,
        length: copiedText.length
    });
});