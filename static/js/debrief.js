// static/js/debrief.js

document.addEventListener('DOMContentLoaded', () => {
    // We do not auto-load the data visually yet. 
    // They must read the debrief text first.
});

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
    
    const session = JSON.parse(rawData);
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(session, null, 2));
    
    const link = document.createElement("a");
    link.setAttribute("href", dataStr);
    link.setAttribute("download", `HTI_Study_${session.participantId}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function downloadCSV() {
    const rawData = localStorage.getItem('hti_session');
    if (!rawData) return;
    
    const session = JSON.parse(rawData);
    
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Participant_ID,Group,Task,Timestamp,Sender,Message\n";
    
    session.events.forEach(event => {
        let cleanText = event.content.replace(/,/g, "").replace(/\n/g, " ");
        let row = `${session.participantId},${session.group},${event.task},${event.timestamp},${event.type},"${cleanText}"`;
        csvContent += row + "\n";
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `HTI_Study_${session.participantId}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}